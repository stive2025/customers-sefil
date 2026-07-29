# Guía de Uso — API de Centralización de Personas (MDM)

> Pensada para ser consumida **desde otra API/servicio** (no desde un navegador). Todos los ejemplos de este documento son respuestas **reales**, capturadas ejecutando la API localmente contra una base de datos limpia (Docker, Postgres 15, migraciones al día) el 2026-07-27. No son respuestas inventadas.

- **Base URL (producción):** `https://services.sefil.com.ec/customers/api/v1`
- **Base URL (local/docker):** `http://localhost:8002/api/v1`
- **Swagger UI:** `.../docs` · **ReDoc:** `.../redoc`
- **Formato:** JSON en request y response. `Content-Type: application/json` en todos los `POST`/`PATCH`.

---

## 1. Autenticación

Todos los endpoints bajo `/api/v1/customers` y `/api/v1/sync` requieren la cabecera `X-API-Key`. No hay OAuth, JWT ni sesiones — es autenticación M2M por clave estática.

```bash
curl -H "X-API-Key: sk_live_xxx" https://services.sefil.com.ec/customers/api/v1/customers/
```

Las claves se configuran en el servidor vía variable de entorno `API_KEYS` (formato `NombreSistema:clave`, separadas por coma). Pide a Sefil que te asigne una clave con un nombre identificable (queda registrada en logs como origen del request).

**Sin cabecera o con clave inválida:**

```http
GET /api/v1/customers/
```
```json
HTTP 401
{
  "detail": "API Key ausente o inválida. Incluye una cabecera 'X-API-Key' válida."
}
```

No hay rate limiting a nivel de aplicación.

---

## 2. Recurso `Customer`

### 2.1 Crear cliente — `POST /customers/`

Request:

```json
{
  "identification": "0912345678",
  "first_name": "MARIA JOSE",
  "last_name": "PEREZ GOMEZ",
  "gender": "FEMALE",
  "birth_date": "1990-05-15",
  "birth_place": "GUAYAQUIL",
  "nationality": "Ecuadorian",
  "civil_status": "SINGLE",
  "economic_activity": "COMERCIANTE"
}
```

Response `201 Created`:

```json
{
  "identification": "0912345678",
  "first_name": "MARIA JOSE",
  "last_name": "PEREZ GOMEZ",
  "gender": "FEMALE",
  "birth_date": "1990-05-15",
  "birth_place": "GUAYAQUIL",
  "nationality": "Ecuadorian",
  "civil_status": "SINGLE",
  "economic_activity": "COMERCIANTE",
  "id": 1,
  "created_at": "2026-07-27T15:09:49.365554Z",
  "updated_at": null,
  "full_name": "MARIA JOSE PEREZ GOMEZ",
  "age": 36
}
```

`full_name` y `age` son **campos calculados** al serializar (no existen como columnas en la base de datos).

Campos obligatorios: `identification` (10 o 13 caracteres), `first_name`, `last_name`. El resto es opcional.

**Cédula duplicada:**

```json
HTTP 409
{ "detail": "Ya existe un cliente con la identificación '0912345678'." }
```

**Campo obligatorio faltante** (ej. sin `first_name`):

```json
HTTP 422
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "first_name"],
      "msg": "Field required",
      "input": {"identification": "0999999999", "last_name": "SOLO APELLIDO"}
    }
  ]
}
```

> Este es el formato estándar de error de validación de FastAPI/Pydantic — aplica a **todos** los endpoints de este API, no solo a este.

### 2.2 Obtener cliente — `GET /customers/{identification}`

```http
GET /customers/0912345678
```
```json
HTTP 200
{
  "identification": "0912345678",
  "first_name": "MARIA JOSE",
  "last_name": "PEREZ GOMEZ",
  "gender": "FEMALE",
  "birth_date": "1990-05-15",
  "birth_place": "GUAYAQUIL",
  "nationality": "Ecuadorian",
  "civil_status": "SINGLE",
  "economic_activity": "COMERCIANTE",
  "id": 1,
  "created_at": "2026-07-27T15:09:49.365554Z",
  "updated_at": null,
  "full_name": "MARIA JOSE PEREZ GOMEZ",
  "age": 36
}
```

No encontrado:

```json
HTTP 404
{ "detail": "Cliente con identificación '9999999999' no encontrado." }
```

### 2.3 Cliente completo (con relaciones) — `GET /customers/{identification}/full`

Incluye teléfonos, direcciones, correos, información financiera, consultas Equifax y relaciones familiares en un solo request.

```json
HTTP 200
{
  "identification": "0912345678",
  "first_name": "MARIA JOSE",
  "last_name": "PEREZ GOMEZ",
  "...": "... mismos campos que arriba ...",
  "phones": [
    {
      "phone_number": "0991234567",
      "country_code": "+593",
      "phone_type": "MOVIL",
      "alias": "Celular actualizado",
      "note": "Contacto principal",
      "is_verified": true,
      "id": 1,
      "customer_id": 1,
      "calls_effective": null,
      "calls_not_effective": null,
      "is_active": false,
      "created_by": "docs-test",
      "created_source": "Manual",
      "updated_at": "2026-07-27T15:10:05.432789Z",
      "updated_by": null,
      "updated_source": null,
      "deleted_at": "2026-07-27T15:10:05.480530Z",
      "deleted_by": "docs-test",
      "deleted_source": "Manual",
      "created_at": "2026-07-27T15:10:05.279971Z"
    }
  ],
  "addresses": [
    {
      "address_line": "AV. FRANCISCO DE ORELLANA Y JUSTINO CORNEJO",
      "province": "GUAYAS",
      "city": "GUAYAQUIL",
      "canton": "GUAYAQUIL",
      "parish": "TARQUI",
      "neighborhood": "KENNEDY NORTE",
      "address_type": "Hogar",
      "latitude": -2.14987,
      "longitude": -79.90123,
      "id": 1,
      "customer_id": 1,
      "is_active": true,
      "created_by": "docs-test",
      "created_source": "Manual",
      "created_at": "2026-07-27T15:10:25.134347Z"
    }
  ],
  "emails": [
    {
      "email_address": "maria.perez@example.com",
      "is_active": true,
      "id": 1,
      "customer_id": 1,
      "created_by": "docs-test",
      "created_source": "Manual",
      "created_at": "2026-07-27T15:10:25.074119Z"
    }
  ],
  "financial_information": null,
  "equifax_queries": [],
  "relationships": [],
  "full_name": "MARIA JOSE PEREZ GOMEZ",
  "age": 36
}
```

> ⚠️ `address_type` se **normaliza siempre** en el servidor: cualquier valor de entrada distinto de las variantes reconocidas de "trabajo" cae por defecto en `"Hogar"` (ver §6.2). Se envió `"domicilio"` y volvió `"Hogar"`.

### 2.4 Buscar por teléfono — `GET /customers/by-phone/{phone_number}`

El número se normaliza igual que en la ingesta (`clean_phone_number`) antes de buscar.

```json
HTTP 200
{
  "identification": "0912345678",
  "first_name": "MARIA JOSE",
  "...": "..."
}
```

### 2.5 Búsqueda por nombre/geografía — `GET /customers/search`

Retorna **solo cédulas**, no objetos completos. Requiere al menos un parámetro (`name`, `province`, `canton`, `parish`, `neighborhood`, `address_type`). Límite: 500 resultados.

```http
GET /customers/search?name=Maria
```
```json
HTTP 200
{ "identifications": ["0912345678"] }
```

Sin parámetros:

```json
HTTP 422
{ "detail": "Se requiere al menos un parámetro de búsqueda." }
```

### 2.6 Lookup en lote — `POST /customers/batch`

Útil cuando otra API necesita el perfil completo de muchas cédulas en un solo round-trip (hasta 200). Las cédulas no encontradas se **omiten silenciosamente** — no generan error.

Request:

```json
{ "identifications": ["0912345678", "9999999999"] }
```

Response `200 OK` (nótese que `9999999999` no aparece, y cada item trae el mismo shape que `/full`):

```json
[
  {
    "identification": "0912345678",
    "first_name": "MARIA JOSE",
    "last_name": "PEREZ GOMEZ",
    "phones": ["..."],
    "addresses": ["..."],
    "emails": ["..."],
    "financial_information": null,
    "equifax_queries": [],
    "relationships": [],
    "full_name": "MARIA JOSE PEREZ GOMEZ",
    "age": 36
  }
]
```

### 2.7 Listar clientes — `GET /customers/?skip=0&limit=20`

Retorna un array de `CustomerResponse` (shape básico, sin relaciones anidadas). `limit` máximo 100.

### 2.8 Actualizar parcialmente — `PATCH /customers/{identification}`

Solo los campos enviados se modifican (`exclude_unset`); el resto se conserva sin comparar valores previos.

Request:

```json
{ "economic_activity": "COMERCIANTE MINORISTA", "civil_status": "MARRIED" }
```

Response `200 OK`:

```json
{
  "identification": "0912345678",
  "first_name": "MARIA JOSE",
  "last_name": "PEREZ GOMEZ",
  "civil_status": "MARRIED",
  "economic_activity": "COMERCIANTE MINORISTA",
  "id": 1,
  "created_at": "2026-07-27T15:09:49.365554Z",
  "updated_at": "2026-07-27T15:10:43.421489Z",
  "full_name": "MARIA JOSE PEREZ GOMEZ",
  "age": 36
}
```

### 2.9 Eliminar cliente — `DELETE /customers/{identification}`

Borrado **físico** (no soft-delete) en cascada: se eliminan también sus teléfonos, direcciones, correos y relaciones.

```json
HTTP 204
(sin body)
```

Un `GET` posterior confirma la eliminación:

```json
HTTP 404
{ "detail": "Cliente con identificación '0945678901' no encontrado." }
```

---

## 3. Sub-recursos: teléfonos, correos, direcciones, relaciones

Todos comparten el patrón `GET` (listado paginado), `POST` (crear bajo `/customers/{identification}/...`), `PATCH` (solo teléfonos/correos/direcciones), `DELETE` (soft-delete, solo teléfonos/correos/direcciones).

### 3.1 Teléfonos

**Agregar** — `POST /customers/{identification}/phones`

Request:

```json
{
  "phone_number": "0991234567",
  "phone_type": "celular",
  "alias": "Personal",
  "note": "Contacto principal",
  "created_by": "docs-test",
  "created_source": "Manual"
}
```

Response `201 Created`:

```json
{
  "phone_number": "0991234567",
  "country_code": "+593",
  "phone_type": "MOVIL",
  "alias": "Personal",
  "note": "Contacto principal",
  "is_verified": true,
  "id": 1,
  "customer_id": 1,
  "calls_effective": null,
  "calls_not_effective": null,
  "is_active": true,
  "created_by": "docs-test",
  "created_source": "Manual",
  "updated_at": null,
  "updated_by": null,
  "updated_source": null,
  "deleted_at": null,
  "deleted_by": null,
  "deleted_source": null,
  "created_at": "2026-07-27T15:10:05.279971Z"
}
```

> `phone_type: "celular"` entra libre y el servidor lo **normaliza** a `"MOVIL"` (o `"FIJO"`) vía un mapeo de sinónimos insensible a acentos/mayúsculas. Un teléfono agregado por este endpoint nace `is_verified: true` automáticamente.

**Duplicado ya verificado** → `409`:

```json
{ "detail": "El número '0991234567' ya está registrado y visible." }
```

> Caso especial: si el número ya existe pero **no** estaba verificado (por ejemplo, llegó oculto vía DATA SEFIL), este mismo `POST` lo actualiza in-place (`is_verified=true`, reactiva si estaba borrado) y responde `200`-equivalente con el registro actualizado, en vez de crear uno nuevo.

**Actualizar** — `PATCH /customers/{identification}/phones/{phone_id}` (solo campos enviados):

```json
// Request
{ "alias": "Celular actualizado", "is_verified": true }
```
```json
// Response 200 — nótese updated_at con timestamp nuevo
{ "...": "...", "alias": "Celular actualizado", "updated_at": "2026-07-27T15:10:05.432789Z" }
```

**Eliminar (soft-delete)** — `DELETE /customers/{identification}/phones/{phone_id}`, body opcional:

```json
// Request
{ "deleted_by": "docs-test", "deleted_source": "Manual" }
```
```json
// Response 200 — is_active pasa a false, se llenan deleted_*
{ "...": "...", "is_active": false, "deleted_at": "2026-07-27T15:10:05.480530Z", "deleted_by": "docs-test", "deleted_source": "Manual" }
```

No es un DELETE HTTP real — el registro sigue existiendo en la tabla con `is_active=false`.

### 3.2 Correos — `POST /customers/{identification}/emails`

Request:

```json
{
  "email_address": "maria.perez@example.com",
  "is_active": true,
  "created_by": "docs-test",
  "created_source": "Manual"
}
```

Response `201 Created`:

```json
{
  "email_address": "maria.perez@example.com",
  "is_active": true,
  "id": 1,
  "customer_id": 1,
  "created_by": "docs-test",
  "created_source": "Manual",
  "updated_at": null,
  "updated_by": null,
  "updated_source": null,
  "deleted_at": null,
  "deleted_by": null,
  "deleted_source": null,
  "created_at": "2026-07-27T15:10:25.074119Z"
}
```

`email_address` se valida con formato RFC vía `EmailStr` (Pydantic) — un valor mal formado devuelve `422` antes de tocar la base de datos.

### 3.3 Direcciones — `POST /customers/{identification}/addresses`

Request:

```json
{
  "address_line": "AV. FRANCISCO DE ORELLANA Y JUSTINO CORNEJO",
  "province": "GUAYAS",
  "city": "GUAYAQUIL",
  "canton": "GUAYAQUIL",
  "parish": "TARQUI",
  "neighborhood": "KENNEDY NORTE",
  "address_type": "domicilio",
  "latitude": -2.14987,
  "longitude": -79.90123,
  "created_by": "docs-test",
  "created_source": "Manual"
}
```

Response `201 Created` (`address_type` normalizado a `"Hogar"`):

```json
{
  "address_line": "AV. FRANCISCO DE ORELLANA Y JUSTINO CORNEJO",
  "province": "GUAYAS",
  "city": "GUAYAQUIL",
  "canton": "GUAYAQUIL",
  "parish": "TARQUI",
  "neighborhood": "KENNEDY NORTE",
  "address_type": "Hogar",
  "latitude": -2.14987,
  "longitude": -79.90123,
  "id": 1,
  "customer_id": 1,
  "is_active": true,
  "created_by": "docs-test",
  "created_source": "Manual",
  "created_at": "2026-07-27T15:10:25.134347Z"
}
```

### 3.4 Relaciones familiares — `POST /customers/{identification}/relationships`

> ### 🐞 Bug confirmado — este endpoint siempre responde `500`
>
> El código construye el registro con `source=payload.source`, pero el schema de entrada (`RelationshipItem`) **no tiene** un campo `source` — tiene `created_source`. Cualquier `POST` a este endpoint, con cualquier payload válido, revienta:
>
> ```json
> HTTP 500
> {"detail": "Internal Server Error"}
> ```
> Traceback real (`docker logs`):
> ```
> File "/app/app/api/routers/customers.py", line 650, in add_customer_relationship
>     source=payload.source,
> AttributeError: 'RelationshipItem' object has no attribute 'source'
> ```
> **Si vas a consumir este endpoint, repórtalo al equipo de Sefil antes — no está usable tal como está.** El resto de endpoints de este documento sí funcionan como se describe (fueron probados en vivo).
>
> Nota: el mismo tipo de bug existe también en la vía masiva (`/sync/bulk-upsert`), ver §4.2 — ahí el síntoma es distinto (el item queda registrado en `errors[]` en vez de tumbar el request).

**GET (listado) sí funciona normalmente:**

```http
GET /customers/{identification}/relationships
```
```json
HTTP 200
[]
```

---

## 4. Sincronización — pensado para integraciones API-a-API

Este es el módulo más relevante si vas a **consumir** este servicio desde otro sistema para alimentar datos de clientes.

### 4.1 Ingesta de un cliente — `POST /sync/customer`

Recibe el **payload crudo** de un sistema origen (no el schema normalizado) más un campo `source`. La API detecta la forma del payload según `source` y lo transforma internamente.

Request (forma DATA SEFIL — ver `app/services/etl_datasefil.py` para el shape completo aceptado):

```json
{
  "source": "DATA SEFIL",
  "data": {
    "identification": "1723456789",
    "name": "CARLOS ANDRES LOPEZ TORRES",
    "gender": "M",
    "birth": "1985-11-02",
    "place_birth": "QUITO",
    "state_civil": "soltero",
    "nationality": "ECUATORIANA",
    "profession": "INGENIERO",
    "salary": 1800.50,
    "contacts": [{"phone_number": "0987654321", "phone_type": "CELULAR"}],
    "address": [{"address": "AV. AMAZONAS N34-56", "province": "PICHINCHA", "city": "QUITO", "type": "DOMICILIO"}],
    "emails": [{"direction": "carlos.lopez@example.com", "active": true}]
  }
}
```

Response `200 OK`:

```json
{
  "identification": "1723456789",
  "first_name": "LOPEZ TORRES",
  "last_name": "CARLOS ANDRES",
  "gender": "MALE",
  "birth_date": "1985-11-02",
  "birth_place": "QUITO",
  "nationality": "ECUATORIANA",
  "civil_status": "SINGLE",
  "economic_activity": "INGENIERO",
  "id": 3,
  "created_at": "2026-07-27T15:10:54.718831Z",
  "updated_at": null,
  "full_name": "LOPEZ TORRES CARLOS ANDRES",
  "age": 40
}
```

> ⚠️ **Ojo con `first_name`/`last_name`:** el parser de `name` en `etl_datasefil.py` no siempre separa nombres/apellidos en el orden que se esperaría intuitivamente — en este caso real, `"CARLOS ANDRES LOPEZ TORRES"` se guardó con `first_name: "LOPEZ TORRES"` y `last_name: "CARLOS ANDRES"`. No asumas orden nombre-apellido sin probarlo con datos reales de tu fuente.

**Reenvío del mismo cliente (upsert):** si el cliente ya existe, los campos que ya tienen valor **no se sobrescriben** — solo se rellenan los que estaban vacíos. Reenviar `"economic_activity": "EMPLEADO PRIVADO"` sobre un cliente que ya tenía `"economic_activity": "INGENIERO"` no cambia nada; la respuesta sigue trayendo `"INGENIERO"`.

`source: "collapi"` se normaliza automáticamente a `"Collecta"` (alias reconocido en el validador).

**Payload sin identificación reconocible** → `422`:

```json
{ "source": "Leads", "data": {"foo": "bar"} }
```
```json
HTTP 422
{ "detail": "No se pudo extraer una identification válida del payload: {'foo': 'bar'}" }
```

### 4.2 Ingesta por lotes — `POST /sync/bulk-upsert`

Pensado para cargas masivas desde un worker/ETL. A diferencia de `/sync/customer`, aquí el payload **sí** sigue un schema fijo (`CustomerUpsertItem`) — no formas crudas por fuente.

Request:

```json
{
  "customers": [
    {
      "identification": "0934567890",
      "first_name": "ANA LUCIA",
      "last_name": "MENDEZ SOLIS",
      "gender": "FEMALE",
      "birth_date": "1995-02-10",
      "civil_status": "SINGLE",
      "salary": 950.00,
      "phones": [
        {"phone_number": "0998765432", "phone_type": "MOVIL", "created_source": "Collecta", "calls_effective": 2, "calls_not_effective": 1}
      ],
      "addresses": [
        {"address_line": "CALLE 10 DE AGOSTO Y COLON", "province": "PICHINCHA", "city": "QUITO", "address_type": "DOMICILIO", "created_source": "Collecta"}
      ],
      "emails": [
        {"email_address": "ana.mendez@example.com", "created_source": "Collecta"}
      ]
    },
    {
      "identification": "0945678901",
      "first_name": "PEDRO",
      "last_name": "RAMIREZ VERA"
    }
  ]
}
```

Response `200 OK`:

```json
{ "created": 2, "updated": 0, "skipped": 0, "errors": [] }
```

> La respuesta **no** retorna los objetos creados — solo contadores. Si necesitas el registro completo después de un upsert, sigue con `GET /customers/{identification}/full`.

**Reenviar el mismo cliente con un teléfono ya existente:** no se duplica el teléfono; en su lugar se **actualizan** `calls_effective` / `calls_not_effective` con los nuevos valores (comportamiento exclusivo de esta vía — `/sync/customer` no hace esto):

```json
// Request (mismo phone_number, nuevos contadores)
{ "customers": [{ "identification": "0934567890", "first_name": "ANA LUCIA", "last_name": "MENDEZ SOLIS",
  "phones": [{"phone_number": "0998765432", "phone_type": "MOVIL", "created_source": "Collecta",
              "calls_effective": 5, "calls_not_effective": 3}] }] }
```
```json
// Response
{ "created": 0, "updated": 1, "skipped": 0, "errors": [] }
```
```json
// GET /customers/0934567890/phones — confirma el merge in-place
[{ "phone_number": "0998765432", "calls_effective": 5, "calls_not_effective": 3, "...": "..." }]
```

> ### 🐞 Un `identification` inválido rechaza **todo el batch**, no solo ese item
>
> ```json
> { "customers": [
>     {"identification": "0934567890", "first_name": "ANA", "last_name": "MENDEZ"},
>     {"identification": "12", "first_name": "INVALIDO"}
>   ] }
> ```
> ```json
> HTTP 422
> {"detail":[{"type":"string_too_short","loc":["body","customers",1,"identification"],
>             "msg":"String should have at least 10 characters","input":"12","ctx":{"min_length":10}}]}
> ```
> Ningún registro del batch se persiste, ni siquiera el válido. Valida `identification` (10–13 caracteres) en tu lado **antes** de enviar el lote, o divide el batch para aislar fallas.

> ### 🐞 `relationships` en el batch: el item se descarta silenciosamente (no tumba el batch)
>
> ```json
> { "customers": [{ "identification": "0956789012", "first_name": "LUIS", "last_name": "TORRES",
>     "relationships": [{"relationship_type": "MADRE", "related_name": "ROSA TORRES", "created_source": "DATA SEFIL"}] }] }
> ```
> ```json
> HTTP 200
> {"created":0,"updated":0,"skipped":0,"errors":["0956789012: 'created_source' is an invalid keyword argument for CustomerRelationship"]}
> ```
> El mismo bug de nombre de campo que en §3.4, pero aquí el batch entero sigue procesándose — solo se pierde ese item, reportado en `errors[]`. **Si tu integración envía `relationships`, revisa siempre `errors[]` en la respuesta**, incluso cuando el HTTP status es `200`.

### 4.3 Sincronización manual por fuente — `POST /sync/run/*`

Pensados para disparo manual/cron, no para integración directa cliente-a-cliente. Responden `202` de inmediato y corren en background.

```http
POST /sync/run/collecta
```
```json
HTTP 202
{ "job_id": "ba9fd466", "status": "running", "check_url": "/api/v1/sync/status/ba9fd466" }
```

Consultar resultado — `GET /sync/status/{job_id}`:

```json
HTTP 200
{
  "job_id": "ba9fd466",
  "status": "completed",
  "results": [
    { "source": "ERROR", "created": 0, "updated": 0, "skipped": 0,
      "errors": ["401 Client Error: Unauthorized for url: https://collapi.sefil.com.ec/public/api/clients?page=1&per_page=100"] }
  ]
}
```

> El ejemplo de arriba es real: falló porque el entorno local de prueba no tenía token de Collecta configurado — así se ve un fallo de fuente externa. Con credenciales válidas, `results` trae un objeto por fuente con `created`/`updated`/`skipped`/`errors` reales.

`job_id` inexistente → `404`:

```json
{ "detail": "Job 'noexiste' no encontrado." }
```

> ⚠️ El estado de jobs vive **en memoria del proceso**. En producción, si la API corre con más de un worker Uvicorn, `GET /sync/status/{job_id}` puede devolver `404` falso si la request cae en un worker distinto al que ejecutó el job. Producción corre con `--workers 1` para evitar esto — no lo cambies sin revisar este mecanismo.

Variantes también disponibles: `POST /sync/run/collecta/{identification}` y `POST /sync/run/datasefil/{identification}` (síncronos, para un solo cliente, no usan `job_id`) y `POST /sync/run/leads`, `POST /sync/run/all` (mismo patrón `202` + `job_id`).

---

## 5. Manejo de errores — referencia rápida

| Status | Cuándo | Shape del body |
|---|---|---|
| `401` | Falta `X-API-Key` o es inválida | `{"detail": "API Key ausente o inválida..."}` |
| `404` | Recurso no encontrado (`identification`, `phone_id`, `job_id`, etc.) | `{"detail": "<mensaje específico>"}` |
| `409` | Conflicto — cédula ya existe, teléfono ya existe y está verificado, relación duplicada | `{"detail": "<mensaje específico>"}` |
| `422` | Validación Pydantic (campo faltante, tipo/longitud incorrecta) o regla de negocio (`identification` no extraíble, `search` sin filtros) | `{"detail": "<string>"}` o `{"detail": [{"type","loc","msg","input"}, ...]}` (formato Pydantic) |
| `500` | Error de servidor no controlado (ver bug de §3.4) o error de BD en `/sync/*` | `{"detail": "Internal Server Error"}` o `{"detail": "Error de base de datos: <detalle>"}` |

**Regla práctica para el consumidor:** en `/sync/bulk-upsert` un `200` **no garantiza que todos los registros se guardaron** — siempre revisa `errors[]` en el body. En el resto de endpoints, un `2xx` sí implica éxito completo de ese request puntual.

---

## 6. Reglas de negocio que afectan la integración

### 6.1 Deduplicación

La clave única es `identification` (cédula 10 dígitos o RUC 13 dígitos), con `UNIQUE` a nivel de base de datos. No hay validación de dígito verificador — solo longitud y formato numérico tras limpieza.

### 6.2 Normalización automática de campos de entrada

Estos campos se transforman **siempre**, sin importar el valor exacto que envíes:

| Campo | Entrada | Salida |
|---|---|---|
| `phone_number` | Con o sin `+593`/`593`, 8-9 dígitos sin `0` inicial | Formato local limpio (dígitos, con `0` inicial si aplica) |
| `phone_type` | `"celular"`, `"CEL"`, `"mobile"`, etc. | `"MOVIL"` |
| `phone_type` | `"fijo"`, `"casa"`, `"trabajo"`, `"home"`, etc. | `"FIJO"` |
| `phone_type` | Cualquier otro valor no reconocido | `null` |
| `address_type` | `"trabajo"`, `"work"`, `"oficina"`, etc. | `"Trabajo"` |
| `address_type` | Cualquier otro valor (incluido `"domicilio"`) | `"Hogar"` (es el default, no solo el resultado de matchear "casa") |

### 6.3 Merge "no destructivo" en upserts (ambos: `/sync/customer` y `/sync/bulk-upsert`)

Un campo del cliente que **ya tiene valor** en la base de datos nunca se sobrescribe con un valor entrante, aunque el valor entrante sea distinto. Solo se rellenan campos que estaban vacíos (`None`/`""`/`0` — comparación por *truthiness* de Python, no `IS NULL` estricto). Si necesitas forzar un cambio de valor, usa `PATCH /customers/{identification}` directamente en vez de la vía de sync.

### 6.4 Teléfonos/correos/direcciones no se duplican, pero tampoco se actualizan (excepto `calls_*` en bulk)

Si envías un teléfono con el mismo `phone_number` que ya existe, no se crea un duplicado. La única vía de sync que además actualiza contadores de llamadas sobre un duplicado existente es `/sync/bulk-upsert` (ver §4.2). El resto de campos de un duplicado (`alias`, `note`, dirección, correo) se ignoran silenciosamente si el registro ya existe.

---

## 7. Checklist para integrar otra API contra este servicio

1. Solicita a Sefil una `X-API-Key` con nombre identificable para tu sistema.
2. Para ingesta continua de datos: usa `/sync/bulk-upsert` con el schema `CustomerUpsertItem` (§4.2) — es el único endpoint con contrato de entrada estable y versionado explícitamente por Pydantic.
3. Valida `identification` (10-13 chars, solo dígitos) **en tu lado** antes de enviar batches — un item inválido tumba el batch completo con `422`.
4. Siempre revisa `errors[]` en la respuesta de `/sync/bulk-upsert`, incluso con `200`.
5. No envíes `relationships` en `/sync/bulk-upsert` ni llames a `POST /customers/{id}/relationships` hasta que el bug de `source`/`created_source` (§3.4, §4.2) esté corregido — hoy se pierde el dato o revienta el endpoint.
6. Para lectura, usa `GET /customers/{identification}/full` (un cliente) o `POST /customers/batch` (varios) — ambos traen el perfil 360° en un solo request.
7. No dependas de `/sync/status/{job_id}` para lógica crítica: vive en memoria de un solo proceso y no sobrevive a un restart de la API.
