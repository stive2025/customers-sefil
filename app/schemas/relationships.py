"""
Pydantic V2 schemas for CustomerRelationship (family/genomic relationships from DATA SEFIL).
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CustomerRelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    relationship_type: str = Field(description="MADRE, PADRE, HIJO, HERMANO, CONYUGE, etc.")
    related_identification: Optional[str] = None
    related_name: Optional[str] = None
    related_birth_date: Optional[date] = None
    related_gender: Optional[str] = None
    related_civil_status: Optional[str] = None
    related_death_date: Optional[date] = None
    source: Optional[str] = None
    created_at: datetime
