"""
Dependencias reutilizables para inyección en los endpoints de FastAPI.
"""

from typing import Generator

from sqlalchemy.orm import Session

from app.core.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    Dependencia de FastAPI que provee una sesión de base de datos por request.

    - Abre la sesión al inicio del request.
    - La cierra automáticamente al finalizar, incluso si ocurre una excepción.
    - Uso: `db: Session = Depends(get_db)` en cualquier endpoint.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()