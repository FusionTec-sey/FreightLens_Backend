
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends, HTTPException,  Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
# from sqlalchemy import func, desc, case
from Model.db import get_db
from Model import BillOfLanding as BOfL
from Model import ContainerDetails, Supplier, LogisticsProvider,  Vessal, BillOfLanding, Consignee, ShippingDocument, ContainerDocs, ReportDetails, DamageProduct, ReportImage
from Schema import   BillOfLandingInSchema, BillOfLandingWithContainersSchema, ContainerDetailsSchemaWithBl, BillOfLandingUpdateOnlySchema, BillOfLandingListResponse
from Utils import *
# from auth.dependencies import get_current_user
from fastapi import  Depends, Body
# from fastapi.responses import FileResponse, StreamingResponse
# import json
# import mimetypes
from typing import List, Optional
# import os 
from datetime import datetime
# from io import BytesIO

BillOfLandingRouter = InferringRouter()

def get_bls_with_in_transit_containers(db: Session):
    result = (
        db.query(BillOfLanding)
        .join(BillOfLanding.containers)  # assuming .containers is the relationship
        .filter(ContainerDetails.state == "In Transit")
        .distinct()
        .all()
    )
    return result

@cbv(BillOfLandingRouter)
class BillOfLandingAPI:
    
    @BillOfLandingRouter.post("/bills-of-lading")
    async def addBl(
        self,
        data: BillOfLandingInSchema = Body(...),
        db: Session = Depends(get_db)
        ):
        # 1. Create Bill of Landing
        new_bl = BillOfLanding(
            BillOfLanding=data.BillOfLanding,
            Consignee=data.Consignee,
            Vessel=data.Vessel,
            ArrivalDate=data.ArrivalDate,
            Doc=data.Doc,
            Supplier=data.Supplier,
            Provider=data.Provider
        )
        db.add(new_bl)
        db.flush()  # Gets persisted BL value for FK reference

        # 2. Create new containers associated with this BL
        for container in data.new_containers:
            new_container = ContainerDetails(
                container_no=container.container_no,
                type=container.type,
                in_bound=container.in_bound,
                emptied_at=container.emptied_at,
                empty_date=container.empty_date,
                out_bound=container.out_bound,
                unloaded_at_port=container.unloaded_at_port,
                note=container.note,
                status=container.status if container.status is not None else data.status,
                tax=container.tax,
                PONo=container.PONo,
                FreeDays=container.FreeDays if hasattr(container, 'FreeDays') and container.FreeDays is not None else data.FreeDays,
                BillOfLanding=data.BillOfLanding,
            )
            db.add(new_container)

        db.commit()
        return {"msg": "BL and containers created successfully"}
    
    @BillOfLandingRouter.get("/bills-of-lading", response_model=BillOfLandingListResponse)
    async def get_bls(self,
        BillOfLanding: Optional[str] = Query(None),
        ConsigneeName: Optional[str] = Query(None),
        Vessel: Optional[str] = Query(None),
        SupplierName: Optional[str] = Query(None),
        Provider: Optional[str] = Query(None),
        ArrivalDate: Optional[datetime] = Query(None),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, le=100),
        sort_by_arrival: bool = Query(True, description="Sort by ArrivalDate descending if True"),
        db: Session = Depends(get_db),
        ):
        try:
            query = (
                db.query(BOfL)
                .options(
                    joinedload(BOfL.consignee_rel),
                    joinedload(BOfL.vessel_rel),
                    joinedload(BOfL.supplier_rel),
                    joinedload(BOfL.provider_rel),
                    joinedload(BOfL.doc_rel)
                )
            )

            # Apply filters
            if BillOfLanding:
                query = query.filter(BOfL.BillOfLanding == BillOfLanding)

            if ConsigneeName:
                query = query.join(BOfL.consignee_rel).filter(
                    Consignee.consignee_name.ilike(f"%{ConsigneeName}%")
                )

            if Vessel:
                query = query.join(BOfL.vessel_rel).filter(
                    Vessal.name.ilike(f"%{Vessel}%")
                )

            if SupplierName:
                query = query.join(BOfL.supplier_rel).filter(
                    Supplier.name.ilike(f"%{SupplierName}%")
                )

            if Provider:
                query = query.join(BOfL.provider_rel).filter(
                    LogisticsProvider.name.ilike(f"%{Provider}%")
                )

            if ArrivalDate:
                query = query.filter(BOfL.ArrivalDate == ArrivalDate)

            # Optional sorting
            if sort_by_arrival:
                query = query.order_by(BOfL.ArrivalDate.desc())
            else:
                query = query.order_by(BOfL.ArrivalDate.asc())
                
            total_count = query.count()
            # Apply pagination
            bl_results = query.offset(offset).limit(limit).all()

            # Construct response with nested containers
            response = []
            for bl in bl_results:
                containers = (
                    db.query(ContainerDetails)
                    .filter(ContainerDetails.BillOfLanding == bl.BillOfLanding)
                    .options(
                        joinedload(ContainerDetails.status_rel),
                        joinedload(ContainerDetails.type_rel),
                        joinedload(ContainerDetails.emptied_at_rel),
                        joinedload(ContainerDetails.documents),
                        joinedload(ContainerDetails.materials)
                    )
                    .all()
                )

                bl_schema = BillOfLandingWithContainersSchema.from_orm_flat(bl)
                bl_schema.containers = [ContainerDetailsSchemaWithBl.from_orm_flat(c) for c in containers]
                response.append(bl_schema)

            return {
                "total_count": total_count,
                "data": response
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching Bill of Lading data: {str(e)}")


    @BillOfLandingRouter.patch("/bills-of-lading/{bl_number}")
    async def update_bl(self,
        bl_number: str,
        data: BillOfLandingUpdateOnlySchema = Body(...),
        db: Session = Depends(get_db)
        ):
        
        # 1. Fetch the existing Bill of Landing
        bl = db.query(BillOfLanding).filter_by(BillOfLanding=bl_number).first()
        if not bl:
            raise HTTPException(status_code=404, detail="Bill of Landing not found")

        # 2. Handle Cascading Updates with Conflict Resolution
        update_data = data.dict(exclude_unset=True)
        containers = db.query(ContainerDetails).filter_by(BillOfLanding=bl_number).all()

        # ── FreeDays cascade logic ──────────────────────────────────────────
        if 'FreeDays' in update_data and update_data['FreeDays'] != bl.FreeDays:
            for child in containers:
                # If child has a custom value (different from BoL current), block BoL update
                if child.FreeDays is not None and bl.FreeDays is not None and child.FreeDays != bl.FreeDays:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Cannot update Bill of Lading FreeDays: Container '{child.container_no}' has a custom value. Please update individual containers instead."
                    )
            # Apply to all children if no conflicts
            for child in containers:
                child.FreeDays = update_data['FreeDays']

        # ── Status cascade logic ────────────────────────────────────────────
        if 'status' in update_data and update_data['status'] != bl.status:
            for child in containers:
                # If child has a custom status (different from BoL current), block BoL update
                if child.status is not None and bl.status is not None and child.status != bl.status:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Cannot update Bill of Lading status: Container '{child.container_no}' has a custom status. Please update individual containers instead."
                    )
            # Apply to all children if no conflicts
            for child in containers:
                child.status = update_data['status']

        # 3. Update the Bill of Landing record itself
        for key, value in update_data.items():
            setattr(bl, key, value)

        db.commit()
        return {"msg": "Bill of Landing and associated containers updated successfully"}

    @BillOfLandingRouter.delete("/bills-of-lading/{bl_code}")
    async def delete_bill_of_lading(self, 
        bl_code: str,
        db: Session = Depends(get_db),
        # current_user: dict = Depends(get_current_user),
        ):
        # Step 1: Fetch the Bill of Lading
        bl = db.query(BillOfLanding).filter(BillOfLanding.BillOfLanding == bl_code).first()
        if not bl:
            raise HTTPException(status_code=404, detail="Bill of Lading not found")

        # Step 2: Fetch all containers linked to this BL
        containers = db.query(ContainerDetails).filter(ContainerDetails.BillOfLanding == bl_code).all()

        for container in containers:
            container_id = container.Container_ID

            # 2.1: Report IDs
            report_ids = db.query(ReportDetails.report_id).filter(
                ReportDetails.container_id == container_id
            ).all()
            report_ids = [r[0] for r in report_ids]

            # 2.2: Damage product IDs
            dmgp_ids = db.query(DamageProduct.id).filter(
                DamageProduct.report_id.in_(report_ids)
            ).all()
            dmgp_ids = [d[0] for d in dmgp_ids]

            # 2.3: Delete report images
            if dmgp_ids:
                db.query(ReportImage).filter(
                    ReportImage.DMGP_id.in_(dmgp_ids)
                ).delete(synchronize_session=False)

            # 2.4: Delete damage products
            if report_ids:
                db.query(DamageProduct).filter(
                    DamageProduct.report_id.in_(report_ids)
                ).delete(synchronize_session=False)

            # 2.5: Delete reports
            db.query(ReportDetails).filter(
                ReportDetails.container_id == container_id
            ).delete(synchronize_session=False)

            # 2.6: Delete container documents
            db.query(ContainerDocs).filter(
                ContainerDocs.container_id == container_id
            ).delete(synchronize_session=False)

            # 2.7: Clear many-to-many material links
            container.materials.clear()

            # 2.8: Delete container itself
            db.delete(container)

        # Step 3: Delete the Bill of Lading
        db.delete(bl)

        # Step 4: Commit all deletions
        db.commit()

        return {"message": f"Bill of Lading '{bl_code}' and all associated containers deleted successfully"}
