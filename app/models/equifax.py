"""
Modelo ORM para las consultas realizadas al Buró de Crédito (Equifax).
Almacena el historial de consultas por cliente con el raw data de la respuesta.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.customer import Customer


class EquifaxQuery(Base):
    """
    Registra cada consulta realizada al Buró Equifax para un cliente.
    Guarda el score, el resultado del análisis y el payload crudo de la respuesta.

    Nota: Se usa JSONB para PostgreSQL por su eficiencia en almacenamiento y búsqueda.
    Si usas SQLite o MySQL, cambia JSONB por sqlalchemy.types.JSON.
    """

    __tablename__ = "equifax_queries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Datos de la Consulta ---
    fecha_consulta: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Fecha y hora exacta en que se realizó la consulta al buró",
    )
    score_buro: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Score de crédito retornado por Equifax (generalmente 0 - 999)",
    )
    estado_consulta: Mapped[str] = mapped_column(
        String(20),
        default="EXITOSA",
        nullable=False,
        comment="Estado de la consulta: EXITOSA, FALLIDA, SIN_INFORMACION",
    )

    # --- Payload Crudo ---
    raw_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Respuesta cruda (raw data) retornada por la API de Equifax en formato JSON",
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Relación inversa hacia Customer ---
    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="equifax_queries"
    )

    def __repr__(self) -> str:
        return (
            f"<EquifaxQuery(id={self.id}, customer_id={self.customer_id}, "
            f"score_buro={self.score_buro}, fecha='{self.fecha_consulta}')>"
        )
