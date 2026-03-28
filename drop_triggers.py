from Model.db import engine
from sqlalchemy import text

def drop_triggers():
    with engine.begin() as conn:
        conn.execute(text("DROP TRIGGER IF EXISTS set_status_before_INSERT;"))
        conn.execute(text("DROP TRIGGER IF EXISTS set_status_before_UPDATE;"))
        print("Triggers dropped successfully.")

if __name__ == "__main__":
    drop_triggers()
