"""
ETL específico para DATA SEFIL.

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
    "contacts": [
        {"phone_number": "0991234567", "phone_type": "CELULAR"}
    ],
    "addresses": [
        {"address": "Av. 6 de Diciembre N24-01", "province": "PICHINCHA", "city": "QUITO", "type": "DOMICILIO"}
    ],
    "emails": [
        {"direction": "juan.perez@email.com", "active": true}
    ]
}
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.collections import CollectionAddress, CollectionEmail, CollectionPhone
from app.models.customer import Customer
from app.models.financial import FinancialInformation
from app.models.relationships import CustomerRelationship
from app.services.data_cleaning import (
    clean_civil_status,
    clean_date,
    clean_email,
    clean_gender,
    clean_identification,
    clean_phone_number,
    clean_salary,
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
        last_name = f"{parts[0]} {parts[1]}"
        first_name = " ".join(parts[2:])
    elif len(parts) == 3:
        last_name = f"{parts[0]} {parts[1]}"
        first_name = parts[2]
    else:
        last_name = parts[0]
        first_name = parts[1]

    return first_name, last_name


def _map_sefil_record(raw: dict) -> dict | None:
    """
    Maps a raw DATA SEFIL record to Customer model kwargs.
    Returns None if the record is invalid and must be skipped.
    """
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

    def _trunc(value: str | None, limit: int) -> str | None:
        return value[:limit] if value and len(value) > limit else value

    return {
        "identification": identification,
        "first_name": _trunc(first_name, 199),
        "last_name": _trunc(last_name, 199),
        "gender": clean_gender(raw.get("gender")),
        "birth_date": clean_date(raw.get("birth")),
        "birth_place": _trunc(standardize_text(raw.get("place_birth")) or None, 199),
        "civil_status": clean_civil_status(raw.get("state_civil")),
        "nationality": _trunc(standardize_text(raw.get("nationality")) or None, 99),
        "profession": _trunc(standardize_text(raw.get("profession")) or None, 499),
    }


def _sync_phones(customer: Customer, contacts_raw: list[dict], db: Session) -> None:
    """
    Inserts phones that don't already exist on the customer.
    Deduplication is by phone_number. Skips blank or uncleanable numbers.
    """
    existing_numbers = {p.phone_number for p in customer.phones}

    for contact in contacts_raw:
        local_number = clean_phone_number(contact.get("phone_number"))
        if not local_number or local_number in existing_numbers:
            continue

        raw_type = str(contact.get("phone_type", "")).upper()
        if "CELULAR" in raw_type:
            phone_type = "MOBILE"
        elif "FIJO" in raw_type:
            phone_type = "HOME"
        elif raw_type in ("ACTUALIZADO", "UPDATED", "OTRO"):
            phone_type = None
        else:
            phone_type = raw_type or None

        phone = CollectionPhone(
            customer_id=customer.id,
            country_code="+593",
            phone_number=local_number,
            phone_type=phone_type,
            source="DATA SEFIL",
        )
        db.add(phone)
        customer.phones.append(phone)
        existing_numbers.add(local_number)


def _sync_addresses(customer: Customer, addresses_raw: list[dict], db: Session) -> None:
    """
    Inserts addresses that don't already exist on the customer.
    Deduplication is by exact address_line match.
    """
    existing_lines = {a.address_line for a in customer.addresses}

    for addr_data in addresses_raw:
        address_line = standardize_text(addr_data.get("address"))
        if not address_line or address_line in existing_lines:
            continue

        raw_type = str(addr_data.get("type", "")).upper()
        if "DOMICILIO" in raw_type:
            address_type = "HOME"
        elif "TRABAJO" in raw_type:
            address_type = "WORK"
        else:
            address_type = raw_type or None

        addr = CollectionAddress(
            customer_id=customer.id,
            address_line=address_line,
            province=standardize_text(addr_data.get("province")) or None,
            city=standardize_text(addr_data.get("city")) or None,
            address_type=address_type,
            source="DATA SEFIL",
        )
        db.add(addr)
        customer.addresses.append(addr)
        existing_lines.add(address_line)


def _sync_emails(customer: Customer, emails_raw: list[dict], db: Session) -> None:
    """
    Inserts emails that don't already exist on the customer.
    Deduplication is by exact email_address match. Skips invalid formats.
    """
    existing_addresses = {e.email_address for e in customer.emails}

    for email_data in emails_raw:
        email_address = clean_email(email_data.get("direction"))
        if not email_address or email_address in existing_addresses:
            continue

        email = CollectionEmail(
            customer_id=customer.id,
            email_address=email_address,
            is_active=bool(email_data.get("active", True)),
            source="DATA SEFIL",
        )
        db.add(email)
        customer.emails.append(email)
        existing_addresses.add(email_address)


def _sync_relationships(customer: Customer, parents_raw: list[dict], db: Session) -> None:
    """
    Inserts family relationships from DATA SEFIL `parents` array.
    Deduplication by (relationship_type, related_identification or related_name).
    """
    existing_keys = {
        (r.relationship_type, r.related_identification or r.related_name)
        for r in customer.relationships
    }

    for parent in parents_raw:
        rel_type = str(parent.get("type", "")).upper().strip()
        if not rel_type:
            continue

        related_id = clean_identification(parent.get("identification")) or None
        related_name = standardize_text(parent.get("name")) or None
        dedup_key = (rel_type, related_id or related_name)

        if dedup_key in existing_keys:
            continue

        rel = CustomerRelationship(
            customer_id=customer.id,
            relationship_type=rel_type,
            related_identification=related_id,
            related_name=related_name,
            related_birth_date=clean_date(parent.get("birth")),
            related_gender=clean_gender(parent.get("gender")),
            related_civil_status=clean_civil_status(parent.get("state_civil")),
            related_death_date=clean_date(parent.get("death")) if parent.get("death") else None,
            source="DATA SEFIL",
        )
        db.add(rel)
        customer.relationships.append(rel)
        existing_keys.add(dedup_key)


def _sync_financial(customer: Customer, salary_raw: float | str | int | None, db: Session) -> None:
    """
    Creates or updates the One-to-One FinancialInformation record.
    Only sets salary if it is not already present on an existing record.
    """
    salary = clean_salary(salary_raw)
    if salary is None:
        return

    if customer.financial_information:
        if customer.financial_information.salary is None:
            customer.financial_information.salary = salary
    else:
        db.add(FinancialInformation(customer_id=customer.id, salary=salary))


# ---------------------------------------------------------------------------
# Main ETL entry point
# ---------------------------------------------------------------------------

_MERGEABLE_FIELDS: tuple[str, ...] = (
    "gender", "birth_date", "birth_place",
    "civil_status", "nationality", "profession",
)


def sync_datasefil_data(raw_data: list[dict], db: Session) -> SyncResult:
    """
    Upserts a batch of DATA SEFIL records into the centralized database.

    Merge strategy:
    - Match on `identification`.
    - New customer  → insert Customer + all relations (phones, addresses, emails, financial).
    - Existing customer → update demographic fields ONLY if currently null/empty;
      append new phones, addresses, and emails (anti-duplicate by exact value).
    - Single commit at the end of the batch (atomic transaction).

    Args:
        raw_data: List of raw dicts from DATA SEFIL.
        db:       Active SQLAlchemy session.

    Returns:
        SyncResult with counts of created, updated, skipped, and error records.
    """
    result = SyncResult()

    for raw in raw_data:
        try:
            customer_fields = _map_sefil_record(raw)
            if not customer_fields:
                result.skipped += 1
                continue

            identification: str = customer_fields["identification"]

            stmt = (
                select(Customer)
                .where(Customer.identification == identification)
                .options(
                    selectinload(Customer.phones),
                    selectinload(Customer.addresses),
                    selectinload(Customer.emails),
                    selectinload(Customer.financial_information),
                    selectinload(Customer.relationships),
                )
            )
            existing = db.execute(stmt).scalar_one_or_none()

            # Combine emails array + top-level "email" single field
            emails_raw = list(raw.get("emails", []))
            top_email = raw.get("email")
            if top_email:
                emails_raw.append({"direction": top_email, "active": 1})

            if existing:
                for attr in _MERGEABLE_FIELDS:
                    incoming = customer_fields.get(attr)
                    if incoming and not getattr(existing, attr):
                        setattr(existing, attr, incoming)

                _sync_phones(existing, raw.get("contacts", []), db)
                _sync_addresses(existing, raw.get("address", []), db)
                _sync_emails(existing, emails_raw, db)
                _sync_financial(existing, raw.get("salary"), db)
                _sync_relationships(existing, raw.get("parents", []), db)
                result.updated += 1
                logger.info("Updated customer %s", identification)

            else:
                new_customer = Customer(**customer_fields)
                db.add(new_customer)
                db.flush()  # resolve new_customer.id before adding children
                new_customer.phones = []
                new_customer.addresses = []
                new_customer.emails = []
                new_customer.financial_information = None
                new_customer.relationships = []

                _sync_phones(new_customer, raw.get("contacts", []), db)
                _sync_addresses(new_customer, raw.get("address", []), db)
                _sync_emails(new_customer, emails_raw, db)
                _sync_financial(new_customer, raw.get("salary"), db)
                _sync_relationships(new_customer, raw.get("parents", []), db)
                result.created += 1
                logger.info("Created customer %s", identification)

        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{raw.get('identification', '?')}: {exc}")
            logger.error(
                "Unexpected error processing record %r: %s",
                raw.get("identification"),
                exc,
                exc_info=True,
            )

    db.commit()
    logger.info(
        "DATA SEFIL sync complete — created: %d | updated: %d | skipped: %d | errors: %d",
        result.created,
        result.updated,
        result.skipped,
        len(result.errors),
    )
    return result
