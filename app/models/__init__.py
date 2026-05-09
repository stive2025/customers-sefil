"""
Models package entry point.
Importing all models here ensures SQLAlchemy registers them
in Base.metadata — critical for Alembic autogenerate to work correctly.
"""

from app.models.base import Base
from app.models.customer import Customer
from app.models.collections import CollectionPhone, CollectionAddress, CollectionEmail
from app.models.financial import FinancialInformation
from app.models.equifax import EquifaxQuery

__all__ = [
    "Base",
    "Customer",
    "CollectionPhone",
    "CollectionAddress",
    "CollectionEmail",
    "FinancialInformation",
    "EquifaxQuery",
]
