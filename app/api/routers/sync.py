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
# Helpers internos de sync (background tasks)
# ---------------------------------------------------------------------------

class SyncStartedResponse(BaseModel):
    message: str
    source: str


def _upsert_in_background(customers: list, label: str) -> None:
    """Persiste en BD usando una sesión propia (independiente del request)."""
    if not customers:
        logger.warning("[%s] No hay registros para persistir.", label)
        return
    db: Session = SessionLocal()
    try:
        result = bulk_upsert_customers(customers, db)
        logger.info("[%s] SYNC COMPLETADO — created: %d | updated: %d | skipped: %d | errors: %d",
                    label, result.created, result.updated, result.skipped, len(result.errors))
    except Exception as exc:
        db.rollback()
        logger.error("[%s] Error al persistir: %s", label, exc, exc_info=True)
    finally:
        db.close()


def _bg_collecta() -> None:
    url   = os.getenv("COLLECTA_API_URL", "https://collapi.sefil.com.ec/public/api/clients")
    token = os.getenv("COLLECTA_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = url.rsplit("/", 1)[0]

    for label, endpoint, prepare_fn in [
        ("Collecta-clients",    url,                    prepare_collecta_customers),
        ("Collecta-contacts",   f"{base}/contacts",     prepare_collecta_contacts),
        ("Collecta-directions", f"{base}/directions",   prepare_collecta_directions),
    ]:
        raw = fetch_all_pages(fetch_collecta_page, endpoint, headers, label)
        if raw:
            _upsert_in_background(prepare_fn(raw), label)


def _bg_datasefil() -> None:
    url     = os.getenv("DATASEFIL_API_URL", "http://172.20.1.105:8000/api/clients")
    token   = os.getenv("DATASEFIL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    raw = fetch_all_pages(fetch_datasefil_page, url, headers, "DATA SEFIL")
    if raw:
        _upsert_in_background(prepare_datasefil_customers(raw), "DATA SEFIL")


def _bg_leads() -> None:
    try:
        customers = prepare_leads_customers()
        _upsert_in_background(customers, "Leads")
    except Exception as exc:
        logger.error("[Leads] Error en extracción MySQL: %s", exc, exc_info=True)


def _bg_all() -> None:
    for label, fn in [
        ("Collecta",   _bg_collecta),
        ("DATA SEFIL", _bg_datasefil),
        ("Leads",      _bg_leads),
    ]:
        logger.info("=== [%s] Iniciando sync ===", label)
        try:
            fn()
        except Exception as exc:
            logger.error("[%s] Error inesperado: %s", label, exc, exc_info=True)
    logger.info("=== SYNC MANUAL COMPLETADO ===")


# ---------------------------------------------------------------------------
# POST /run/* — Endpoints de sincronización manual
# ---------------------------------------------------------------------------

@router.post(
    "/run/collecta",
    response_model=SyncStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync manual — Collecta",
    description="Descarga clientes, contactos y direcciones de Collecta y los persiste en la BD. Corre en background.",
)
def run_collecta(background_tasks: BackgroundTasks) -> SyncStartedResponse:
    background_tasks.add_task(_bg_collecta)
    return SyncStartedResponse(message="Sync de Collecta iniciado. Revisa los logs para el progreso.", source="Collecta")


@router.post(
    "/run/datasefil",
    response_model=SyncStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync manual — DATA SEFIL",
    description="Descarga todos los clientes de DATA SEFIL y los persiste en la BD. Corre en background.",
)
def run_datasefil(background_tasks: BackgroundTasks) -> SyncStartedResponse:
    background_tasks.add_task(_bg_datasefil)
    return SyncStartedResponse(message="Sync de DATA SEFIL iniciado. Revisa los logs para el progreso.", source="DATA SEFIL")


@router.post(
    "/run/leads",
    response_model=SyncStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync manual — Leads",
    description="Extrae clientes de la BD MySQL de Leads y los persiste. Corre en background.",
)
def run_leads(background_tasks: BackgroundTasks) -> SyncStartedResponse:
    background_tasks.add_task(_bg_leads)
    return SyncStartedResponse(message="Sync de Leads iniciado. Revisa los logs para el progreso.", source="Leads")


@router.post(
    "/run/all",
    response_model=SyncStartedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync manual — Todas las fuentes",
    description="Ejecuta el sync completo de Collecta + DATA SEFIL + Leads en secuencia. Corre en background.",
)
def run_all(background_tasks: BackgroundTasks) -> SyncStartedResponse:
    background_tasks.add_task(_bg_all)
    return SyncStartedResponse(message="Sync completo iniciado (Collecta + DATA SEFIL + Leads). Revisa los logs.", source="ALL")
