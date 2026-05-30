"""
Pydantic V2 schemas for the POST /sync/bulk-upsert endpoint.
Shared between Worker (serializer) and API (deserializer/validator).
"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PhoneItem(BaseModel):
    phone_number: str = Field(..., max_length=20)
    phone_type: Optional[str] = Field(None, max_length=20)
    country_code: str = Field(default="+593", max_length=5)
    source: str = Field(..., max_length=50)
    calls_effective: Optional[int] = None
    calls_not_effective: Optional[int] = None


class AddressItem(BaseModel):
    address_line: str = Field(..., max_length=500)
    province: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    canton: Optional[str] = Field(None, max_length=100)
    parish: Optional[str] = Field(None, max_length=100)
    neighborhood: Optional[str] = Field(None, max_length=100)
    address_type: Optional[str] = Field(None, max_length=30)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str = Field(..., max_length=50)


class EmailItem(BaseModel):
    email_address: str = Field(..., max_length=150)
    is_active: bool = True
    source: str = Field(..., max_length=50)


class RelationshipItem(BaseModel):
    relationship_type: str = Field(..., max_length=30)
    related_identification: Optional[str] = Field(None, max_length=13)
    related_name: Optional[str] = Field(None, max_length=200)
    related_birth_date: Optional[date] = None
    related_gender: Optional[str] = Field(None, max_length=20)
    related_civil_status: Optional[str] = Field(None, max_length=30)
    related_death_date: Optional[date] = None
    source: str = Field(default="DATA SEFIL", max_length=50)


class CustomerUpsertItem(BaseModel):
    """
    Standardized customer record for batch ingestion from the Worker.
    All fields except identification are optional — the API merges them into existing records.
    If the customer does not exist and first_name is absent, the record is skipped.
    """
    identification: str = Field(..., min_length=10, max_length=13)
    first_name: Optional[str] = Field(None, max_length=200)
    last_name: Optional[str] = Field(None, max_length=200)
    gender: Optional[str] = Field(None, max_length=20)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = Field(None, max_length=200)
    nationality: Optional[str] = Field(None, max_length=100)
    civil_status: Optional[str] = Field(None, max_length=30)
    profession: Optional[str] = Field(None, max_length=500)
    salary: Optional[float] = None
    phones: List[PhoneItem] = []
    addresses: List[AddressItem] = []
    emails: List[EmailItem] = []
    relationships: List[RelationshipItem] = []


class BulkUpsertRequest(BaseModel):
    customers: List[CustomerUpsertItem] = Field(..., min_length=1)


class BulkUpsertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = []
