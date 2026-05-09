"""
Punto de entrada principal de la aplicación FastAPI.
Servicio de Centralización de Personas - CASV
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routers import customers, sync

# ---------------------------------------------------------------------------
# Inicialización de la aplicación
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Servicio de Centralización de Personas",
    description=(
        "API REST para la gestión centralizada de información de clientes, "
        "incluyendo datos de contacto, información financiera y consultas al "
        "Buró de Crédito (Equifax)."
    ),
    version="1.0.0",
    contact={
        "name": "Sefil",
        "email": "sefil.sa@sefil.com",
    },
    license_info={
        "name": "Privado - Uso Interno",
    },
    docs_url="/docs",       # Swagger UI
    redoc_url="/redoc",     # ReDoc UI
)

# ---------------------------------------------------------------------------
# Middlewares
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Restringir en producción a dominios específicos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
# Cada router define sus propios tags internamente.
# Aquí solo se registra el prefix de la URL base.
app.include_router(customers.router, prefix="/api/v1/customers")
app.include_router(sync.router,      prefix="/api/v1/sync")
# app.include_router(collections.router, prefix="/api/v1/collections")
# app.include_router(financial.router, prefix="/api/v1/financial")
# app.include_router(equifax.router, prefix="/api/v1/equifax")


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"], summary="Health Check")
def root() -> dict:
    """Endpoint de verificación de estado del servicio."""
    return {
        "service": "Servicio de Centralización de Personas",
        "status": "online",
        "version": "1.0.0",
    }
