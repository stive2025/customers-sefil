"""
Pydantic V2 schemas for the POST /sync/bulk-upsert endpoint.
Shared between Worker (serializer) and API (deserializer/validator).
"""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PhoneItem(BaseModel):
    phone_number: str = Field(..., max_length=20)
    phone_type: Optional[str] = Field(None, max_length=20)
    country_code: str = Field(default="+593", max_length=5)
    calls_effective: Optional[int] = None
    calls_not_effective: Optional[int] = None
    created_source: Optional[str] = Field(None, max_length=50)

    @field_validator("created_source", mode="before")
    @classmethod
    def normalize_source(cls, v: str | None) -> str | None:
        if v and v.strip().lower() == "collapi":
            return "Collecta"
        return v

    @field_validator("phone_type", mode="before")
    @classmethod
    def normalize_phone_type(cls, v: str | None) -> str | None:
        if not v:
            return None
        import unicodedata
        val = ''.join(c for c in unicodedata.normalize('NFD', v) if unicodedata.category(c) != 'Mn')
        val = val.upper().strip()
        if val in ("MOVIL", "MOBILE", "CELULAR", "CEL", "MOBI", "CELU"):
            return "MOVIL"
        if val in ("FIJO", "CONVENCIONAL", "CASA", "TRABAJO", "DOMICILIO", "WORK", "HOME", "CONV", "OFICINA"):
            return "FIJO"
        if "MOVIL" in val or "MOBILE" in val or "CEL" in val:
            return "MOVIL"
        if "FIJO" in val or "CONV" in val or "CASA" in val:
            return "FIJO"
        return None


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
    created_source: Optional[str] = Field(None, max_length=50)

    @field_validator("created_source", mode="before")
    @classmethod
    def normalize_source(cls, v: str | None) -> str | None:
        if v and v.strip().lower() == "collapi":
            return "Collecta"
        return v

    @field_validator("address_type", mode="before")
    @classmethod
    def normalize_address_type(cls, v: str | None) -> str | None:
        if not v:
            return None
        val = v.upper().strip()
        if val in ("TRABAJO", "WORK", "JOB", "OFICINA", "EMPRESA"):
            return "Trabajo"
        if val in ("DOMICILIO", "HOME", "CASA", "RESIDENCIA", "HOGAR"):
            return "Hogar"
        return "Hogar"


class EmailItem(BaseModel):
    email_address: str = Field(..., max_length=150)
    is_active: bool = True
    created_source: Optional[str] = Field(None, max_length=50)

    @field_validator("created_source", mode="before")
    @classmethod
    def normalize_source(cls, v: str | None) -> str | None:
        if v and v.strip().lower() == "collapi":
            return "Collecta"
        return v


class RelationshipItem(BaseModel):
    relationship_type: str = Field(..., max_length=30)
    related_identification: Optional[str] = Field(None, max_length=13)
    related_name: Optional[str] = Field(None, max_length=200)
    related_birth_date: Optional[date] = None
    related_gender: Optional[str] = Field(None, max_length=20)
    related_civil_status: Optional[str] = Field(None, max_length=30)
    related_death_date: Optional[date] = None
    created_source: Optional[str] = Field(None, max_length=50)

    @field_validator("created_source", mode="before")
    @classmethod
    def normalize_source(cls, v: str | None) -> str | None:
        if v and v.strip().lower() == "collapi":
            return "Collecta"
        return v


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
    economic_activity: Optional[str] = Field(None, max_length=500)
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
