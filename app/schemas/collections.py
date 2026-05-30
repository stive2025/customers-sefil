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
# Shared soft-delete body
# ---------------------------------------------------------------------------

class SoftDeleteBody(BaseModel):
    deleted_by: Optional[str] = Field(None, max_length=100)
    deleted_source: Optional[str] = Field(None, max_length=50)


# ---------------------------------------------------------------------------
# CollectionPhone
# ---------------------------------------------------------------------------

class CollectionPhoneBase(BaseModel):
    phone_number: str = Field(..., max_length=20, examples=["0991234567"])
    country_code: Optional[str] = Field(default="+593", max_length=5)
    phone_type: Optional[str] = Field(None, max_length=20)
    source: str = Field(default="Manual", max_length=50)


class CollectionPhoneCreate(CollectionPhoneBase):
    created_by: Optional[str] = Field(None, max_length=100)
    created_source: Optional[str] = Field(None, max_length=50)


class CollectionPhoneUpdate(BaseModel):
    phone_number: Optional[str] = Field(None, max_length=20)
    phone_type: Optional[str] = Field(None, max_length=20)
    country_code: Optional[str] = Field(None, max_length=5)
    updated_by: Optional[str] = Field(None, max_length=100)
    updated_source: Optional[str] = Field(None, max_length=50)


class CollectionPhoneResponse(CollectionPhoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    calls_effective: Optional[int] = None
    calls_not_effective: Optional[int] = None
    is_active: bool = True
    created_by: Optional[str] = None
    created_source: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    updated_source: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    deleted_source: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# CollectionAddress
# ---------------------------------------------------------------------------

class CollectionAddressBase(BaseModel):
    address_line: str = Field(..., max_length=500)
    province: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    canton: Optional[str] = Field(None, max_length=100)
    parish: Optional[str] = Field(None, max_length=100)
    neighborhood: Optional[str] = Field(None, max_length=100)
    address_type: Optional[str] = Field(None, max_length=30)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str = Field(default="Manual", max_length=50)


class CollectionAddressCreate(CollectionAddressBase):
    created_by: Optional[str] = Field(None, max_length=100)
    created_source: Optional[str] = Field(None, max_length=50)


class CollectionAddressUpdate(BaseModel):
    address_line: Optional[str] = Field(None, max_length=500)
    province: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    canton: Optional[str] = Field(None, max_length=100)
    parish: Optional[str] = Field(None, max_length=100)
    neighborhood: Optional[str] = Field(None, max_length=100)
    address_type: Optional[str] = Field(None, max_length=30)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    updated_by: Optional[str] = Field(None, max_length=100)
    updated_source: Optional[str] = Field(None, max_length=50)


class CollectionAddressResponse(CollectionAddressBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    is_active: bool = True
    created_by: Optional[str] = None
    created_source: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    updated_source: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    deleted_source: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# CollectionEmail
# ---------------------------------------------------------------------------

class CollectionEmailBase(BaseModel):
    email_address: EmailStr = Field(...)
    is_active: bool = Field(default=True)
    source: str = Field(default="Manual", max_length=50)


class CollectionEmailCreate(CollectionEmailBase):
    created_by: Optional[str] = Field(None, max_length=100)
    created_source: Optional[str] = Field(None, max_length=50)


class CollectionEmailUpdate(BaseModel):
    email_address: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    updated_by: Optional[str] = Field(None, max_length=100)
    updated_source: Optional[str] = Field(None, max_length=50)


class CollectionEmailResponse(CollectionEmailBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    created_by: Optional[str] = None
    created_source: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    updated_source: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    deleted_source: Optional[str] = None
    created_at: datetime
