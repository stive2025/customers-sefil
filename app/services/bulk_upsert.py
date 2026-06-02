"""
Server-side merge service consumed by POST /sync/bulk-upsert.
Accepts pre-cleaned CustomerUpsertItem records and merges them into PostgreSQL
using the same anti-duplicate, fill-empty-fields strategy as the individual ETLs.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.collections import CollectionAddress, CollectionEmail, CollectionPhone
from app.models.customer import Customer
from app.models.financial import FinancialInformation
from app.models.relationships import CustomerRelationship
from app.schemas.sync import (
    AddressItem,
    BulkUpsertResponse,
    CustomerUpsertItem,
    EmailItem,
    PhoneItem,
    RelationshipItem,
)
from app.services.data_cleaning import clean_salary

logger = logging.getLogger(__name__)

_DEMOGRAPHIC_FIELDS: tuple[str, ...] = (
    "gender", "birth_date", "birth_place",
    "nationality", "civil_status", "profession", "economic_activity"
)


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def _merge_phones(customer: Customer, phones: list[PhoneItem], db: Session) -> None:
    existing = {p.phone_number: p for p in customer.phones}
    for item in phones:
        if not item.phone_number:
            continue
        if item.phone_number in existing:
            phone = existing[item.phone_number]
            if item.calls_effective is not None:
                phone.calls_effective = item.calls_effective
            if item.calls_not_effective is not None:
                phone.calls_not_effective = item.calls_not_effective
        else:
            phone = CollectionPhone(
                customer_id=customer.id,
                phone_number=item.phone_number,
                phone_type=item.phone_type,
                country_code=item.country_code,
                created_source=item.created_source,
                calls_effective=item.calls_effective,
                calls_not_effective=item.calls_not_effective,
            )
            db.add(phone)
            customer.phones.append(phone)
            existing[item.phone_number] = phone


def _merge_addresses(customer: Customer, addresses: list[AddressItem], db: Session) -> None:
    existing = {(a.address_line, a.city) for a in customer.addresses}
    for item in addresses:
        if not item.address_line:
            continue
        key = (item.address_line, item.city)
        if key in existing:
            continue
        addr = CollectionAddress(
            customer_id=customer.id,
            address_line=item.address_line,
            province=item.province,
            city=item.city,
            canton=item.canton,
            parish=item.parish,
            neighborhood=item.neighborhood,
            address_type=item.address_type,
            latitude=item.latitude,
            longitude=item.longitude,
            source=item.source,
            created_source=item.source,
        )
        db.add(addr)
        customer.addresses.append(addr)
        existing.add(key)


def _merge_emails(customer: Customer, emails: list[EmailItem], db: Session) -> None:
    existing = {e.email_address for e in customer.emails}
    for item in emails:
        if not item.email_address or item.email_address in existing:
            continue
        email = CollectionEmail(
            customer_id=customer.id,
            email_address=item.email_address,
            is_active=item.is_active,
            source=item.source,
            created_source=item.source,
        )
        db.add(email)
        customer.emails.append(email)
        existing.add(item.email_address)


def _merge_financial(customer: Customer, salary: float | None, db: Session) -> None:
    value = clean_salary(salary)
    if value is None:
        return
    if customer.financial_information:
        if customer.financial_information.salary is None:
            customer.financial_information.salary = value
    else:
        db.add(FinancialInformation(customer_id=customer.id, salary=value))


def _merge_relationships(customer: Customer, rels: list[RelationshipItem], db: Session) -> None:
    existing = {
        (r.relationship_type, r.related_identification or r.related_name)
        for r in customer.relationships
    }
    for item in rels:
        key = (item.relationship_type, item.related_identification or item.related_name)
        if key in existing:
            continue
        rel = CustomerRelationship(
            customer_id=customer.id,
            relationship_type=item.relationship_type,
            related_identification=item.related_identification,
            related_name=item.related_name,
            related_birth_date=item.related_birth_date,
            related_gender=item.related_gender,
            related_civil_status=item.related_civil_status,
            related_death_date=item.related_death_date,
            source=item.source,
        )
        db.add(rel)
        customer.relationships.append(rel)
        existing.add(key)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def bulk_upsert_customers(
    customers: list[CustomerUpsertItem],
    db: Session,
) -> BulkUpsertResponse:
    """
    Merge a batch of pre-cleaned CustomerUpsertItem records into PostgreSQL.

    Strategy:
    - Existing customer → fill empty demographic fields + append new contacts.
    - New customer     → create only if first_name is present; skip otherwise.
    - Per-record savepoints isolate failures; single commit at the end.
    """
    result = BulkUpsertResponse()

    for item in customers:
        try:
            # ── SAVEPOINT wraps the entire per-record operation ──
            # This includes the SELECT so that if anything fails,
            # we rollback to a clean state and can continue with
            # the next record.
            with db.begin_nested():
                stmt = (
                    select(Customer)
                    .where(Customer.identification == item.identification)
                    .options(
                        selectinload(Customer.phones),
                        selectinload(Customer.addresses),
                        selectinload(Customer.emails),
                        selectinload(Customer.financial_information),
                        selectinload(Customer.relationships),
                    )
                )
                existing = db.execute(stmt).scalar_one_or_none()

                if existing:
                    for attr in _DEMOGRAPHIC_FIELDS:
                        incoming = getattr(item, attr)
                        if incoming and not getattr(existing, attr):
                            setattr(existing, attr, incoming)
                    if item.first_name and not existing.first_name:
                        existing.first_name = item.first_name
                    if item.last_name and not existing.last_name:
                        existing.last_name = item.last_name

                    _merge_phones(existing, item.phones, db)
                    _merge_addresses(existing, item.addresses, db)
                    _merge_emails(existing, item.emails, db)
                    _merge_financial(existing, item.salary, db)
                    _merge_relationships(existing, item.relationships, db)
                    result.updated += 1

                else:
                    if not item.first_name:
                        result.skipped += 1
                        continue

                    new_customer = Customer(
                        identification=item.identification,
                        first_name=item.first_name,
                        last_name=item.last_name or "",
                        gender=item.gender,
                        birth_date=item.birth_date,
                        birth_place=item.birth_place,
                        nationality=item.nationality,
                        civil_status=item.civil_status,
                        profession=item.profession,
                        economic_activity=item.economic_activity,
                    )
                    db.add(new_customer)
                    db.flush()
                    new_customer.phones = []
                    new_customer.addresses = []
                    new_customer.emails = []
                    new_customer.financial_information = None
                    new_customer.relationships = []

                    _merge_phones(new_customer, item.phones, db)
                    _merge_addresses(new_customer, item.addresses, db)
                    _merge_emails(new_customer, item.emails, db)
                    _merge_financial(new_customer, item.salary, db)
                    _merge_relationships(new_customer, item.relationships, db)
                    result.created += 1

        except Exception as exc:
            # ── The savepoint was already rolled back by begin_nested().__exit__
            # when the exception propagated. However, if the exception happened
            # outside the savepoint context, we must ensure the session is usable.
            db.rollback()
            result.errors.append(f"{item.identification}: {exc}")
            logger.error("Upsert error for %s: %s", item.identification, exc, exc_info=True)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Final commit failed: %s", exc, exc_info=True)
        result.errors.append(f"commit: {exc}")
    logger.info(
        "Bulk upsert complete — created: %d | updated: %d | skipped: %d | errors: %d",
        result.created, result.updated, result.skipped, len(result.errors),
    )
    return result
