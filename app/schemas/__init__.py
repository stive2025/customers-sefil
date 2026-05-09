"""
Schemas package entry point.
Centralizes all Pydantic schema exports for the application.
"""

from app.schemas.customer import (
    CustomerBase,
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerResponseFull,
)
from app.schemas.collections import (
    CollectionPhoneCreate,
    CollectionPhoneResponse,
    CollectionAddressCreate,
    CollectionAddressResponse,
    CollectionEmailCreate,
    CollectionEmailResponse,
)
from app.schemas.financial import (
    FinancialInformationCreate,
    FinancialInformationUpdate,
    FinancialInformationResponse,
)
from app.schemas.equifax import (
    EquifaxQueryCreate,
    EquifaxQueryResponse,
)

__all__ = [
    # Customer
    "CustomerBase",
    "CustomerCreate",
    "CustomerUpdate",
    "CustomerResponse",
    "CustomerResponseFull",
    # Collections
    "CollectionPhoneCreate",
    "CollectionPhoneResponse",
    "CollectionAddressCreate",
    "CollectionAddressResponse",
    "CollectionEmailCreate",
    "CollectionEmailResponse",
    # Financial
    "FinancialInformationCreate",
    "FinancialInformationUpdate",
    "FinancialInformationResponse",
    # Equifax
    "EquifaxQueryCreate",
    "EquifaxQueryResponse",
]
