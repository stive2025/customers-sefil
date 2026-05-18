"""
Pydantic V2 schemas for contact collection models:
  - CollectionPhone
  - CollectionAddress
  - CollectionEmail
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# CollectionPhone
# ---------------------------------------------------------------------------

class CollectionPhoneBase(BaseModel):
    phone_number: str = Field(
        ..., max_length=20, description="Local phone number", examples=["0991234567"]
    )
    country_code: Optional[str] = Field(
        default="+593", max_length=5, description="Country dialing code, e.g. +593"
    )
    phone_type: Optional[str] = Field(
        None, max_length=20, description="MOBILE, HOME, WORK"
    )
    source: str = Field(
        default="Manual", max_length=50, description="Origin system: Collecta, DATA SEFIL, Manual, etc."
    )


class CollectionPhoneCreate(CollectionPhoneBase):
    """Schema for creating a phone record. customer_id is injected from the path parameter."""
    pass


class CollectionPhoneResponse(CollectionPhoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# CollectionAddress
# ---------------------------------------------------------------------------

class CollectionAddressBase(BaseModel):
    address_line: str = Field(
        ..., max_length=500, description="Full street address including number"
    )
    province: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    address_type: Optional[str] = Field(
        None, max_length=30, description="HOME, WORK, REFERENCE"
    )
    source: str = Field(
        default="Manual", max_length=50, description="Origin system: Collecta, DATA SEFIL, Manual, etc."
    )


class CollectionAddressCreate(CollectionAddressBase):
    """Schema for creating an address record."""
    pass


class CollectionAddressResponse(CollectionAddressBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# CollectionEmail
# ---------------------------------------------------------------------------

class CollectionEmailBase(BaseModel):
    email_address: EmailStr = Field(..., description="Valid email address")
    is_active: bool = Field(default=True, description="Whether this email is currently active")
    source: str = Field(
        default="Manual", max_length=50, description="Origin system: Collecta, DATA SEFIL, Manual, etc."
    )


class CollectionEmailCreate(CollectionEmailBase):
    """Schema for creating an email record."""
    pass


class CollectionEmailResponse(CollectionEmailBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    created_at: datetime
