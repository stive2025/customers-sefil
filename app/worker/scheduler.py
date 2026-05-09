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

import schedule

from app.core.database import SessionLocal
from app.services.etl_collecta import sync_collecta_data
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

def _run_collecta(db) -> None:
    """
    Paso 1 — Collecta.
    Hace una petición GET autenticada a la API real de Collecta.
    """
    url_collecta = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token_collecta = os.getenv("COLLECTA_TOKEN", "")
    
    headers = {
        "Authorization": f"Bearer {token_collecta}",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url_collecta, headers=headers, timeout=15)
        response.raise_for_status()
        raw_data = response.json()
    except Exception as exc:
        logger.error("[Collecta] No se pudo descargar la información de la API: %s", exc)
        return

    if not raw_data:
        logger.warning("[Collecta] API respondió correctamente pero sin datos — omitiendo este ciclo.")
        return

    result = sync_collecta_data(raw_data, db)
    logger.info(
        "[Collecta] Finalizado — creados: %d | actualizados: %d | omitidos: %d | errores: %d",
        result.created, result.updated, result.skipped, len(result.errors)
    )


def _run_datasefil(db) -> None:
    """
    Paso 2 — DATA SEFIL.
    Hace una petición GET autenticada a la API real de DATA SEFIL.
    """
    url_sefil = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token_sefil = os.getenv("DATASEFIL_TOKEN", "")
    
    headers = {
        "Authorization": f"Bearer {token_sefil}",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url_sefil, headers=headers, timeout=15)
        response.raise_for_status()
        
        json_resp = response.json()
        raw_data = json_resp.get("data", []) if isinstance(json_resp, dict) else json_resp
        
    except Exception as exc:
        logger.error("[DATA SEFIL] No se pudo descargar la información de la API: %s", exc)
        return

    if not raw_data:
        logger.warning("[DATA SEFIL] Sin datos disponibles — omitiendo este ciclo.")
        return

    result = sync_datasefil_data(raw_data, db)
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
        "[Leads] Finalizado — clientes actualizados: %d | teléfonos añadidos: %d | "
        "omitidos: %d | errores: %d",
        result.customers_updated,
        result.phones_added,
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
            ("Collecta",  _run_collecta),
            ("DATA SEFIL", _run_datasefil),
            ("Leads",     _run_leads),
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
