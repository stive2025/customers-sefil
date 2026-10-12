"""
Módulo base para los modelos SQLAlchemy.
Define la clase Base de la que heredarán todos los modelos ORM del proyecto.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """
    Clase base declarativa para todos los modelos ORM.
    Usar DeclarativeBase es la forma recomendada en SQLAlchemy 2.0+.
    """
    pass


class UTCDateTime(TypeDecorator):
    """
    DATETIME(6) que siempre almacena UTC.

    MySQL no guarda la zona horaria: al escribir se convierte el valor a UTC
    (sin tzinfo) y al leer se marca como UTC, así la API sigue devolviendo
    fechas con zona ("...Z") como cuando la base era PostgreSQL.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name in ("mysql", "mariadb"):
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value
