
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends, HTTPException,  Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
# from sqlalchemy import func, desc, case
from Model.db import get_db
from Model import BillOfLanding as BOfL
from Model import ContainerDetails, Supplier, LogisticsProvider,  Vessal, BillOfLanding, Consignee, ShippingDocument, ContainerDocs, ReportDetails, DamageProduct, ReportImage, Material, ContainerType, UnloadVenue, Status
from Schema import   BillOfLandingInSchema, BillOfLandingWithContainersSchema, ContainerDetailsSchemaWithBl, BillOfLandingUpdateOnlySchema, BillOfLandingListResponse
from Utils import *
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import can_view_bl_user, can_view_supplier_user
from Model.Credentials.users import User
from Utils.org_filter import OrgContext, apply_org_filter, apply_shared_or_org_filter
from fastapi import  Depends, Body, status

# from fastapi.responses import FileResponse, StreamingResponse
# import asyncio
from datetime import datetime
import json
import mimetypes
from typing import List, Optional, Any, Union
# import os 
from datetime import datetime
# from io import BytesIO

BillOfLandingRouter = InferringRouter()

# Helpers to resolve reference data dynamically
def resolve_vessel(db: Session, entry: Any, current_user_id: int) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    vessel = db.query(Vessal).filter(Vessal.VessalNo.ilike(val), Vessal.is_deleted != True).first()
    if not vessel:
        vessel = Vessal(VessalNo=val, created_by=current_user_id, updated_by=current_user_id)
        db.add(vessel)
        db.flush()
    return vessel.id

def resolve_supplier(db: Session, entry: Any, current_user_id: int, org_context: OrgContext) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    supplier_query = db.query(Supplier).filter(Supplier.name.ilike(val), Supplier.is_deleted != True)
    supplier = apply_shared_or_org_filter(supplier_query, Supplier, org_context).first()
    if not supplier:
        supplier = Supplier(name=val, org_id=org_context.org_id, is_shared=False, created_by=current_user_id, updated_by=current_user_id)
        db.add(supplier)
        db.flush()
    return supplier.supplier_id

def resolve_provider(db: Session, entry: Any, current_user_id: int) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    provider = db.query(LogisticsProvider).filter(LogisticsProvider.Name.ilike(val), LogisticsProvider.is_deleted != True).first()
    if not provider:
        provider = LogisticsProvider(Name=val, created_by=current_user_id, updated_by=current_user_id)
        db.add(provider)
        db.flush()
    return provider.Id

def resolve_doc(db: Session, entry: Any, current_user_id: int) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    doc = db.query(ShippingDocument).filter(ShippingDocument.doc_type.ilike(val), ShippingDocument.is_deleted != True).first()
    if not doc:
        doc = ShippingDocument(doc_type=val, created_by=current_user_id, updated_by=current_user_id)
        db.add(doc)
        db.flush()
    return doc.doc_id

def resolve_consignee(db: Session, entry: Any, current_user_id: int) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    consignee = db.query(Consignee).filter(Consignee.consignee_name.ilike(val), Consignee.is_deleted != True).first()
    if not consignee:
        consignee = Consignee(consignee_name=val, created_by=current_user_id, updated_by=current_user_id)
        db.add(consignee)
        db.flush()
    return consignee.consignee_id

def resolve_container_type(db: Session, entry: Any, current_user_id: int) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    c_type = db.query(ContainerType).filter(ContainerType.type.ilike(val), ContainerType.is_deleted != True).first()
    if not c_type:
        c_type = ContainerType(type=val, created_by=current_user_id, updated_by=current_user_id)
        db.add(c_type)
        db.flush()
    return c_type.type_id

def resolve_unload_venue(db: Session, entry: Any, current_user_id: int) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    venue = db.query(UnloadVenue).filter(UnloadVenue.venue.ilike(val), UnloadVenue.is_deleted != True).first()
    if not venue:
        venue = UnloadVenue(venue=val, created_by=current_user_id, updated_by=current_user_id)
        db.add(venue)
        db.flush()
    return venue.venue_id

def resolve_status(db: Session, entry: Any) -> Any:
    if entry is None or entry == "": return None
    if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()): return int(entry)
    val = str(entry).strip()
    status = db.query(Status).filter(Status.name.ilike(val), Status.is_deleted != True).first()
    if status:
        return status.status_id
    return None

def resolve_materials(db: Session, materials_list: List[Union[int, str]], current_user_id: int) -> List[Material]:
    resolved = []
    for entry in materials_list:
        if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()):
            material = db.query(Material).filter_by(Id=int(entry)).first()
            if material:
                resolved.append(material)
        elif isinstance(entry, str) and entry.strip():
            material_name = entry.strip()
            material = db.query(Material).filter(Material.Name.ilike(material_name), Material.is_deleted != True).first()
            if not material:
                material = Material(Name=material_name, created_by=current_user_id, updated_by=current_user_id)
                db.add(material)
                db.flush()
            resolved.append(material)
    return resolved

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
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        org_context: OrgContext = Depends(get_org_context)
        ):
        if not can_view_bl_user(current_user, org_context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: You do not have permission to manage Bills of Lading."
            )
        # 1. Create Bill of Landing
        resolved_consignee_id = resolve_consignee(db, data.Consignee, current_user.id)
        resolved_vessel_id = resolve_vessel(db, data.Vessel, current_user.id)
        resolved_doc_id = resolve_doc(db, data.Doc, current_user.id)
        resolved_supplier_id = resolve_supplier(db, data.Supplier, current_user.id, org_context)
        resolved_provider_id = resolve_provider(db, data.Provider, current_user.id)
        resolved_status_id = resolve_status(db, data.status)

        existing_query = db.query(BillOfLanding).filter(BillOfLanding.BillOfLanding == data.BillOfLanding)
        existing_bl = apply_org_filter(existing_query, BillOfLanding, org_context).first()
        if existing_bl:
            if existing_bl.is_deleted:
                existing_bl.is_deleted = False
                existing_bl.deleted_at = None
                existing_bl.deleted_by = None
                existing_bl.Consignee = resolved_consignee_id
                existing_bl.Vessel = resolved_vessel_id
                existing_bl.ArrivalDate = data.ArrivalDate
                existing_bl.Doc = resolved_doc_id
                existing_bl.Supplier = resolved_supplier_id
                existing_bl.Provider = resolved_provider_id
                existing_bl.FreeDays = data.FreeDays
                existing_bl.status = resolved_status_id
                existing_bl.updated_by = current_user.id
                existing_bl.org_id = org_context.org_id
                new_bl = existing_bl
            else:
                raise HTTPException(status_code=409, detail="Bill of Lading already exists")
        else:
            new_bl = BillOfLanding(
                org_id=org_context.org_id,
                BillOfLanding=data.BillOfLanding,
                Consignee=resolved_consignee_id,
                Vessel=resolved_vessel_id,
                ArrivalDate=data.ArrivalDate,
                Doc=resolved_doc_id,
                Supplier=resolved_supplier_id,
                Provider=resolved_provider_id,
                FreeDays=data.FreeDays,
                status=resolved_status_id,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            db.add(new_bl)
        db.flush()  # Gets persisted BL value for FK reference

        # 2. Create new containers associated with this BL
        for container in data.new_containers:
            resolved_type_id = resolve_container_type(db, container.type, current_user.id)
            resolved_venue_id = resolve_unload_venue(db, container.emptied_at, current_user.id)
            
            # Determine container status
            container_status_input = container.status if container.status is not None else data.status
            resolved_container_status_id = resolve_status(db, container_status_input)

            new_container = ContainerDetails(
                org_id=org_context.org_id,
                container_no=container.container_no,
                type=resolved_type_id,
                in_bound=container.in_bound,
                emptied_at=resolved_venue_id,
                empty_date=container.empty_date,
                out_bound=container.out_bound,
                unloaded_at_port=container.unloaded_at_port,
                note=container.note,
                status=resolved_container_status_id,
                tax=container.tax,
                PONo=container.PONo,
                FreeDays=container.FreeDays if hasattr(container, 'FreeDays') and container.FreeDays is not None else data.FreeDays,
                BillOfLanding=data.BillOfLanding,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            db.add(new_container)
            
            # Resolve materials and link to container
            if getattr(container, "materials", None):
                resolved_m = resolve_materials(db, container.materials, current_user.id)
                new_container.materials.extend(resolved_m)

        db.commit()
        return {"msg": "BL and containers created successfully"}
    
    @BillOfLandingRouter.get("/bills-of-lading", response_model=BillOfLandingListResponse)
    @BillOfLandingRouter.get("/bill-of-landing", response_model=BillOfLandingListResponse)
    async def get_bls(self,
        BillOfLanding: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        ConsigneeName: Optional[str] = Query(None),
        Vessel: Optional[str] = Query(None),
        SupplierName: Optional[str] = Query(None),
        Provider: Optional[str] = Query(None),
        ArrivalDate: Optional[datetime] = Query(None),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, le=100),
        sort_by_arrival: bool = Query(True, description="Sort by ArrivalDate descending if True"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        org_context: OrgContext = Depends(get_org_context)
        ):
        if not can_view_bl_user(current_user, org_context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: You do not have permission to view Bills of Lading."
            )
        can_see_supplier = can_view_supplier_user(current_user, org_context)
        try:
            query = db.query(BOfL).filter(BOfL.is_deleted == False)
            query = apply_org_filter(query, BOfL, org_context)
            query = query.options(
                joinedload(BOfL.consignee_rel),
                joinedload(BOfL.vessel_rel),
                joinedload(BOfL.supplier_rel),
                joinedload(BOfL.provider_rel),
                joinedload(BOfL.doc_rel),
                joinedload(BOfL.created_by_user),
                joinedload(BOfL.updated_by_user)
            )

            # Apply filters
            if BillOfLanding:
                query = query.filter(BOfL.BillOfLanding.ilike(f"%{BillOfLanding.strip()}%"))

            if search and search.strip():
                term = f"%{search.strip()}%"
                query = query.outerjoin(BOfL.consignee_rel).outerjoin(BOfL.vessel_rel).outerjoin(BOfL.supplier_rel).outerjoin(BOfL.provider_rel).filter(
                    or_(
                        BOfL.BillOfLanding.ilike(term),
                        Consignee.consignee_name.ilike(term),
                        Vessal.name.ilike(term),
                        Supplier.name.ilike(term),
                        LogisticsProvider.name.ilike(term)
                    )
                )

            if ConsigneeName:
                query = query.join(BOfL.consignee_rel).filter(
                    Consignee.consignee_name.ilike(f"%{ConsigneeName}%")
                )

            if Vessel:
                query = query.join(BOfL.vessel_rel).filter(
                    Vessal.name.ilike(f"%{Vessel}%")
                )

            if SupplierName:
                if not can_see_supplier:
                    query = query.filter(1 == 0)
                else:
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
                if not can_see_supplier:
                    bl_schema.supplier_name = None
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
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        org_context: OrgContext = Depends(get_org_context)
        ):
        if not can_view_bl_user(current_user, org_context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: You do not have permission to modify Bills of Lading."
            )
        
        # 1. Fetch the existing Bill of Landing
        bl = db.query(BillOfLanding).filter_by(BillOfLanding=bl_number).first()
        if not bl:
            raise HTTPException(status_code=404, detail="Bill of Landing not found")

        # 2. Handle Cascading Updates with Conflict Resolution
        update_data = data.dict(exclude_unset=True)
        
        # Resolve BL reference fields dynamically before conflict logic
        if "Consignee" in update_data and update_data["Consignee"] is not None:
            update_data["Consignee"] = resolve_consignee(db, update_data["Consignee"], current_user.id)
        if "Vessel" in update_data and update_data["Vessel"] is not None:
            update_data["Vessel"] = resolve_vessel(db, update_data["Vessel"], current_user.id)
        if "Supplier" in update_data and update_data["Supplier"] is not None:
            update_data["Supplier"] = resolve_supplier(db, update_data["Supplier"], current_user.id, org_context)
        if "Provider" in update_data and update_data["Provider"] is not None:
            update_data["Provider"] = resolve_provider(db, update_data["Provider"], current_user.id)
        if "Doc" in update_data and update_data["Doc"] is not None:
            update_data["Doc"] = resolve_doc(db, update_data["Doc"], current_user.id)
        if "status" in update_data and update_data["status"] is not None:
            update_data["status"] = resolve_status(db, update_data["status"])

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
        bl.updated_by = current_user.id

        db.commit()
        return {"msg": "Bill of Landing and associated containers updated successfully"}

    @BillOfLandingRouter.delete("/bills-of-lading/{bl_code}")
    async def delete_bill_of_lading(self, 
        bl_code: str,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        org_context: OrgContext = Depends(get_org_context)
        ):
        if not can_view_bl_user(current_user, org_context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: You do not have permission to delete Bills of Lading."
            )
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
            now = datetime.utcnow()
            if dmgp_ids:
                db.query(ReportImage).filter(
                    ReportImage.DMGP_id.in_(dmgp_ids)
                ).update({"is_deleted": True, "deleted_by": current_user.id, "deleted_at": now}, synchronize_session=False)

            # 2.4: Delete damage products
            if report_ids:
                db.query(DamageProduct).filter(
                    DamageProduct.report_id.in_(report_ids)
                ).update({"is_deleted": True, "deleted_by": current_user.id, "deleted_at": now}, synchronize_session=False)

            # 2.5: Delete reports
            db.query(ReportDetails).filter(
                ReportDetails.container_id == container_id
            ).update({"is_deleted": True, "deleted_by": current_user.id, "deleted_at": now}, synchronize_session=False)

            # 2.6: Delete container documents
            db.query(ContainerDocs).filter(
                ContainerDocs.container_id == container_id
            ).update({"is_deleted": True, "deleted_by": current_user.id, "deleted_at": now}, synchronize_session=False)

            # 2.7: Clear many-to-many material links
            container.materials.clear()

            # 2.8: Soft delete container
            container.is_deleted = True
            container.deleted_by = current_user.id
            container.deleted_at = datetime.utcnow()

        # Step 3: Soft delete the Bill of Lading
        bl.is_deleted = True
        bl.deleted_by = current_user.id
        bl.deleted_at = datetime.utcnow()

        # Step 4: Commit all deletions
        db.commit()

        return {"message": f"Bill of Lading '{bl_code}' and all associated containers deleted successfully"}
