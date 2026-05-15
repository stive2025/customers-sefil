"""
ETL para la fuente de datos "Leads" (MySQL externo en 172.20.1.102).

Lógica de extracción:
  - Conecta a MySQL mediante un Engine secundario (credenciales desde env vars).
  - Ejecuta un JOIN entre `leads` y `entries` filtrando por event = 'LEAD.UPDATED'.
  - Del campo `attributes` (JSON) extrae: nombre, teléfono, email y dirección de trabajo.

Comportamiento de fusión:
  - Cliente YA EXISTE en BD central → añade teléfono/email/dirección si son nuevos.
  - Cliente NO EXISTE → lo crea con los datos del JSON y añade sus contactos.
  - Deduplicación por phone_number, email_address y (address_line, city).
  - Todos los registros llevan source="Leads".
  - Commit único al final del lote (atómico).

Tablas origen (MySQL):
  leads   → id, document (cédula)
  entries → lead_id, event, attributes (JSON)

Campos del JSON `attributes`:
  Nombre  : PRIMER NOMBRE, SEGUNDO NOMBRE, APELLIDO PATERNO, APELLIDO MATERNO
  Teléfono: TELEFONO TRABAJO, TELEFONO CELULAR 1/2, TELEFONO DOMICILIO
  Email   : EMAIL PERSONAL
  Dirección: DIRECCION TRABAJO + PARROQUIA TRABAJO → address_line
             CANTON TRABAJO → city | PROVINCIA TRABAJO → province
"""

import json
import logging
import os
from dataclasses import dataclass, field

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.collections import CollectionAddress, CollectionEmail, CollectionPhone
from app.models.customer import Customer
from app.services.data_cleaning import (
    clean_email,
    clean_identification,
    clean_phone_number,
    standardize_text,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conexión MySQL externa
# ---------------------------------------------------------------------------

def _build_leads_url() -> str:
    user     = os.getenv("LEADS_DB_USER",     "leads_user")
    password = os.getenv("LEADS_DB_PASSWORD", "leads_password")
    host     = os.getenv("LEADS_DB_HOST",     "172.20.1.102")
    port     = os.getenv("LEADS_DB_PORT",     "3306")
    db       = os.getenv("LEADS_DB_NAME",     "leads_db")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}"


# ---------------------------------------------------------------------------
# Mapeos de claves del JSON
# ---------------------------------------------------------------------------

_PHONE_KEY_MAP: dict[str, str] = {
    "TELEFONO TRABAJO":    "WORK",
    "TELEFONO CELULAR 1":  "MOBILE",
    "TELEFONO CELULAR 2":  "MOBILE",
    "TELEFONO DOMICILIO":  "HOME",
    "Telefono Particular": "HOME",
}

_EMAIL_KEYS: tuple[str, ...] = ("EMAIL PERSONAL", "EMAIL TRABAJO", "EMAIL")


# ---------------------------------------------------------------------------
# SQL de extracción
# ---------------------------------------------------------------------------

_EXTRACT_SQL = text("""
    SELECT
        l.document        AS identification,
        e.attributes      AS raw_attributes
    FROM leads l
    JOIN entries e ON e.lead_id = l.id
    WHERE e.event = 'LEAD.UPDATED'
      AND e.attributes IS NOT NULL
""")


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    customers_created: int = 0
    customers_updated: int = 0
    phones_added: int = 0
    emails_added: int = 0
    addresses_added: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extracción desde MySQL
# ---------------------------------------------------------------------------

def _fetch_leads_data() -> dict[str, dict]:
    """
    Abre MySQL, ejecuta el JOIN y devuelve:
      {
        identification: {
          first_name, last_name,
          phones: [...], emails: [...], addresses: [...]
        }
      }
    Deduplicación interna para múltiples entries por lead.
    """
    engine = create_engine(
        _build_leads_url(),
        echo=False,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(_EXTRACT_SQL).mappings().all()
    finally:
        engine.dispose()

    grouped: dict[str, dict] = {}

    for row in rows:
        identification = clean_identification(str(row.get("identification") or ""))
        if not identification:
            continue

        raw_attributes = row.get("raw_attributes")
        try:
            attributes: dict = json.loads(raw_attributes)
        except (json.JSONDecodeError, TypeError):
            continue

        entry = grouped.setdefault(identification, {
            "first_name":      None,
            "last_name":       None,
            "phones":          [],
            "emails":          [],
            "addresses":       [],
            "_seen_phones":    set(),
            "_seen_emails":    set(),
            "_seen_addresses": set(),
        })

        # — Nombre (primer entry con datos gana) —
        if not entry["first_name"]:
            parts = [
                standardize_text(attributes.get("PRIMER NOMBRE")),
                standardize_text(attributes.get("SEGUNDO NOMBRE")),
            ]
            fn = " ".join(filter(None, parts)) or None
            if fn:
                entry["first_name"] = fn

        if not entry["last_name"]:
            parts = [
                standardize_text(attributes.get("APELLIDO PATERNO")),
                standardize_text(attributes.get("APELLIDO MATERNO")),
            ]
            ln = " ".join(filter(None, parts)) or None
            if ln:
                entry["last_name"] = ln

        # — Teléfonos —
        for key, phone_type in _PHONE_KEY_MAP.items():
            raw_number = attributes.get(key)
            if raw_number and str(raw_number).strip():
                number = str(raw_number).strip()
                if number not in entry["_seen_phones"]:
                    entry["phones"].append({"phone_number": number, "phone_type": phone_type})
                    entry["_seen_phones"].add(number)

        # — Email —
        for email_key in _EMAIL_KEYS:
            raw_email = attributes.get(email_key)
            if raw_email and str(raw_email).strip():
                addr = str(raw_email).strip().lower()
                if addr not in entry["_seen_emails"]:
                    entry["emails"].append(addr)
                    entry["_seen_emails"].add(addr)

        # — Dirección de trabajo —
        parts = [
            standardize_text(attributes.get("DIRECCION TRABAJO")),
            standardize_text(attributes.get("PARROQUIA TRABAJO")),
        ]
        address_line = " ".join(filter(None, parts)) or None
        city         = standardize_text(attributes.get("CANTON TRABAJO")) or None
        province     = standardize_text(attributes.get("PROVINCIA TRABAJO")) or None

        if address_line:
            key_addr = (address_line, city)
            if key_addr not in entry["_seen_addresses"]:
                entry["addresses"].append({
                    "address_line": address_line[:499],
                    "city":         city,
                    "province":     province,
                    "address_type": "WORK",
                })
                entry["_seen_addresses"].add(key_addr)

    # Limpiar sets internos de dedup
    for entry in grouped.values():
        entry.pop("_seen_phones", None)
        entry.pop("_seen_emails", None)
        entry.pop("_seen_addresses", None)

    return grouped


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def _merge_phones(customer: Customer, phones: list[dict], db: Session) -> int:
    existing = {p.phone_number for p in customer.phones}
    added = 0
    for item in phones:
        local_number = clean_phone_number(item["phone_number"])
        if not local_number or local_number in existing:
            continue
        phone = CollectionPhone(
            customer_id=customer.id,
            country_code="+593",
            phone_number=local_number,
            phone_type=item["phone_type"],
            source="Leads",
        )
        db.add(phone)
        customer.phones.append(phone)
        existing.add(local_number)
        added += 1
    return added


def _merge_emails(customer: Customer, raw_emails: list[str], db: Session) -> int:
    existing = {e.email_address for e in customer.emails}
    added = 0
    for raw_addr in raw_emails:
        email_address = clean_email(raw_addr)
        if not email_address or email_address in existing:
            continue
        email = CollectionEmail(
            customer_id=customer.id,
            email_address=email_address,
            is_active=True,
            source="Leads",
        )
        db.add(email)
        customer.emails.append(email)
        existing.add(email_address)
        added += 1
    return added


def _merge_addresses(customer: Customer, addresses: list[dict], db: Session) -> int:
    existing = {(a.address_line, a.city) for a in customer.addresses}
    added = 0
    for addr_data in addresses:
        key = (addr_data["address_line"], addr_data["city"])
        if key in existing:
            continue
        addr = CollectionAddress(
            customer_id=customer.id,
            address_line=addr_data["address_line"],
            city=addr_data["city"],
            province=addr_data["province"],
            address_type=addr_data["address_type"],
            source="Leads",
        )
        db.add(addr)
        customer.addresses.append(addr)
        existing.add(key)
        added += 1
    return added


# ---------------------------------------------------------------------------
# ETL entry point
# ---------------------------------------------------------------------------

def sync_leads_data(db_central: Session) -> SyncResult:
    """
    Extrae datos de la BD MySQL "Leads" y los fusiona con la PostgreSQL centralizada.

    - Clientes existentes: añade teléfonos, emails y direcciones nuevos.
    - Clientes nuevos: los crea con los datos del JSON y añade sus contactos.
    - Un único commit al final garantiza atomicidad sobre todo el lote.
    """
    result = SyncResult()

    try:
        leads_data = _fetch_leads_data()
    except Exception as exc:
        logger.error("Cannot extract data from Leads MySQL: %s", exc, exc_info=True)
        result.errors.append(f"MySQL extraction error: {exc}")
        return result

    logger.info("Leads extraction complete — %d unique identifications found.", len(leads_data))

    for identification, data in leads_data.items():
        try:
            stmt = (
                select(Customer)
                .where(Customer.identification == identification)
                .options(
                    selectinload(Customer.phones),
                    selectinload(Customer.emails),
                    selectinload(Customer.addresses),
                )
            )
            customer = db_central.execute(stmt).scalar_one_or_none()

            if not customer:
                # Crear cliente nuevo desde los datos del JSON
                first_name = data.get("first_name")
                last_name  = data.get("last_name") or ""

                if not first_name:
                    logger.debug("No name for %s — skipping.", identification)
                    result.skipped += 1
                    continue

                with db_central.begin_nested():
                    new_customer = Customer(
                        identification=identification,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    db_central.add(new_customer)
                    db_central.flush()
                    new_customer.phones    = []
                    new_customer.emails    = []
                    new_customer.addresses = []

                    phones_added    = _merge_phones(new_customer, data["phones"], db_central)
                    emails_added    = _merge_emails(new_customer, data["emails"], db_central)
                    addresses_added = _merge_addresses(new_customer, data["addresses"], db_central)

                result.customers_created += 1
                result.phones_added      += phones_added
                result.emails_added      += emails_added
                result.addresses_added   += addresses_added
                logger.info(
                    "Created customer %s (%s %s) — phones: +%d | emails: +%d | addresses: +%d",
                    identification, first_name, last_name,
                    phones_added, emails_added, addresses_added,
                )

            else:
                phones_added    = _merge_phones(customer, data["phones"], db_central)
                emails_added    = _merge_emails(customer, data["emails"], db_central)
                addresses_added = _merge_addresses(customer, data["addresses"], db_central)

                if phones_added or emails_added or addresses_added:
                    result.phones_added      += phones_added
                    result.emails_added      += emails_added
                    result.addresses_added   += addresses_added
                    result.customers_updated += 1
                    logger.info(
                        "Updated customer %s — phones: +%d | emails: +%d | addresses: +%d",
                        identification, phones_added, emails_added, addresses_added,
                    )

        except IntegrityError:
            db_central.rollback()
            logger.warning("Duplicate identification %s — skipping.", identification)
            result.skipped += 1
        except Exception as exc:
            result.errors.append(f"{identification}: {exc}")
            logger.error("Error processing lead %s: %s", identification, exc, exc_info=True)

    db_central.commit()
    logger.info(
        "Leads sync complete — created: %d | updated: %d | phones: +%d | emails: +%d | "
        "addresses: +%d | skipped: %d | errors: %d",
        result.customers_created,
        result.customers_updated,
        result.phones_added,
        result.emails_added,
        result.addresses_added,
        result.skipped,
        len(result.errors),
    )
    return result
