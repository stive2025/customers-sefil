"""
Servicio de Limpieza y Migración de Datos (ETL).
Unifica datos provenientes de 4 sistemas fuente:
  - Collecta
  - CRM WhatsApp
  - DATA SEFIL
  - Leads

Flujo ETL:
  1. EXTRACT  — Recibir raw_data de cada sistema (lista de dicts)
  2. TRANSFORM — Limpiar y normalizar con las funciones de utilidad
  3. LOAD      — Validar con Pydantic y persistir en la BD con SQLAlchemy
"""

import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.schemas.customer import CustomerCreate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Sistemas fuente reconocidos por el ETL
SISTEMAS_VALIDOS: set[str] = {"COLLECTA", "CRM_WHATSAPP", "DATA_SEFIL", "LEADS"}

# Longitud de cédula ecuatoriana (10 dígitos) y RUC (13 dígitos)
CEDULA_LEN = 10
RUC_LEN = 13


# ---------------------------------------------------------------------------
# TRANSFORM — Funciones de limpieza y normalización
# ---------------------------------------------------------------------------

def standardize_text(texto: str | None) -> str:
    """
    Normaliza un texto a MAYÚSCULAS, elimina espacios extra y
    caracteres de control, preservando tildes y ñ.

    Args:
        texto: Cadena de texto cruda proveniente del sistema fuente.

    Returns:
        Texto normalizado en mayúsculas sin espacios dobles ni caracteres de control.
        Retorna cadena vacía si la entrada es None o vacía.

    Examples:
        >>> standardize_text("  juan   carlos  ")
        'JUAN CARLOS'
        >>> standardize_text("maría josé")
        'MARÍA JOSÉ'
    """
    if not texto:
        return ""
    # Eliminar caracteres de control (tabs, saltos de línea, etc.)
    texto = re.sub(r"[\x00-\x1f\x7f]", " ", texto)
    # Colapsar múltiples espacios en uno
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto.upper()


def clean_phone_number(telefono: str | None) -> str:
    """
    Limpia y normaliza un número de teléfono ecuatoriano.

    Transformaciones aplicadas:
      - Elimina el prefijo internacional "+593" o "593"
      - Elimina espacios, guiones, paréntesis y puntos
      - Si el resultado empieza en "0", lo conserva
      - Si queda sin el "0" inicial (9 dígitos para celular), lo agrega

    Args:
        telefono: Número de teléfono crudo (ej: "+593 99-123-4567", "099 123 4567").

    Returns:
        Número limpio de 10 dígitos para celular o 9 para convencional.
        Retorna cadena vacía si la entrada es None o inválida.

    Examples:
        >>> clean_phone_number("+593991234567")
        '0991234567'
        >>> clean_phone_number("+593 2 234-5678")
        '022345678'
        >>> clean_phone_number("099 123 45 67")
        '0991234567'
    """
    if not telefono:
        return ""

    numero: str = str(telefono).strip()

    # Remover prefijo internacional +593 o 593
    numero = re.sub(r"^\+?593", "", numero)

    # Remover todo excepto dígitos
    numero = re.sub(r"\D", "", numero)

    if not numero:
        return ""

    # Si el número quedó sin el "0" inicial (celular: 9 dígitos, conv: 8)
    if len(numero) in (9, 8) and not numero.startswith("0"):
        numero = "0" + numero

    return numero


def infer_phone_type(numero_limpio: str) -> str | None:
    """
    Infiere el tipo de teléfono (MOVIL o FIJO) en base a su patrón ecuatoriano.
    - MOVIL: 10 dígitos empezando con '09'.
    - FIJO: 9 dígitos empezando con código provincial, o 7 dígitos (local sin prefijo).
    
    Debe llamarse DESPUÉS de haber pasado el número por clean_phone_number.
    """
    if not numero_limpio:
        return None
        
    if len(numero_limpio) == 10 and numero_limpio.startswith("09"):
        return "MOVIL"
        
    if len(numero_limpio) == 9 and numero_limpio.startswith(("02", "03", "04", "05", "06", "07")):
        return "FIJO"
        
    if len(numero_limpio) == 7:
        return "FIJO"
        
    return None


def clean_identification(identificacion: str | None) -> str:
    """
    Valida y limpia un número de cédula ecuatoriana o RUC.

    Transformaciones aplicadas:
      - Elimina espacios, guiones y puntos
      - Verifica que sea numérico
      - Verifica longitud (10 para cédula, 13 para RUC)

    Args:
        identificacion: Número de cédula o RUC crudo.

    Returns:
        Identificación limpia (solo dígitos, longitud válida).
        Retorna cadena vacía si no es válida.

    Examples:
        >>> clean_identification("09-1234567-8")
        '0912345678'
        >>> clean_identification("1791234560001")
        '1791234560001'
        >>> clean_identification("ABC123")
        ''
    """
    if not identificacion:
        return ""

    # Eliminar separadores comunes
    limpia: str = re.sub(r"[\s\-\.]", "", str(identificacion)).strip()

    # Debe ser numérico
    if not limpia.isdigit():
        logger.debug("Identificación no numérica descartada: %s", identificacion)
        return ""

    # Cédulas de 9 dígitos: el cero inicial fue eliminado por el sistema origen
    # (tratamiento numérico). Restaurar igual que clean_phone_number.
    if len(limpia) == CEDULA_LEN - 1:
        limpia = "0" + limpia

    # Validar longitud
    if len(limpia) not in (CEDULA_LEN, RUC_LEN):
        logger.debug(
            "Identificación con longitud inválida (%d): %s", len(limpia), identificacion
        )
        return ""

    return limpia


def normalize_tipo_persona(valor: str | None) -> str:
    """
    Normaliza el tipo de persona a los valores aceptados: 'NATURAL' o 'JURIDICA'.

    Mapea variantes comunes de los sistemas fuente:
      - "natural", "persona natural", "PN", "1" → "NATURAL"
      - "juridica", "empresa", "PJ", "sociedad", "2" → "JURIDICA"

    Args:
        valor: Cadena cruda del sistema fuente.

    Returns:
        'NATURAL' o 'JURIDICA'. Por defecto retorna 'NATURAL' si no puede determinarse.
    """
    if not valor:
        return "NATURAL"

    normalizado: str = standardize_text(valor)

    juridica_keywords: set[str] = {"JURIDICA", "JURÍDICA", "EMPRESA", "PJ", "SOCIEDAD", "2", "S.A.", "CIA", "COMPAÑIA"}
    if any(kw in normalizado for kw in juridica_keywords):
        return "JURIDICA"

    return "NATURAL"


# ---------------------------------------------------------------------------
# Mapeo de campos por sistema fuente (EXTRACT → campo estándar)
# ---------------------------------------------------------------------------
# Cada sistema nombra sus campos de forma distinta. Este diccionario mapea
# los nombres de campo de cada sistema al campo estándar del modelo Customer.
FIELD_MAPPING: dict[str, dict[str, str]] = {
    "COLLECTA": {
        "cedula": "identificacion",
        "nombre": "nombres",
        "apellido": "apellidos",
        "tipo": "tipo_persona",
        "telefono": "telefono_raw",
    },
    "CRM_WHATSAPP": {
        "identification": "identificacion",
        "full_name": "nombres",
        "last_name": "apellidos",
        "person_type": "tipo_persona",
        "phone": "telefono_raw",
    },
    "DATA_SEFIL": {
        "num_cedula": "identificacion",
        "pnombre": "nombres",
        "papellido": "apellidos",
        "tipo_p": "tipo_persona",
        "celular": "telefono_raw",
    },
    "LEADS": {
        "document": "identificacion",
        "names": "nombres",
        "lastnames": "apellidos",
        "kind": "tipo_persona",
        "mobile": "telefono_raw",
    },
}


def _map_raw_record(system_name: str, record: dict[str, Any]) -> dict[str, Any]:
    """
    Mapea los campos de un registro crudo al esquema estándar interno,
    usando el mapeo definido en FIELD_MAPPING.

    Args:
        system_name: Nombre del sistema fuente (debe estar en FIELD_MAPPING).
        record: Diccionario crudo con los datos del sistema fuente.

    Returns:
        Diccionario con claves estándar internas.
    """
    mapping = FIELD_MAPPING.get(system_name.upper(), {})
    resultado: dict[str, Any] = {}

    for campo_origen, campo_destino in mapping.items():
        if campo_origen in record:
            resultado[campo_destino] = record[campo_origen]

    return resultado


# ---------------------------------------------------------------------------
# LOAD — Función de migración ETL asíncrona principal
# ---------------------------------------------------------------------------

async def migrate_system_data(
    system_name: str,
    raw_data: list[dict[str, Any]],
    db: Session,
) -> dict[str, int]:
    """
    Proceso ETL completo para migrar datos de un sistema fuente a la BD.

    Flujo por cada registro:
      1. Mapear campos del sistema fuente al esquema estándar.
      2. Limpiar y normalizar cada campo con las funciones de transformación.
      3. Validar el registro limpio con el schema Pydantic `CustomerCreate`.
      4. Verificar si el cliente ya existe (por identificación).
      5. Persistir en la BD (INSERT) o saltar duplicados.

    Args:
        system_name: Nombre del sistema fuente. Debe ser uno de SISTEMAS_VALIDOS.
        raw_data:    Lista de registros crudos (dicts) del sistema fuente.
        db:          Sesión activa de SQLAlchemy (inyectada por FastAPI o script).

    Returns:
        Diccionario con contadores: {"procesados": n, "insertados": n, "omitidos": n, "errores": n}

    Raises:
        ValueError: Si el system_name no es reconocido.

    Example:
        >>> raw = [{"cedula": "0912345678", "nombre": "juan", "apellido": "perez"}]
        >>> await migrate_system_data("COLLECTA", raw, db)
        {'procesados': 1, 'insertados': 1, 'omitidos': 0, 'errores': 0}
    """
    system_upper = system_name.upper()

    if system_upper not in SISTEMAS_VALIDOS:
        raise ValueError(
            f"Sistema '{system_name}' no reconocido. "
            f"Sistemas válidos: {', '.join(sorted(SISTEMAS_VALIDOS))}"
        )

    contadores: dict[str, int] = {
        "procesados": 0,
        "insertados": 0,
        "omitidos": 0,
        "errores": 0,
    }

    logger.info(
        "[ETL] Iniciando migración desde '%s' — %d registros a procesar.",
        system_upper,
        len(raw_data),
    )

    for idx, registro_crudo in enumerate(raw_data):
        contadores["procesados"] += 1

        try:
            # ---------------------------------------------------------------
            # 1. EXTRACT — Mapear campos del sistema fuente
            # ---------------------------------------------------------------
            registro_mapeado = _map_raw_record(system_upper, registro_crudo)

            # ---------------------------------------------------------------
            # 2. TRANSFORM — Limpiar y normalizar cada campo
            # ---------------------------------------------------------------
            identificacion_limpia = clean_identification(
                registro_mapeado.get("identificacion")
            )
            if not identificacion_limpia:
                logger.warning(
                    "[ETL] Registro #%d omitido — identificación inválida: '%s'",
                    idx,
                    registro_mapeado.get("identificacion"),
                )
                contadores["omitidos"] += 1
                continue

            datos_limpios: dict[str, Any] = {
                "identificacion": identificacion_limpia,
                "nombres": standardize_text(registro_mapeado.get("nombres")),
                "apellidos": standardize_text(registro_mapeado.get("apellidos")),
                "tipo_persona": normalize_tipo_persona(registro_mapeado.get("tipo_persona")),
            }

            # Validar que los nombres no estén vacíos tras la limpieza
            if not datos_limpios["nombres"]:
                logger.warning(
                    "[ETL] Registro #%d omitido — campo 'nombres' vacío tras limpieza. ID: %s",
                    idx,
                    identificacion_limpia,
                )
                contadores["omitidos"] += 1
                continue

            # ---------------------------------------------------------------
            # 3. VALIDATE — Validar con Pydantic
            # ---------------------------------------------------------------
            try:
                payload_validado = CustomerCreate(**datos_limpios)
            except ValidationError as exc:
                logger.warning(
                    "[ETL] Registro #%d inválido (Pydantic) — ID: %s | Errores: %s",
                    idx,
                    identificacion_limpia,
                    exc.error_count(),
                )
                contadores["errores"] += 1
                continue

            # ---------------------------------------------------------------
            # 4. CHECK — ¿Ya existe este cliente?
            # ---------------------------------------------------------------
            existente = (
                db.query(Customer)
                .filter(Customer.identification == payload_validado.identification)
                .first()
            )
            if existente:
                logger.debug(
                    "[ETL] Registro #%d omitido — cliente ya existe. ID: %s",
                    idx,
                    identificacion_limpia,
                )
                contadores["omitidos"] += 1
                continue

            # ---------------------------------------------------------------
            # 5. LOAD — Insertar en la base de datos
            # ---------------------------------------------------------------
            nuevo_cliente = Customer(
                identification=payload_validado.identification,
                first_name=payload_validado.first_name,
                last_name=payload_validado.last_name,
                gender=payload_validado.gender,
                birth_date=payload_validado.birth_date,
                birth_place=payload_validado.birth_place,
                nationality=payload_validado.nationality,
                civil_status=payload_validado.civil_status,
                profession=payload_validado.profession,
            )
            db.add(nuevo_cliente)

            try:
                db.commit()
                db.refresh(nuevo_cliente)
                contadores["insertados"] += 1
                logger.info(
                    "[ETL] Registro #%d insertado — ID: %s | Nombre: %s %s",
                    idx,
                    nuevo_cliente.identification,
                    nuevo_cliente.first_name,
                    nuevo_cliente.last_name or "",
                )
            except IntegrityError:
                # Race condition: otro proceso insertó el mismo registro
                db.rollback()
                contadores["omitidos"] += 1
                logger.warning(
                    "[ETL] Registro #%d — IntegrityError (race condition). ID: %s",
                    idx,
                    identificacion_limpia,
                )

        except Exception as exc:  # noqa: BLE001
            db.rollback()
            contadores["errores"] += 1
            logger.error(
                "[ETL] Error inesperado en registro #%d del sistema '%s': %s",
                idx,
                system_upper,
                exc,
                exc_info=True,
            )

    logger.info(
        "[ETL] Migración '%s' finalizada — %s",
        system_upper,
        contadores,
    )

    return contadores


# ---------------------------------------------------------------------------
# Funciones utilitarias adicionales para ETL de Collecta
# ---------------------------------------------------------------------------

_GENDER_MAP: dict[str, str] = {
    "m": "MALE", "masculino": "MALE", "hombre": "MALE", "male": "MALE",
    "f": "FEMALE", "femenino": "FEMALE", "mujer": "FEMALE", "female": "FEMALE",
}

_CIVIL_STATUS_MAP: dict[str, str] = {
    "soltero": "SINGLE", "soltera": "SINGLE",
    "casado": "MARRIED", "casada": "MARRIED",
    "divorciado": "DIVORCED", "divorciada": "DIVORCED",
    "viudo": "WIDOWED", "viuda": "WIDOWED",
    "union_libre": "COMMON_LAW", "union libre": "COMMON_LAW", "unión libre": "COMMON_LAW",
}


def clean_gender(raw: str | None) -> str | None:
    """Maps gender variants to 'MALE' or 'FEMALE'. Returns None if unrecognized."""
    if not raw:
        return None
    return _GENDER_MAP.get(str(raw).strip().lower())


def clean_civil_status(raw: str | None) -> str | None:
    """Maps civil status variants to SINGLE/MARRIED/DIVORCED/WIDOWED/COMMON_LAW."""
    if not raw:
        return None
    return _CIVIL_STATUS_MAP.get(str(raw).strip().lower())


def clean_email(raw: str | None) -> str | None:
    """Lowercases and validates basic email format. Returns None if invalid."""
    if not raw:
        return None
    email = str(raw).strip().lower()
    return email if re.fullmatch(r"[a-z0-9_.+\-]+@[a-z0-9\-]+\.[a-z0-9.\-]+", email) else None


def clean_date(raw: str | None) -> date | None:
    """Parses dates in common formats: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def clean_salary(raw: str | float | int | None) -> float | None:
    """Converts salary to float, accepting comma as decimal separator."""
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", ".").strip())
    except (ValueError, TypeError):
        return None
