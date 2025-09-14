# db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base
from auth.config import settings
Base = declarative_base()


DATABASE_URL = "mysql+mysqlconnector://mysql:APVKegtlmgswVmkWPT12b13p0cmVyzIdqPnHxokldgWb0motvP7HV5EQT8tIXVm0@r44ws8w88w4kgkk0gk4wsok8:3306"  # or your actual DB URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
