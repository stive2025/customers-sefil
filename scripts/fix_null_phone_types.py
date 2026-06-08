import logging
from app.db.session import SessionLocal
from app.models.collections import CollectionPhone
from app.services.data_cleaning import infer_phone_type
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting batch update for null phone_types...")
    
    with SessionLocal() as db:
        # Find all phones where phone_type is NULL
        phones_to_fix = db.query(CollectionPhone).filter(CollectionPhone.phone_type.is_(None)).all()
        
        logger.info(f"Found {len(phones_to_fix)} phones with null phone_type.")
        
        updated_count = 0
        skipped_count = 0
        
        for phone in phones_to_fix:
            new_type = infer_phone_type(phone.phone_number)
            if new_type:
                phone.phone_type = new_type
                updated_count += 1
            else:
                skipped_count += 1
                
        if updated_count > 0:
            db.commit()
            logger.info(f"Committed changes for {updated_count} phones.")
            
        logger.info(f"Finished! Updated: {updated_count}, Skipped (could not infer): {skipped_count}")

if __name__ == "__main__":
    main()
