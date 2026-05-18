"""
ETL para la fuente de datos "Leads" (MySQL externo en 172.20.1.102).

En la arquitectura híbrida este módulo ya NO escribe en PostgreSQL.
Sigue conectándose a MySQL (fuente de datos local) para extraer los registros,
los transforma en CustomerUpsertItem y los devuelve para que el Worker los
envíe vía HTTP al endpoint POST /sync/bulk-upsert de Hostinger.

Lógica de extracción:
  - Conecta a MySQL mediante un Engine (credenciales desde env vars).
  - Ejecuta un JOIN entre `leads` y `entries` filtrando event = 'LEAD.UPDATED'.
  - Del campo `attributes` (JSON) extrae: nombre, teléfono, email y dirección de trabajo.

Tablas origen (MySQL):
  leads   → id, document (cédula)
  entries → lead_id, event, attributes (JSON)

Campos del JSON `attributes`:
  Nombre  : PRIMER NOMBRE, SEGUNDO NOMBRE, APELLIDO PATERNO, APELLIDO MATERNO
  Teléfono: TELEFONO TRABAJO, TELEFONO CELULAR 1/2, TELEFONO DOMICILIO
  Email   : EMAIL PERSONAL, EMAIL TRABAJO, EMAIL
  Dirección: DIRECCION TRABAJO + PARROQUIA TRABAJO → address_line
             CANTON TRABAJO → city | PROVINCIA TRABAJO → province
"""

import json
import logging
import os

from sqlalchemy import create_engine, text

from app.schemas.sync import AddressItem, CustomerUpsertItem, EmailItem, PhoneItem
from app.services.data_cleaning import (
    clean_email,
    clean_identification,
    clean_phone_number,
    standardize_text,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MySQL connection
# ---------------------------------------------------------------------------

def _build_leads_url() -> str:
    user     = os.getenv("LEADS_DB_USER",     "leads_user")
    password = os.getenv("LEADS_DB_PASSWORD", "leads_password")
    host     = os.getenv("LEADS_DB_HOST",     "172.20.1.102")
    port     = os.getenv("LEADS_DB_PORT",     "3306")
    db       = os.getenv("LEADS_DB_NAME",     "leads_db")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}"


# ---------------------------------------------------------------------------
# JSON attribute maps
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
# SQL
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
# Internal: fetch and group from MySQL
# ---------------------------------------------------------------------------

def _fetch_leads_data() -> dict[str, dict]:
    """
    Connect to MySQL, run the JOIN and return:
      { identification: { first_name, last_name, phones, emails, addresses } }
    Multiple entries per lead are merged (first-wins for name).
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

        # Name (first entry with data wins)
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

        # Phones
        for key, phone_type in _PHONE_KEY_MAP.items():
            raw_number = attributes.get(key)
            if raw_number and str(raw_number).strip():
                number = str(raw_number).strip()
                if number not in entry["_seen_phones"]:
                    entry["phones"].append({"phone_number": number, "phone_type": phone_type})
                    entry["_seen_phones"].add(number)

        # Emails
        for email_key in _EMAIL_KEYS:
            raw_email = attributes.get(email_key)
            if raw_email and str(raw_email).strip():
                addr = str(raw_email).strip().lower()
                if addr not in entry["_seen_emails"]:
                    entry["emails"].append(addr)
                    entry["_seen_emails"].add(addr)

        # Work address
        parts = [
            standardize_text(attributes.get("DIRECCION TRABAJO")),
            standardize_text(attributes.get("PARROQUIA TRABAJO")),
        ]
        address_line = " ".join(filter(None, parts)) or None
        city         = standardize_text(attributes.get("CANTON TRABAJO"))   or None
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

    # Remove internal dedup sets
    for entry in grouped.values():
        entry.pop("_seen_phones", None)
        entry.pop("_seen_emails", None)
        entry.pop("_seen_addresses", None)

    return grouped


# ---------------------------------------------------------------------------
# Public prepare function — returns CustomerUpsertItem list, no PostgreSQL needed
# ---------------------------------------------------------------------------

def prepare_leads_customers() -> list[CustomerUpsertItem]:
    """
    Fetch leads from MySQL and return as a CustomerUpsertItem list.
    Phone numbers and email addresses are cleaned before being embedded.
    Records without a valid identification are silently dropped.
    """
    leads_data = _fetch_leads_data()
    logger.info("Leads extraction complete — %d unique identifications found.", len(leads_data))

    result: list[CustomerUpsertItem] = []

    for identification, data in leads_data.items():
        # Build phones (apply clean_phone_number)
        phones: list[PhoneItem] = []
        seen_phones: set[str] = set()
        for p in data["phones"]:
            local_number = clean_phone_number(p["phone_number"])
            if local_number and local_number not in seen_phones:
                phones.append(PhoneItem(
                    phone_number=local_number,
                    phone_type=p["phone_type"],
                    country_code="+593",
                    source="Leads",
                ))
                seen_phones.add(local_number)

        # Build emails (apply clean_email)
        emails: list[EmailItem] = []
        seen_emails: set[str] = set()
        for raw_addr in data["emails"]:
            email_address = clean_email(raw_addr)
            if email_address and email_address not in seen_emails:
                emails.append(EmailItem(
                    email_address=email_address,
                    is_active=True,
                    source="Leads",
                ))
                seen_emails.add(email_address)

        # Build addresses (already cleaned in _fetch_leads_data)
        addresses: list[AddressItem] = [
            AddressItem(
                address_line=a["address_line"],
                city=a["city"],
                province=a["province"],
                address_type=a["address_type"],
                source="Leads",
            )
            for a in data["addresses"]
        ]

        result.append(CustomerUpsertItem(
            identification=identification,
            first_name=data.get("first_name"),
            last_name=data.get("last_name") or "",
            phones=phones,
            emails=emails,
            addresses=addresses,
        ))

    logger.info("prepare_leads_customers — prepared: %d CustomerUpsertItems", len(result))
    return result
