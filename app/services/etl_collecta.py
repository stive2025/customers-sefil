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
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.collections import CollectionPhone
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

    return {
        "identification": identification,
        "first_name": first_name,
        "last_name": last_name,
        "gender": clean_gender(raw.get("gender")),
        "civil_status": clean_civil_status(raw.get("civil_status")),
        "profession": standardize_text(raw.get("economic_activity")) or None,
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

        stmt = (
            select(Customer)
            .where(Customer.identification == identification)
            .options(selectinload(Customer.phones))
        )
        existing = db.execute(stmt).scalar_one_or_none()

        if existing:
            for attr, value in customer_fields.items():
                if value is not None:
                    setattr(existing, attr, value)
            _sync_phones(existing, raw.get("phones", []), db)
            result.updated += 1
            logger.info("Updated customer %s", identification)
        else:
            new_customer = Customer(**customer_fields)
            db.add(new_customer)
            db.flush()  # resolve new_customer.id before adding children
            # Initialize phones list for _sync_phones dedup check
            new_customer.phones = []
            _sync_phones(new_customer, raw.get("phones", []), db)
            result.created += 1
            logger.info("Created customer %s", identification)

    db.commit()
    logger.info(
        "Collecta sync complete — created: %d | updated: %d | skipped: %d",
        result.created,
        result.updated,
        result.skipped,
    )
    return result
