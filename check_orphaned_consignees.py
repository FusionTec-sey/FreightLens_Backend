from sqlalchemy import text
from Model.db import engine

with engine.connect() as conn:
    res = conn.execute(text(
        "SELECT DISTINCT Consignee FROM containermgmt.bill_of_landing b LEFT JOIN containermgmt.consignee c ON b.Consignee = c.consignee_id WHERE b.Consignee IS NOT NULL AND c.consignee_id IS NULL"
    ))
    rows = res.fetchall()
    print("Orphaned Consignee IDs in bill_of_landing:", [r[0] for r in rows])
