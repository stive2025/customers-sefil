"""
ETL para la fuente de datos "Leads" (MySQL externo en 172.20.1.102).

Lógica de extracción:
  - Conecta a MySQL mediante un Engine secundario (credenciales desde env vars).
  - Ejecuta un JOIN entre `leads` y `entries` filtrando por event = 'LEAD.UPDATED'.
  - Agrupa los contactos por identification y los fusiona con la PostgreSQL centralizada.

Comportamiento de fusión:
  - Solo añade teléfonos a clientes YA EXISTENTES en la BD central.
  - Evita duplicados por phone_number exacto.
  - Todos los registros insertados llevan source="Leads".
  - Un único db.commit() al final del lote (atómico).

Tablas origen (MySQL):
  leads   → lead_id, identification, ...
  entries → lead_id, event, field, value
"""

import logging
import os
from dataclasses import dataclass, field

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, selectinload

from app.models.collections import CollectionPhone
from app.models.customer import Customer
from app.services.data_cleaning import clean_identification, clean_phone_number
import json
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conexión MySQL externa (credenciales desde variables de entorno)
# ---------------------------------------------------------------------------

def _build_leads_url() -> str:
    user     = os.getenv("LEADS_DB_USER",     "leads_user")
    password = os.getenv("LEADS_DB_PASSWORD", "leads_password")
    host     = os.getenv("LEADS_DB_HOST",     "172.20.1.102")
    port     = os.getenv("LEADS_DB_PORT",     "3306")
    db       = os.getenv("LEADS_DB_NAME",     "leads_db")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}"


# ---------------------------------------------------------------------------
# Mapeo de nombres de campo en entries → phone_type interno
# ---------------------------------------------------------------------------

_PHONE_TYPE_MAP: dict[str, str] = {
    "TELEFONO TRABAJO":    "WORK",
    "TELEFONO CELULAR 1":  "MOBILE",
    "TELEFONO CELULAR 2":  "MOBILE",
    "TELEFONO DOMICILIO":  "HOME",
    "Telefono Particular": "PERSONAL",
}

# ---------------------------------------------------------------------------
# SQL de extracción (raw join)
# ---------------------------------------------------------------------------

_EXTRACT_SQL = text("""
    SELECT
        l.document AS identification,
        e.attributes AS raw_attributes
    FROM leads l
    JOIN entries e ON e.lead_id = l.id
    WHERE e.event = 'LEAD.UPDATED'
""")

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    customers_updated: int = 0
    phones_added: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_leads_phones() -> dict[str, list[dict[str, str | None]]]:
    """
    Abre una conexión MySQL, ejecuta el JOIN y devuelve un dict:
      { identification: [ {phone_number, phone_type}, ... ] }

    Raises:
        RuntimeError: si no puede conectar al MySQL externo.
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

    grouped: dict[str, list[dict[str, str | None]]] = {}
    
    for row in rows:
        # Usamos tu función de limpieza de cédula
        identification = clean_identification(row.get("identification"))
        if not identification:
            continue
            
        # Extraemos el paquete JSON
        raw_attributes = row.get("raw_attributes")
        if not raw_attributes:
            continue
            
        # Abrimos el paquete JSON
        try:
            attributes = json.loads(raw_attributes)
        except (json.JSONDecodeError, TypeError):
            continue # Si hay basura en lugar de un JSON válido, lo ignoramos
            
        # Iteramos sobre el mapa de traducción que ya tienes definido (_PHONE_TYPE_MAP)
        for leads_key, our_type in _PHONE_TYPE_MAP.items():
            # Si el JSON contiene la llave (ej. 'TELEFONO TRABAJO') y no está vacía:
            if leads_key in attributes and attributes[leads_key]:
                grouped.setdefault(identification, []).append({
                    "phone_number": str(attributes[leads_key]).strip(),
                    "phone_type": our_type,
                })

    return grouped


def _merge_phones(
    customer: Customer,
    phones: list[dict[str, str | None]],
    db: Session,
) -> int:
    """
    Inserta los teléfonos que aún no existen para el customer.
    Retorna el número de teléfonos efectivamente añadidos.
    """
    existing_numbers: set[str] = {p.phone_number for p in customer.phones}
    added = 0

    for phone_data in phones:
        local_number = clean_phone_number(phone_data["phone_number"])
        if not local_number or local_number in existing_numbers:
            continue

        db.add(CollectionPhone(
            customer_id=customer.id,
            country_code="+593",
            phone_number=local_number,
            phone_type=phone_data["phone_type"],
            source="Leads",
        ))
        existing_numbers.add(local_number)
        added += 1

    return added


# ---------------------------------------------------------------------------
# ETL entry point
# ---------------------------------------------------------------------------

def sync_leads_data(db_central: Session) -> SyncResult:
    """
    Extrae contactos de la BD MySQL "Leads" y los fusiona con la PostgreSQL centralizada.

    Solo modifica clientes que YA EXISTEN en la BD central (no crea registros nuevos).
    Los teléfonos nuevos se insertan con source="Leads".
    Un único commit al final garantiza atomicidad sobre todo el lote.

    Args:
        db_central: Sesión activa de SQLAlchemy apuntando a la PostgreSQL centralizada.

    Returns:
        SyncResult con contadores de customers_updated, phones_added, skipped y errors.
    """
    result = SyncResult()

    # 1. EXTRACT — obtener datos del MySQL externo
    try:
        leads_phones = _fetch_leads_phones()
    except Exception as exc:
        logger.error("Cannot extract data from Leads MySQL: %s", exc, exc_info=True)
        result.errors.append(f"MySQL extraction error: {exc}")
        return result

    logger.info("Leads extraction complete — %d unique identifications found.", len(leads_phones))

    # 2. TRANSFORM + LOAD — fusionar contra la PostgreSQL centralizada
    for identification, phones in leads_phones.items():
        try:
            stmt = (
                select(Customer)
                .where(Customer.identification == identification)
                .options(selectinload(Customer.phones))
            )
            customer = db_central.execute(stmt).scalar_one_or_none()

            if not customer:
                logger.debug("No customer found for identification %s — skipping.", identification)
                result.skipped += 1
                continue

            phones_added = _merge_phones(customer, phones, db_central)

            if phones_added:
                result.phones_added += phones_added
                result.customers_updated += 1
                logger.info(
                    "Customer %s — added %d phone(s) from Leads.",
                    identification,
                    phones_added,
                )

        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{identification}: {exc}")
            logger.error(
                "Error merging leads phones for customer %s: %s",
                identification,
                exc,
                exc_info=True,
            )

    # 3. COMMIT — único commit atómico al final del lote
    db_central.commit()
    logger.info(
        "Leads sync complete — customers_updated: %d | phones_added: %d | skipped: %d | errors: %d",
        result.customers_updated,
        result.phones_added,
        result.skipped,
        len(result.errors),
    )
    return result
