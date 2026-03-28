import sys
import os
from sqlalchemy import text
from Model.db import engine

def run_migration():
    queries = [
        "ALTER TABLE containermgmt.bill_of_landing ADD COLUMN FreeDays INT NULL;",
        "ALTER TABLE containermgmt.container_details ADD COLUMN FreeDays INT NULL;"
    ]
    
    with engine.connect() as conn:
        for q in queries:
            try:
                conn.execute(text(q))
                print(f"Executed: {q}")
            except Exception as e:
                print(f"Skipped (may already exist or error): {e}")
        conn.commit()
        
if __name__ == "__main__":
    print("Running migration...")
    run_migration()
    print("Migration finished.")
