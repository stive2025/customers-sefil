"""
Sincronización manual de fuentes LAN → Hostinger.

Uso:
  python sync_manual.py --source datasefil
  python sync_manual.py --source leads
  python sync_manual.py --source collecta
  python sync_manual.py --source all

Variables de entorno requeridas (se leen de .env.worker automáticamente):
  HOSTINGER_API_URL   URL base del API público  (ej. https://services.sefil.com.ec/customers/api/v1)
  HOSTINGER_API_KEY   API Key válida            (X-API-Key header)
  COLLECTA_API_URL    URL del endpoint /clients de Collecta
  COLLECTA_TOKEN      Bearer token de Collecta
  DATASEFIL_API_URL   URL del endpoint /clients de DATA SEFIL
  DATASEFIL_TOKEN     Bearer token de DATA SEFIL
  LEADS_DB_*          Credenciales MySQL de Leads
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

# Cargar .env.sync antes de importar los módulos de la app
load_dotenv(".env.sync")

from app.services.etl_collecta import (
    prepare_collecta_contacts,
    prepare_collecta_customers,
)
from app.services.etl_datasefil import prepare_datasefil_customers
from app.services.etl_fetcher import fetch_all_pages, fetch_collecta_page, fetch_datasefil_page
from app.services.etl_leads import prepare_leads_customers
from app.schemas.sync import CustomerUpsertItem

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_manual")

# ---------------------------------------------------------------------------
# Envío HTTP → Hostinger /sync/bulk-upsert
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 500
_TIMEOUT    = 120


@dataclass
class SendStats:
    chunks_sent: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _send_to_hostinger(customers: list[CustomerUpsertItem], label: str) -> SendStats:
    """Envía los registros en chunks al /sync/bulk-upsert de Hostinger."""
    api_url = os.getenv("HOSTINGER_API_URL", "").rstrip("/")
    api_key = os.getenv("HOSTINGER_API_KEY", "")

    if not api_url or not api_key:
        logger.error("Faltan HOSTINGER_API_URL o HOSTINGER_API_KEY en .env.worker")
        sys.exit(1)

    endpoint = f"{api_url}/sync/bulk-upsert"
    headers  = {"X-API-Key": api_key, "Content-Type": "application/json"}
    stats    = SendStats()

    chunks = [customers[i:i + _CHUNK_SIZE] for i in range(0, len(customers), _CHUNK_SIZE)]
    total  = len(chunks)

    for i, chunk in enumerate(chunks, 1):
        payload = {"customers": [c.model_dump(mode="json") for c in chunk]}
        try:
            import time
            t0 = time.time()
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=_TIMEOUT)
            elapsed = time.time() - t0
            resp.raise_for_status()
            data = resp.json()
            stats.chunks_sent += 1
            stats.created  += data.get("created", 0)
            stats.updated  += data.get("updated", 0)
            stats.skipped  += data.get("skipped", 0)
            stats.errors   += data.get("errors", [])
            logger.info(
                "[%s] Chunk %d/%d — HTTP %d (%.1fs) | created: +%d | updated: +%d | skipped: %d | errors: %d",
                label, i, total, resp.status_code, elapsed,
                data.get("created", 0), data.get("updated", 0),
                data.get("skipped", 0), len(data.get("errors", [])),
            )
        except Exception as exc:
            stats.errors.append(str(exc))
            logger.error("[%s] Chunk %d/%d — ERROR: %s", label, i, total, exc)

    logger.info(
        "[%s] TOTAL — chunks: %d | created: %d | updated: %d | skipped: %d | errors: %d",
        label, stats.chunks_sent, stats.created, stats.updated, stats.skipped, len(stats.errors),
    )
    return stats


# ---------------------------------------------------------------------------
# Runners por fuente
# ---------------------------------------------------------------------------

def run_collecta() -> None:
    url     = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token   = os.getenv("COLLECTA_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base    = url.rsplit("/", 1)[0]

    for label, endpoint, prepare_fn in [
        ("Collecta-clients",    url,                  prepare_collecta_customers),
        ("Collecta-contacts",   f"{base}/contacts",   prepare_collecta_contacts),
        # Collecta /directions ahora requiere client_ci por registro — no permite descarga masiva
    ]:
        logger.info("=== [%s] Iniciando ===", label)
        raw = fetch_all_pages(fetch_collecta_page, endpoint, headers, label)
        if raw:
            _send_to_hostinger(prepare_fn(raw), label)


def run_datasefil() -> None:
    url     = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token   = os.getenv("DATASEFIL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    logger.info("=== [DATA SEFIL] Iniciando ===")
    raw = fetch_all_pages(fetch_datasefil_page, url, headers, "DATA SEFIL")
    if raw:
        _send_to_hostinger(prepare_datasefil_customers(raw), "DATA SEFIL")


def run_leads() -> None:
    logger.info("=== [Leads] Iniciando ===")
    try:
        customers = prepare_leads_customers()
        _send_to_hostinger(customers, "Leads")
    except Exception as exc:
        logger.error("[Leads] Error en extracción MySQL: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SOURCES = {
    "collecta":  run_collecta,
    "datasefil": run_datasefil,
    "leads":     run_leads,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronización manual LAN → Hostinger")
    parser.add_argument(
        "--source",
        choices=[*SOURCES.keys(), "all"],
        required=True,
        help="Fuente a sincronizar",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("INICIO DE SINCRONIZACIÓN MANUAL — fuente: %s", args.source.upper())
    logger.info("=" * 60)

    if args.source == "all":
        for name, fn in SOURCES.items():
            try:
                fn()
            except Exception as exc:
                logger.error("[%s] Error inesperado: %s", name, exc, exc_info=True)
    else:
        SOURCES[args.source]()

    logger.info("=" * 60)
    logger.info("SINCRONIZACIÓN COMPLETADA")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
