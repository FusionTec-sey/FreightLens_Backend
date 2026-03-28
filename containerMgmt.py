from fastapi import FastAPI

from sqlalchemy import text
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.middleware.cors import CORSMiddleware
scheduler = BackgroundScheduler()
import uvicorn
from auth.config import settings
from Schema import *
from Model import *
from apscheduler.schedulers.background import BackgroundScheduler
from  datetime import datetime
from Model.db import Base, engine
from ShippingProvider.Shipping import track_and_trace


import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from auth import auth_router

from Routes import *
from Model.containermgmt.Container.BillOfLanding import BillOfLanding as bl

def updateArrivalDate():
    db = next(get_db())
    try:
        # use db here
        records = (db.query(bl)
                   .filter(bl.ArrivalDate > datetime.now())
                   .all())
        
        for i in records:
            data = track_and_trace(i.BillOfLanding)
            print(data)
            if len(data) > 0:
                db.query(bl).filter(bl.BillOfLanding == i.BillOfLanding).update(
                    {
                    bl.ArrivalDate:  datetime.fromisoformat(data[0]["eventDateTime"]).strftime("%Y-%m-%d %H:%M:%S")
                    }
                )
                db.commit()
    finally:
        db.close()

# def updateStatus():
#     """
#     Run a single set-based UPDATE to refresh container status according to rules.
#     Uses the DB session from get_db() so it matches how you run other tasks.
#     """
#     STATUS_UPDATE_SQL = """
#         UPDATE container_details cd
#         LEFT JOIN bill_of_landing bol ON bol.BillOfLading = cd.BillOfLading
#         SET cd.status = CASE
#             WHEN cd.out_bound IS NOT NULL OR cd.unloaded_at_port IS NOT NULL THEN 4
#             WHEN cd.empty_date IS NOT NULL THEN 7
#             WHEN cd.in_bound IS NOT NULL THEN 6
#             WHEN bol.ArrivalDate IS NULL THEN 8
#             WHEN bol.ArrivalDate > CURDATE() THEN 1
#             ELSE 2
#         END
#         -- OPTIONAL: add WHERE clause to limit rows to update for big tables
#         ;
#         """
    
#     db = next(get_db())
#     try:
#         # logger.info("Starting status update at %s", datetime.now().isoformat())
#         # Use the session's connection to execute raw SQL; this avoids depending on model names
#         conn = db.connection()
#         conn.execute(text(STATUS_UPDATE_SQL))
#         db.commit()
#         # logger.info("Status update completed successfully.")
#     except Exception as e:
#         # logger.exception("Error during status update: %s", e)
#         try:
#             db.rollback()
#         except Exception:
#             print()
#             # logger.exception("Rollback failed")
#     finally:
#         db.close()    
           
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
 )


scheduler = BackgroundScheduler()
scheduler.add_job(updateArrivalDate, "cron", hour=15, minute=44)  # every day at 03:00 AM
scheduler.start()


@app.on_event("startup")
async def startup_event():
    
    # scheduler.add_job(call_my_api, "cron", hour=2, minute=0)  # 🔁 Daily at 2:00 AM
    # scheduler.start()
    
    print(" Initializing database...")
    Base.metadata.create_all(bind=engine)
    print(" Database tables are ready.")
    # updateArrivalDate()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()




app.include_router(auth_router)
app.include_router(Cinfo)
app.include_router(ContainerRouter)
app.include_router(CreadentialsInfo)
app.include_router(TrackingRouter)
app.include_router(BillOfLandingRouter)

# Add this block to run with `python main.py`
if __name__ == "__main__":
     uvicorn.run("containerMgmt:app", host=settings.HOST_IP, port=settings.HOST_PORT, reload=True)
    # uvicorn.run("containerMgmt:app", host="172.16.32.6", port=8000)

         