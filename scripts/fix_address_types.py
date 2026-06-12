import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import SessionLocal

def normalize(v):
    if not v:
        return None
    val = v.upper().strip()
    if val in ("TRABAJO", "WORK", "JOB", "OFICINA", "EMPRESA"):
        return "JOB"
    if val in ("DOMICILIO", "HOME", "CASA", "RESIDENCIA"):
        return "HOME"
    return "HOME"  # Default to HOME if not specified or unknown, as requested by user

def backfill_address_types():
    with SessionLocal() as db:
        print("Starting address_type backfill...")
        # Get all distinct address_types
        types = db.execute(text("SELECT DISTINCT address_type FROM collection_addresses WHERE address_type IS NOT NULL")).scalars().all()
        
        for t in types:
            new_type = normalize(t)
            if new_type != t:
                res = db.execute(
                    text("UPDATE collection_addresses SET address_type = :new_type WHERE address_type = :old_type"),
                    {"new_type": new_type, "old_type": t}
                )
                print(f"Updated '{t}' -> '{new_type}' ({res.rowcount} rows)")
        
        db.commit()
        print("Backfill complete.")

if __name__ == "__main__":
    backfill_address_types()
