# api/tracking/routes.py

from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Query, HTTPException
# from ShippingProvider.maersk import MaerskProvider
# from ShippingProvider.Mearsk import MaerskProvider
from ShippingProvider.Mearsk.mearsk_api import MaerskAPI
from ShippingProvider.CMACGM.camcgm_api import CMACGMTrackTrace
from ShippingProvider import track_and_trace
# from providers.uafl import UAFLProvider

TrackingRouter = InferringRouter()

@cbv(TrackingRouter)
class TrackingAPI:
    def __init__(self):
        self.providers = [
            
            MaerskAPI() , 
            CMACGMTrackTrace(
                api_key="X2wG7Gc7In0roXj2u1OG2qp4yMIhHwOm",
                client_id="beapp-fusiontech",
                client_secret="T3FefGXrLjQBWCQT98D1VsbKXb1aKGgOWamRUSGWkDmvlNzR1ZsLv0El8XF7RDFS"
            )] #UAFLProvider()]  # You can dynamically load these too

    @TrackingRouter.get("/track/bl")
    async def track_bl(self, bl: str = Query(...)):
        # containers = self.providers[0].get_BoL(bl)
        # print(containers)
        for provider in self.providers:
            
            try:
                containers = provider.get_BoL(bl)
                # print(containers)
                if len(containers) == 0:
                    
                    continue 
                print(f"Containers for BL {bl} from {provider.__class__.__name__}: {containers}")

                return containers
            except Exception:
                continue
        raise HTTPException(status_code=404, detail="BL not found in any provider")

    @TrackingRouter.get("/track/container")
    def track_container(self, container_no: str = Query(...)):
        for provider in self.providers:
            try:
                arrival = provider.get_arrival(container_no)
                if arrival:
                    return {"arrivalDateTime": arrival["eventDateTime"]}
            except Exception:
                continue
        raise HTTPException(status_code=404, detail="Container not found")

    @TrackingRouter.get("/track_and_trace")
    async def track_and_trace(self, bl: str = Query(...)):
        return track_and_trace(bl)