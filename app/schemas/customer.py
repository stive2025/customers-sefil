"""
Pydantic V2 schemas for the Customer model.
Separates write (Create/Update) from read (Response) validation.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


# ---------------------------------------------------------------------------
# Base schema (shared fields for write and read)
# ---------------------------------------------------------------------------

class CustomerBase(BaseModel):
    """Common fields for Customer creation and read schemas."""

    identification: str = Field(
        ...,
        min_length=10,
        max_length=13,
        description="National ID (cédula, 10 digits) or company tax ID (RUC, 13 digits)",
        examples=["0912345678", "0912345670001"],
    )
    first_name: str = Field(..., max_length=100, description="Customer's first name(s)")
    last_name: str = Field(..., max_length=100, description="Customer's last name(s)")
    gender: Optional[str] = Field(
        None, max_length=20, description="MALE, FEMALE, OTHER"
    )
    birth_date: Optional[date] = Field(
        None, description="Date of birth in ISO format (YYYY-MM-DD)"
    )
    birth_place: Optional[str] = Field(None, max_length=100, description="City of birth")
    nationality: Optional[str] = Field(
        default="Ecuadorian", max_length=50, description="Customer's nationality"
    )
    civil_status: Optional[str] = Field(
        None, max_length=30, description="SINGLE, MARRIED, DIVORCED, WIDOWED"
    )
    profession: Optional[str] = Field(None, max_length=100, description="Customer's profession")


# ---------------------------------------------------------------------------
# Write schemas (input)
# ---------------------------------------------------------------------------

class CustomerCreate(CustomerBase):
    """Schema for creating a new Customer. Inherits all fields from CustomerBase."""
    pass


class CustomerUpdate(BaseModel):
    """
    Schema for partial (PATCH) updates to a Customer.
    All fields are optional — only provided fields are updated.
    """

    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    gender: Optional[str] = Field(None, max_length=20)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = Field(None, max_length=100)
    nationality: Optional[str] = Field(None, max_length=50)
    civil_status: Optional[str] = Field(None, max_length=30)
    profession: Optional[str] = Field(None, max_length=100)


# ---------------------------------------------------------------------------
# Read schemas (output)
# ---------------------------------------------------------------------------

class CustomerResponse(CustomerBase):
    """
    Response schema for Customer, including database-generated fields
    and computed properties.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    # --- Computed fields (generated at serialization time, not stored in DB) ---

    @computed_field
    @property
    def full_name(self) -> str:
        """Concatenates first_name and last_name into a single string."""
        return f"{self.first_name} {self.last_name}".strip()

    @computed_field
    @property
    def age(self) -> Optional[int]:
        """
        Calculates the customer's exact age in years based on birth_date.
        Returns None if birth_date is not set.
        """
        if not self.birth_date:
            return None
        today = date.today()
        # Subtract 1 if the birthday hasn't occurred yet this year
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )


class CustomerResponseFull(CustomerResponse):
    """
    Extended response schema that includes all nested relationships.
    Use this for customer detail endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    phones: List["CollectionPhoneResponse"] = []
    addresses: List["CollectionAddressResponse"] = []
    emails: List["CollectionEmailResponse"] = []
    financial_information: Optional["FinancialInformationResponse"] = None
    equifax_queries: List["EquifaxQueryResponse"] = []
    relationships: List["CustomerRelationshipResponse"] = []


# ---------------------------------------------------------------------------
# Forward reference resolution
# Imported at module bottom to avoid circular imports.
# ---------------------------------------------------------------------------
from app.schemas.collections import (  # noqa: E402
    CollectionAddressResponse,
    CollectionEmailResponse,
    CollectionPhoneResponse,
)
from app.schemas.financial import FinancialInformationResponse  # noqa: E402
from app.schemas.equifax import EquifaxQueryResponse  # noqa: E402
from app.schemas.relationships import CustomerRelationshipResponse  # noqa: E402

CustomerResponseFull.model_rebuild()
