# Servicio de Centralización de Personas (MDM)

API REST para la gestión centralizada de información de clientes, unificando datos provenientes de múltiples sistemas fuente: **Collecta**, **DATA SEFIL** y **Leads**.

---

## Tabla de Contenidos

- [Arquitectura](#arquitectura)
- [Stack Tecnológico](#stack-tecnológico)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Archivos de Entorno](#archivos-de-entorno)
- [Ejecución](#ejecución)
- [Endpoints de la API](#endpoints-de-la-api)
- [Autenticación](#autenticación)
- [Sincronización Manual](#sincronización-manual)
- [Modelos de Datos](#modelos-de-datos)
- [Migraciones](#migraciones)

---

## Arquitectura

```
                    ┌─────────────────────────────────────────┐
                    │           SERVIDOR HOSTINGER            │
                    │                                         │
  Internet ──:443──►│  [ Nginx del servidor ]                 │
                    │         │                               │
                    │         ▼ :8002                         │
                    │     [ API ]  →  [ PostgreSQL ]          │
                    │                                         │
                    └─────────────────────────────────────────┘
                                        ▲
                                        │ HTTPS /sync/bulk-upsert
                    ┌─────────────────────────────────────────┐
                    │         RED LOCAL DE OFICINA            │
                    │                                         │
                    │  sync_manual.py ──► DATA SEFIL (LAN)   │
                    │                └──► Leads MySQL (LAN)  │
                    │                                         │
                    │  API /sync/run/collecta ──► Collecta   │
                    └─────────────────────────────────────────┘
```

**No existe un worker automático.** La sincronización es 100% manual:

| Fuente | Cómo sincronizar | Requiere red LAN |
|---|---|---|
| Collecta | `POST /sync/run/collecta` en Hostinger | No (URL pública) |
| DATA SEFIL | `python sync_manual.py --source datasefil` | Sí (172.20.1.105) |
| Leads | `python sync_manual.py --source leads` | Sí (172.20.1.102) |
| Todo | `python sync_manual.py --source all` | Sí |

---

## Stack Tecnológico

| Componente | Tecnología |
|---|---|
| Framework web | FastAPI |
| Servidor ASGI | Uvicorn |
| ORM | SQLAlchemy 2.0 |
| Validación | Pydantic V2 |
| Base de datos central | PostgreSQL 15 |
| Conector PostgreSQL | psycopg2-binary |
| Conector MySQL (Leads) | PyMySQL + cryptography |
| Migraciones | Alembic |
| Contenedores | Docker + Docker Compose |

---

## Estructura del Proyecto

```
.
├── app/
│   ├── api/
│   │   ├── dependencies.py          # Dependencia get_db() para FastAPI
│   │   └── routers/
│   │       ├── customers.py         # CRUD, búsqueda y sub-recursos de clientes
│   │       ├── sync.py              # Ingesta externa + endpoints /run/*
│   │       └── equifax.py           # Consultas Equifax
│   ├── core/
│   │   ├── database.py              # Engine, SessionLocal, Base
│   │   └── security.py              # Validación de API Keys (X-API-Key)
│   ├── models/
│   │   ├── base.py                  # DeclarativeBase compartida
│   │   ├── customer.py              # Modelo Customer (entidad central)
│   │   ├── collections.py           # CollectionPhone, CollectionAddress, CollectionEmail
│   │   ├── relationships.py         # CustomerRelationship (familiares — DATA SEFIL)
│   │   ├── financial.py             # FinancialInformation (One-to-One)
│   │   └── equifax.py               # EquifaxQuery
│   ├── schemas/
│   │   ├── customer.py              # CustomerCreate, CustomerUpdate, CustomerResponse
│   │   ├── collections.py           # Schemas de teléfonos, direcciones y emails
│   │   ├── relationships.py         # CustomerRelationshipResponse
│   │   ├── sync.py                  # CustomerUpsertItem, BulkUpsertRequest/Response
│   │   ├── financial.py             # FinancialInformationResponse
│   │   └── equifax.py               # EquifaxQueryResponse
│   └── services/
│       ├── data_cleaning.py         # Limpieza y normalización (teléfonos, cédulas, etc.)
│       ├── bulk_upsert.py           # Merge masivo: upsert + enriquecimiento de contactos
│       ├── unified_sync.py          # sync_external_customer() — ingesta individual
│       ├── etl_collecta.py          # ETL Collecta: clientes, contactos y direcciones
│       ├── etl_datasefil.py         # ETL DATA SEFIL: clientes, relaciones familiares
│       ├── etl_leads.py             # ETL Leads: extracción desde MySQL
│       └── etl_fetcher.py           # Helpers de paginación HTTP paralela
├── alembic/
│   └── versions/                    # Migraciones de esquema
├── .env                             # Variables del API y PostgreSQL (NO commitear)
├── .env.sync                        # Variables de fuentes externas para sync_manual.py (NO commitear)
├── sync_manual.py                   # Script de sincronización manual desde red LAN
├── Dockerfile                       # Imagen base para la API
├── docker-compose.yml               # Entorno local (db + api)
├── docker-compose.prod.yml          # Entorno Hostinger (db + api + nginx)
└── requirements.txt                 # Dependencias Python
```

---

## Archivos de Entorno

### `.env` — API y PostgreSQL

Usado por `docker-compose.yml` y `docker-compose.prod.yml`:

```env
# ── PostgreSQL ────────────────────────────────────────────────────────────────
POSTGRES_USER=postgres
POSTGRES_PASSWORD=tu_password
POSTGRES_DB=centralizacion_db

# ── API Keys (formato: nombre:clave o solo clave) ─────────────────────────────
API_KEYS="sk_live_collecta_xxx,sk_live_sefil_yyy,sk_live_worker_zzz"

# ── Collecta (para /sync/run/collecta desde el API) ───────────────────────────
COLLECTA_API_URL=https://collapi.sefil.com.ec/public/api/clients
COLLECTA_TOKEN=bearer_token_collecta

# ── DATA SEFIL (solo funciona si el API corre en red LAN) ─────────────────────
DATASEFIL_API_URL=http://172.20.1.105:8000/api/clients
DATASEFIL_TOKEN=bearer_token_sefil

# ── Leads MySQL (solo funciona si el API corre en red LAN) ───────────────────
LEADS_DB_USER=root
LEADS_DB_PASSWORD=password_leads
LEADS_DB_HOST=172.20.1.102
LEADS_DB_PORT=3306
LEADS_DB_NAME=lead_process
```

### `.env.sync` — Script de sincronización manual

Usado exclusivamente por `sync_manual.py`:

```env
# ── Destino: API pública en Hostinger ─────────────────────────────────────────
HOSTINGER_API_URL=https://services.sefil.com.ec/customers/api/v1
HOSTINGER_API_KEY=sk_live_worker_zzz

# ── Fuentes locales LAN ───────────────────────────────────────────────────────
COLLECTA_API_URL=https://collapi.sefil.com.ec/public/api/clients
COLLECTA_TOKEN=bearer_token_collecta

DATASEFIL_API_URL=http://172.20.1.105:8000/api/clients
DATASEFIL_TOKEN=bearer_token_sefil

LEADS_DB_USER=root
LEADS_DB_PASSWORD=password_leads
LEADS_DB_HOST=172.20.1.102
LEADS_DB_PORT=3306
LEADS_DB_NAME=lead_process
```

---

## Ejecución

### Entorno local (desarrollo)

```bash
# Levantar DB + API
docker compose up --build -d

# Logs en tiempo real
docker compose logs -f api

# Detener
docker compose down
```

La API queda disponible en `http://localhost:8002`.

### Entorno producción (Hostinger)

```bash
# Levantar DB + API + Nginx
docker compose -f docker-compose.prod.yml up --build -d

# Logs
docker compose -f docker-compose.prod.yml logs -f api
```

### Aplicar migraciones en producción

```bash
# Ejecutar dentro del contenedor API en Hostinger
docker exec centralizacion_api alembic upgrade head
```

---

## Endpoints de la API

Documentación interactiva: `https://services.sefil.com.ec/customers/docs`

### Clientes — `/api/v1/customers`

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/` | Crear cliente |
| `GET` | `/` | Listar clientes (paginado: `skip`, `limit`) |
| `GET` | `/search?q=...` | Buscar por cédula exacta, nombre parcial o nombre completo |
| `GET` | `/by/{identification}` | Obtener cliente por cédula o RUC |
| `GET` | `/by-phone/{phone_number}` | Buscar cliente por número de teléfono (normalizado) |
| `GET` | `/{id}` | Obtener cliente por ID interno |
| `GET` | `/{id}/full` | Cliente con **todas** sus relaciones cargadas |
| `GET` | `/{id}/phones?skip&limit` | Teléfonos paginados |
| `GET` | `/{id}/emails?skip&limit` | Correos paginados |
| `GET` | `/{id}/addresses?skip&limit` | Direcciones paginadas |
| `GET` | `/{id}/relationships?skip&limit` | Relaciones familiares paginadas |
| `POST` | `/by/{identification}/phones` | Agregar teléfono a un cliente por cédula |
| `DELETE` | `/{id}/phones/{phone_id}` | Eliminar un teléfono |
| `PATCH` | `/{id}` | Actualización parcial de campos |
| `DELETE` | `/{id}` | Eliminar cliente (cascade) |

### Sincronización — `/api/v1/sync`

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/customer` | Ingestar un cliente individual desde sistema externo |
| `POST` | `/bulk-upsert` | Upsert por lotes (payload `CustomerUpsertItem[]`) |
| `POST` | `/run/collecta` | Sync manual Collecta → BD (background, 202) |
| `POST` | `/run/datasefil` | Sync manual DATA SEFIL → BD (background, 202) |
| `POST` | `/run/leads` | Sync manual Leads → BD (background, 202) |
| `POST` | `/run/all` | Sync manual todas las fuentes (background, 202) |

> Los endpoints `/run/*` retornan `202 Accepted` inmediatamente. El progreso se sigue con `docker logs centralizacion_api -f`.
>
> `/run/datasefil` y `/run/leads` solo funcionan si la API corre en la red LAN. Para sincronizar desde Hostinger usa `sync_manual.py`.

---

## Autenticación

Todos los endpoints requieren la cabecera `X-API-Key`:

```bash
curl -H "X-API-Key: sk_live_xxx" https://services.sefil.com.ec/customers/api/v1/customers/
```

Las claves se configuran en `API_KEYS` (formato: `nombre:clave` o solo `clave`, separadas por comas). Responde `401` si la clave es inválida o ausente.

---

## Sincronización Manual

### Desde la red LAN (DATA SEFIL + Leads)

El script `sync_manual.py` extrae de las fuentes LAN y envía al `/sync/bulk-upsert` de Hostinger:

```powershell
# Activar entorno virtual
.\venv\Scripts\Activate.ps1

# Sincronizar solo DATA SEFIL
python sync_manual.py --source datasefil

# Sincronizar solo Leads
python sync_manual.py --source leads

# Sincronizar todas las fuentes
python sync_manual.py --source all
```

El script lee las credenciales de `.env.sync` automáticamente.

### Desde Hostinger (Collecta)

Collecta es una URL pública y puede sincronizarse directamente via API:

```bash
curl -X POST https://services.sefil.com.ec/customers/api/v1/sync/run/collecta \
  -H "X-API-Key: sk_live_xxx"
```

### Lógica de fusión (Upsert/Merge)

La clave de deduplicación es `identification` (cédula o RUC):

| Escenario | Comportamiento |
|---|---|
| Cliente nuevo | Se crea con todos sus datos y contactos |
| Cliente existente — campos vacíos | Se rellenan con los nuevos datos |
| Cliente existente — campos con valor | No se sobreescriben |
| Teléfonos / emails / direcciones | Se agregan si no existen; duplicados ignorados |
| Contadores de llamadas | Se actualizan siempre (`calls_effective`, `calls_not_effective`) |

### Trazabilidad por fuente (`source`)

| Valor | Origen |
|---|---|
| `"Collecta"` | API Collecta (CollAPI) |
| `"DATA SEFIL"` | API DATA SEFIL |
| `"Leads"` | BD MySQL de Leads |
| `"WS/Manual"` o `"Manual"` | Insertado vía API REST |

---

## Modelos de Datos

```
Customer (customers)
│  identification  VARCHAR(13) UNIQUE   ← cédula o RUC
│  first_name      VARCHAR(200)
│  last_name       VARCHAR(200)
│  gender          VARCHAR(20)          ← MALE | FEMALE
│  birth_date      DATE
│  birth_place     VARCHAR(200)
│  nationality     VARCHAR(100)
│  civil_status    VARCHAR(30)          ← SINGLE | MARRIED | DIVORCED | WIDOWED | COMMON_LAW
│  profession      VARCHAR(500)
│
├── CollectionPhone (collection_phones)          [One-to-Many]
│     phone_number          VARCHAR(20)
│     country_code          VARCHAR(5)           ← default "+593"
│     phone_type            VARCHAR(20)          ← MOBILE | HOME | WORK | ...
│     source                VARCHAR(50)
│     calls_effective       SMALLINT             ← llamadas efectivas (Collecta/DATA SEFIL)
│     calls_not_effective   SMALLINT             ← llamadas no efectivas
│
├── CollectionAddress (collection_addresses)     [One-to-Many]
│     address_line   VARCHAR(500)
│     province       VARCHAR(100)
│     city           VARCHAR(100)
│     address_type   VARCHAR(30)                 ← HOME | WORK | DIRECCION | ...
│     source         VARCHAR(50)
│
├── CollectionEmail (collection_emails)          [One-to-Many]
│     email_address  VARCHAR(150)
│     is_active      BOOLEAN
│     source         VARCHAR(50)
│
├── CustomerRelationship (customer_relationships) [One-to-Many]
│     relationship_type       VARCHAR(30)        ← CONYUGE | HIJO | PADRE | HERMANO | ...
│     related_identification  VARCHAR(13)
│     related_name            VARCHAR(200)
│     related_birth_date      DATE
│     related_gender          VARCHAR(20)
│     related_civil_status    VARCHAR(30)
│     related_death_date      DATE
│     source                  VARCHAR(50)        ← "DATA SEFIL"
│
├── FinancialInformation (financial_information) [One-to-One]
│     salary         NUMERIC
│
└── EquifaxQuery (equifax_queries)               [One-to-Many]
      (consultas al Buró de Crédito)
```

---

## Migraciones

```bash
# Crear una nueva migración (después de modificar un modelo)
alembic revision --autogenerate -m "descripcion_del_cambio"

# Aplicar migraciones pendientes
alembic upgrade head

# Ver historial
alembic history

# Revertir la última migración
alembic downgrade -1
```

### Migraciones aplicadas

| Revisión | Descripción |
|---|---|
| `4c3a34ff25d1` | Tablas iniciales |
| `7991cee60d14` | Columna `source` en colecciones |
| `a1b2c3d4e5f6` | Expansión de columnas VARCHAR + tabla `customer_relationships` |
| `b2c3d4e5f6a7` | Columnas `calls_effective` y `calls_not_effective` en `collection_phones` |

> **Nota:** Si Alembic reporta `Can't locate revision`, la tabla `alembic_version` tiene una revisión huérfana. Corrección:
> ```bash
> docker compose exec db psql -U postgres -d centralizacion_db \
>   -c "UPDATE alembic_version SET version_num = 'b2c3d4e5f6a7';"
> alembic upgrade head
> ```
