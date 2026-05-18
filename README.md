# Servicio de Centralización de Personas (MDM)

API REST para la gestión centralizada de información de clientes, unificando datos provenientes de múltiples sistemas fuente: **Collecta**, **DATA SEFIL** y **Leads**.

---

## Tabla de Contenidos

- [Arquitectura](#arquitectura)
- [Stack Tecnológico](#stack-tecnológico)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Configuración del Entorno](#configuración-del-entorno)
- [Ejecución](#ejecución)
- [Endpoints de la API](#endpoints-de-la-api)
- [Autenticación](#autenticación)
- [ETLs y Sincronización](#etls-y-sincronización)
- [Modelos de Datos](#modelos-de-datos)
- [Migraciones](#migraciones)

---

## Arquitectura

```
Internet / Red Interna
        │
        ▼ :80
    [ Nginx ]          Proxy inverso — hardening de cabeceras, SSL termination
        │
        │  red interna Docker (mdm_network)
        ▼
    [ API ]            FastAPI + Uvicorn — lógica de negocio y endpoints REST
        │
        ▼
  [ PostgreSQL ]       Base de datos centralizada
        ▲
        │
   [ Worker ]          Scheduler — ETL polling periódico hacia sistemas externos
        │
        ├──► Collecta API    (HTTPS — Bearer Token) — /clients, /contacts, /directions
        ├──► DATA SEFIL API  (HTTP interno — Bearer Token) — /clients
        └──► Leads MySQL     (conexión directa — SQLAlchemy secundario)
```

La **API** nunca expone su puerto directamente al host; solo **Nginx** es accesible desde el exterior. El **Worker** corre como proceso independiente y comparte la misma imagen Docker que la API.

> **Entorno Windows (desarrollo):** El Worker debe ejecutarse de forma **nativa** (no dentro de Docker) porque Docker Desktop en Windows no puede alcanzar hosts LAN de la red interna (`172.20.x.x`). La API y PostgreSQL sí corren en Docker. En producción Linux todos los servicios corren en Docker.

---

## Stack Tecnológico

| Componente | Tecnología |
|---|---|
| Framework web | FastAPI 0.136 |
| Servidor ASGI | Uvicorn 0.45 |
| ORM | SQLAlchemy 2.0 |
| Validación | Pydantic V2 |
| Base de datos central | PostgreSQL 15 |
| Conector PostgreSQL | psycopg2-binary |
| Conector MySQL (Leads) | PyMySQL + cryptography |
| Migraciones | Alembic |
| Proxy inverso | Nginx Alpine |
| Scheduler | schedule 1.2 |
| Contenedores | Docker + Docker Compose |

---

## Estructura del Proyecto

```
.
├── app/
│   ├── api/
│   │   ├── dependencies.py          # Dependencia get_db() para FastAPI
│   │   └── routers/
│   │       ├── customers.py         # CRUD + búsqueda de clientes
│   │       └── sync.py              # Endpoint de ingesta externa (POST /sync/customer)
│   ├── core/
│   │   ├── database.py              # Engine, SessionLocal, Base
│   │   └── security.py              # Validación de API Keys (X-API-Key)
│   ├── models/
│   │   ├── base.py                  # DeclarativeBase compartida
│   │   ├── customer.py              # Modelo Customer (entidad central)
│   │   ├── collections.py           # CollectionPhone, CollectionAddress, CollectionEmail
│   │   ├── financial.py             # FinancialInformation (One-to-One)
│   │   └── equifax.py               # EquifaxQuery
│   ├── schemas/
│   │   ├── customer.py              # CustomerCreate, CustomerUpdate, CustomerResponse
│   │   ├── collections.py           # Schemas de teléfonos, direcciones y emails
│   │   ├── financial.py             # FinancialInformationResponse
│   │   └── equifax.py               # EquifaxQueryResponse
│   ├── services/
│   │   ├── data_cleaning.py         # Funciones de limpieza y normalización (ETL)
│   │   ├── unified_sync.py          # Servicio MDM hub — sync_external_customer()
│   │   ├── etl_collecta.py          # ETL Collecta: clientes, contactos y direcciones
│   │   ├── etl_datasefil.py         # ETL DATA SEFIL: clientes con paginación paralela
│   │   └── etl_leads.py             # ETL Leads: crea y enriquece clientes desde MySQL
│   ├── worker/
│   │   └── scheduler.py             # Scheduled Polling — 5 pasos de sync secuenciales
│   └── main.py                      # Punto de entrada FastAPI
├── nginx/
│   └── default.conf                 # Configuración Nginx (proxy + hardening)
├── .env                             # Variables de entorno (NO commitear)
├── .env.example                     # Plantilla de variables de entorno
├── Dockerfile                       # Imagen base para api y worker
├── docker-compose.yml               # Orquestación de los 4 servicios
└── requirements.txt                 # Dependencias Python (pip freeze)
```

---

## Configuración del Entorno

Copia `.env.example` a `.env` y completa los valores:

```env
# ── PostgreSQL (Base de datos central) ──────────────────────────────────────
POSTGRES_USER=postgres
POSTGRES_PASSWORD=tu_password_seguro
POSTGRES_DB=centralizacion_db

# En desarrollo nativo Windows, usar puerto 5433 (5432 está reservado por Hyper-V/WSL2)
DATABASE_URL=postgresql+psycopg2://postgres:tu_password_seguro@localhost:5433/centralizacion_db

# ── MySQL externo (Leads) ────────────────────────────────────────────────────
LEADS_DB_USER=root
LEADS_DB_PASSWORD=password_leads
LEADS_DB_HOST=172.20.1.102
LEADS_DB_PORT=3306
LEADS_DB_NAME=lead_process

# ── API Keys de acceso (seguridad M2M) ──────────────────────────────────────
VALID_API_KEYS="sk_live_xxx,sk_live_yyy,sk_live_zzz"

# ── ETL — URLs de sistemas fuente ────────────────────────────────────────────
COLLECTA_API_URL=https://collapi.sefil.com.ec/public/api/clients
COLLECTA_TOKEN=bearer_token_collecta

DATASEFIL_API_URL=http://172.20.1.105:8000/api/clients
DATASEFIL_TOKEN=bearer_token_sefil

# ── Scheduler — Horarios de sincronización (formato 24h HH:MM) ───────────────
SYNC_SCHEDULE_1=02:00
SYNC_SCHEDULE_2=13:30
```

---

## Ejecución

### Con Docker (API + PostgreSQL)

```bash
# Primera vez — construir imágenes y levantar
docker compose up --build -d

# Ver estado de los servicios
docker compose ps

# Logs en tiempo real
docker compose logs -f
docker compose logs -f api   # solo la API

# Detener
docker compose down
```

### Worker en Windows (nativo — requerido para acceder a red LAN)

El worker debe correr fuera de Docker para poder alcanzar los servidores internos (`172.20.1.102`, `172.20.1.105`):

```powershell
# Activar entorno virtual
.\venv\Scripts\Activate.ps1

# Arrancar el scheduler (se ejecuta según SYNC_SCHEDULE_1/2)
python -m app.worker.scheduler

# O forzar una sincronización completa inmediata
python -c "from app.worker.scheduler import run_all_syncs; run_all_syncs()"

# Ejecutar solo un ETL específico
python -c "from app.worker.scheduler import _run_leads; from app.core.database import SessionLocal; db = SessionLocal(); _run_leads(db); db.close()"
```

---

## Endpoints de la API

La API es accesible en `http://localhost:8002` (Docker) o `http://localhost:8000` en desarrollo local.

La documentación interactiva está disponible en:
- **Swagger UI**: `http://localhost:8002/docs`
- **ReDoc**: `http://localhost:8002/redoc`

### Clientes (`/api/v1/customers`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/` | Crear un nuevo cliente |
| `GET` | `/` | Listar clientes (paginado con `skip` y `limit`) |
| `GET` | `/search?q=...` | Buscar por cédula exacta o nombre parcial (mín. 3 chars) |
| `GET` | `/by/{identification}` | Obtener cliente por cédula o RUC |
| `GET` | `/{customer_id}` | Obtener cliente por ID interno |
| `GET` | `/{customer_id}/full` | Obtener cliente con **todas** sus relaciones (eager load) |
| `PATCH` | `/{customer_id}` | Actualización parcial de campos |
| `DELETE` | `/{customer_id}` | Eliminar cliente (cascade) |

### Sincronización (`/api/v1/sync`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/customer` | Ingestar y fusionar un cliente desde un sistema externo |

---

## Autenticación

Todos los endpoints (excepto `/` health check) requieren la cabecera `X-API-Key`.

```bash
curl -H "X-API-Key: sk_live_xxx" http://localhost:8002/api/v1/customers/
```

Las claves se configuran en `VALID_API_KEYS` (lista separada por comas). Si la cabecera está ausente o la clave no es válida, se retorna `401 Unauthorized`.

---

## ETLs y Sincronización

El sistema implementa un patrón de **Scheduled Polling (Batch CDC)**. El worker ejecuta **5 pasos secuenciales** a las horas configuradas en `SYNC_SCHEDULE_1` y `SYNC_SCHEDULE_2`.

### Pasos del ciclo de sincronización

| Paso | Fuente | Endpoint | Qué sincroniza |
|---|---|---|---|
| 1 | Collecta | `/public/api/clients` | Datos demográficos + teléfonos principales |
| 2 | Collecta | `/public/api/contacts` | Teléfonos adicionales por cliente |
| 3 | Collecta | `/public/api/directions` | Direcciones por cliente |
| 4 | DATA SEFIL | `/api/clients` | Demográficos, teléfonos, emails, direcciones, salario |
| 5 | Leads (MySQL) | tabla `entries` | Nombre, teléfono trabajo, email personal, dirección trabajo |

Los pasos 1, 2, 3 y 4 usan **paginación paralela** (`ThreadPoolExecutor`, 5 workers, 100 registros/página) para reducir el tiempo de descarga.

### Lógica de fusión (Upsert/Merge)

La clave de búsqueda en todos los ETLs es el campo `identification` (cédula o RUC).

| Escenario | Comportamiento |
|---|---|
| Cliente nuevo | Se crea el registro `Customer` con todos sus datos y contactos |
| Cliente existente (demográficos) | Se actualizan **solo** los campos que estén vacíos en la BD (nunca sobreescribe) |
| Contactos (teléfonos, emails, direcciones) | Se agregan los nuevos; los duplicados se ignoran por valor exacto |
| Leads — cliente no existente | Se **crea** el cliente con nombre y contactos extraídos del JSON `attributes` |
| `source` | Cada registro insertado lleva etiquetado el sistema de origen |

### Trazabilidad (Data Lineage)

Cada registro en `collection_phones`, `collection_addresses` y `collection_emails` incluye el campo `source` que indica el sistema que lo aportó:

| Valor | Origen |
|---|---|
| `"Collecta"` | API Collecta (CollAPI) |
| `"DATA SEFIL"` | API DATA SEFIL (incluye datos de datadiverservice) |
| `"Leads"` | Base de datos MySQL de Leads |
| `"Manual"` | Insertado directamente vía API REST |

### Campos extraídos del JSON `attributes` de Leads

| Campo JSON | Destino en BD |
|---|---|
| `PRIMER NOMBRE` + `SEGUNDO NOMBRE` | `Customer.first_name` |
| `APELLIDO PATERNO` + `APELLIDO MATERNO` | `Customer.last_name` |
| `TELEFONO TRABAJO` | `CollectionPhone` (tipo WORK) |
| `TELEFONO CELULAR 1` / `TELEFONO CELULAR 2` | `CollectionPhone` (tipo MOBILE) |
| `TELEFONO DOMICILIO` | `CollectionPhone` (tipo HOME) |
| `EMAIL PERSONAL` | `CollectionEmail` |
| `DIRECCION TRABAJO` + `PARROQUIA TRABAJO` | `CollectionAddress.address_line` (tipo WORK) |
| `CANTON TRABAJO` | `CollectionAddress.city` |
| `PROVINCIA TRABAJO` | `CollectionAddress.province` |

---

## Modelos de Datos

```
Customer (customers)
│  identification  VARCHAR(13) UNIQUE   ← cédula o RUC
│  first_name      VARCHAR(200)
│  last_name       VARCHAR(200)
│  gender          VARCHAR(20)          ← MALE | FEMALE | OTHER
│  birth_date      DATE
│  birth_place     VARCHAR(200)
│  nationality     VARCHAR(100)
│  civil_status    VARCHAR(30)          ← SINGLE | MARRIED | DIVORCED | WIDOWED
│  profession      VARCHAR(500)
│
├── CollectionPhone (collection_phones)       [One-to-Many]
│     phone_number   VARCHAR(20)
│     country_code   VARCHAR(5)         ← default "+593"
│     phone_type     VARCHAR(20)        ← MOBILE | HOME | WORK | REFERENCE | ...
│     source         VARCHAR(50)
│
├── CollectionAddress (collection_addresses)  [One-to-Many]
│     address_line   VARCHAR(500)       ← largo para aceptar descripciones de Leads
│     province       VARCHAR(100)
│     city           VARCHAR(100)
│     address_type   VARCHAR(30)        ← HOME | WORK | GUARANTOR | OTHER
│     source         VARCHAR(50)
│
├── CollectionEmail (collection_emails)       [One-to-Many]
│     email_address  VARCHAR(150)
│     is_active      BOOLEAN
│     source         VARCHAR(50)
│
├── FinancialInformation (financial_information) [One-to-One]
│     salary         NUMERIC
│
└── EquifaxQuery (equifax_queries)            [One-to-Many]
      (consultas al Buró de Crédito)
```

---

## Migraciones

El proyecto usa **Alembic** para gestionar el esquema de la base de datos.

```bash
# Crear una nueva migración (después de modificar un modelo)
alembic revision --autogenerate -m "descripcion_del_cambio"

# Aplicar migraciones pendientes
alembic upgrade head

# Ver historial de migraciones
alembic history

# Revertir la última migración
alembic downgrade -1
```

> **Nota:** Si Alembic reporta `Can't locate revision` al iniciar, la tabla `alembic_version` tiene una revisión huérfana. Corrección:
> ```bash
> docker compose exec db psql -U postgres -d centralizacion_db \
>   -c "UPDATE alembic_version SET version_num = '<ultima_revision_valida>';"
> alembic upgrade head
> ```
