# Contratos de Datos y Lógica de Merge

> Generado por lectura directa del código el 2026-07-10. Todas las citas son `archivo:línea`.

## 1. Shape esperado por fuente

### Collecta (`app/services/etl_collecta.py`)

```
GET /api/clients    → {success, message, data: {data: [{ci, name, gender, civil_status, economic_activity, ...}], last_page}}
GET /api/contacts   → {success, message, data: {data: [{phone_number, phone_type, calls_effective, calls_not_effective, client_ci?}], last_page}}
GET /api/directions → {success, message, data: {data: [{direction, canton, client_ci, latitude?, longitude?, ...}], last_page}}
```
(`etl_collecta.py:8-13`)

- Todos los campos se leen con `.get()`, nunca indexación directa (excepción única y controlada: `row["latitude"]` en `etl_collecta.py:172-178`, solo evaluada si `row.get("latitude")` ya fue verdadero, y envuelta en `try/except`).
- **No hay validación Pydantic del payload crudo** — Pydantic (`CustomerUpsertItem`, `PhoneItem`, `AddressItem`) solo se aplica al resultado ya transformado (`etl_collecta.py:190,214,249,262`).
- Limitación documentada pero no forzada por código: en modo bulk, `/api/contacts` no trae `client_ci`, por lo que el agrupamiento de teléfonos por cliente no funciona en ese modo (`etl_collecta.py:230-256`) — no falla, simplemente no asocia nada.
- `sync_manual.py` solo sincroniza `/clients` (customers); contactos y direcciones de Collecta no se sincronizan desde el script manual (`sync_manual.py:117-129`).

### DATA SEFIL (`app/services/etl_datasefil.py`)

```python
{
  "identification": "1712345678", "name": "...", "gender": "M", "birth": "1990-05-15",
  "place_birth": "...", "state_civil": "soltero", "nationality": "...", "profession": "...",
  "salary": 1500.00,
  "contacts": [{"phone_number": "...", "phone_type": "CELULAR"}],
  "address":  [{"address": "...", "province": "...", "city": "...", "type": "DOMICILIO"}],
  "emails":   [{"direction": "juan@email.com", "active": true}],
  "parents":  [{"type": "MADRE", "name": "...", "identification": "...", ...}],
}
```
(`etl_datasefil.py:8-23`)

- Mismo patrón defensivo: todo vía `.get()`, listas anidadas vía `raw.get("contacts", [])` etc. (`etl_datasefil.py:105-226`).
- Sin validación Pydantic del payload crudo; se aplica solo al output ya limpio (`etl_datasefil.py:253-260`).
- `emails` también acepta un campo singular `email` a nivel raíz, mezclado con la lista `emails` (`etl_datasefil.py:248-251`).

### Leads (`app/services/etl_leads.py`)

- No es HTTP: es un JOIN MySQL `leads` + `entries` filtrando `event = 'LEAD.UPDATED'` (`etl_leads.py:75-83`).
- El campo `attributes` es JSON en texto; se parsea con `json.loads` dentro de `try/except (JSONDecodeError, TypeError)` — si es inválido, la fila se descarta silenciosamente, no se aborta el proceso (`etl_leads.py:116-119`).
- Dentro de `attributes`, todos los campos (`PRIMER NOMBRE`, `APELLIDO PATERNO`, teléfonos vía `_PHONE_KEY_MAP`, emails vía `_EMAIL_KEYS`, dirección de trabajo) se leen con `.get()` (`etl_leads.py:133-187`).
- Conexión MySQL: `pool_pre_ping=True`, `connect_timeout=10s` (`etl_leads.py:96-101`) — pero **la ejecución del query no tiene timeout**; una consulta lenta puede bloquear indefinidamente.

## 2. Limpieza y normalización (`app/services/data_cleaning.py`)

| Función | Línea | Comportamiento clave |
|---|---|---|
| `standardize_text` | `46-70` | Mayúsculas, quita caracteres de control, colapsa espacios. **No castea a `str`** — si el campo llega con otro tipo (int, list), lanza `TypeError`. |
| `clean_phone_number` | `73-116` | Quita prefijo `+593`/`593`, deja solo dígitos, si queda en 8-9 dígitos y no empieza en `0`, antepone `0`. **No re-agrega `+593` al resultado** (eso lo hace cada ETL por separado, hardcodeado) y **no valida longitud** más allá de esa heurística de 8/9 dígitos — cualquier otra longitud pasa tal cual. |
| `infer_phone_type` | `119-139` | 10 dígitos empezando en `09` → `MOVIL`; 9 dígitos con código provincial `02`-`07` → `FIJO`; 7 dígitos → `FIJO`; si no, `None`. |
| `clean_identification` | `142-189` | Exige solo dígitos tras limpiar separadores; si tiene 9 dígitos antepone `0`; exige longitud final exacta 10 (cédula) o 13 (RUC), si no `""`. **Sin dígito verificador** — no valida el algoritmo módulo-10 de cédula ecuatoriana; cualquier cadena numérica de 10/13 dígitos pasa. |
| `clean_email` | `495-500` | Regex simple; `None` si no matchea. |
| `clean_date` | `503-512` | Prueba 4 formatos (`%Y-%m-%d`, `%d/%m/%Y`, `%d-%m-%Y`, `%Y/%m/%d`); `None` si ninguno matchea. |
| `clean_salary` | `515-522` | `str` → reemplaza `,` por `.` → `float()`; `None` en error. |
| `clean_gender` / `clean_civil_status` | `481-492` | Mapas de texto libre en español → enums internos; `None` si no reconoce. |
| `migrate_system_data` (async, legacy) | `281-460` | Flujo alterno **ya no usado** por los 3 ETL actuales. Es la única función que envuelve **cada registro individualmente** en `try/except` (`443-452`) — los ETL activos no tienen este aislamiento (ver §4). |

**Teléfono**: no se fuerza `+593` en el valor limpio; el país se hardcodea aparte como `country_code="+593"` al construir `PhoneItem` en cada ETL (`etl_collecta.py:135`, `etl_datasefil.py:126`, `etl_leads.py:223`), ignorando cualquier código de país real que traiga la fuente.

**Cédula/RUC**: valida longitud (10/13) y heurística de cero perdido, pero **no valida dígito verificador**. Un identificador de longitud correcta pero matemáticamente inválido se acepta igual.

## 3. Paginación y concurrencia (`app/services/etl_fetcher.py`)

- Paginación por número de página, `_PER_PAGE = 100` (`etl_fetcher.py:12`), total de páginas tomado de `last_page` en la respuesta.
- **Riesgo de pérdida silenciosa de datos**: si la fuente renombra u omite `last_page`, el código usa `.get("last_page", 1)` (`etl_fetcher.py:27,35`) — sin error, simplemente se trae solo la página 1.
- Timeout `30s` por request (`etl_fetcher.py:23,32`) — no se cuelga indefinidamente.
- Paralelismo: página 1 se trae sincrónicamente, páginas 2..N en paralelo con `ThreadPoolExecutor(max_workers=5)` (`etl_fetcher.py:13,47-51`).
- Fallo en página 1: **no está envuelto en try/except**, la excepción se propaga (comentario explícito en `etl_fetcher.py:40`: dejar que la excepción suba para que el caller la registre).
- Fallo en páginas 2..N: se captura individualmente, se loguea como `warning` y **se descarta esa página silenciosamente** — el sync continúa con datos parciales, sin retry (`etl_fetcher.py:52-58`).

## 4. Lógica de Merge/Upsert

Existen **dos implementaciones independientes y divergentes**, no una lógica compartida: `app/services/bulk_upsert.py` (usado por `/sync/bulk-upsert` y por todos los `/run/*`) y `app/services/unified_sync.py` (usado por `/sync/customer`).

### Clave de dedup
`identification`, consistente en ambos paths (`bulk_upsert.py:172-174`, `unified_sync.py:241-243`), respaldado a nivel DB por `UNIQUE` en `customers.identification` (`app/models/customer.py:34-40`).

### `identification` inválida
- **Bulk path**: `CustomerUpsertItem.identification` es `Field(..., min_length=10, max_length=13)` en Pydantic (`app/schemas/sync.py:116`) — se valida **antes** de tocar la BD, a nivel de request completo. Un solo item con `identification` fuera de rango rechaza **todo el batch** con 422 (no hay validación de solo-dígitos a este nivel).
- **Single path**: `SyncPayload.data` es un `dict` sin schema; se extrae con `_extract_identification()` + `clean_identification()` (`unified_sync.py:47-51`, `data_cleaning.py:142-189`); si no se puede extraer, `ValueError` → 422 (`unified_sync.py:230-233`, `app/api/routers/sync.py:70-73`).
- En ningún caso se crea un "bucket" de duplicados silencioso: se rechaza antes de escribir.

### Campos vacíos se rellenan / campos con valor no se sobreescriben
Confirmado en ambos paths, mismo patrón `if incoming and not getattr(existing, attr): setattr(...)`:
- Bulk: `_DEMOGRAPHIC_FIELDS = (gender, birth_date, birth_place, nationality, civil_status, economic_activity)` (`bulk_upsert.py:27-30,186-193`) — **además** rellena `first_name`/`last_name` vacíos (`bulk_upsert.py:190-193`), algo que `unified_sync.py` **no hace**.
- Single: `_MERGEABLE_FIELDS` — mismos 6 campos, constante distinta, definida por separado (`unified_sync.py:37-40,256-259`).
- **Caveat**: el chequeo es por *truthiness* de Python, no `IS NULL` estricto — un valor `""`/`0`/`False` ya guardado se trataría como "vacío" y sería sobreescrito.
- Salario: mismo patrón, solo si `salary is None` (`bulk_upsert.py:111-119`, `unified_sync.py:162-170`).

### Contactos: qué cuenta como duplicado

| Colección | Bulk (`bulk_upsert.py`) | Single (`unified_sync.py`) |
|---|---|---|
| Teléfonos | Match exacto en `phone_number` crudo (`:38,42`). **Si hay match, SÍ actualiza** `calls_effective`, `calls_not_effective`, `alias`, `note` con el valor entrante si no es `None` (`:44-51`) — no es un "ignorar duplicado" puro. | Match en `phone_number` ya limpiado con `clean_phone_number` (`:99-102`). Si hay match, simplemente `continue` — no actualiza nada existente. |
| Direcciones | Match exacto en tupla `(address_line, city)` (`:70,74-76`) | Match en `address_line` normalizado con `standardize_text` (solo esa columna) (`:127,129-132`), más filtro de valores placeholder vía `_clean_geo_field` (`:116-123`), que bulk no tiene |
| Emails | Match exacto en `email_address` crudo (`:96,98`) | Match en `email_address` limpiado con `clean_email` (`:146,148-151`) |
| Relaciones | Tupla `(relationship_type, related_identification or related_name)` (`:123-124,128-129`) | Misma tupla (`:174-175,185-187`) |

No hay matching difuso ni normalización de formato dentro de `bulk_upsert.py` — asume que el payload ya llegó limpio desde el ETL/worker que lo generó (`bulk_upsert.py:1-4`).

### `calls_effective` / `calls_not_effective`
El README dice "se actualizan siempre". Más preciso: **solo en el path bulk**, y solo si el valor entrante no es `None` (si viene `None`, no toca el existente) (`bulk_upsert.py:42-47`). **`unified_sync.py` no tiene ningún código que toque estos dos campos** — es una divergencia real entre los dos endpoints de ingesta.

### Bug encontrado: `created_source` vs `source` en relaciones (bulk path)
`bulk_upsert.py` construye `CustomerRelationship(..., created_source=item.created_source)` (`bulk_upsert.py:131-141`), pero el modelo ORM define la columna como `source`, no `created_source` (`app/models/relationships.py:44`). **Esto lanza `TypeError` en tiempo de ejecución** para cualquier item del batch que traiga `relationships` no vacío. El error es capturado por el `except Exception` por-item (`bulk_upsert.py:233`), así que no tumba el proceso — pero silenciosamente descarta ese registro completo (se revierte su SAVEPOINT, se agrega a `result.errors`). `unified_sync.py` usa correctamente `source=source` (`unified_sync.py:190-200`) — el bug es exclusivo del path bulk, que es el que usan **todos** los `/run/*` (Collecta, DATA SEFIL, Leads). Efecto práctico: **ningún registro de DATA SEFIL con datos de familiares (`parents`) se está guardando correctamente vía `/run/datasefil` o `sync_manual.py --source datasefil`** — es la única fuente que aporta `relationships`.

### Transaccionalidad
- **Bulk**: SAVEPOINT por registro (`db.begin_nested()`, `bulk_upsert.py:171`) + **un solo COMMIT final** para todo el batch (`bulk_upsert.py:241-246`). Un registro que falla se revierte solo él (queda en `result.errors`); los registros previos exitosos permanecen pendientes en la sesión y sí se comitean al final. **El batch no es atómico como unidad** — no es "todo o nada", es "cada uno por su cuenta, commit conjunto al final si el commit no falla".
- **Single**: un commit al final de todo el merge de un solo cliente (`unified_sync.py:284`) — atómico por ser un solo registro; si algo falla antes, no llega a comitear (rollback vía `except SQLAlchemyError` en el router, `app/api/routers/sync.py:74-77`).

### Aislamiento por-registro en el ETL (no en el merge)
A diferencia de `migrate_system_data` (legacy, con `try/except` por registro), **`prepare_collecta_customers`, `prepare_datasefil_customers` y el loop de `prepare_leads_customers` no aíslan registros individuales**. Un solo registro con un campo de tipo inesperado (p.ej. `standardize_text` recibiendo un `int` en vez de `str`) lanza `TypeError` sin capturar dentro del loop de transformación, **abortando todo el `prepare_*` de esa fuente**, no solo ese registro (`etl_collecta.py:197-220`, `etl_datasefil.py:233-266`, `etl_leads.py:213-260`). Esto es distinto y anterior al aislamiento por-registro que sí existe en `bulk_upsert.py` — si la transformación ETL falla, nunca llega a `bulk_upsert_customers`.

### `/run/*` — background tasks y manejo de errores
Los 4 endpoints (`/run/collecta`, `/run/datasefil`, `/run/leads`, `/run/all`) devuelven `202` + `job_id` de inmediato vía `BackgroundTasks` (`app/api/routers/sync.py:194-220,271-326`). El resultado (éxito/error) se guarda en un diccionario en memoria `_JOBS`, consultable en `GET /status/{job_id}`. Excepciones en el trabajo de fondo se capturan y se guardan en `_JOBS`, **pero no se loguean en ese nivel externo** (`sync.py:199-203`) — si nadie consulta `/status/{job_id}`, el fallo es invisible salvo que la excepción ya haya sido logueada más abajo (lo cual sí ocurre para `_sync_leads` y `_run_upsert`, `sync.py:115-131,170-178`). Con `--workers 1` en prod esto funciona; con más de un worker, `/status/{job_id}` puede devolver 404 falso (ver `MAPA_SISTEMA_MDM.md`).
