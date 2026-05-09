"""
ORM model for the central entity: Customer (Person/Client).
All field names and relationships use English for consistency.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# Avoid circular imports: only resolved at type-checking time
if TYPE_CHECKING:
    from app.models.collections import CollectionAddress, CollectionEmail, CollectionPhone
    from app.models.equifax import EquifaxQuery
    from app.models.financial import FinancialInformation


class Customer(Base):
    """
    Represents a natural or legal person in the system.
    Central entity to which all other models relate.
    """

    __tablename__ = "customers"

    # --- Primary Key ---
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)

    # --- Identification ---
    identification: Mapped[str] = mapped_column(
        String(13),
        unique=True,
        index=True,
        nullable=False,
        comment="National ID (cédula) or company tax ID (RUC)",
    )

    # --- Name ---
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # --- Demographics ---
    gender: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="MALE, FEMALE, OTHER"
    )
    birth_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    birth_place: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    nationality: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, default="Ecuadorian"
    )
    civil_status: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="SINGLE, MARRIED, DIVORCED, WIDOWED"
    )
    profession: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )

    # --- Relationships (One-to-Many) ---
    phones: Mapped[List["CollectionPhone"]] = relationship(
        "CollectionPhone",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    addresses: Mapped[List["CollectionAddress"]] = relationship(
        "CollectionAddress",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    emails: Mapped[List["CollectionEmail"]] = relationship(
        "CollectionEmail",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    financial_information: Mapped[Optional["FinancialInformation"]] = relationship(
        "FinancialInformation",
        back_populates="customer",
        uselist=False,
        cascade="all, delete-orphan",
    )
    equifax_queries: Mapped[List["EquifaxQuery"]] = relationship(
        "EquifaxQuery",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Customer(id={self.id}, identification='{self.identification}', "
            f"name='{self.first_name} {self.last_name}')>"
        )
