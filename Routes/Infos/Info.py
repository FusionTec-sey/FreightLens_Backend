
from datetime import datetime
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from Model.db import get_db
from Model import ContainerDetails, Supplier, UnloadVenue, Status, Vessal, Consignee, ShippingDocument, ContainerType, BillOfLanding, LogisticsProvider, Material, OrderStatus

from Utils import *
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter, apply_shared_or_org_filter
import json


Cinfo = InferringRouter()

@cbv(Cinfo)
class CinfoAPI:
    
    @Cinfo.get("/suppliers")
    async def getsupplier(self, db: Session = Depends(get_db), org_context: OrgContext = Depends(get_org_context), current_user: dict = Depends(get_current_user)):
        query = db.query(Supplier).filter(Supplier.is_deleted != True)
        suppliers = apply_shared_or_org_filter(query, Supplier, org_context).order_by(Supplier.name.asc()).all()
        formatted = [
            [
                s.supplier_id,
                s.name,
                float(s.variance_threshold_pct) if s.variance_threshold_pct is not None else 2.0,
                s.default_currency or "USD",
                s.payment_term.name if s.payment_term else ""
            ]
            for s in suppliers
        ]
        return json.dumps({"data": formatted})
    
    @Cinfo.get("/container-types")
    async def gettype(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(ContainerType.type_id, ContainerType.type).filter(ContainerType.is_deleted != True).all()
        
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/unload-venues")
    async def getvenue(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(UnloadVenue.venue_id, UnloadVenue.venue).filter(UnloadVenue.is_deleted != True).all()
        
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/consignees")
    async def getconsignee(
        self, 
        db: Session = Depends(get_db), 
        org_context: OrgContext = Depends(get_org_context)
    ):
        query = db.query(
            Consignee.consignee_id,
            Consignee.consignee_name,
            Consignee.org_id,
            Consignee.code
        ).filter(
            Consignee.is_deleted != True,
            Consignee.consignee_name != None,
            Consignee.consignee_name != ""
        )

        if not org_context.is_root:
            if org_context.selected_org_id:
                query = query.filter(Consignee.org_id == org_context.selected_org_id)
            else:
                query = query.filter(Consignee.org_id.in_(org_context.allowed_org_ids))
        else:
            if org_context.selected_org_id:
                query = query.filter(Consignee.org_id == org_context.selected_org_id)

        data = query.order_by(Consignee.consignee_id.asc()).all()
        return json.dumps({"data": [list(row) for row in data]})
    
    @Cinfo.get("/shipping-documents")
    async def getshippingDocument(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(ShippingDocument.doc_id, ShippingDocument.doc_type).filter(ShippingDocument.is_deleted != True).all()
        # column = ['Document ID', 'Document Name']
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/status")
    async def getStatus(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Status.status_id, Status.name).filter(Status.is_deleted != True).all()
        # column = ['Status ID', 'name']
        return json.dumps({ "data": [list(row) for row in data]})  
    
    @Cinfo.get("/vessels")
    @Cinfo.get("/vessal", deprecated=True)
    async def getVessel(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Vessal.id, Vessal.VessalNo).filter(Vessal.is_deleted != True).all()
        # column = ['Status ID', 'name']
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/logistics-providers")
    @Cinfo.get("/logisticsProvider", deprecated=True)
    async def getLogisticsProvider(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        
        data = db.query(LogisticsProvider.Id, LogisticsProvider.Name, LogisticsProvider.FreeDays).filter(LogisticsProvider.is_deleted != True).distinct().all()
        # column = ['Logistics Provider']
        return json.dumps({ "data": [list(row) for row in data]})
    
    @Cinfo.get("/materials")
    @Cinfo.get("/material", deprecated=True)
    async def getMaterial(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(Material.Id, Material.Name).filter(Material.is_deleted != True).all()
        return json.dumps({ "data": [list(row) for row in data]}) 
    
    @Cinfo.get("/order-statuses")
    async def getOrderStatuses(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = db.query(
            OrderStatus.id,
            OrderStatus.name,
            OrderStatus.code,
            OrderStatus.sequence_order,
            OrderStatus.progress,
            OrderStatus.color,
            OrderStatus.badge_color
        ).filter(OrderStatus.is_deleted != True, OrderStatus.is_active != False).order_by(OrderStatus.sequence_order.asc(), OrderStatus.id.asc()).all()
        return json.dumps({"data": [list(row) for row in data]})
    
    @Cinfo.post("/order-statuses")
    async def create_order_status(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        status_data = await request.json()
        name = status_data.get("name")
        if not name:
            raise HTTPException(status_code=422, detail="Missing status name")
        
        existing = db.query(OrderStatus).filter(OrderStatus.name.ilike(name), OrderStatus.is_deleted != True).first()
        if existing:
            raise HTTPException(status_code=400, detail="Order status with this name already exists")
        
        code = status_data.get("code") or name.upper().replace(" ", "_")[:50]
        progress = status_data.get("progress", 0)
        color = status_data.get("color", "bg-blue-500")
        seq = status_data.get("sequence_order", 10)
        
        new_status = OrderStatus(
            name=name,
            code=code,
            sequence_order=seq,
            progress=progress,
            color=color,
            created_by=current_user.id
        )
        db.add(new_status)
        db.commit()
        db.refresh(new_status)
        return {"id": new_status.id, "name": new_status.name, "code": new_status.code} 
    
    
    @Cinfo.post("/vessels")
    @Cinfo.post("/setVessal", deprecated=True)
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
    @Cinfo.post("/setSupplier", deprecated=True)
    async def create_supplier(self,
        request: Request,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context),
        current_user: dict = Depends(get_current_user)):
        
        supplier_data = await request.json()
        # print(supplier_data)
        name = supplier_data.get("name")

        if not name:
            raise HTTPException(status_code=422, detail="Missing supplier name")

        existing_query = db.query(Supplier).filter(Supplier.name.ilike(name), Supplier.is_deleted != True)
        existing = apply_shared_or_org_filter(existing_query, Supplier, org_context).first()
        if existing:
            raise HTTPException(status_code=400, detail="Supplier with this name already exists")

        var_thresh = supplier_data.get("variance_threshold_pct")
        if var_thresh is not None:
            try:
                var_thresh = float(var_thresh)
            except (ValueError, TypeError):
                var_thresh = 2.0
        else:
            var_thresh = 2.0

        is_shared = bool(supplier_data.get("is_shared", False))
        if is_shared and not org_context.is_root:
            raise HTTPException(status_code=403, detail="Only root organisation users can create shared suppliers")
        new_supplier = Supplier(
            name=name,
            variance_threshold_pct=var_thresh,
            is_shared=is_shared,
            org_id=None if is_shared else org_context.org_id,
        )
        db.add(new_supplier)
        db.commit()
        db.refresh(new_supplier)

        return {"id": new_supplier.supplier_id, "name": new_supplier.name, "variance_threshold_pct": float(new_supplier.variance_threshold_pct or 2.0)}
    
    @Cinfo.post("/unload-venues")
    @Cinfo.post("/setUnloadVenue", deprecated=True)
    async def create_unload_venue(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        venue_data = await request.json()
        # print(venue_data)
        venue_name = venue_data.get("name")

        if not venue_name:
            raise HTTPException(status_code=422, detail="Missing venue name")

        existing = db.query(UnloadVenue).filter(UnloadVenue.venue.ilike(venue_name), UnloadVenue.is_deleted != True).first()
        if existing:
            raise HTTPException(status_code=400, detail="Venue with this name already exists")

        new_venue = UnloadVenue(venue=venue_name)
        db.add(new_venue)
        db.commit()
        db.refresh(new_venue)

        return {"id": new_venue.venue_id, "name": new_venue.venue}
    
    @Cinfo.post("/consignees")
    @Cinfo.post("/setConsignee", deprecated=True)
    async def create_consignee(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        consignee_data = await request.json()
        # print(consignee_data)
        consignee_name = consignee_data.get("name")

        if not consignee_name:
            raise HTTPException(status_code=422, detail="Missing consignee name")

        existing = db.query(Consignee).filter(Consignee.consignee_name.ilike(consignee_name), Consignee.is_deleted != True).first()
        if existing:
            raise HTTPException(status_code=400, detail="Consignee with this name already exists")

        new_consignee = Consignee(consignee_name=consignee_name)
        db.add(new_consignee)
        db.commit()
        db.refresh(new_consignee)

        return {"id": new_consignee.consignee_id, "name": new_consignee.consignee_name}
    
    @Cinfo.post("/container-types")
    @Cinfo.post("/setContainerType", deprecated=True)
    async def create_container_type(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        type_data = await request.json()
        # print(type_data)
        type_name = type_data.get("name")

        if not type_name:
            raise HTTPException(status_code=422, detail="Missing container type name")

        existing = db.query(ContainerType).filter(ContainerType.type.ilike(type_name), ContainerType.is_deleted != True).first()
        if existing:
            raise HTTPException(status_code=400, detail="Container type with this name already exists")

        new_type = ContainerType(type=type_name)
        db.add(new_type)
        db.commit()
        db.refresh(new_type)

        return {"id": new_type.type_id, "name": new_type.type}
    
    @Cinfo.post("/shipping-documents")
    @Cinfo.post("/setShippingDocument", deprecated=True)
    async def create_shipping_document(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        doc_data = await request.json()
    
        doc_type = doc_data.get("name")

        if not doc_type:
            raise HTTPException(status_code=422, detail="Missing document type")

        existing = db.query(ShippingDocument).filter(ShippingDocument.doc_type.ilike(doc_type), ShippingDocument.is_deleted != True).first()
        if existing:
            raise HTTPException(status_code=400, detail="Document type with this name already exists")

        new_doc = ShippingDocument(doc_type=doc_type)
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)

        return {"id": new_doc.doc_id, "name": new_doc.doc_type}
   
    @Cinfo.post("/materials")
    @Cinfo.post("/setMaterial", deprecated=True)
    async def create_Material(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        material_data = await request.json()
        # print(doc_data)
        materials = material_data.get("name") or material_data.get("material")

        if not materials:
            raise HTTPException(status_code=422, detail="Missing material name")

        existing = db.query(Material).filter(Material.Name.ilike(materials), Material.is_deleted != True).first()
        if existing:
            raise HTTPException(status_code=400, detail="Material with this name already exists")

        new_material = Material(Name=materials)
        db.add(new_material)
        db.commit()
        db.refresh(new_material)
        
        return {"id": new_material.Id, "name": new_material.Name} 
    
    @Cinfo.post("/logistics-providers")
    @Cinfo.post("/setProvider", deprecated=True)
    async def create_logisticsProvider(self,
        request: Request,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)):
        
        provider_data = await request.json()
        provider = provider_data.get("name") or provider_data.get("Name")

        if not provider:
            raise HTTPException(status_code=422, detail="Missing logistics provider name")

        existing = db.query(LogisticsProvider).filter(LogisticsProvider.Name.ilike(provider), LogisticsProvider.is_deleted != True).first()
        if existing:
            raise HTTPException(status_code=400, detail="Logistics Provider with this name already exists")

        free_days = provider_data.get("FreeDays", provider_data.get("free_days", 0))
        excluding_days_list = provider_data.get("ExcludingDaysList", provider_data.get("excluding_days_list", []))
        
        bitmask = 0
        if excluding_days_list:
            try:
                bitmask = store_days(excluding_days_list)
            except Exception:
                bitmask = 0

        new_provider = LogisticsProvider(Name=provider, FreeDays=int(free_days or 0), ExcludingDays=bitmask)
        db.add(new_provider)
        db.commit()
        db.refresh(new_provider)
        
        return {
            "Id": new_provider.Id,
            "id": new_provider.Id,
            "Name": new_provider.Name,
            "name": new_provider.Name,
            "FreeDays": new_provider.FreeDays,
            "ExcludingDaysList": get_days(new_provider.ExcludingDays) if new_provider.ExcludingDays else []
        }
    
    @Cinfo.put("/suppliers/{item_id}")
    async def update_supplier(self, item_id: int, request: Request, db: Session = Depends(get_db), org_context: OrgContext = Depends(get_org_context), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item_query = db.query(Supplier).filter(Supplier.supplier_id == item_id, Supplier.is_deleted != True)
        item = apply_shared_or_org_filter(item_query, Supplier, org_context).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        if item.is_shared and not org_context.is_root: raise HTTPException(status_code=403, detail="Shared suppliers are root-managed")
        
        new_name = data.get("name")
        if new_name:
            existing_query = db.query(Supplier).filter(Supplier.name.ilike(new_name), Supplier.supplier_id != item_id, Supplier.is_deleted != True)
            existing = apply_shared_or_org_filter(existing_query, Supplier, org_context).first()
            if existing: raise HTTPException(status_code=400, detail="Supplier with this name already exists")
            item.name = new_name
        if "variance_threshold_pct" in data:
            try:
                item.variance_threshold_pct = float(data["variance_threshold_pct"])
            except (ValueError, TypeError):
                pass
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.supplier_id, "name": item.name, "variance_threshold_pct": float(item.variance_threshold_pct or 2.0)}

    @Cinfo.delete("/suppliers/{item_id}")
    async def delete_supplier(self, item_id: int, db: Session = Depends(get_db), org_context: OrgContext = Depends(get_org_context), current_user: dict = Depends(get_current_user)):
        item_query = db.query(Supplier).filter(Supplier.supplier_id == item_id, Supplier.is_deleted != True)
        item = apply_shared_or_org_filter(item_query, Supplier, org_context).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        if item.is_shared and not org_context.is_root: raise HTTPException(status_code=403, detail="Shared suppliers are root-managed")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/vessels/{item_id}")
    async def update_vessel(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(Vessal).filter(Vessal.id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.VessalNo = data.get("name")
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.id, "name": item.VessalNo}

    @Cinfo.delete("/vessels/{item_id}")
    async def delete_vessel(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(Vessal).filter(Vessal.id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/unload-venues/{item_id}")
    async def update_venue(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(UnloadVenue).filter(UnloadVenue.venue_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        
        new_name = data.get("name")
        if new_name:
            existing = db.query(UnloadVenue).filter(UnloadVenue.venue.ilike(new_name), UnloadVenue.venue_id != item_id, UnloadVenue.is_deleted != True).first()
            if existing: raise HTTPException(status_code=400, detail="Venue with this name already exists")
            item.venue = new_name
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.venue_id, "name": item.venue}

    @Cinfo.delete("/unload-venues/{item_id}")
    async def delete_venue(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(UnloadVenue).filter(UnloadVenue.venue_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/consignees/{item_id}")
    async def update_consignee(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(Consignee).filter(Consignee.consignee_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        
        new_name = data.get("name")
        if new_name:
            existing = db.query(Consignee).filter(Consignee.consignee_name.ilike(new_name), Consignee.consignee_id != item_id, Consignee.is_deleted != True).first()
            if existing: raise HTTPException(status_code=400, detail="Consignee with this name already exists")
            item.consignee_name = new_name
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.consignee_id, "name": item.consignee_name}

    @Cinfo.delete("/consignees/{item_id}")
    async def delete_consignee(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(Consignee).filter(Consignee.consignee_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/materials/{item_id}")
    async def update_material(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(Material).filter(Material.Id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        
        new_name = data.get("name")
        if new_name:
            existing = db.query(Material).filter(Material.Name.ilike(new_name), Material.Id != item_id, Material.is_deleted != True).first()
            if existing: raise HTTPException(status_code=400, detail="Material with this name already exists")
            item.Name = new_name
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.Id, "name": item.Name}

    @Cinfo.delete("/materials/{item_id}")
    async def delete_material(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(Material).filter(Material.Id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/shipping-documents/{item_id}")
    async def update_shipping_doc(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(ShippingDocument).filter(ShippingDocument.doc_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        
        new_name = data.get("name")
        if new_name:
            existing = db.query(ShippingDocument).filter(ShippingDocument.doc_type.ilike(new_name), ShippingDocument.doc_id != item_id, ShippingDocument.is_deleted != True).first()
            if existing: raise HTTPException(status_code=400, detail="Shipping document with this name already exists")
            item.doc_type = new_name
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.doc_id, "name": item.doc_type}

    @Cinfo.delete("/shipping-documents/{item_id}")
    async def delete_shipping_doc(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(ShippingDocument).filter(ShippingDocument.doc_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/container-types/{item_id}")
    async def update_container_type(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(ContainerType).filter(ContainerType.type_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        
        new_name = data.get("name")
        if new_name:
            existing = db.query(ContainerType).filter(ContainerType.type.ilike(new_name), ContainerType.type_id != item_id, ContainerType.is_deleted != True).first()
            if existing: raise HTTPException(status_code=400, detail="Container type with this name already exists")
            item.type = new_name
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.type_id, "name": item.type}

    @Cinfo.delete("/container-types/{item_id}")
    async def delete_container_type(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(ContainerType).filter(ContainerType.type_id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/logistics-providers/{item_id}")
    @Cinfo.put("/logisticsProvider/{item_id}", deprecated=True)
    async def update_logistics_provider(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(LogisticsProvider).filter(LogisticsProvider.Id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        
        new_name = data.get("name")
        if new_name:
            existing = db.query(LogisticsProvider).filter(LogisticsProvider.Name.ilike(new_name), LogisticsProvider.Id != item_id, LogisticsProvider.is_deleted != True).first()
            if existing: raise HTTPException(status_code=400, detail="Logistics Provider with this name already exists")
            item.Name = new_name
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.Id, "name": item.Name}

    @Cinfo.delete("/logistics-providers/{item_id}")
    @Cinfo.delete("/logisticsProvider/{item_id}", deprecated=True)
    async def delete_logistics_provider(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(LogisticsProvider).filter(LogisticsProvider.Id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}

    @Cinfo.put("/order-statuses/{item_id}")
    async def update_order_status(self, item_id: int, request: Request, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = await request.json()
        item = db.query(OrderStatus).filter(OrderStatus.id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        
        new_name = data.get("name")
        if new_name:
            existing = db.query(OrderStatus).filter(OrderStatus.name.ilike(new_name), OrderStatus.id != item_id, OrderStatus.is_deleted != True).first()
            if existing: raise HTTPException(status_code=400, detail="Order status with this name already exists")
            item.name = new_name
        if "code" in data:
            item.code = data["code"]
        if "sequence_order" in data:
            item.sequence_order = data["sequence_order"]
        if "progress" in data:
            item.progress = data["progress"]
        if "color" in data:
            item.color = data["color"]
        
        item.updated_by = current_user.id
        db.commit()
        return {"id": item.id, "name": item.name, "code": item.code}

    @Cinfo.delete("/order-statuses/{item_id}")
    async def delete_order_status(self, item_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        item = db.query(OrderStatus).filter(OrderStatus.id == item_id).first()
        if not item: raise HTTPException(status_code=404, detail="Not found")
        item.is_deleted = True
        item.deleted_at = datetime.utcnow()
        item.deleted_by = current_user.id
        db.commit()
        return {"success": True}
    
    @Cinfo.get("/getDashboardInfo")
    async def getContainerInfo(
        self,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context)
    ):
        base_query = db.query(ContainerDetails).filter(ContainerDetails.is_deleted == False)
        base_query = apply_org_filter(base_query, ContainerDetails, org_context)

        total_all = base_query.count()
        total_active = base_query.filter(ContainerDetails.status != 4).count()
        gate_pass = base_query.filter(ContainerDetails.status == 3).count()
        on_port = base_query.filter(ContainerDetails.status == 2).count()
        in_transit = base_query.filter(ContainerDetails.status == 1).count()
        arrived = base_query.filter(ContainerDetails.status == 6).count()
        emptied_count = base_query.filter(ContainerDetails.status == 7).count()

        arrived_at_location = (
            base_query.filter(ContainerDetails.status == 6)
            .outerjoin(UnloadVenue, ContainerDetails.emptied_at == UnloadVenue.venue_id)
            .with_entities(ContainerDetails.container_no, UnloadVenue.venue)
            .all()
        )

        return {
            "TotalContainer": total_active,
            "TotalAllContainers": total_all,
            "TotalActive": total_active,
            "GatePass": gate_pass,
            "OnPort": on_port,
            "InTransit": in_transit,
            "Arrived": arrived,
            "Emptied": emptied_count,
            "ArrivedAtLocation": [{"container_no": row[0], "location": row[1]} for row in arrived_at_location]
        }
    
    @Cinfo.get("/getContainerCountsByMonth/{year}")
    async def get_container_counts_by_month(
        self,
        year: int,
        db: Session = Depends(get_db),
        org_context: OrgContext = Depends(get_org_context)
    ):
        query = (
            db.query(
                extract('month', BillOfLanding.ArrivalDate).label('month'),
                func.count(ContainerDetails.Container_ID).label('count')
            )
            .outerjoin(BillOfLanding, BillOfLanding.BillOfLanding == ContainerDetails.BillOfLanding)
            .filter(
                ContainerDetails.is_deleted == False,
                extract('year', BillOfLanding.ArrivalDate) == year
            )
        )
        query = apply_org_filter(query, ContainerDetails, org_context)
        results = (
            query
            .group_by(extract('month', BillOfLanding.ArrivalDate))
            .order_by('month')
            .all()
        )

        month_counts = {int(month): count for month, count in results if month is not None}
        full_year_counts = [month_counts.get(m, 0) for m in range(1, 13)]
        return full_year_counts
    
