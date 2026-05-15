"""
ETL específico para la API de Collecta (CollAPI).

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
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.collections import CollectionAddress, CollectionPhone
from app.models.customer import Customer
from app.services.data_cleaning import (
    clean_civil_status,
    clean_gender,
    clean_identification,
    clean_phone_number,
    standardize_text,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_name(full_name: str) -> tuple[str, str]:
    """
    Splits a combined full name into (first_name, last_name).

    Assumes the input from Collecta is in "APELLIDOS NOMBRES" format.
    
    Examples:
        "PEREZ LOPEZ JUAN CARLOS" -> ("JUAN CARLOS", "PEREZ LOPEZ")
        "GOMEZ ZAMBRANO MARIA"    -> ("MARIA", "GOMEZ ZAMBRANO")
        "RUIZ CARLOS"             -> ("CARLOS", "RUIZ")
    """
    parts = full_name.strip().split()
    
    if len(parts) <= 1:
        return full_name.strip(), ""
    
    if len(parts) >= 4:
        # Asumimos 2 apellidos y 2 (o más) nombres
        last_name = f"{parts[0]} {parts[1]}"
        first_name = " ".join(parts[2:])
    elif len(parts) == 3:
        # Asumimos 2 apellidos y 1 nombre (muy común en Latam)
        last_name = f"{parts[0]} {parts[1]}"
        first_name = parts[2]
    else:
        # 2 palabras: 1 apellido y 1 nombre
        last_name = parts[0]
        first_name = parts[1]
        
    return first_name, last_name


def _map_collecta_record(raw: dict) -> dict | None:
    """
    Maps a raw Collecta client record to Customer model kwargs.
    Returns None if the record is invalid and must be skipped.
    """
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

    def _trunc(value: str | None, limit: int) -> str | None:
        return value[:limit] if value and len(value) > limit else value

    return {
        "identification": identification,
        "first_name": _trunc(first_name, 199),
        "last_name": _trunc(last_name, 199),
        "gender": clean_gender(raw.get("gender")),
        "civil_status": clean_civil_status(raw.get("civil_status")),
        "profession": _trunc(standardize_text(raw.get("economic_activity")) or None, 499),
    }


def _sync_phones(customer: Customer, phones_raw: list[dict], db: Session) -> None:
    """
    Inserts phones from the Collecta payload that don't already exist on the customer.
    Only ACTIVE phones (phone_status == "ACTIVE") are synced.
    """
    existing_numbers = {p.phone_number for p in customer.phones}

    for phone_data in phones_raw:
        status = str(phone_data.get("phone_status", "ACTIVE")).upper()
        if status != "ACTIVE":
            continue

        local_number = clean_phone_number(phone_data.get("phone_number"))
        if not local_number or local_number in existing_numbers:
            continue

        raw_type = str(phone_data.get("phone_type", "")).upper()
        if "CELULAR" in raw_type:
            phone_type = "MOBILE"
        elif "FIJO" in raw_type:
            phone_type = "HOME"
        else:
            phone_type = raw_type or None

        db.add(CollectionPhone(
            customer_id=customer.id,
            country_code="+593",
            phone_number=local_number,
            phone_type=phone_type,
            source="Collecta",
        ))
        existing_numbers.add(local_number)


# ---------------------------------------------------------------------------
# Main ETL entry point
# ---------------------------------------------------------------------------

def sync_collecta_data(raw_collecta_data: list[dict], db: Session) -> SyncResult:
    """
    Upserts a batch of Collecta client records into the centralized database.

    Strategy:
    - Match on `identification` (ci).
    - Existing customer → update non-None fields + sync phones.
    - New customer → insert Customer + phones.
    - Single commit at the end of the batch (atomic transaction).

    Args:
        raw_collecta_data: List of raw dicts from the Collecta API.
        db:                 Active SQLAlchemy session.

    Returns:
        SyncResult with counts of created, updated, and skipped records.
    """
    result = SyncResult()

    for raw in raw_collecta_data:
        customer_fields = _map_collecta_record(raw)
        if not customer_fields:
            result.skipped += 1
            continue

        identification: str = customer_fields["identification"]

        try:
            stmt = (
                select(Customer)
                .where(Customer.identification == identification)
                .options(selectinload(Customer.phones))
            )
            existing = db.execute(stmt).scalar_one_or_none()

            with db.begin_nested():  # savepoint: aísla el fallo tanto en create como en update
                if existing:
                    for attr, value in customer_fields.items():
                        if value is not None:
                            setattr(existing, attr, value)
                    _sync_phones(existing, raw.get("phones", []), db)
                else:
                    new_customer = Customer(**customer_fields)
                    db.add(new_customer)
                    db.flush()
                    new_customer.phones = []
                    _sync_phones(new_customer, raw.get("phones", []), db)

            if existing:
                result.updated += 1
                logger.info("Updated customer %s", identification)
            else:
                result.created += 1
                logger.info("Created customer %s", identification)

        except Exception as exc:
            logger.error("Failed to process customer %s: %s", identification, exc)
            result.errors.append(f"{identification}: {exc}")
            continue

    db.commit()
    if result.errors:
        logger.warning(
            "Collecta sync — primeros %d error(es):\n  %s",
            min(5, len(result.errors)),
            "\n  ".join(result.errors[:5]),
        )
    logger.info(
        "Collecta sync complete — created: %d | updated: %d | skipped: %d | errors: %d",
        result.created,
        result.updated,
        result.skipped,
        len(result.errors),
    )
    return result


# ---------------------------------------------------------------------------
# Contacts ETL — /public/api/contacts
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


def sync_collecta_contacts(raw_contacts: list[dict], db: Session) -> SyncResult:
    """
    Sincroniza teléfonos desde el endpoint /contacts de Collecta.
    Agrupa por client_ci, localiza el Customer y añade los teléfonos ACTIVE
    que no existan ya en la BD.
    """
    result = SyncResult()

    # Agrupar contactos por cédula del cliente
    contacts_by_ci: dict[str, list[dict]] = defaultdict(list)
    for contact in raw_contacts:
        ci = clean_identification(str(contact.get("client_ci", "")))
        if ci:
            contacts_by_ci[ci].append(contact)

    for ci, contacts in contacts_by_ci.items():
        try:
            stmt = (
                select(Customer)
                .where(Customer.identification == ci)
                .options(selectinload(Customer.phones))
            )
            customer = db.execute(stmt).scalar_one_or_none()
            if not customer:
                result.skipped += 1
                continue

            existing_numbers = {p.phone_number for p in customer.phones}
            added = 0

            for contact in contacts:
                if str(contact.get("phone_status", "")).upper() != "ACTIVE":
                    continue

                local_number = clean_phone_number(contact.get("phone_number"))
                if not local_number or local_number in existing_numbers:
                    continue

                raw_type = str(contact.get("phone_type", "")).upper()
                phone_type = _CONTACT_TYPE_MAP.get(raw_type, raw_type or None)

                db.add(CollectionPhone(
                    customer_id=customer.id,
                    country_code="+593",
                    phone_number=local_number,
                    phone_type=phone_type,
                    source="Collecta",
                ))
                existing_numbers.add(local_number)
                added += 1

            if added > 0:
                result.updated += 1
                logger.info("Customer %s — added %d contact phone(s) from Collecta.", ci, added)
            else:
                result.skipped += 1

        except Exception as exc:
            logger.error("Failed to sync contacts for %s: %s", ci, exc)
            result.errors.append(f"{ci}: {exc}")

    db.commit()
    logger.info(
        "Collecta contacts sync complete — updated: %d | skipped: %d | errors: %d",
        result.updated, result.skipped, len(result.errors),
    )
    return result


# ---------------------------------------------------------------------------
# Directions ETL — /public/api/directions
# ---------------------------------------------------------------------------

_ADDRESS_TYPE_MAP: dict[str, str] = {
    "DOMICILIO": "HOME",
    "TRABAJO":   "WORK",
    "GARANTE":   "GUARANTOR",
    "OTRO":      "OTHER",
}


def sync_collecta_directions(raw_directions: list[dict], db: Session) -> SyncResult:
    """
    Sincroniza direcciones desde el endpoint /directions de Collecta.
    Agrupa por client_ci y añade las que no existan ya (dedup por address_line+city).
    Campos origen: direction, type, province, canton, parish, neighborhood, client_ci.
    """
    result = SyncResult()

    # Agrupar por cédula
    directions_by_ci: dict[str, list[dict]] = defaultdict(list)
    for row in raw_directions:
        ci = clean_identification(str(row.get("client_ci", "")))
        if ci:
            directions_by_ci[ci].append(row)

    for ci, rows in directions_by_ci.items():
        try:
            stmt = (
                select(Customer)
                .where(Customer.identification == ci)
                .options(selectinload(Customer.addresses))
            )
            customer = db.execute(stmt).scalar_one_or_none()
            if not customer:
                result.skipped += 1
                continue

            # Claves de dedup: (address_line, city)
            existing_keys = {
                (a.address_line, a.city) for a in customer.addresses
            }
            added = 0

            for row in rows:
                # Componer address_line desde los campos disponibles
                parts = [
                    standardize_text(row.get("direction")),
                    standardize_text(row.get("neighborhood")),
                    standardize_text(row.get("parish")),
                ]
                address_line = " ".join(filter(None, parts)) or None

                province = standardize_text(row.get("province")) or None
                city     = standardize_text(row.get("canton"))   or None

                raw_type     = str(row.get("type", "")).upper()
                address_type = _ADDRESS_TYPE_MAP.get(raw_type, raw_type or None)

                key = (address_line, city)
                if key in existing_keys or not address_line:
                    continue

                db.add(CollectionAddress(
                    customer_id=customer.id,
                    address_line=address_line[:499] if address_line else None,
                    province=province,
                    city=city,
                    address_type=address_type,
                    source="Collecta",
                ))
                existing_keys.add(key)
                added += 1

            if added > 0:
                result.updated += 1
                logger.info("Customer %s — added %d address(es) from Collecta.", ci, added)
            else:
                result.skipped += 1

        except Exception as exc:
            logger.error("Failed to sync directions for %s: %s", ci, exc)
            result.errors.append(f"{ci}: {exc}")

    db.commit()
    logger.info(
        "Collecta directions sync complete — updated: %d | skipped: %d | errors: %d",
        result.updated, result.skipped, len(result.errors),
    )
    return result
