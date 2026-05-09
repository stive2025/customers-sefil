"""
ORM model for a customer's financial information.
One-to-Many relationship with Customer (a customer can have multiple records over time).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.customer import Customer


class FinancialInformation(Base):
    """
    Stores financial data for a customer.
    Relates back to Customer via a Many-to-One relationship.
    """

    __tablename__ = "financial_information"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # Enforces One-to-One at the database level
        index=True,
    )

    # --- Income & Expenses ---
    salary: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=True,
        comment="Monthly net salary or income in USD",
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # --- Inverse relationship to Customer ---
    customer: Mapped["Customer"] = relationship(
        "Customer", back_populates="financial_information"
    )

    def __repr__(self) -> str:
        return (
            f"<FinancialInformation(id={self.id}, "
            f"customer_id={self.customer_id}, salary={self.salary})>"
        )
