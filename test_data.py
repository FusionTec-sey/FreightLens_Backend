from sqlalchemy import text
from Model.db import engine

with engine.connect() as conn:
    # Check max length of supplier names
    res = conn.execute(text("SELECT MAX(LENGTH(name)) FROM containermgmt.supplier"))
    max_len = res.fetchone()[0]
    print(f"Max supplier name length: {max_len}")
    
    # Check nulls in logisticsprovider ExcludingDays and FreeDays
    res = conn.execute(text("SELECT COUNT(*) FROM containermgmt.logisticsprovider WHERE ExcludingDays IS NULL"))
    null_ex = res.fetchone()[0]
    res = conn.execute(text("SELECT COUNT(*) FROM containermgmt.logisticsprovider WHERE FreeDays IS NULL"))
    null_free = res.fetchone()[0]
    print(f"LogisticsProvider Null ExcludingDays: {null_ex}, Null FreeDays: {null_free}")
