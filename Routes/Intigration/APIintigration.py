# api/tracking/routes.py

from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Query, HTTPException
# from ShippingProvider.maersk import MaerskProvider
# from ShippingProvider.Mearsk import MaerskProvider
from ShippingProvider.Mearsk.mearsk_api import MaerskAPI
from ShippingProvider.CMACGM.camcgm_api import CMACGMTrackTrace
from ShippingProvider import track_and_trace
from auth.config import settings

TrackingRouter = InferringRouter()



@cbv(TrackingRouter)
class TrackingAPI:
    def __init__(self):
        self.providers = [
            
            MaerskAPI(), 
            CMACGMTrackTrace(
                api_key=settings.CMA_CGM_API_KEY,
                client_id=settings.CMA_CGM_CLIENT_ID,
                client_secret=settings.CMA_CGM_SECRET
            )] #UAFLProvider()]  # You can dynamically load these too

    # @TrackingRouter.get("/track/bl")
    # async def track_bl(self, bl: str = Query(...)):
    #     for provider in self.providers:
            
    #         try:
    #             containers = provider.get_BoL(bl)
    #             # print(containers)
    #             if len(containers) == 0:
                    
    #                 continue 
    #             print(f"Containers for BL {bl} from {provider.__class__.__name__}: {containers}")

    #             return containers
    #         except Exception:
    #             continue
    #     raise HTTPException(status_code=404, detail="BL not found in any provider")

    # @TrackingRouter.get("/track/container")
    # def track_container(self, container_no: str = Query(...)):
    #     for provider in self.providers:
    #         try:
    #             arrival = provider.get_arrival(container_no)
    #             if arrival:
    #                 return {"arrivalDateTime": arrival["eventDateTime"]}
    #         except Exception:
    #             continue
    #     raise HTTPException(status_code=404, detail="Container not found")

    @TrackingRouter.get("/track_and_trace")
    async def track_and_trace(self, bl: str = Query(...)):
        return track_and_trace(bl)
    
    
    