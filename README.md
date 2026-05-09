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
        ├──► Collecta API    (HTTPS — Bearer Token)
        ├──► DATA SEFIL API  (HTTP interno — Bearer Token)
        └──► Leads MySQL     (conexión directa — SQLAlchemy secundario)
```

La **API** nunca expone su puerto directamente al host; solo **Nginx** es accesible desde el exterior. El **Worker** corre como proceso independiente y comparte la misma imagen Docker que la API.

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
│   │   └── security.py             # Validación de API Keys (X-API-Key)
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
│   │   ├── etl_collecta.py          # ETL específico para Collecta (CollAPI)
│   │   ├── etl_datasefil.py         # ETL específico para DATA SEFIL
│   │   └── etl_leads.py             # ETL específico para Leads (MySQL externo)
│   ├── worker/
│   │   └── scheduler.py             # Scheduled Polling — ejecuta ETLs periódicamente
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

# DATABASE_URL se sobreescribe en docker-compose para usar el hostname 'db'
# En desarrollo local sin Docker, apunta a localhost:
DATABASE_URL=postgresql+psycopg2://postgres:tu_password_seguro@localhost:5432/centralizacion_db

# ── MySQL externo (Leads) ────────────────────────────────────────────────────
LEADS_DB_USER=root
LEADS_DB_PASSWORD=password_leads
LEADS_DB_HOST=172.20.1.102
LEADS_DB_PORT=3306
LEADS_DB_NAME=lead_process

# ── API Keys de acceso (seguridad M2M) ──────────────────────────────────────
# Formato: "NombreSistema:clave_secreta" separados por comas
VALID_API_KEYS="Collecta:sk_live_xxx,DATA_SEFIL:sk_live_yyy,Leads:sk_live_zzz"

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

### Con Docker (recomendado)

```bash
# Primera vez — construir imágenes y levantar
docker compose up --build -d

# Ver estado de los servicios
docker compose ps

# Logs en tiempo real
docker compose logs -f
docker compose logs -f worker   # solo el scheduler

# Detener
docker compose down
```

### Desarrollo local (sin Docker)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Levantar la API
uvicorn app.main:app --reload --port 8000

# Levantar el worker en otra terminal
python -m app.worker.scheduler
```

---

## Endpoints de la API

La API es accesible en `http://localhost` (a través de Nginx en Docker) o en `http://localhost:8000` en desarrollo local.

La documentación interactiva está disponible en:
- **Swagger UI**: `http://localhost/docs`
- **ReDoc**: `http://localhost/redoc`

### Clientes (`/api/v1/customers`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/` | Crear un nuevo cliente |
| `GET` | `/` | Listar clientes (paginado con `skip` y `limit`) |
| `GET` | `/search?q=...` | Buscar por cédula exacta o nombre parcial (mín. 3 chars) |
| `GET` | `/by/{identification}` | Obtener cliente por cédula o RUC |
| `GET` | `/{customer_id}` | Obtener cliente por ID interno |
| `GET` | `/{customer_id}/full` | Obtener cliente con todas sus relaciones |
| `PATCH` | `/{customer_id}` | Actualización parcial de campos |
| `DELETE` | `/{customer_id}` | Eliminar cliente (cascade) |

### Sincronización (`/api/v1/sync`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/customer` | Ingestar y fusionar un cliente desde un sistema externo |

**Body de ejemplo para `/api/v1/sync/customer`:**

```json
{
  "source": "Collecta",
  "data": {
    "ci": "0912345678",
    "name": "PEREZ LOPEZ JUAN CARLOS",
    "gender": "M",
    "civil_status": "soltero",
    "economic_activity": "COMERCIANTE",
    "phones": [
      { "phone_number": "0991234567", "phone_type": "MOBILE" }
    ]
  }
}
```

---

## Autenticación

Todos los endpoints (excepto `/` health check) requieren la cabecera `X-API-Key`.

```bash
curl -H "X-API-Key: sk_live_xxx" http://localhost/api/v1/customers/
```

Las claves se configuran en `VALID_API_KEYS` con el formato `NombreSistema:clave`. Si la cabecera está ausente o la clave no es válida, se retorna `401 Unauthorized`.

---

## ETLs y Sincronización

El sistema implementa un patrón de **Scheduled Polling (Batch CDC)**. El worker ejecuta los tres ETLs de forma secuencial a las horas configuradas en `SYNC_SCHEDULE_1` y `SYNC_SCHEDULE_2`.

### Lógica de fusión (Upsert/Merge)

La clave de búsqueda en todos los ETLs es el campo `identification` (cédula o RUC).

| Escenario | Comportamiento |
|---|---|
| Cliente nuevo | Se inserta `Customer` + todas sus relaciones |
| Cliente existente | Se actualizan **solo** los campos demográficos que estén vacíos en la BD |
| Contactos (teléfonos, emails, direcciones) | Se agregan los nuevos; los duplicados se ignoran por valor exacto |
| `source` | Cada registro insertado lleva etiquetado el sistema de origen |

### Trazabilidad (Data Lineage)

Cada registro en `collection_phones`, `collection_addresses` y `collection_emails` incluye el campo `source` que indica el sistema que lo aportó (`"Collecta"`, `"DATA SEFIL"`, `"Leads"`, `"Manual"`).

---

## Modelos de Datos

```
Customer (customers)
│  identification  VARCHAR(13) UNIQUE   ← cédula o RUC
│  first_name      VARCHAR(100)
│  last_name       VARCHAR(100)
│  gender          VARCHAR(20)          ← MALE | FEMALE | OTHER
│  birth_date      DATE
│  birth_place     VARCHAR(100)
│  nationality     VARCHAR(50)
│  civil_status    VARCHAR(30)          ← SINGLE | MARRIED | DIVORCED | WIDOWED
│  profession      VARCHAR(100)
│
├── CollectionPhone (collection_phones)       [One-to-Many]
│     phone_number, country_code, phone_type, source
│
├── CollectionAddress (collection_addresses)  [One-to-Many]
│     address_line, province, city, address_type, source
│
├── CollectionEmail (collection_emails)       [One-to-Many]
│     email_address, is_active, source
│
├── FinancialInformation (financial_information) [One-to-One]
│     salary
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

> **Nota:** Cada vez que se añada un campo nuevo a un modelo (como `source` en las colecciones), es necesario generar y aplicar una migración antes de ejecutar los ETLs en producción.
