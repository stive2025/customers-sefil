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
from typing import Annotated, List

from fastapi import APIRouter, Body, Depends, HTTPException, status
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
    base    = url.rsplit("/", 1)[0]

    for label, endpoint, prepare_fn in [
        ("Collecta-clients",  url,                prepare_collecta_customers),
        ("Collecta-contacts", f"{base}/contacts", prepare_collecta_contacts),
        # /directions requiere client_ci individual — no permite descarga masiva
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
# POST /run/* — Endpoints de sincronización manual
# ---------------------------------------------------------------------------

@router.post(
    "/run/collecta",
    tags=["Sync"],
    response_model=SyncRunResponse,
    summary="Sync manual — Collecta",
    description="Descarga clientes y contactos de Collecta y los persiste. Retorna estadísticas al finalizar.",
)
def run_collecta() -> SyncRunResponse:
    return _sync_collecta()


@router.post(
    "/run/datasefil",
    tags=["Sync"],
    response_model=SyncRunResponse,
    summary="Sync manual — DATA SEFIL",
    description="Descarga todos los clientes de DATA SEFIL y los persiste. Retorna estadísticas al finalizar.",
)
def run_datasefil() -> SyncRunResponse:
    return _sync_datasefil()


@router.post(
    "/run/leads",
    tags=["Sync"],
    response_model=SyncRunResponse,
    summary="Sync manual — Leads",
    description="Extrae clientes de la BD MySQL de Leads y los persiste. Retorna estadísticas al finalizar.",
)
def run_leads() -> SyncRunResponse:
    return _sync_leads()


@router.post(
    "/run/all",
    tags=["Sync"],
    response_model=List[SyncRunResponse],
    summary="Sync manual — Todas las fuentes",
    description="Ejecuta el sync de Collecta + DATA SEFIL + Leads en secuencia. Retorna estadísticas por fuente.",
)
def run_all() -> List[SyncRunResponse]:
    return [_sync_collecta(), _sync_datasefil(), _sync_leads()]
