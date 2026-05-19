"""
ORM models for customer contact data collections:
  - CollectionPhone    → table: collection_phones
  - CollectionAddress  → table: collection_addresses
  - CollectionEmail    → table: collection_emails

All models share a Many-to-One relationship with Customer.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.customer import Customer


class CollectionPhone(Base):
    """
    Stores phone numbers associated with a customer.
    One customer can have multiple phone records (One-to-Many).
    """

    __tablename__ = "collection_phones"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Local phone number without country code",
    )
    country_code: Mapped[Optional[str]] = mapped_column(
        String(5),
        nullable=True,
        default="+593",
        comment="Country dialing code, e.g. +593",
    )
    phone_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="MOBILE, HOME, WORK",
    )
    source: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default="Manual",
        comment="Origin system: Collecta, DATA SEFIL, Manual, etc.",
    )
    calls_effective: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True, comment="Number of effective calls (Collecta)"
    )
    calls_not_effective: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True, comment="Number of non-effective calls (Collecta)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Inverse relationship to Customer ---
    customer: Mapped["Customer"] = relationship("Customer", back_populates="phones")

    def __repr__(self) -> str:
        return (
            f"<CollectionPhone(id={self.id}, "
            f"phone_number='{self.phone_number}', customer_id={self.customer_id})>"
        )


class CollectionAddress(Base):
    """
    Stores physical addresses associated with a customer.
    One customer can have multiple address records (One-to-Many).
    """

    __tablename__ = "collection_addresses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    address_line: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Full street address including number",
    )
    province: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_type: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="HOME, WORK, REFERENCE",
    )
    source: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default="Manual",
        comment="Origin system: Collecta, DATA SEFIL, Manual, etc.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Inverse relationship to Customer ---
    customer: Mapped["Customer"] = relationship("Customer", back_populates="addresses")

    def __repr__(self) -> str:
        return (
            f"<CollectionAddress(id={self.id}, "
            f"city='{self.city}', customer_id={self.customer_id})>"
        )


class CollectionEmail(Base):
    """
    Stores email addresses associated with a customer.
    One customer can have multiple email records (One-to-Many).
    """

    __tablename__ = "collection_emails"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email_address: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        comment="Customer email address",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Indicates whether this email address is currently active",
    )
    source: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default="Manual",
        comment="Origin system: Collecta, DATA SEFIL, Manual, etc.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Inverse relationship to Customer ---
    customer: Mapped["Customer"] = relationship("Customer", back_populates="emails")

    def __repr__(self) -> str:
        return (
            f"<CollectionEmail(id={self.id}, "
            f"email_address='{self.email_address}', customer_id={self.customer_id})>"
        )
