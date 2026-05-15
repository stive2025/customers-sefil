"""
Scheduler de Sincronización — Scheduled Polling (Batch CDC).

Lee dos horarios opcionales desde el entorno (SYNC_SCHEDULE_1 / SYNC_SCHEDULE_2)
y ejecuta run_all_syncs() a cada hora configurada, de forma desatendida.

Variables de entorno:
  SYNC_SCHEDULE_1  Hora de la primera ejecución, formato HH:MM  (ej. "02:00")
  SYNC_SCHEDULE_2  Hora de la segunda ejecución, formato HH:MM  (ej. "14:00")
  Si ninguna está definida, el scheduler arranca pero no programa ningún job.

Uso:
  python -m app.worker.scheduler
"""

import logging
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import schedule
from dotenv import load_dotenv

load_dotenv()  # carga .env cuando se ejecuta fuera de Docker (no-op si las vars ya existen)

from app.core.database import SessionLocal
from app.services.etl_collecta import sync_collecta_contacts, sync_collecta_data, sync_collecta_directions
from app.services.etl_datasefil import sync_datasefil_data
from app.services.etl_leads import sync_leads_data

# ---------------------------------------------------------------------------
# Logging básico
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# Wrappers por fuente (cada uno aísla sus propios errores)
# ---------------------------------------------------------------------------

_COLLECTA_PER_PAGE = 100
_COLLECTA_MAX_WORKERS = 5
_DATASEFIL_PER_PAGE = 100
_DATASEFIL_MAX_WORKERS = 5


def _fetch_collecta_page(url: str, headers: dict, page: int) -> tuple[list[dict], int]:
    """Descarga una página y retorna (registros, last_page)."""
    resp = requests.get(
        url, headers=headers,
        params={"page": page, "per_page": _COLLECTA_PER_PAGE},
        timeout=30,
    )
    resp.raise_for_status()
    result_block = resp.json().get("result", {})
    return result_block.get("data", []), result_block.get("last_page", 1)


def _run_collecta(db) -> None:
    """
    Paso 1 — Collecta.
    Descarga todas las páginas en paralelo (5 workers) y las sincroniza.
    Usa per_page=100 para reducir el número de peticiones HTTP.
    """
    url_collecta = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token_collecta = os.getenv("COLLECTA_TOKEN", "")

    headers = {
        "Authorization": f"Bearer {token_collecta}",
        "Accept": "application/json",
    }

    # Página 1: obtiene datos y total de páginas
    try:
        first_page_records, last_page = _fetch_collecta_page(url_collecta, headers, 1)
    except Exception as exc:
        logger.error("[Collecta] No se pudo descargar la información de la API: %s", exc)
        return

    logger.info("[Collecta] %d páginas a descargar (per_page=%d)", last_page, _COLLECTA_PER_PAGE)

    all_records: list[dict] = list(first_page_records)

    # Páginas restantes en paralelo
    if last_page > 1:
        pages = range(2, last_page + 1)
        with ThreadPoolExecutor(max_workers=_COLLECTA_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_collecta_page, url_collecta, headers, p): p
                for p in pages
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    records, _ = future.result()
                    all_records.extend(records)
                except Exception as exc:
                    logger.warning("[Collecta] Error en página %d: %s", page_num, exc)

    if not all_records:
        logger.warning("[Collecta] Sin datos disponibles — omitiendo este ciclo.")
        return

    logger.info("[Collecta] %d registros descargados", len(all_records))
    result = sync_collecta_data(all_records, db)
    logger.info(
        "[Collecta] Finalizado — creados: %d | actualizados: %d | omitidos: %d | errores: %d",
        result.created, result.updated, result.skipped, len(result.errors)
    )


def _run_collecta_contacts(db) -> None:
    """
    Paso 1b — Collecta Contacts.
    Descarga todos los teléfonos desde /public/api/contacts con paginación paralela
    y los vincula a los clientes existentes por client_ci.
    """
    base_url = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    contacts_url = base_url.rsplit("/", 1)[0] + "/contacts"
    token_collecta = os.getenv("COLLECTA_TOKEN", "")

    headers = {
        "Authorization": f"Bearer {token_collecta}",
        "Accept": "application/json",
    }

    # Página 1: obtiene datos y total de páginas
    try:
        first_page_records, last_page = _fetch_collecta_page(contacts_url, headers, 1)
    except Exception as exc:
        logger.error("[Collecta Contacts] No se pudo descargar la información: %s", exc)
        return

    logger.info("[Collecta Contacts] %d páginas a descargar", last_page)
    all_contacts: list[dict] = list(first_page_records)

    if last_page > 1:
        with ThreadPoolExecutor(max_workers=_COLLECTA_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_collecta_page, contacts_url, headers, p): p
                for p in range(2, last_page + 1)
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    records, _ = future.result()
                    all_contacts.extend(records)
                except Exception as exc:
                    logger.warning("[Collecta Contacts] Error en página %d: %s", page_num, exc)

    if not all_contacts:
        logger.warning("[Collecta Contacts] Sin datos disponibles — omitiendo este ciclo.")
        return

    logger.info("[Collecta Contacts] %d contactos descargados", len(all_contacts))
    result = sync_collecta_contacts(all_contacts, db)
    logger.info(
        "[Collecta Contacts] Finalizado — actualizados: %d | omitidos: %d | errores: %d",
        result.updated, result.skipped, len(result.errors),
    )


def _run_collecta_directions(db) -> None:
    """
    Paso 1c — Collecta Directions.
    Descarga todas las direcciones desde /public/api/directions con paginación paralela.
    """
    base_url = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    directions_url = base_url.rsplit("/", 1)[0] + "/directions"
    token_collecta = os.getenv("COLLECTA_TOKEN", "")

    headers = {
        "Authorization": f"Bearer {token_collecta}",
        "Accept": "application/json",
    }

    try:
        first_page_records, last_page = _fetch_collecta_page(directions_url, headers, 1)
    except Exception as exc:
        logger.error("[Collecta Directions] No se pudo descargar la información: %s", exc)
        return

    logger.info("[Collecta Directions] %d páginas a descargar", last_page)
    all_directions: list[dict] = list(first_page_records)

    if last_page > 1:
        with ThreadPoolExecutor(max_workers=_COLLECTA_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_collecta_page, directions_url, headers, p): p
                for p in range(2, last_page + 1)
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    records, _ = future.result()
                    all_directions.extend(records)
                except Exception as exc:
                    logger.warning("[Collecta Directions] Error en página %d: %s", page_num, exc)

    if not all_directions:
        logger.warning("[Collecta Directions] Sin datos disponibles — omitiendo este ciclo.")
        return

    logger.info("[Collecta Directions] %d direcciones descargadas", len(all_directions))
    result = sync_collecta_directions(all_directions, db)
    logger.info(
        "[Collecta Directions] Finalizado — actualizados: %d | omitidos: %d | errores: %d",
        result.updated, result.skipped, len(result.errors),
    )


def _fetch_datasefil_page(url: str, headers: dict, page: int) -> tuple[list[dict], int]:
    """Descarga una página de DATA SEFIL y retorna (registros, last_page)."""
    resp = requests.get(
        url, headers=headers,
        params={"page": page, "per_page": _DATASEFIL_PER_PAGE},
        timeout=30,
    )
    resp.raise_for_status()
    json_resp = resp.json()
    return json_resp.get("data", []), json_resp.get("last_page", 1)


def _run_datasefil(db) -> None:
    """
    Paso 2 — DATA SEFIL.
    Descarga todas las páginas en paralelo (5 workers) y las sincroniza.
    Usa per_page=100 para reducir el número de peticiones HTTP.
    """
    url_sefil = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token_sefil = os.getenv("DATASEFIL_TOKEN", "")

    headers = {
        "Authorization": f"Bearer {token_sefil}",
        "Accept": "application/json",
    }

    # Página 1: obtiene datos y total de páginas
    try:
        first_page_records, last_page = _fetch_datasefil_page(url_sefil, headers, 1)
    except Exception as exc:
        logger.error("[DATA SEFIL] No se pudo descargar la información de la API: %s", exc)
        return

    logger.info("[DATA SEFIL] %d páginas a descargar (per_page=%d)", last_page, _DATASEFIL_PER_PAGE)

    all_records: list[dict] = list(first_page_records)

    # Páginas restantes en paralelo
    if last_page > 1:
        pages = range(2, last_page + 1)
        with ThreadPoolExecutor(max_workers=_DATASEFIL_MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_datasefil_page, url_sefil, headers, p): p
                for p in pages
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    records, _ = future.result()
                    all_records.extend(records)
                except Exception as exc:
                    logger.warning("[DATA SEFIL] Error en página %d: %s", page_num, exc)

    if not all_records:
        logger.warning("[DATA SEFIL] Sin datos disponibles — omitiendo este ciclo.")
        return

    logger.info("[DATA SEFIL] %d registros descargados", len(all_records))
    result = sync_datasefil_data(all_records, db)
    logger.info(
        "[DATA SEFIL] Finalizado — creados: %d | actualizados: %d | omitidos: %d | errores: %d",
        result.created, result.updated, result.skipped, len(result.errors)
    )


def _run_leads(db) -> None:
    """
    Paso 3 — Leads (MySQL externo).
    sync_leads_data gestiona su propia conexión MySQL; solo necesita la sesión central.
    """
    result = sync_leads_data(db)
    logger.info(
        "[Leads] Finalizado — creados: %d | actualizados: %d | teléfonos: +%d | "
        "emails: +%d | direcciones: +%d | omitidos: %d | errores: %d",
        result.customers_created,
        result.customers_updated,
        result.phones_added,
        result.emails_added,
        result.addresses_added,
        result.skipped,
        len(result.errors),
    )


# ---------------------------------------------------------------------------
# Orquestador principal
# ---------------------------------------------------------------------------

def run_all_syncs() -> None:
    """
    Ejecuta secuencialmente los tres ETLs dentro de una única sesión de BD.
    Si un ETL falla, el error se registra y el proceso continúa con el siguiente.
    Un fallo de sesión de BD aborta el ciclo completo.
    """
    logger.info("=" * 60)
    logger.info("INICIO DE CICLO DE SINCRONIZACIÓN")
    logger.info("=" * 60)

    db = SessionLocal()
    try:
        for name, runner in [
            ("Collecta",            _run_collecta),
            ("Collecta Contacts",   _run_collecta_contacts),
            ("Collecta Directions", _run_collecta_directions),
            ("DATA SEFIL",          _run_datasefil),
            ("Leads",               _run_leads),
        ]:
            try:
                runner(db)
            except Exception as exc:
                logger.error(
                    "[%s] Error inesperado — el ciclo continúa con la siguiente fuente. Detalle: %s",
                    name,
                    exc,
                    exc_info=True,
                )
    finally:
        db.close()

    logger.info("=" * 60)
    logger.info("CICLO DE SINCRONIZACIÓN COMPLETADO")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Programación dinámica desde variables de entorno
# ---------------------------------------------------------------------------

def _register_schedules() -> int:
    """
    Lee SYNC_SCHEDULE_1 y SYNC_SCHEDULE_2 del entorno y registra los jobs.
    Retorna el número de horarios registrados.
    """
    registered = 0
    for var in ("SYNC_SCHEDULE_1", "SYNC_SCHEDULE_2"):
        horario = os.getenv(var, "").strip()
        if not horario:
            continue
        # Validación básica del formato HH:MM
        parts = horario.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            logger.warning("Valor inválido para %s=%r — se ignora (formato esperado: HH:MM)", var, horario)
            continue
        schedule.every().day.at(horario).do(run_all_syncs)
        logger.info("Job registrado desde %s: ejecución diaria a las %s", var, horario)
        registered += 1

    return registered


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Iniciando Scheduler de Sincronización…")

    jobs_registered = _register_schedules()

    if jobs_registered == 0:
        logger.warning(
            "No se encontraron horarios configurados. "
            "Define SYNC_SCHEDULE_1 y/o SYNC_SCHEDULE_2 en el entorno "
            "(ej. SYNC_SCHEDULE_1=02:00). El scheduler permanece activo pero no ejecutará jobs."
        )
    else:
        logger.info("%d job(s) programado(s). Próximas ejecuciones:", jobs_registered)
        for job in schedule.get_jobs():
            logger.info("  • %s", job)

    logger.info("Bucle de ejecución iniciado (intervalo de comprobación: 60 s).")
    while True:
        schedule.run_pending()
        time.sleep(60)
