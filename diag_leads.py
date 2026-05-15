from app.worker.scheduler import _run_leads
from app.core.database import SessionLocal
import logging
logging.basicConfig(level=logging.WARNING)
db = SessionLocal()
result = _run_leads(db)
db.close()
for e in result.errors: print(e)