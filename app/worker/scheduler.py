"""
Scheduler de Sincronización — Arquitectura Híbrida.

El Worker ya NO conecta a PostgreSQL. El ciclo completo es:
  1. Extraer datos de Collecta / DATA SEFIL / Leads MySQL (fuentes locales).
  2. Transformar en CustomerUpsertItem (limpieza local).
  3. Enviar por HTTP POST al endpoint /sync/bulk-upsert en Hostinger.

Variables de entorno requeridas:
  HOSTINGER_API_URL   URL base de la API pública (ej. https://services.sefil.com.ec/customers/api/v1)
  HOSTINGER_API_KEY   API Key válida (X-API-Key header)
  COLLECTA_API_URL    URL del endpoint /clients de Collecta
  COLLECTA_TOKEN      Bearer token de Collecta
  DATASEFIL_API_URL   URL del endpoint /clients de DATA SEFIL
  DATASEFIL_TOKEN     Bearer token de DATA SEFIL
  LEADS_DB_*          Credenciales MySQL de Leads
  SYNC_SCHEDULE_1     Primera hora de ejecución (HH:MM, ej. "02:00")
  SYNC_SCHEDULE_2     Segunda hora de ejecución (HH:MM, ej. "12:00")

Uso:
  python -m app.worker.scheduler
  python -c "from app.worker.scheduler import run_all_syncs; run_all_syncs()"
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import schedule
from dotenv import load_dotenv

load_dotenv()  # no-op si las variables ya existen en el entorno

from app.services.etl_collecta import (
    prepare_collecta_contacts,
    prepare_collecta_customers,
    prepare_collecta_directions,
)
from app.services.etl_datasefil import prepare_datasefil_customers
from app.services.etl_leads import prepare_leads_customers
from app.worker.http_sender import send_customers

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# Pagination helpers (extraction — unchanged from previous architecture)
# ---------------------------------------------------------------------------

_PER_PAGE    = 100
_MAX_WORKERS = 5


def _fetch_collecta_page(url: str, headers: dict, page: int) -> tuple[list[dict], int]:
    """Download one Collecta page; return (records, last_page)."""
    resp = requests.get(
        url, headers=headers,
        params={"page": page, "per_page": _PER_PAGE},
        timeout=30,
    )
    resp.raise_for_status()
    block = resp.json().get("result", {})
    return block.get("data", []), block.get("last_page", 1)


def _fetch_datasefil_page(url: str, headers: dict, page: int) -> tuple[list[dict], int]:
    """Download one DATA SEFIL page; return (records, last_page)."""
    resp = requests.get(
        url, headers=headers,
        params={"page": page, "per_page": _PER_PAGE},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", []), body.get("last_page", 1)


def _fetch_all_pages(
    fetch_fn,
    url: str,
    headers: dict,
    label: str,
) -> list[dict]:
    """Fetch page 1 to discover last_page, then download remaining pages in parallel."""
    try:
        first_records, last_page = fetch_fn(url, headers, 1)
    except Exception as exc:
        logger.error("[%s] Cannot fetch page 1: %s", label, exc)
        return []

    logger.info("[%s] %d page(s) to download (per_page=%d)", label, last_page, _PER_PAGE)
    all_records = list(first_records)

    if last_page > 1:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            futures = {
                executor.submit(fetch_fn, url, headers, p): p
                for p in range(2, last_page + 1)
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    records, _ = future.result()
                    all_records.extend(records)
                except Exception as exc:
                    logger.warning("[%s] Error on page %d: %s", label, page_num, exc)

    logger.info("[%s] %d total records downloaded.", label, len(all_records))
    return all_records


# ---------------------------------------------------------------------------
# Per-source runners  (extract → transform → send)
# ---------------------------------------------------------------------------

def _run_collecta() -> None:
    """Step 1 — Collecta /clients."""
    url   = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token = os.getenv("COLLECTA_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    raw = _fetch_all_pages(_fetch_collecta_page, url, headers, "Collecta-clients")
    if not raw:
        return

    customers = prepare_collecta_customers(raw)
    send_customers(customers, "Collecta-clients")


def _run_collecta_contacts() -> None:
    """Step 2 — Collecta /contacts."""
    base_url = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    url      = base_url.rsplit("/", 1)[0] + "/contacts"
    token    = os.getenv("COLLECTA_TOKEN", "")
    headers  = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    raw = _fetch_all_pages(_fetch_collecta_page, url, headers, "Collecta-contacts")
    if not raw:
        return

    customers = prepare_collecta_contacts(raw)
    send_customers(customers, "Collecta-contacts")


def _run_collecta_directions() -> None:
    """Step 3 — Collecta /directions."""
    base_url = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    url      = base_url.rsplit("/", 1)[0] + "/directions"
    token    = os.getenv("COLLECTA_TOKEN", "")
    headers  = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    raw = _fetch_all_pages(_fetch_collecta_page, url, headers, "Collecta-directions")
    if not raw:
        return

    customers = prepare_collecta_directions(raw)
    send_customers(customers, "Collecta-directions")


def _run_datasefil() -> None:
    """Step 4 — DATA SEFIL /clients."""
    url     = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token   = os.getenv("DATASEFIL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    raw = _fetch_all_pages(_fetch_datasefil_page, url, headers, "DATA SEFIL")
    if not raw:
        return

    customers = prepare_datasefil_customers(raw)
    send_customers(customers, "DATA SEFIL")


def _run_leads() -> None:
    """Step 5 — Leads (MySQL externo)."""
    try:
        customers = prepare_leads_customers()
    except Exception as exc:
        logger.error("[Leads] MySQL extraction failed: %s", exc, exc_info=True)
        return

    send_customers(customers, "Leads")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_all_syncs() -> None:
    """
    Execute all 5 ETL steps sequentially.
    Each step is isolated — an error in one does not abort the rest.
    No database session is created here; all persistence happens via HTTP.
    """
    logger.info("=" * 60)
    logger.info("INICIO DE CICLO DE SINCRONIZACIÓN (Worker → Hostinger)")
    logger.info("=" * 60)

    steps = [
        ("Collecta clients",    _run_collecta),
        ("Collecta contacts",   _run_collecta_contacts),
        ("Collecta directions", _run_collecta_directions),
        ("DATA SEFIL",          _run_datasefil),
        ("Leads",               _run_leads),
    ]

    for name, runner in steps:
        logger.info("--- [%s] Iniciando ---", name)
        try:
            runner()
        except Exception as exc:
            logger.error(
                "[%s] Error inesperado — el ciclo continúa. Detalle: %s",
                name, exc, exc_info=True,
            )

    logger.info("=" * 60)
    logger.info("CICLO DE SINCRONIZACIÓN COMPLETADO")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Schedule registration
# ---------------------------------------------------------------------------

def _register_schedules() -> int:
    registered = 0
    for var in ("SYNC_SCHEDULE_1", "SYNC_SCHEDULE_2"):
        horario = os.getenv(var, "").strip()
        if not horario:
            continue
        parts = horario.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            logger.warning(
                "Valor inválido para %s=%r — se ignora (formato esperado: HH:MM)", var, horario
            )
            continue
        schedule.every().day.at(horario).do(run_all_syncs)
        logger.info("Job registrado desde %s: ejecución diaria a las %s", var, horario)
        registered += 1
    return registered


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Iniciando Scheduler de Sincronización (arquitectura híbrida)…")

    jobs_registered = _register_schedules()

    if jobs_registered == 0:
        logger.warning(
            "No se encontraron horarios configurados. "
            "Define SYNC_SCHEDULE_1 y/o SYNC_SCHEDULE_2 en el entorno. "
            "El scheduler permanece activo pero no ejecutará jobs."
        )
    else:
        logger.info("%d job(s) programado(s):", jobs_registered)
        for job in schedule.get_jobs():
            logger.info("  • %s", job)

    logger.info("Bucle de ejecución iniciado (intervalo de comprobación: 60 s).")
    while True:
        schedule.run_pending()
        time.sleep(60)
