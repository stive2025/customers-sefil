"""
Router de ingesta de datos externos (sincronización MDM).

Expone dos endpoints:
  POST /customer      — ingesta en tiempo real de un único cliente (sistemas externos).
  POST /bulk-upsert   — ingesta en lote desde el Worker (Collecta / DATA SEFIL / Leads).
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.security import get_api_key
from app.schemas.customer import CustomerResponse
from app.schemas.sync import BulkUpsertRequest, BulkUpsertResponse
from app.services.bulk_upsert import bulk_upsert_customers
from app.services.unified_sync import sync_external_customer

router = APIRouter(tags=["Sync"], dependencies=[Depends(get_api_key)])


# ---------------------------------------------------------------------------
# POST /customer — Ingesta en tiempo real (payload raw de sistema externo)
# ---------------------------------------------------------------------------

class SyncPayload(BaseModel):
    source: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Sistema origen del registro (ej. 'Collecta', 'DATA SEFIL', 'Leads')",
        examples=["Collecta"],
    )
    data: dict = Field(
        ...,
        description=(
            "Payload crudo del sistema origen. Debe contener al menos un campo de "
            "identification (identification / ci / cedula / document) y un nombre."
        ),
    )


@router.post(
    "/customer",
    response_model=CustomerResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincronizar cliente externo (tiempo real)",
    description=(
        "Recibe un payload crudo de un sistema externo y lo fusiona con la base de datos "
        "centralizada. Crea el cliente si no existe; si ya existe, enriquece los "
        "campos vacíos y añade contactos nuevos. Retorna el registro resultante."
    ),
)
def sync_customer(
    body: SyncPayload,
    db: Session = Depends(get_db),
) -> CustomerResponse:
    try:
        customer = sync_external_customer(db=db, payload=body.data, source=body.source)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error de base de datos: {exc}",
        )
    return customer


# ---------------------------------------------------------------------------
# POST /bulk-upsert — Ingesta por lotes desde el Worker
# ---------------------------------------------------------------------------

@router.post(
    "/bulk-upsert",
    response_model=BulkUpsertResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert por lotes (Worker)",
    description=(
        "Recibe un lote de hasta 500 registros estandarizados desde el Worker ETL y los "
        "fusiona en la base de datos. Requiere X-API-Key. Retorna estadísticas del lote: "
        "creados, actualizados, omitidos y errores."
    ),
)
def bulk_upsert(
    body: Annotated[BulkUpsertRequest, Body()],
    db: Session = Depends(get_db),
) -> BulkUpsertResponse:
    """
    Merge masivo de clientes provenientes del Worker.
    - Clientes nuevos: se crean si tienen first_name; se omiten si no.
    - Clientes existentes: se enriquecen campos vacíos y se agregan contactos nuevos.
    - Commit único al final del lote (atómico).
    """
    try:
        return bulk_upsert_customers(body.customers, db)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error de base de datos en bulk-upsert: {exc}",
        )
