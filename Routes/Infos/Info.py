

from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from sqlalchemy import func, extract
from Model.db import get_db
from Model import ContainerDetails, Supplier, UnloadVenue, Status, Vessal, Consignee, ShippingDocument, ContainerType, BillOfLanding, LogisticsProvider, Material

from Utils import *
from auth.dependencies import get_current_user
from fastapi import  Depends, HTTPException,   Request

import json


Cinfo = InferringRouter()

@cbv(Cinfo)
class CinfoAPI:
    
    @Cinfo.get("/suppliers")
    async def getsupplier(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Supplier.supplier_id, Supplier.name).all()
    
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/container-types")
    async def gettype(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(ContainerType.type_id, ContainerType.type).all()
        
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/unload-venues")
    async def getvenue(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(UnloadVenue.venue_id, UnloadVenue.venue).all()
        
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/consignees")
    async def getconsignee(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Consignee.consignee_id, Consignee.consignee_name).all()
        
        return json.dumps({"data": [list(row) for row in data]})
    
    @Cinfo.get("/shipping-documents")
    async def getshippingDocument(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(ShippingDocument.doc_id, ShippingDocument.doc_type).all()
        # column = ['Document ID', 'Document Name']
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/status")
    async def getStatus(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Status.status_id, Status.name).all()
        # column = ['Status ID', 'name']
        return json.dumps({ "data": [list(row) for row in data]})  
    
    @Cinfo.get("/vessels")
    async def getVessel(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Vessal.id, Vessal.VessalNo).all()
        # column = ['Status ID', 'name']
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/logistics-providers")
    async def getLogisticsProvider(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        
        data = db.query(LogisticsProvider.Id, LogisticsProvider.Name).distinct().all()
        # column = ['Logistics Provider']
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/materials")
    async def getMaterial(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Material.Id, Material.Name).all()
        return json.dumps({ "data": [list(row) for row in data]}) 
    
    
    @Cinfo.post("/vessels")
    async def create_vessal(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        vessal_data = await request.json()
        # print(vessal_data)
        vessal_no = vessal_data.get("name")
        # name = vessal_data.get("name")

        if not vessal_no or not vessal_no:
            raise HTTPException(status_code=422, detail="Missing VessalNo or name")


        new_vessal = Vessal(VessalNo=vessal_no)
        db.add(new_vessal)
        db.commit()
        db.refresh(new_vessal)

        return {"id": new_vessal.id, "name": new_vessal.VessalNo}

    @Cinfo.post("/suppliers")
    async def create_supplier(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        supplier_data = await request.json()
        # print(supplier_data)
        name = supplier_data.get("name")

        if not name:
            raise HTTPException(status_code=422, detail="Missing supplier name")

        new_supplier = Supplier(name=name)
        db.add(new_supplier)
        db.commit()
        db.refresh(new_supplier)

        return {"id": new_supplier.supplier_id, "name": new_supplier.name}
    
    @Cinfo.post("/unload-venues")
    async def create_unload_venue(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        venue_data = await request.json()
        # print(venue_data)
        venue_name = venue_data.get("name")

        if not venue_name:
            raise HTTPException(status_code=422, detail="Missing venue name")

        new_venue = UnloadVenue(venue=venue_name)
        db.add(new_venue)
        db.commit()
        db.refresh(new_venue)

        return {"id": new_venue.venue_id, "name": new_venue.venue}
    
    @Cinfo.post("/consignees")
    async def create_consignee(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        consignee_data = await request.json()
        # print(consignee_data)
        consignee_name = consignee_data.get("name")

        if not consignee_name:
            raise HTTPException(status_code=422, detail="Missing consignee name")

        new_consignee = Consignee(consignee_name=consignee_name)
        db.add(new_consignee)
        db.commit()
        db.refresh(new_consignee)

        return {"id": new_consignee.consignee_id, "name": new_consignee.consignee_name}
    
    @Cinfo.post("/container-types")
    async def create_container_type(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        type_data = await request.json()
        # print(type_data)
        type_name = type_data.get("name")

        if not type_name:
            raise HTTPException(status_code=422, detail="Missing container type name")

        new_type = ContainerType(type=type_name)
        db.add(new_type)
        db.commit()
        db.refresh(new_type)

        return {"id": new_type.type_id, "name": new_type.type}
    
    @Cinfo.post("/shipping-documents")
    async def create_shipping_document(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        doc_data = await request.json()
    
        doc_type = doc_data.get("name")

        if not doc_type:
            raise HTTPException(status_code=422, detail="Missing document type")

        new_doc = ShippingDocument(doc_type=doc_type)
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)

        return {"id": new_doc.doc_id, "name": new_doc.doc_type}
   
    @Cinfo.post("/materials")
    async def create_Material(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        material_data = await request.json()
        # print(doc_data)
        materials = material_data.get("material")

        if not materials:
            raise HTTPException(status_code=422, detail="Missing document type")

        new_material = Material(Name=materials)
        db.add(new_material)
        db.commit()
        db.refresh(new_material)
        
        return {"id": new_material.Id, "name": new_material.Name} 
    
    @Cinfo.post("/logistics-providers")
    async def create_logisticsProvider(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        provider_data = await request.json()
        # print(doc_data)
        provider = provider_data.get("name")

        if not provider:
            raise HTTPException(status_code=422, detail="Missing document type")

        new_provider = LogisticsProvider(Name=provider)
        db.add(new_provider)
        db.commit()
        db.refresh(new_provider)
        return {"id": new_provider.Id, "name": new_provider.Name}
    
    @Cinfo.get("/getDashboardInfo")
    async def getContainerInfo(self, db: Session = Depends(get_db)):
        TotalContainer = db.query(ContainerDetails).count()
        GatePass = db.query(ContainerDetails).filter(ContainerDetails.status == 3).count()
        OnPort = db.query(ContainerDetails).filter(ContainerDetails.status == 2).count()
        InTransit = db.query(ContainerDetails).filter(ContainerDetails.status == 1).count()
        Arrived = db.query(ContainerDetails).filter(ContainerDetails.status == 6).count()
        ArrivedAtLocation = (db.query(ContainerDetails.container_no, UnloadVenue.venue)
                             .filter(ContainerDetails.status == 6)
                             .outerjoin(UnloadVenue, ContainerDetails.emptied_at == UnloadVenue.venue_id)
                             ).all()
        emptied_count = db.query(ContainerDetails).filter(ContainerDetails.status == 7).count()
        return { "TotalContainer": TotalContainer,
                 "GatePass": GatePass,
                 "OnPort": OnPort,
                "InTransit": InTransit,
                 "Arrived": Arrived,
                 "Emptied": emptied_count,
                 "ArrivedAtLocation": [{"container_no": row[0], "location": row[1]} for row in ArrivedAtLocation]}
    
    @Cinfo.get("/getContainerCountsByMonth/{year}")
    async def get_container_counts_by_month(self, year: int, db: Session = Depends(get_db)):
        results = (
            db.query(
                extract('month', BillOfLanding.ArrivalDate).label('month'),
                func.count(ContainerDetails.Container_ID).label('count')
            )
            .outerjoin(BillOfLanding, BillOfLanding.BillOfLanding == ContainerDetails.BillOfLanding)
            .filter(extract('year', BillOfLanding.ArrivalDate) == year)  # <-- fix here
            .group_by(extract('month', BillOfLanding.ArrivalDate))
            .order_by('month')
            .all()
        )

        # Convert to dictionary or list for easy use
        month_counts = {int(month): count for month, count in results}

        # Ensure all 12 months are included (fill missing with 0)
        full_year_counts = [month_counts.get(m, 0) for m in range(1, 13)]
        return full_year_counts
    
