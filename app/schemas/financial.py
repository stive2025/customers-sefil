"""
Pydantic V2 schemas for the FinancialInformation model.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FinancialInformationBase(BaseModel):
    salary: Optional[float] = Field(
        None, ge=0, description="Monthly net salary or income in USD"
    )


class FinancialInformationCreate(FinancialInformationBase):
    """Schema for creating or registering a customer's financial information."""
    pass


class FinancialInformationUpdate(BaseModel):
    """Schema for partial update of financial information."""

    salary: Optional[float] = Field(None, ge=0)


class FinancialInformationResponse(FinancialInformationBase):
    """Response schema including database-generated fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
