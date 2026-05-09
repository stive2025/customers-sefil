"""
Esquemas Pydantic v2 para el modelo EquifaxQuery.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class EquifaxQueryBase(BaseModel):
    score_buro: Optional[int] = Field(
        None, ge=0, le=999, description="Score del buró Equifax (0 - 999)"
    )
    estado_consulta: str = Field(
        default="EXITOSA",
        description="Estado de la consulta: EXITOSA, FALLIDA, SIN_INFORMACION",
    )
    raw_response: Optional[Dict[str, Any]] = Field(
        None, description="Payload crudo de la respuesta de la API de Equifax"
    )


class EquifaxQueryCreate(EquifaxQueryBase):
    """
    Schema para registrar una nueva consulta de Equifax.
    El customer_id se inyecta desde el contexto del endpoint.
    """
    pass


class EquifaxQueryResponse(EquifaxQueryBase):
    """Schema de respuesta completo para una consulta de Equifax."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    fecha_consulta: datetime
    created_at: datetime
