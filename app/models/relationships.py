"""
ORM model for family/genomic relationships between customers.
Stores the `parents` array from DATA SEFIL (MADRE, PADRE, HIJO, HERMANO, CONYUGE, etc.).
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.customer import Customer


class CustomerRelationship(Base):
    """
    Stores a directional family relationship from one Customer to a related person.
    The related person is identified by their cedula (related_identification).
    They may or may not exist as a Customer in the central DB.
    """

    __tablename__ = "customer_relationships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Tipo de relación: MADRE, PADRE, HIJO, HERMANO, CONYUGE, etc.
    relationship_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Datos de la persona relacionada (desnormalizados desde DATA SEFIL)
    related_identification: Mapped[Optional[str]] = mapped_column(String(13), nullable=True, index=True)
    related_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    related_birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    related_gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    related_civil_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    related_death_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default="DATA SEFIL")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="relationships")
