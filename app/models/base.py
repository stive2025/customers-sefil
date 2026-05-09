"""
Módulo base para los modelos SQLAlchemy.
Define la clase Base de la que heredarán todos los modelos ORM del proyecto.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Clase base declarativa para todos los modelos ORM.
    Usar DeclarativeBase es la forma recomendada en SQLAlchemy 2.0+.
    """
    pass
