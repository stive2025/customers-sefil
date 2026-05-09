# ── Imagen base ligera ────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── Dependencias de sistema ───────────────────────────────────────────────────
# libpq5: runtime de PostgreSQL que necesita psycopg2-binary
# Los headers de compilación NO son necesarios con psycopg2-binary
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ── Directorio de trabajo ─────────────────────────────────────────────────────
WORKDIR /app

# ── Dependencias Python ───────────────────────────────────────────────────────
# Copiamos requirements.txt primero para aprovechar la caché de capas de Docker.
# Solo se reinstala si requirements.txt cambia.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código de la aplicación ───────────────────────────────────────────────────
COPY . .

# ── Variables de entorno de Python ────────────────────────────────────────────
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── Puerto expuesto (solo la API lo usa; el worker no escucha) ────────────────
EXPOSE 8002

# CMD por defecto: la API. El worker lo sobreescribe en docker-compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
