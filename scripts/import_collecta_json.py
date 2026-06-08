import json
import logging
import sys
from pathlib import Path
from collections import defaultdict

# Agrega la raíz del proyecto al sys.path para poder importar 'app'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.schemas.sync import CustomerUpsertItem, PhoneItem, AddressItem
from app.services.bulk_upsert import bulk_upsert_customers
from app.services.data_cleaning import clean_phone_number, standardize_text, clean_identification
from app.services.etl_collecta import infer_phone_type, _ADDRESS_TYPE_MAP

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    root_dir = Path(__file__).resolve().parent.parent
    contacts_path = root_dir / "collection_contacts.json"
    directions_path = root_dir / "collection_directions.json"

    from typing import Dict
    customers_map: Dict[str, CustomerUpsertItem] = {}

    # --- 1. Load Phones ---
    if contacts_path.exists():
        logger.info("Leyendo %s...", contacts_path.name)
        with open(contacts_path, "r", encoding="utf-8") as f:
            contacts_json = json.load(f)
        
        for item in contacts_json:
            if item.get("type") == "table" and item.get("name") == "collection_contacts":
                data_rows = item.get("data", [])
                logger.info("Encontrados %d teléfonos en el JSON", len(data_rows))
                for row in data_rows:
                    ci = clean_identification(row.get("client_identification"))
                    if not ci:
                        continue
                    
                    local_number = clean_phone_number(row.get("phone_number"))
                    if not local_number:
                        continue
                    
                    phone_type = infer_phone_type(local_number)
                    
                    phone_item = PhoneItem(
                        phone_number=local_number,
                        phone_type=phone_type,
                        country_code="+593",
                        created_source="Collecta JSON"
                    )
                    
                    if ci not in customers_map:
                        customers_map[ci] = CustomerUpsertItem(identification=ci, phones=[], addresses=[])
                    customers_map[ci].phones.append(phone_item)
                break
    else:
        logger.warning("No se encontró %s", contacts_path)

    # --- 2. Load Addresses ---
    if directions_path.exists():
        logger.info("Leyendo %s...", directions_path.name)
        with open(directions_path, "r", encoding="utf-8") as f:
            directions_json = json.load(f)
        
        for item in directions_json:
            if item.get("type") == "table" and item.get("name") == "collection_directions":
                data_rows = item.get("data", [])
                logger.info("Encontradas %d direcciones en el JSON", len(data_rows))
                for row in data_rows:
                    ci = clean_identification(row.get("client_identification"))
                    if not ci:
                        continue
                    
                    # Construir address_line igual que en el ETL
                    parts = [
                        standardize_text(row.get("address")),
                        standardize_text(row.get("neighborhood")),
                        standardize_text(row.get("parish")),
                    ]
                    address_line = " ".join(filter(None, parts)) or None
                    if not address_line:
                        continue
                    
                    province = standardize_text(row.get("province")) or None
                    city = standardize_text(row.get("canton")) or None
                    
                    raw_type = str(row.get("type", "")).upper()
                    address_type = _ADDRESS_TYPE_MAP.get(raw_type, raw_type or None)
                    
                    try:
                        lat = float(row["latitude"]) if row.get("latitude") else None
                    except (ValueError, TypeError):
                        lat = None
                    try:
                        lng = float(row["longitude"]) if row.get("longitude") else None
                    except (ValueError, TypeError):
                        lng = None
                        
                    addr_item = AddressItem(
                        address_line=address_line[:499],
                        province=province,
                        city=city,
                        canton=city,
                        parish=standardize_text(row.get("parish")) or None,
                        neighborhood=standardize_text(row.get("neighborhood")) or None,
                        address_type=address_type,
                        latitude=lat,
                        longitude=lng,
                        source="Collecta JSON"
                    )
                    
                    if ci not in customers_map:
                        customers_map[ci] = CustomerUpsertItem(identification=ci, phones=[], addresses=[])
                    customers_map[ci].addresses.append(addr_item)
                break
    else:
        logger.warning("No se encontró %s", directions_path)

    # --- 3. Upsert into DB ---
    upsert_items = list(customers_map.values())
    if not upsert_items:
        logger.info("No hay datos para procesar.")
        return

    logger.info("Preparados %d clientes para Upsert (inyección de contactos y direcciones)", len(upsert_items))
    
    batch_size = 1000
    try:
        total_created = 0
        total_updated = 0
        total_skipped = 0
        
        for i in range(0, len(upsert_items), batch_size):
            batch = upsert_items[i : i + batch_size]
            logger.info("Procesando lote %d a %d...", i, i + len(batch))
            
            # Usar una sesión fresca por cada lote asegura que si la conexión se corta,
            # el siguiente lote intentará reconectarse y no fallará en cadena.
            with SessionLocal() as db:
                result = bulk_upsert_customers(batch, db)
                
                total_created += result.created
                total_updated += result.updated
                total_skipped += result.skipped
                
                for err in result.errors:
                    logger.error("Error en lote: %s", err)
                
        logger.info("FINALIZADO:")
        logger.info("Creados: %d", total_created)
        logger.info("Actualizados: %d", total_updated)
        logger.info("Omitidos (sin cambios o no encontrados): %d", total_skipped)
    except Exception as exc:
        logger.error("Error crítico durante el procesamiento: %s", exc)

if __name__ == "__main__":
    main()
