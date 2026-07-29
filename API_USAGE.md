# Guía de Uso — API de Centralización de Personas (MDM)

> Pensada para ser consumida **desde otra API/servicio** (no desde un navegador). Todos los ejemplos de este documento son respuestas **reales**, capturadas ejecutando la API localmente contra una base de datos limpia (Docker, Postgres 15, migraciones al día). No son respuestas inventadas.

- **Base URL (producción):** `https://services.sefil.com.ec/customers/api/v1`
- **Base URL (local/docker):** `http://localhost:8002/api/v1`
- **Swagger UI:** `.../docs` · **ReDoc:** `.../redoc`
- **Formato:** JSON en request y response. `Content-Type: application/json` en todos los `POST`/`PATCH`.

## Autenticación

Todos los endpoints bajo `/api/v1/customers` requieren la cabecera `X-API-Key`. No hay OAuth, JWT ni sesiones — es autenticación M2M por clave estática.

```bash
curl -H "X-API-Key: sk_live_xxx" https://services.sefil.com.ec/customers/api/v1/customers/{identification}/phones
```

**Sin cabecera o con clave inválida:**

```http
GET /api/v1/customers/{identification}/phones
```
```json
HTTP 401
{
  "detail": "API Key ausente o inválida. Incluye una cabecera 'X-API-Key' válida."
}
```

---

## Sub-recursos: teléfonos, correos, direcciones

Todos comparten el patrón `GET` (listado paginado bajo `/customers/{identification}/...`), `POST` (crear), `PATCH` (actualizar, solo campos enviados), `DELETE` (soft-delete: `is_active=false`, no borra la fila).

### 1. Teléfonos

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
  "count_effective": null,
  "count_not_effective": null,
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

> **`count_effective` / `count_not_effective`** (SmallInteger, opcionales) son campos **nuevos e independientes** de `calls_effective`/`calls_not_effective`. Estos últimos los llenan los ETLs de Collecta/DATA SEFIL (llamadas telefónicas); `count_effective`/`count_not_effective` son de gestión **puramente manual vía API** — no los toca ningún ETL ni `/sync/bulk-upsert`. No están disponibles en el `POST` de creación (nacen en `null`); se cargan/actualizan después vía `PATCH`.

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

Registrar el resultado de una gestión (llamada, visita, etc.) sobre este teléfono:

```json
// Request
{ "count_effective": 1, "count_not_effective": 0 }
```
```json
// Response 200
{ "...": "...", "count_effective": 1, "count_not_effective": 0, "updated_at": "2026-07-29T10:00:00.000000Z" }
```

> El `PATCH` **sobrescribe** el valor recibido (no lo suma al existente) — quien consuma este endpoint es responsable de enviar el contador acumulado si necesita incrementar.

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

### 2. Correos — `POST /customers/{identification}/emails`

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

### 3. Direcciones — `POST /customers/{identification}/addresses`

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
  "count_effective": null,
  "count_not_effective": null,
  "id": 1,
  "customer_id": 1,
  "is_active": true,
  "created_by": "docs-test",
  "created_source": "Manual",
  "created_at": "2026-07-27T15:10:25.134347Z"
}
```

> ⚠️ `address_type` se **normaliza siempre** en el servidor: cualquier valor de entrada distinto de las variantes reconocidas de "trabajo" cae por defecto en `"Hogar"`. Se envió `"domicilio"` y volvió `"Hogar"`.

**Actualizar** — `PATCH /customers/{identification}/addresses/{address_id}` (solo campos enviados). Al igual que en teléfonos, `count_effective`/`count_not_effective` son de gestión manual (no los llena ningún ETL) y el `PATCH` sobrescribe el valor, no lo suma:

```json
// Request
{ "count_effective": 2, "count_not_effective": 1 }
```
```json
// Response 200
{ "...": "...", "count_effective": 2, "count_not_effective": 1, "updated_at": "2026-07-29T10:00:00.000000Z" }
```

**Eliminar (soft-delete)** — `DELETE /customers/{identification}/addresses/{address_id}`, body opcional:

```json
// Request
{ "deleted_by": "docs-test", "deleted_source": "Manual" }
```
```json
// Response 200 — is_active pasa a false, se llenan deleted_*
{ "...": "...", "is_active": false, "deleted_at": "2026-07-27T15:10:25.480530Z", "deleted_by": "docs-test", "deleted_source": "Manual" }
```

No es un DELETE HTTP real — el registro sigue existiendo en la tabla con `is_active=false`.
