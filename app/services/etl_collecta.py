"""
ETL de extracción/transformación para la API de Collecta (CollAPI).

En la arquitectura híbrida este módulo ya NO escribe en la base de datos.
Sólo transforma los registros crudos en listas de CustomerUpsertItem que el
Worker enviará posteriormente al endpoint POST /sync/bulk-upsert de Hostinger.

Payload esperado por registro (campos confirmados en app/api/api_collecta.json):
{
    "ci":                "1712345678",
    "name":              "Juan Carlos Pérez López",
    "type":              "natural",
    "gender":            "M",
    "civil_status":      "soltero",
    "economic_activity": "Comerciante",
    "phones": [
        {"phone_number": "0991234567", "phone_type": "CELULAR", "phone_status": "ACTIVE"}
    ]
}
"""

import logging
from collections import defaultdict

from app.schemas.sync import AddressItem, CustomerUpsertItem, PhoneItem
from app.services.data_cleaning import (
    clean_civil_status,
    clean_gender,
    clean_identification,
    clean_phone_number,
    standardize_text,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type maps
# ---------------------------------------------------------------------------

_CONTACT_TYPE_MAP: dict[str, str] = {
    "CELULAR":    "MOBILE",
    "FIJO":       "HOME",
    "DOMICILIO":  "HOME",
    "TRABAJO":    "WORK",
    "GARANTE":    "GUARANTOR",
    "REFERENCIA": "REFERENCE",
    "DEUDOR":     "DEBTOR",
}

_ADDRESS_TYPE_MAP: dict[str, str] = {
    "DOMICILIO": "HOME",
    "TRABAJO":   "WORK",
    "GARANTE":   "GUARANTOR",
    "OTRO":      "OTHER",
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _trunc(value: str | None, limit: int) -> str | None:
    return value[:limit] if value and len(value) > limit else value


def _parse_name(full_name: str) -> tuple[str, str]:
    """
    Splits a combined full name into (first_name, last_name).
    Assumes Collecta format: "APELLIDO1 APELLIDO2 NOMBRE1 NOMBRE2".

    Examples:
        "PEREZ LOPEZ JUAN CARLOS" -> ("JUAN CARLOS", "PEREZ LOPEZ")
        "GOMEZ ZAMBRANO MARIA"    -> ("MARIA", "GOMEZ ZAMBRANO")
        "RUIZ CARLOS"             -> ("CARLOS", "RUIZ")
    """
    parts = full_name.strip().split()

    if len(parts) <= 1:
        return full_name.strip(), ""
    if len(parts) >= 4:
        return " ".join(parts[2:]), f"{parts[0]} {parts[1]}"
    if len(parts) == 3:
        return parts[2], f"{parts[0]} {parts[1]}"
    return parts[1], parts[0]


def _map_collecta_record(raw: dict) -> dict | None:
    """Maps a raw Collecta record to Customer field kwargs. Returns None if invalid."""
    identification = clean_identification(raw.get("ci"))
    if not identification:
        logger.warning("Skipping record — invalid ci: %r", raw.get("ci"))
        return None

    raw_name = standardize_text(raw.get("name"))
    if not raw_name:
        logger.warning("Skipping record %s — empty name", identification)
        return None

    first_name, last_name = _parse_name(raw_name)
    if not first_name:
        logger.warning("Skipping record %s — could not parse first_name", identification)
        return None

    return {
        "identification": identification,
        "first_name":     _trunc(first_name, 199),
        "last_name":      _trunc(last_name, 199),
        "gender":         clean_gender(raw.get("gender")),
        "civil_status":   clean_civil_status(raw.get("civil_status")),
        "profession":     _trunc(standardize_text(raw.get("economic_activity")) or None, 499),
    }


def _build_phones(phones_raw: list[dict], only_active: bool = True) -> list[PhoneItem]:
    """Convert raw Collecta phone dicts into PhoneItem objects."""
    result: list[PhoneItem] = []
    seen: set[str] = set()

    for phone_data in phones_raw:
        if only_active:
            status = str(phone_data.get("phone_status", "ACTIVE")).upper()
            if status != "ACTIVE":
                continue

        local_number = clean_phone_number(phone_data.get("phone_number"))
        if not local_number or local_number in seen:
            continue

        raw_type   = str(phone_data.get("phone_type", "")).upper()
        phone_type = _CONTACT_TYPE_MAP.get(raw_type, raw_type or None)

        result.append(PhoneItem(
            phone_number=local_number,
            phone_type=phone_type,
            country_code="+593",
            source="Collecta",
            calls_effective=phone_data.get("calls_effective"),
            calls_not_effective=phone_data.get("calls_not_effective"),
        ))
        seen.add(local_number)

    return result


# ---------------------------------------------------------------------------
# Public prepare functions — return CustomerUpsertItem lists, no DB needed
# ---------------------------------------------------------------------------

def prepare_collecta_customers(raw_data: list[dict]) -> list[CustomerUpsertItem]:
    """
    Transform raw Collecta /clients records into CustomerUpsertItem list.
    Phones from each record's `phones` array are embedded inline.
    """
    result: list[CustomerUpsertItem] = []
    skipped = 0

    for raw in raw_data:
        fields = _map_collecta_record(raw)
        if not fields:
            skipped += 1
            continue

        result.append(CustomerUpsertItem(
            **fields,
            phones=_build_phones(raw.get("phones", [])),
        ))

    logger.info(
        "prepare_collecta_customers — prepared: %d | skipped: %d",
        len(result), skipped,
    )
    return result


def prepare_collecta_contacts(raw_contacts: list[dict]) -> list[CustomerUpsertItem]:
    """
    Transform raw Collecta /contacts records into CustomerUpsertItem list.
    Each item carries only phone data — the API merges them into the existing customer.
    """
    contacts_by_ci: dict[str, list[dict]] = defaultdict(list)
    for contact in raw_contacts:
        ci = clean_identification(str(contact.get("client_ci", "")))
        if ci:
            contacts_by_ci[ci].append(contact)

    result: list[CustomerUpsertItem] = []

    for ci, contacts in contacts_by_ci.items():
        phones = _build_phones(contacts, only_active=True)
        if phones:
            result.append(CustomerUpsertItem(identification=ci, phones=phones))

    logger.info("prepare_collecta_contacts — prepared: %d CIs with phones", len(result))
    return result


def prepare_collecta_directions(raw_directions: list[dict]) -> list[CustomerUpsertItem]:
    """
    Transform raw Collecta /directions records into CustomerUpsertItem list.
    Each item carries only address data — the API merges them into the matching customer.
    """
    directions_by_ci: dict[str, list[dict]] = defaultdict(list)
    for row in raw_directions:
        ci = clean_identification(str(row.get("client_ci", "")))
        if ci:
            directions_by_ci[ci].append(row)

    result: list[CustomerUpsertItem] = []

    for ci, rows in directions_by_ci.items():
        addresses: list[AddressItem] = []
        seen: set[tuple] = set()

        for row in rows:
            parts = [
                standardize_text(row.get("direction")),
                standardize_text(row.get("neighborhood")),
                standardize_text(row.get("parish")),
            ]
            address_line = " ".join(filter(None, parts)) or None
            if not address_line:
                continue

            province     = standardize_text(row.get("province")) or None
            city         = standardize_text(row.get("canton"))   or None
            raw_type     = str(row.get("type", "")).upper()
            address_type = _ADDRESS_TYPE_MAP.get(raw_type, raw_type or None)

            key = (address_line, city)
            if key in seen:
                continue
            seen.add(key)

            addresses.append(AddressItem(
                address_line=address_line[:499],
                province=province,
                city=city,
                address_type=address_type,
                source="Collecta",
            ))

        if addresses:
            result.append(CustomerUpsertItem(identification=ci, addresses=addresses))

    logger.info("prepare_collecta_directions — prepared: %d CIs with addresses", len(result))
    return result
