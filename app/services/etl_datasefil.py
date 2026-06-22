"""
ETL de extracción/transformación para DATA SEFIL.

En la arquitectura híbrida este módulo ya NO escribe en la base de datos.
Transforma los registros crudos en CustomerUpsertItem que el Worker enviará
al endpoint POST /sync/bulk-upsert de Hostinger.

Payload esperado por registro:
{
    "identification": "1712345678",
    "name":           "PEREZ LOPEZ JUAN CARLOS",
    "gender":         "M",
    "birth":          "1990-05-15",
    "place_birth":    "QUITO",
    "state_civil":    "soltero",
    "nationality":    "Ecuatoriana",
    "profession":     "INGENIERO",
    "salary":         1500.00,
    "contacts":  [{"phone_number": "0991234567", "phone_type": "CELULAR"}],
    "address":   [{"address": "Av. 6 de Dic", "province": "PICHINCHA", "city": "QUITO", "type": "DOMICILIO"}],
    "emails":    [{"direction": "juan@email.com", "active": true}],
    "parents":   [{"type": "MADRE", "name": "ANA LOPEZ", "identification": "1101067609", ...}]
}
"""

import logging

from app.schemas.sync import (
    AddressItem, CustomerUpsertItem, EmailItem, PhoneItem, RelationshipItem,
)
from app.services.data_cleaning import (
    clean_civil_status,
    clean_date,
    clean_email,
    clean_gender,
    clean_identification,
    clean_phone_number,
    clean_salary,
    infer_phone_type,
    standardize_text,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _trunc(value: str | None, limit: int) -> str | None:
    return value[:limit] if value and len(value) > limit else value


def _parse_name(full_name: str) -> tuple[str, str]:
    """
    Splits a combined full name into (first_name, last_name).
    Assumes Ecuadorian format: "APELLIDO1 APELLIDO2 NOMBRE1 NOMBRE2".

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


def _map_sefil_record(raw: dict) -> dict | None:
    """Maps a raw DATA SEFIL record to Customer field kwargs. Returns None if invalid."""
    identification = clean_identification(raw.get("identification"))
    if not identification:
        logger.warning("Skipping record — invalid identification: %r", raw.get("identification"))
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
        "birth_date":     clean_date(raw.get("birth")),
        "birth_place":    _trunc(standardize_text(raw.get("place_birth")) or None, 199),
        "civil_status":   clean_civil_status(raw.get("state_civil")),
        "nationality":    _trunc(standardize_text(raw.get("nationality")) or None, 99),
        "economic_activity": _trunc(standardize_text(raw.get("economic_activity")) or standardize_text(raw.get("profession")) or None, 499),
    }


def _extract_phones(contacts_raw: list[dict]) -> list[PhoneItem]:
    result: list[PhoneItem] = []
    seen: set[str] = set()

    for contact in contacts_raw:
        local_number = clean_phone_number(contact.get("phone_number"))
        if not local_number or local_number in seen:
            continue

        raw_type = str(contact.get("phone_type", "")).upper()
        if "CELULAR" in raw_type or "MOVIL" in raw_type or "MÓVIL" in raw_type:
            phone_type = "MOVIL"
        elif "FIJO" in raw_type or "TELEFONO" in raw_type or "DOMICILIO" in raw_type or "TRABAJO" in raw_type:
            phone_type = "FIJO"
        else:
            # Si manda basura o algo no reconocido, inferir el tipo basado en el número
            phone_type = infer_phone_type(local_number)

        result.append(PhoneItem(
            phone_number=local_number,
            phone_type=phone_type,
            country_code="+593",
            created_source="DATA SEFIL",
            calls_effective=contact.get("counter_correct_number"),
            calls_not_effective=contact.get("counter_incorrect_number"),
        ))
        seen.add(local_number)

    return result


def _clean_geo_field(value: str | None) -> str | None:
    """Returns None if the value is empty, 'SIN DATOS', 'SIN DATO', 'N/A', etc."""
    if not value:
        return None
    cleaned = standardize_text(value)
    if not cleaned or cleaned in ("SIN DATOS", "SIN DATO", "N/A", "NO TIENE", "NO APLICA", "NINGUNO", "NINGUNA", ".", "-"):
        return None
    return cleaned


def _extract_addresses(addresses_raw: list[dict]) -> list[AddressItem]:
    result: list[AddressItem] = []
    seen: set[str] = set()

    for addr_data in addresses_raw:
        address_line = standardize_text(addr_data.get("address"))
        if not address_line or address_line in seen:
            continue

        raw_type = str(addr_data.get("type", "")).upper()
        if "DOMICILIO" in raw_type:
            address_type = "HOME"
        elif "TRABAJO" in raw_type:
            address_type = "JOB"
        else:
            address_type = None

        result.append(AddressItem(
            address_line=address_line[:499],
            province=_clean_geo_field(addr_data.get("province")),
            city=_clean_geo_field(addr_data.get("city")),
            address_type=address_type,
            created_source="DATA SEFIL",
        ))
        seen.add(address_line)

    return result


def _extract_emails(emails_raw: list[dict]) -> list[EmailItem]:
    result: list[EmailItem] = []
    seen: set[str] = set()

    for email_data in emails_raw:
        email_address = clean_email(email_data.get("direction"))
        if not email_address or email_address in seen:
            continue

        lower_email = email_address.lower()
        if lower_email.startswith("vacunacion") or lower_email.startswith("soporte.covid"):
            continue

        result.append(EmailItem(
            email_address=email_address,
            is_active=bool(email_data.get("active", True)),
            created_source="DATA SEFIL",
        ))
        seen.add(email_address)

    return result


def _extract_relationships(parents_raw: list[dict]) -> list[RelationshipItem]:
    result: list[RelationshipItem] = []
    seen: set[tuple] = set()

    for parent in parents_raw:
        rel_type = str(parent.get("type", "")).upper().strip()
        if not rel_type:
            continue

        related_id   = clean_identification(parent.get("identification")) or None
        related_name = standardize_text(parent.get("name")) or None
        key          = (rel_type, related_id or related_name)

        if key in seen:
            continue
        seen.add(key)

        result.append(RelationshipItem(
            relationship_type=rel_type,
            related_identification=related_id,
            related_name=related_name,
            related_birth_date=clean_date(parent.get("birth")),
            related_gender=clean_gender(parent.get("gender")),
            related_civil_status=clean_civil_status(parent.get("state_civil")),
            related_death_date=clean_date(parent.get("death")) if parent.get("death") else None,
            created_source="DATA SEFIL",
        ))

    return result


# ---------------------------------------------------------------------------
# Public prepare function — returns CustomerUpsertItem list, no DB needed
# ---------------------------------------------------------------------------

def prepare_datasefil_customers(raw_data: list[dict]) -> list[CustomerUpsertItem]:
    """
    Transform raw DATA SEFIL records into a CustomerUpsertItem list.
    Phones, addresses, emails, relationships and salary are embedded inline.
    """
    result:  list[CustomerUpsertItem] = []
    skipped = 0

    for raw in raw_data:
        fields = _map_sefil_record(raw)
        if not fields:
            skipped += 1
            continue

        # Combine emails array + top-level "email" single field
        emails_raw = list(raw.get("emails", []))
        top_email  = raw.get("email")
        if top_email:
            emails_raw.append({"direction": top_email, "active": 1})

        result.append(CustomerUpsertItem(
            **fields,
            salary=raw.get("salary"),
            phones=_extract_phones(raw.get("contacts", [])),
            addresses=_extract_addresses(raw.get("address", [])),
            emails=_extract_emails(emails_raw),
            relationships=_extract_relationships(raw.get("parents", [])),
        ))

    logger.info(
        "prepare_datasefil_customers — prepared: %d | skipped: %d",
        len(result), skipped,
    )
    return result
