import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
url = os.getenv("DATABASE_URL")
print("Connecting to:", url)

try:
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    with engine.connect() as conn:
        res = conn.execute(text("SELECT 1"))
        print("Result:", res.fetchone())
except Exception as e:
    print("Error connecting:", e)
