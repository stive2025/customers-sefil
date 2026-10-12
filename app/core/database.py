"""
Configuración de la conexión a la base de datos con SQLAlchemy 2.0.
Gestiona el Engine, la SessionFactory y provee la dependencia de sesión para FastAPI.
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# URL de conexión (MySQL / MariaDB)
# ---------------------------------------------------------------------------
# Se arma desde MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER y MYSQL_PASSWORD.
# URL.create escapa los caracteres especiales de la contraseña (@, %, etc.).
# DATABASE_URL, si está definida, tiene prioridad:
#   "mysql+pymysql://user:password@host:3306/dbname?charset=utf8mb4"


def _build_database_url() -> URL:
    if os.getenv("DATABASE_URL"):
        return make_url(os.environ["DATABASE_URL"])
    return URL.create(
        "mysql+pymysql",
        username=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.getenv("MYSQL_DATABASE", "centralizacion_db"),
        query={"charset": "utf8mb4"},
    )


DATABASE_URL: URL = _build_database_url()

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# El servidor de Hostinger limita a 100 conexiones por usuario (max_user_connections)
# y cierra las conexiones inactivas a los 300 s (wait_timeout), por eso el pool
# es acotado y se reciclan las conexiones antes de ese límite.
engine = create_engine(
    DATABASE_URL,
    echo=False,           # Cambiar a True para ver el SQL en consola (debugging)
    pool_pre_ping=True,   # Verifica la conexión antes de usarla (evita errores de conexión caída)
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_timeout=120,     # Tiempo de espera máximo de 120s
    pool_recycle=280,     # Menor que wait_timeout (300 s) del servidor
    # Las fechas se guardan en UTC (ver UTCDateTime en app/models/base.py)
    connect_args={"init_command": "SET time_zone = '+00:00'"},
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
