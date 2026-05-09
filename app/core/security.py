"""
Seguridad M2M mediante API Keys estáticas en la cabecera X-API-Key.

Configuración (.env):
  API_KEYS="Collecta:sk_live_abc123,DATA_SEFIL:sk_live_def456,Leads:sk_live_ghi789"

  Formato por entrada: "NombreSistema:clave_secreta"
  Si una entrada no tiene ":", la clave se usa como su propio nombre.

Uso como dependencia de router (protege todos los endpoints del router):
  router = APIRouter(dependencies=[Depends(get_api_key)])

Uso en un endpoint individual (para loguear el sistema origen):
  def mi_endpoint(system: str = Depends(get_api_key)): ...
"""

import logging
import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Esquema de cabecera
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,   # Manejamos el 401 manualmente para personalizar el mensaje
    description="API Key del sistema cliente. Formato: 'NombreSistema:clave' en API_KEYS.",
)


# ---------------------------------------------------------------------------
# Carga de claves desde el entorno (una sola vez al arranque)
# ---------------------------------------------------------------------------

def _load_api_keys() -> dict[str, str]:
    """
    Parsea API_KEYS del entorno y retorna un dict {clave_secreta: nombre_sistema}.

    Formato esperado en el .env:
      API_KEYS="Collecta:sk_live_abc123,DATA_SEFIL:sk_live_def456"

    Si una entrada no tiene ":", la clave funciona como nombre propio.
    Las entradas vacías o duplicadas se ignoran silenciosamente.
    """
    raw = os.getenv("API_KEYS", "").strip()
    if not raw:
        logger.warning(
            "[security] La variable de entorno API_KEYS está vacía. "
            "Todos los requests serán rechazados."
        )
        return {}

    keys: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            name, _, secret = entry.partition(":")
            name, secret = name.strip(), secret.strip()
        else:
            name = secret = entry

        if not secret:
            continue
        if secret in keys:
            logger.warning("[security] Clave duplicada detectada para sistema '%s' — se ignora.", name)
            continue

        keys[secret] = name

    logger.info("[security] %d API key(s) cargada(s): %s", len(keys), list(keys.values()))
    return keys


# Dict inmutable en memoria: {clave_secreta: nombre_sistema}
_API_KEYS: dict[str, str] = _load_api_keys()


# ---------------------------------------------------------------------------
# Dependencia de seguridad
# ---------------------------------------------------------------------------

async def get_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """
    Valida la cabecera X-API-Key contra las claves cargadas en memoria.

    Returns:
        El nombre del sistema asociado a la clave (ej. "Collecta").
        Útil para auditoría/logging en endpoints que quieran saber el origen.

    Raises:
        HTTPException 401: si la cabecera está ausente o la clave no es válida.
    """
    if api_key and api_key in _API_KEYS:
        return _API_KEYS[api_key]

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API Key ausente o inválida. Incluye una cabecera 'X-API-Key' válida.",
        headers={"WWW-Authenticate": "ApiKey"},
    )
