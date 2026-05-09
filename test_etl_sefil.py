import json
import os
from app.core.database import SessionLocal
from app.services.etl_datasefil import sync_datasefil_data

def run():
    print("🚀 Iniciando el proceso ETL de DATA SEFIL...")
    
    filepath = "mock_datasefil.json"
    
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            raw_data = json.load(file)
            
        # --- NUEVA LÓGICA DE EXTRACCIÓN ---
        # Si la API devolvió un diccionario con metadata, extraemos solo la lista
        if isinstance(raw_data, dict):
            # Usualmente la data viene dentro de la llave "data", "results" o "clientes"
            if "data" in raw_data:
                raw_data = raw_data["data"]
            else:
                print(f"⚠️ El JSON es un diccionario con estas llaves: {list(raw_data.keys())}")
                print("Por favor, dime qué llave contiene los clientes para ajustar el código.")
                return
                
        print(f"📥 Se obtuvieron {len(raw_data)} clientes reales de DATA SEFIL.")
        # ----------------------------------
        
    except FileNotFoundError:
        print(f"❌ Error: No se encontró el archivo en {filepath}")
        return

    db = SessionLocal()
    try:
        print("⚙️  Unificando datos en PostgreSQL...")
        
        resultado = sync_datasefil_data(raw_data, db)
        
        print("\n✅ Proceso completado. Resumen:")
        print(f"   🔹 Nuevos clientes creados: {resultado.created}")
        print(f"   🔹 Clientes fusionados/actualizados: {resultado.updated}")
        print(f"   🔹 Registros omitidos: {resultado.skipped}")
        
    except Exception as e:
        print(f"\n❌ Ocurrió un error en la base de datos: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run()