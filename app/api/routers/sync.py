"""
Router de sincronización MDM.

Endpoints:
  POST /customer        — ingesta en tiempo real de un único cliente.
  POST /bulk-upsert     — ingesta por lotes (payload estandarizado).
  POST /run/collecta    — sync manual completo de Collecta (clients + contacts + directions).
  POST /run/datasefil   — sync manual completo de DATA SEFIL.
  POST /run/leads       — sync manual completo de Leads (MySQL).
  POST /run/all         — sync manual de todas las fuentes en secuencia.

Los endpoints /run/* se ejecutan en background y retornan 202 inmediatamente.
El progreso se puede seguir con: docker logs <container> -f
"""
import logging
import os
import uuid
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import Annotated

from app.api.dependencies import get_db
from app.core.database import SessionLocal
from app.core.security import get_api_key
from app.schemas.customer import CustomerResponse
from app.schemas.sync import BulkUpsertRequest, BulkUpsertResponse
from app.services.bulk_upsert import bulk_upsert_customers
from app.services.etl_collecta import (
    prepare_collecta_contacts,
    prepare_collecta_customers,
    prepare_collecta_directions,
)
from app.services.etl_datasefil import prepare_datasefil_customers
from app.services.etl_fetcher import fetch_all_pages, fetch_collecta_page, fetch_datasefil_page
from app.services.etl_leads import prepare_leads_customers
from app.services.unified_sync import sync_external_customer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Sync"], dependencies=[Depends(get_api_key)])


# ---------------------------------------------------------------------------
# POST /customer — Ingesta en tiempo real
# ---------------------------------------------------------------------------

class SyncPayload(BaseModel):
    source: str = Field(..., min_length=1, max_length=50, examples=["Collecta"])
    data: dict = Field(..., description="Payload crudo del sistema origen.")


@router.post(
    "/customer",
    response_model=CustomerResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincronizar cliente externo (tiempo real)",
)
def sync_customer(body: SyncPayload, db: Session = Depends(get_db)) -> CustomerResponse:
    try:
        customer = sync_external_customer(db=db, payload=body.data, source=body.source)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error de base de datos: {exc}")
    return customer


# ---------------------------------------------------------------------------
# POST /bulk-upsert — Ingesta por lotes
# ---------------------------------------------------------------------------

@router.post(
    "/bulk-upsert",
    response_model=BulkUpsertResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert por lotes",
)
def bulk_upsert(
    body: Annotated[BulkUpsertRequest, Body()],
    db: Session = Depends(get_db),
) -> BulkUpsertResponse:
    try:
        return bulk_upsert_customers(body.customers, db)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error de base de datos en bulk-upsert: {exc}")


# ---------------------------------------------------------------------------
# Helpers internos de sync (síncronos — devuelven estadísticas reales)
# ---------------------------------------------------------------------------

class SyncRunResponse(BaseModel):
    source: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = []


def _run_upsert(customers: list, label: str) -> BulkUpsertResponse:
    """Persiste en BD y retorna las estadísticas del lote."""
    if not customers:
        logger.warning("[%s] No hay registros para persistir.", label)
        return BulkUpsertResponse()
    db: Session = SessionLocal()
    try:
        result = bulk_upsert_customers(customers, db)
        logger.info("[%s] SYNC COMPLETADO — created: %d | updated: %d | skipped: %d | errors: %d",
                    label, result.created, result.updated, result.skipped, len(result.errors))
        return result
    except Exception as exc:
        db.rollback()
        logger.error("[%s] Error al persistir: %s", label, exc, exc_info=True)
        return BulkUpsertResponse(errors=[str(exc)])
    finally:
        db.close()


def _accumulate(total: SyncRunResponse, partial: BulkUpsertResponse) -> None:
    total.created += partial.created
    total.updated += partial.updated
    total.skipped += partial.skipped
    total.errors  += partial.errors


def _sync_collecta() -> SyncRunResponse:
    result = SyncRunResponse(source="Collecta")
    url     = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token   = os.getenv("COLLECTA_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # NOTA: /contacts y /directions retornan 422 sin filtro obligatorio —
    # no permiten descarga masiva. Se sincronizan por cédula individual
    # usando POST /sync/run/collecta/{identification}.
    for label, endpoint, prepare_fn in [
        ("Collecta-clients", url, prepare_collecta_customers),
    ]:
        raw = fetch_all_pages(fetch_collecta_page, endpoint, headers, label)
        if raw:
            _accumulate(result, _run_upsert(prepare_fn(raw), label))
    return result


def _sync_datasefil() -> SyncRunResponse:
    result  = SyncRunResponse(source="DATA SEFIL")
    url     = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token   = os.getenv("DATASEFIL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    raw     = fetch_all_pages(fetch_datasefil_page, url, headers, "DATA SEFIL")
    if raw:
        _accumulate(result, _run_upsert(prepare_datasefil_customers(raw), "DATA SEFIL"))
    return result


def _sync_leads() -> SyncRunResponse:
    result = SyncRunResponse(source="Leads")
    try:
        customers = prepare_leads_customers()
        _accumulate(result, _run_upsert(customers, "Leads"))
    except Exception as exc:
        logger.error("[Leads] Error en extracción MySQL: %s", exc, exc_info=True)
        result.errors.append(str(exc))
    return result


# ---------------------------------------------------------------------------
# Job tracking en memoria (requiere --workers 1 en Uvicorn)
# ---------------------------------------------------------------------------

_JOBS: Dict[str, Optional[List[SyncRunResponse]]] = {}


class JobStartedResponse(BaseModel):
    job_id: str
    status: str = "running"
    check_url: str


def _start_job(fn, background_tasks: BackgroundTasks) -> JobStartedResponse:
    job_id = uuid.uuid4().hex[:8]
    _JOBS[job_id] = None

    def _run():
        try:
            result = fn()
            _JOBS[job_id] = result if isinstance(result, list) else [result]
        except Exception as exc:
            _JOBS[job_id] = [SyncRunResponse(source="ERROR", errors=[str(exc)])]

    background_tasks.add_task(_run)
    return JobStartedResponse(
        job_id=job_id,
        check_url=f"/api/v1/sync/status/{job_id}",
    )


# ---------------------------------------------------------------------------
# POST /run/* — Inician sync en background y retornan job_id
# ---------------------------------------------------------------------------

@router.post("/run/collecta", tags=["Sync"], response_model=JobStartedResponse,
             status_code=status.HTTP_202_ACCEPTED,
             summary="Sync masivo — Collecta (/clients). Teléfonos y direcciones: usar /run/collecta/{ci}")
def run_collecta(background_tasks: BackgroundTasks) -> JobStartedResponse:
    return _start_job(_sync_collecta, background_tasks)


@router.post(
    "/run/collecta/{identification}",
    tags=["Sync"],
    response_model=SyncRunResponse,
    summary="Sync individual — Collecta por cédula",
    description=(
        "Sincroniza un cliente específico desde Collecta: datos básicos (/clients), "
        "teléfonos (/contacts) y direcciones (/directions). "
        "Retorna estadísticas al finalizar."
    ),
)
def run_collecta_by_identification(identification: str) -> SyncRunResponse:
    url     = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token   = os.getenv("COLLECTA_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base    = url.rsplit("/", 1)[0]
    result  = SyncRunResponse(source=f"Collecta/{identification}")

    import requests as _req

    for label, endpoint, param_key, prepare_fn, fn_kwargs in [
        # /clients:    filter by ci
        ("clients",    url,                  "ci",        prepare_collecta_customers, {}),
        # /contacts:   filter by client_ci (NOT client_identification — that param doesn't exist)
        ("contacts",   f"{base}/contacts",   "client_ci", prepare_collecta_contacts,  {"known_ci": identification}),
        # /directions: filter by client_ci
        ("directions", f"{base}/directions", "client_ci", prepare_collecta_directions, {"known_ci": identification}),
    ]:
        try:
            resp = _req.get(
                endpoint, headers=headers,
                params={param_key: identification, "page": 1, "per_page": 100},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            # Collecta API structure: { success, message, data: { data: [...], last_page, ... } }
            pagination = body.get("data", {})
            raw = pagination.get("data", []) if isinstance(pagination, dict) else []
            if raw:
                _accumulate(result, _run_upsert(prepare_fn(raw, **fn_kwargs), f"Collecta-{label}/{identification}"))
        except Exception as exc:
            logger.warning("[Collecta-%s/%s] Error: %s", label, identification, exc)
            result.errors.append(f"{label}: {exc}")

    return result


def _backfill_collecta_basics(db: Session) -> SyncRunResponse:
    import requests as _req
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from sqlalchemy import select
    from app.models.customer import Customer
    from app.services.etl_collecta import prepare_collecta_customers
    from app.services.bulk_upsert import bulk_upsert_customers

    result = SyncRunResponse(source="Collecta-Backfill")
    url = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token = os.getenv("COLLECTA_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # Obtener todas las cédulas
    identifications = db.execute(select(Customer.identification)).scalars().all()
    logger.info("Iniciando backfill basico para %d clientes en Collecta", len(identifications))

    def _fetch_one(ci: str):
        try:
            resp = _req.get(url, headers=headers, params={"ci": ci, "page": 1, "per_page": 10}, timeout=10)
            if resp.status_code == 200:
                pagination = resp.json().get("data", {})
                return pagination.get("data", []) if isinstance(pagination, dict) else []
        except Exception:
            pass
        return []

    # Procesar en lotes pequeños para no saturar memoria
    batch_size = 500
    for i in range(0, len(identifications), batch_size):
        batch_cis = identifications[i:i+batch_size]
        raw_items = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_one, ci): ci for ci in batch_cis}
            for future in as_completed(futures):
                try:
                    data = future.result()
                    if data:
                        raw_items.extend(data)
                except Exception as exc:
                    logger.warning("Error fetching CI %s: %s", futures[future], exc)
        
        if raw_items:
            items_to_upsert = prepare_collecta_customers(raw_items)
            if items_to_upsert:
                try:
                    partial = bulk_upsert_customers(items_to_upsert, db)
                    _accumulate(result, partial)
                except Exception as exc:
                    db.rollback()
                    result.errors.append(f"Batch {i}: {exc}")

    return result


@router.post("/run/collecta/backfill-basics", tags=["Sync"], response_model=JobStartedResponse,
             status_code=status.HTTP_202_ACCEPTED,
             summary="Backfill masivo — Collecta (Rellena actividad economica consultando 1x1)")
def run_collecta_backfill(background_tasks: BackgroundTasks) -> JobStartedResponse:
    # Necesitamos pasar una nueva sesión porque background_tasks no debería usar la de Depends
    # Usaremos SessionLocal internamente
    def _run_backfill():
        from app.db.session import SessionLocal
        local_db = SessionLocal()
        try:
            return _backfill_collecta_basics(local_db)
        finally:
            local_db.close()
            
    return _start_job(_run_backfill, background_tasks)


@router.post("/run/datasefil", tags=["Sync"], response_model=JobStartedResponse,
             status_code=status.HTTP_202_ACCEPTED, summary="Sync manual — DATA SEFIL")
def run_datasefil(background_tasks: BackgroundTasks) -> JobStartedResponse:
    return _start_job(_sync_datasefil, background_tasks)


@router.post(
    "/run/datasefil/{identification}",
    tags=["Sync"],
    response_model=SyncRunResponse,
    summary="Sync individual — DATA SEFIL por cédula",
    description=(
        "Sincroniza un cliente específico desde DATA SEFIL y actualiza su genoma, "
        "teléfonos, direcciones, correos e información básica."
    ),
)
def run_datasefil_by_identification(identification: str) -> SyncRunResponse:
    url     = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token   = os.getenv("DATASEFIL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    result  = SyncRunResponse(source=f"DATA SEFIL/{identification}")

    import requests as _req

    try:
        resp = _req.get(
            url, headers=headers,
            # Se asume que la API soporta filtrar por identification
            params={"identification": identification, "page": 1, "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        raw = body.get("data", [])
        if raw:
            _accumulate(result, _run_upsert(prepare_datasefil_customers(raw), f"DATA SEFIL/{identification}"))
    except Exception as exc:
        logger.warning("[DATA SEFIL/%s] Error: %s", identification, exc)
        result.errors.append(str(exc))

    return result


@router.post("/run/leads", tags=["Sync"], response_model=JobStartedResponse,
             status_code=status.HTTP_202_ACCEPTED, summary="Sync manual — Leads")
def run_leads(background_tasks: BackgroundTasks) -> JobStartedResponse:
    return _start_job(lambda: [_sync_leads()], background_tasks)


@router.post("/run/all", tags=["Sync"], response_model=JobStartedResponse,
             status_code=status.HTTP_202_ACCEPTED, summary="Sync manual — Todas las fuentes")
def run_all(background_tasks: BackgroundTasks) -> JobStartedResponse:
    return _start_job(
        lambda: [_sync_collecta(), _sync_datasefil(), _sync_leads()],
        background_tasks,
    )


# ---------------------------------------------------------------------------
# GET /status/{job_id} — Consultar resultado de un sync
# ---------------------------------------------------------------------------

class JobStatusResponse(BaseModel):
    job_id: str
    status: str                              # "running" | "completed"
    results: Optional[List[SyncRunResponse]] = None


@router.get("/status/{job_id}", tags=["Sync"], response_model=JobStatusResponse,
            summary="Consultar estado/resultado de un sync")
def get_sync_status(job_id: str) -> JobStatusResponse:
    if job_id not in _JOBS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Job '{job_id}' no encontrado.")
    result = _JOBS[job_id]
    if result is None:
        return JobStatusResponse(job_id=job_id, status="running")
    return JobStatusResponse(job_id=job_id, status="completed", results=result)
