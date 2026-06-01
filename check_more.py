from sqlalchemy import text
from Model.db import engine

with engine.connect() as conn:
    queries = {
        "consignee.consignee_name": "SELECT MAX(LENGTH(consignee_name)) FROM containermgmt.consignee",
        "supplier.address": "SELECT MAX(LENGTH(address)) FROM containermgmt.supplier",
        "supplier.email": "SELECT MAX(LENGTH(email)) FROM containermgmt.supplier",
    }
    
    for key, sql in queries.items():
        try:
            res = conn.execute(text(sql))
            val = res.fetchone()[0]
            print(f"Max length of {key}: {val}")
        except Exception as e:
            print(f"Error checking {key}: {e}")
