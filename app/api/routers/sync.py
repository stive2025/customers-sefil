"""
Router de ingesta de datos externos (sincronización MDM).
Permite que sistemas como Collecta, DATA SEFIL o Leads envíen registros
directamente a la API para su fusión en tiempo real.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.security import get_api_key
from app.schemas.customer import CustomerResponse
from app.services.unified_sync import sync_external_customer

router = APIRouter(tags=["Sync"], dependencies=[Depends(get_api_key)])


# ---------------------------------------------------------------------------
# Schema de entrada
# ---------------------------------------------------------------------------

class SyncPayload(BaseModel):
    """Body para el endpoint de sincronización."""

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


# ---------------------------------------------------------------------------
# POST /customer — Sincronizar / upsert un cliente
# ---------------------------------------------------------------------------

@router.post(
    "/customer",
    response_model=CustomerResponse,
    status_code=status.HTTP_200_OK,
    summary="Sincronizar cliente externo",
    description=(
        "Recibe un payload de un sistema externo y lo fusiona con la base de datos "
        "centralizada. Crea el cliente si no existe; si ya existe, enriquece los "
        "campos vacíos y añade contactos nuevos. Retorna el registro resultante."
    ),
)
def sync_customer(
    body: SyncPayload,
    db: Session = Depends(get_db),
) -> CustomerResponse:
    """
    Upsert de un cliente desde un sistema externo.
    - 200: cliente creado o actualizado correctamente.
    - 422: payload inválido (falta identification o nombre).
    - 500: error inesperado de base de datos.
    """
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
            detail=f"Error de base de datos durante la sincronización: {exc}",
        )

    return customer
