"""
Configuración de la conexión a la base de datos con SQLAlchemy 2.0.
Gestiona el Engine, la SessionFactory y provee la dependencia de sesión para FastAPI.
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# URL de conexión
# ---------------------------------------------------------------------------
# Se recomienda mover esto a un archivo de configuración con pydantic-settings.
# Ejemplo para PostgreSQL: "postgresql+psycopg2://user:password@host:5432/dbname"


DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:S3F1L_Dev@localhost:5432/centralizacion_db",
)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
engine = create_engine(
    DATABASE_URL,
    echo=False,           # Cambiar a True para ver el SQL en consola (debugging)
    pool_pre_ping=True,   # Verifica la conexión antes de usarla (evita errores de conexión caída)
    pool_size=50,         # Aumentado para soportar mayor concurrencia de requests/background tasks
    max_overflow=50,      # Permitir hasta 100 conexiones totales
    pool_timeout=120,     # Tiempo de espera máximo de 120s
)

# ---------------------------------------------------------------------------
# SessionFactory
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


# ---------------------------------------------------------------------------
# Dependencia de FastAPI (Dependency Injection)
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """
    Dependencia de FastAPI que provee una sesión de base de datos por request.
    Garantiza que la sesión se cierre al finalizar, incluso si hay una excepción.

    Uso en un router:
        @router.get("/items/")
        def read_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
