"""
Servicio de Sincronización Unificada (MDM Hub).

Expone sync_external_customer() como punto de entrada único para cualquier
sistema externo que necesite crear o enriquecer un registro de Customer.

Reglas de fusión:
  - Clave de búsqueda: identification (acepta variantes de nombre de campo).
  - Cliente nuevo    : crea Customer + relaciones etiquetadas con source.
  - Cliente existente: actualiza solo campos vacíos + añade contactos nuevos
                       sin sobreescribir data ya registrada.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.collections import CollectionAddress, CollectionEmail, CollectionPhone
from app.models.customer import Customer
from app.models.financial import FinancialInformation
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

_MERGEABLE_FIELDS: tuple[str, ...] = (
    "gender", "birth_date", "birth_place",
    "civil_status", "nationality", "profession",
)


# ---------------------------------------------------------------------------
# Extracción flexible desde el payload
# ---------------------------------------------------------------------------

def _extract_identification(payload: dict) -> str | None:
    for key in ("identification", "ci", "cedula", "document"):
        if raw := payload.get(key):
            return clean_identification(str(raw))
    return None


def _parse_name(full_name: str) -> tuple[str, str]:
    """Formato ecuatoriano: 'APELLIDO1 APELLIDO2 NOMBRE1 NOMBRE2' → (first, last)."""
    parts = full_name.strip().split()
    if len(parts) <= 1:
        return full_name.strip(), ""
    if len(parts) >= 4:
        return " ".join(parts[2:]), f"{parts[0]} {parts[1]}"
    if len(parts) == 3:
        return parts[2], f"{parts[0]} {parts[1]}"
    return parts[1], parts[0]


def _extract_name(payload: dict) -> tuple[str, str]:
    first = standardize_text(payload.get("first_name") or payload.get("nombres") or "")
    last  = standardize_text(payload.get("last_name")  or payload.get("apellidos") or "")
    if first:
        return first, last
    raw = standardize_text(payload.get("name") or payload.get("nombre_completo") or "")
    return _parse_name(raw) if raw else ("", "")


def _build_customer_fields(
    payload: dict,
    identification: str,
    first_name: str,
    last_name: str,
) -> dict:
    return {
        "identification": identification,
        "first_name":   first_name,
        "last_name":    last_name,
        "gender":       clean_gender(payload.get("gender")),
        "birth_date":   clean_date(payload.get("birth_date") or payload.get("birth")),
        "birth_place":  standardize_text(payload.get("birth_place") or payload.get("place_birth")) or None,
        "civil_status": clean_civil_status(payload.get("civil_status") or payload.get("state_civil")),
        "nationality":  standardize_text(payload.get("nationality")) or None,
        "profession":   standardize_text(payload.get("profession") or payload.get("economic_activity")) or None,
    }


# ---------------------------------------------------------------------------
# Sincronización de relaciones (anti-duplicado por valor exacto)
# ---------------------------------------------------------------------------

def _sync_phones(customer: Customer, phones_raw: list[dict], source: str, db: Session) -> None:
    existing: set[str] = {p.phone_number for p in customer.phones}
    for phone_data in phones_raw:
        local_number = clean_phone_number(phone_data.get("phone_number"))
        if not local_number or local_number in existing:
            continue
        db.add(CollectionPhone(
            customer_id=customer.id,
            country_code="+593",
            phone_number=local_number,
            phone_type=phone_data.get("phone_type"),
            source=source,
        ))
        existing.add(local_number)


def _sync_addresses(customer: Customer, addresses_raw: list[dict], source: str, db: Session) -> None:
    existing: set[str] = {a.address_line for a in customer.addresses}
    for addr_data in addresses_raw:
        address_line = standardize_text(
            addr_data.get("address_line") or addr_data.get("address")
        )
        if not address_line or address_line in existing:
            continue
        db.add(CollectionAddress(
            customer_id=customer.id,
            address_line=address_line,
            province=standardize_text(addr_data.get("province")) or None,
            city=standardize_text(addr_data.get("city")) or None,
            address_type=addr_data.get("address_type"),
            source=source,
        ))
        existing.add(address_line)


def _sync_emails(customer: Customer, emails_raw: list[dict], source: str, db: Session) -> None:
    existing: set[str] = {e.email_address for e in customer.emails}
    for email_data in emails_raw:
        email_address = clean_email(
            email_data.get("email_address") or email_data.get("direction")
        )
        if not email_address or email_address in existing:
            continue
        db.add(CollectionEmail(
            customer_id=customer.id,
            email_address=email_address,
            is_active=bool(email_data.get("is_active", True)),
            source=source,
        ))
        existing.add(email_address)


def _sync_financial(customer: Customer, salary_raw: float | str | int | None, db: Session) -> None:
    salary = clean_salary(salary_raw)
    if salary is None:
        return
    if customer.financial_information:
        if customer.financial_information.salary is None:
            customer.financial_information.salary = salary
    else:
        db.add(FinancialInformation(customer_id=customer.id, salary=salary))


# ---------------------------------------------------------------------------
# Punto de entrada principal
# ---------------------------------------------------------------------------

def sync_external_customer(db: Session, payload: dict, source: str) -> Customer:
    """
    Crea o enriquece un Customer a partir de un payload de sistema externo.

    Merge rules:
      - identification es la clave única de búsqueda.
      - Cliente nuevo    : inserta Customer + contactos con source.
      - Cliente existente: actualiza campos vacíos + añade contactos nuevos.
      - Un único db.commit() garantiza atomicidad.

    Args:
        db:      Sesión activa de SQLAlchemy (PostgreSQL central).
        payload: Dict con los datos del sistema externo.
        source:  Etiqueta del sistema origen, ej. "Collecta", "DATA SEFIL".

    Returns:
        Objeto Customer creado/actualizado y refrescado desde la BD.

    Raises:
        ValueError: si no puede extraerse identification o nombre del payload.
    """
    identification = _extract_identification(payload)
    if not identification:
        raise ValueError(
            f"No se pudo extraer una identification válida del payload: {payload!r}"
        )

    first_name, last_name = _extract_name(payload)
    if not first_name:
        raise ValueError(
            f"No se pudo extraer el nombre del payload para identification={identification!r}"
        )

    stmt = (
        select(Customer)
        .where(Customer.identification == identification)
        .options(
            selectinload(Customer.phones),
            selectinload(Customer.addresses),
            selectinload(Customer.emails),
            selectinload(Customer.financial_information),
        )
    )
    customer = db.execute(stmt).scalar_one_or_none()
    customer_fields = _build_customer_fields(payload, identification, first_name, last_name)

    if customer:
        for attr in _MERGEABLE_FIELDS:
            incoming = customer_fields.get(attr)
            if incoming and not getattr(customer, attr):
                setattr(customer, attr, incoming)
        logger.info("Enriqueciendo cliente %s desde fuente %r", identification, source)
    else:
        customer = Customer(**customer_fields)
        db.add(customer)
        db.flush()
        customer.phones = []
        customer.addresses = []
        customer.emails = []
        customer.financial_information = None
        logger.info("Creando cliente %s desde fuente %r", identification, source)

    # "phones" (Collecta) y "contacts" (DATA SEFIL) apuntan al mismo concepto
    phones_raw    = payload.get("phones") or payload.get("contacts") or []
    addresses_raw = payload.get("addresses") or []
    emails_raw    = payload.get("emails")   or []

    _sync_phones(customer, phones_raw, source, db)
    _sync_addresses(customer, addresses_raw, source, db)
    _sync_emails(customer, emails_raw, source, db)
    _sync_financial(customer, payload.get("salary"), db)

    db.commit()
    db.refresh(customer)
    return customer