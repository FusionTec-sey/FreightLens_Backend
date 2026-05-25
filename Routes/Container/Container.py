
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends, Form, File, UploadFile, Query
from sqlalchemy.orm import Session, joinedload, selectinload
# from sqlalchemy.sql import nullsfirst, nullslast
from typing import List, Optional
from pydantic import ValidationError
from sqlalchemy import func, desc, case
from Model.db import get_db
from Model import ContainerDetails, Supplier, UnloadVenue, Status, Vessal, ContainerDocs, DocType, ReportDetails, DamageProduct, ReportImage, BillOfLanding, Material
from Schema import ContainerDetailsSchema, ContainerUpdateSchema, ContainerCreateSchema, ContainerListResponse, ReportSchema
from Utils import *
from auth.dependencies import get_current_user
from fastapi import  Depends, HTTPException,  Form, UploadFile, File, Request
from fastapi.responses import FileResponse, StreamingResponse
import json
import mimetypes
from typing import List, Optional, Dict, Any
import os 
from datetime import datetime, date
from io import BytesIO
from dateutil.parser import parse as parse_date  # install python-dateutil if needed
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

ContainerRouter = InferringRouter()

def parse_optional_json(field: Optional[str], field_name: str):
    if field is None or field == "":
        return None
    try:
        return json.loads(field)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid JSON in field '{field_name}': {e}")

def parse_date_optional(field: Optional[str]):
    
    if not field :
        return None
    try:
        return parse_date(field)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid date/time format: {field}")

async def parse_update_form(request: Request) -> ContainerUpdateSchema:
    form = await request.form()
    data = {}

    # Fields expected as ISO date/datetime strings
    datetime_or_date_fields = {"in_bound", "empty_date", "out_bound", "unloaded_at_port"}

    # Fields expected as ints
    int_fields = {"tax", "status", "type", "emptied_at", "FreeDays"}

    # Fields expected as ints in bill_of_landing.*
    bl_int_fields = {"Consignee", "Vessel", "Supplier", "Provider", "Doc", "FreeDays", "status"}

    for key, value in form.items():
        if "." in key or key in {"materials", "remove_doc_ids"}:
            continue  # skip nested or list fields

        if value == "":
            data[key] = None
        elif key in datetime_or_date_fields:
            data[key] = parse_date_optional(value)
        elif key in int_fields:
            try:
                data[key] = int(value)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"{key} must be an integer")
        else:
            data[key] = value

    # bill_of_landing.* nested fields
    bill_data = {}
    for key, value in form.items():
        if key.startswith("bill_of_landing."):
            subkey = key[len("bill_of_landing.") :]
            if value == "":
                bill_data[subkey] = None
            elif subkey in bl_int_fields:
                try:
                    bill_data[subkey] = int(value)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"bill_of_landing.{subkey} must be an integer")
            else:
                bill_data[subkey] = value
    if bill_data:
        data["bill_of_landing"] = bill_data

    # materials=MaterialId[] → List[MaterialEntrySchema]
    material_ids = form.getlist("materials")
    if material_ids:
        try:
            data["materials"] = [int(mid) for mid in material_ids if mid]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid material ID")

    # remove_doc_ids[]=int → List[int] (optional if field enabled)
    remove_doc_ids = form.getlist("remove_doc_ids")
    if remove_doc_ids:
        try:
            data["remove_doc_ids"] = [int(doc_id) for doc_id in remove_doc_ids if doc_id]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid document ID")

    # Validate with schema
    try:
        return ContainerUpdateSchema(**data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

async def parse_create_form(request: Request) -> ContainerCreateSchema:
    form = await request.form()
    data = {}

    # Top-level container fields (non-nested)
    for key, value in form.items():
        if "." not in key and key != "materials":
            data[key] = value

    # Nested bill_of_landing.* fields
    bill_data = {}
    for key, value in form.items():
        if key.startswith("bill_of_landing."):
            nested_key = key.replace("bill_of_landing.", "")
            bill_data[nested_key] = value
    if bill_data:
        data["bill_of_landing"] = bill_data

    # Parse materials as list of ints
    materials = form.getlist("materials")
    if materials:
        try:
            data["materials"] = [int(mid) for mid in materials if mid]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid material ID in materials list")

    # Validate and return the schema
    try:
        return ContainerCreateSchema(**data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

@cbv(ContainerRouter)
class ContainerAPI:

    @ContainerRouter.post("/containers")
    async def create_container(self,
        create_data: ContainerCreateSchema = Depends(parse_create_form),
        new_docs: List[UploadFile] = File([]),
        inbound_images: Optional[List[UploadFile]] = File([]),
        empty_images: Optional[List[UploadFile]] = File([]),
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
        ):
        # 🔒 Manual required field checks
        if not create_data.container_no:
            raise HTTPException(status_code=400, detail="Container number is required.")
        
        if not create_data.bill_of_landing or not create_data.bill_of_landing.BillOfLanding:
            raise HTTPException(status_code=400, detail="Bill of Landing is required.")

        # 📦 Extract BL data
        bl_data = create_data.bill_of_landing.dict(exclude_unset=True)
        bl_number = bl_data.get("BillOfLanding")

        # 🔄 Create or update Bill of Landing
        existing_bl = db.query(BillOfLanding).filter_by(BillOfLanding=bl_number).first()
        if existing_bl:
            for key, value in bl_data.items():
                setattr(existing_bl, key, value)
            existing_bl.updated_by = current_user.id
        else:
            bl_data["created_by"] = current_user.id
            bl_data["updated_by"] = current_user.id
            new_bl = BillOfLanding(**bl_data)
            db.add(new_bl)

        # 📦 Create Container and link to Bill of Landing
        container_data = create_data.dict(exclude_unset=True, exclude={"materials", "bill_of_landing"})
        
        # 🔗 Inherit FreeDays and status from BoL (provided or existing) if not explicitly set on container
        incoming_fd = bl_data.get("FreeDays")
        current_fd = incoming_fd if incoming_fd is not None else (existing_bl.FreeDays if existing_bl else None)
        if "FreeDays" not in container_data and current_fd is not None:
            container_data["FreeDays"] = current_fd

        incoming_st = bl_data.get("status")
        current_st = incoming_st if incoming_st is not None else (existing_bl.status if existing_bl else None)
        if "status" not in container_data and current_st is not None:
            container_data["status"] = current_st
        
        container = ContainerDetails(
            **container_data,
            BillOfLanding=bl_number,  # ✅ Set FK
            created_by=current_user.id,
            updated_by=current_user.id
        )
        db.add(container)
        db.flush()  # Get container.Container_ID for FK refs

        # 🔁 Add materials (many-to-many)
        if create_data.materials:
            for entry in create_data.materials:
                material = db.query(Material).filter_by(Id=entry).first()
                if material:
                    container.materials.append(material)

        # 📁 Upload and save document paths
        shipping_paths = save_uploaded_files(new_docs, "Shipping")
        for path in shipping_paths:
            db.add(ContainerDocs(container_id=container.Container_ID, path=path, Type=DocType.D))

        inbound_paths = save_uploaded_files(inbound_images, "InBoundContainer")
        for path in inbound_paths:
            db.add(ContainerDocs(container_id=container.Container_ID, path=path, Type=DocType.AD))

        empty_paths = save_uploaded_files(empty_images, "EmptyContainer")
        for path in empty_paths:
            db.add(ContainerDocs(container_id=container.Container_ID, path=path, Type=DocType.ED))

        # 💾 Finalize transaction
        db.commit()

        return {"message": "Container created successfully"}
    
    @ContainerRouter.get("/containers", response_model=ContainerListResponse)
    async def get_container_details_by_id(self,
        container_id: Optional[int] = Query(None),
        container_no: Optional[str] = Query(None),
        status: Optional[int] = Query(None),
        status_order: Optional[List[int]] = Query(None),
        excStatus: Optional[int] = Query(None),
        from_date: Optional[date] = Query(None),
        to_date: Optional[date] = Query(None),
        material: Optional[str] = Query(None),
        order_by_arrival: Optional[bool] = Query(True, description="Sort by ArrivalDate (True=descending, False=ascending)"),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, le=100),
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)
        ):

            base_query = (
                db.query(ContainerDetails)
                .filter(ContainerDetails.is_deleted == False)
                .outerjoin(BillOfLanding, ContainerDetails.BillOfLanding == BillOfLanding.BillOfLanding)
                .options(
                    # To-one relationships: safe to joinedload (no collection, no subquery-LIMIT issue)
                    joinedload(ContainerDetails.bill_of_landing)
                    .joinedload(BillOfLanding.consignee_rel),
                    joinedload(ContainerDetails.bill_of_landing)
                    .joinedload(BillOfLanding.vessel_rel),
                    joinedload(ContainerDetails.bill_of_landing)
                    .joinedload(BillOfLanding.supplier_rel),
                    joinedload(ContainerDetails.bill_of_landing)
                    .joinedload(BillOfLanding.provider_rel),
                    joinedload(ContainerDetails.bill_of_landing)
                    .joinedload(BillOfLanding.doc_rel),
                    joinedload(ContainerDetails.status_rel),
                    joinedload(ContainerDetails.type_rel),
                    joinedload(ContainerDetails.emptied_at_rel),
                    joinedload(ContainerDetails.created_by_user),
                    joinedload(ContainerDetails.updated_by_user),
                    # Many-to-many collection: MUST use selectinload to avoid
                    # MySQL's rejection of LIMIT inside a subquery (sqlalche.me/e/20/f405)
                    selectinload(ContainerDetails.materials)
                )
            )

            # Apply filters
            if material:
                base_query = base_query.join(ContainerDetails.materials)
                base_query = base_query.filter(Material.Name.ilike(f"%{material}%"))
            if container_id:
                base_query = base_query.filter(ContainerDetails.Container_ID == container_id)
            if container_no:
                base_query = base_query.filter(ContainerDetails.container_no.ilike(f"%{container_no}%"))
                
            if status is not None:
                base_query = base_query.filter(ContainerDetails.status == status)
            if from_date and to_date:
                base_query = base_query.filter(BillOfLanding.ArrivalDate.between(from_date, to_date))
            elif from_date:
                base_query = base_query.filter(BillOfLanding.ArrivalDate >= from_date)
            elif to_date:
                base_query = base_query.filter(BillOfLanding.ArrivalDate <= to_date)
            if excStatus:
                base_query = base_query.filter(ContainerDetails.status != excStatus)
            
            if status_order:
                status_order_case = case(
                    *[(sid, i) for i, sid in enumerate(status_order)],
                    value=ContainerDetails.status,
                    else_=len(status_order)
                )

                if order_by_arrival is not None:
                    if order_by_arrival:
                        base_query = base_query.order_by(
                            status_order_case,
                            case((BillOfLanding.ArrivalDate == None, 1), else_=0),
                            BillOfLanding.ArrivalDate.desc()
                        )
                    else:
                        base_query = base_query.order_by(
                            status_order_case,
                            case((BillOfLanding.ArrivalDate == None, 0), else_=1),
                            BillOfLanding.ArrivalDate.asc()
                        )
                else:
                    # Just order by status if no date ordering is specified
                    base_query = base_query.order_by(status_order_case)
            else:
                # fallback: only date sorting if no status_order
                if order_by_arrival is not None:
                    if order_by_arrival:
                        base_query = base_query.order_by(
                            case((BillOfLanding.ArrivalDate == None, 1), else_=0),
                            BillOfLanding.ArrivalDate.desc()
                        )
                    else:
                        base_query = base_query.order_by(
                            case((BillOfLanding.ArrivalDate == None, 0), else_=1),
                            BillOfLanding.ArrivalDate.asc()
                        )
   
                    
            # Get total count before pagination
            total_count = base_query.count()

            # Apply pagination
            results = base_query.offset(offset).limit(limit).all()

            # Convert to serializable format
            serialized_data = []
            for container in results:
                container_dict = jsonable_encoder(ContainerDetailsSchema.from_orm_flat(container))
                
                # Manually handle relationships if needed
                if container.bill_of_landing:
                    container_dict["bill_of_landing"] = {
                        "consignee_name": container.bill_of_landing.consignee_rel.consignee_name if container.bill_of_landing.consignee_rel else None,
                        "supplier_name": container.bill_of_landing.supplier_rel.name if container.bill_of_landing.supplier_rel else None,
                        "ArrivalDate": container.bill_of_landing.ArrivalDate.isoformat() if container.bill_of_landing.ArrivalDate else None,
                        "vessal": container.bill_of_landing.vessel_rel.VessalNo if container.bill_of_landing.vessel_rel else None,
                        "Doc_name": container.bill_of_landing.doc_rel.doc_type if container.bill_of_landing.doc_rel else None,
                        "ExcludingDay": container.bill_of_landing.provider_rel.ExcludingDays if container.bill_of_landing.provider_rel else 0,
                        "FreeDays": container.bill_of_landing.FreeDays if container.bill_of_landing and container.bill_of_landing.FreeDays is not None else 0
                        
                    }
                
                if container.materials:
                    container_dict["materials"] = [
                        {"Id": m.Id, "name": m.Name} 
                        for m in container.materials
                    ]
                
                serialized_data.append(container_dict)

            return {
                "total_count": total_count,
                "data": serialized_data
            }
        
    @ContainerRouter.delete("/containers/{container_id}")
    async def delete_container(self, 
        container_id: int,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user),
        ):
        # Step 1: Fetch the container
        container = db.query(ContainerDetails).filter(ContainerDetails.Container_ID == container_id).first()
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        # Step 2: Get related report IDs
        report_ids = db.query(ReportDetails.report_id).filter(
            ReportDetails.container_id == container_id
        ).all()
        report_ids = [r[0] for r in report_ids]

        # Step 3: Get related damage product IDs
        dmgp_ids = db.query(DamageProduct.id).filter(
            DamageProduct.report_id.in_(report_ids)
        ).all()
        dmgp_ids = [d[0] for d in dmgp_ids]

        # Step 4: Delete associated report images
        if dmgp_ids:
            db.query(ReportImage).filter(
                ReportImage.DMGP_id.in_(dmgp_ids)
            ).delete(synchronize_session=False)

        # Step 5: Delete damage products
        if report_ids:
            db.query(DamageProduct).filter(
                DamageProduct.report_id.in_(report_ids)
            ).delete(synchronize_session=False)

        # Step 6: Delete report details
        db.query(ReportDetails).filter(
            ReportDetails.container_id == container_id
        ).delete(synchronize_session=False)

        # Step 7: Delete container documents (and optionally remove files from disk)
        doc_paths = db.query(ContainerDocs.path).filter(ContainerDocs.container_id == container_id).all()
        db.query(ContainerDocs).filter(ContainerDocs.container_id == container_id).delete(synchronize_session=False)

        # OPTIONAL: delete physical files if needed
        # for (path,) in doc_paths:
        #     remove_file_from_disk(path)

        # Step 8: Clear many-to-many materials (optional for soft delete, but good for cleanup)
        container.materials.clear()

        # Step 9: Soft delete the container instead of hard delete
        container.is_deleted = True
        container.deleted_by = current_user.id
        container.deleted_at = datetime.utcnow()
        
        # Soft delete associated reports
        db.query(ReportDetails).filter(ReportDetails.container_id == container_id).update({
            "is_deleted": True,
            "deleted_by": current_user.id,
            "deleted_at": datetime.utcnow()
        }, synchronize_session=False)

        # Step 10: Commit all changes
        db.commit()

        return {"message": "Container and associated data deleted successfully"}
    
    @ContainerRouter.get("/getDocument/{doc_id}")
    async def get_document(self, doc_id: int, db: Session = Depends(get_db)):
        doc = db.query(ContainerDocs).filter(ContainerDocs.docs_id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        file_path = os.path.normpath(doc.path)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        # Guess MIME type based on file extension
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        return FileResponse(
            path=file_path,
            media_type=mime_type,
            filename=os.path.basename(file_path),
            headers={
                "Content-Disposition": f'inline; filename="{os.path.basename(file_path)}"'
            }
        )
    
    @ContainerRouter.put("/containers/{container_id}")
    async def update_container_details(self,
        container_id: int,
        request: Request,
        documents: List[UploadFile] = File([]),
        inbound_images: Optional[List[UploadFile]] = File([]),
        empty_images: Optional[List[UploadFile]] = File([]),
        remove_doc_ids: List[int] = Form([]),
        db: Session = Depends(get_db)
        ):
        
        container = db.query(ContainerDetails).filter_by(Container_ID=container_id).first()
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")

        form = await request.form()
        updated_fields = dict(form)
        skip_fields = {"remove_doc_ids"}
        
        for key in skip_fields:
            updated_fields.pop(key, None)
            # updated_fields.pop(key, '')
            
        # print(updated_fields)

        if "tax" in updated_fields:
            updated_fields["tax"] = int(updated_fields["tax"])

        # Handle date fields properly (parse strings to date/datetime)
        date_fields = {"arrival_on_port", "in_bound", "empty_date", "out_bound", "unloaded_at_dock", "emptied_at"}
        for field in date_fields:
            if field in updated_fields and updated_fields[field]:
                # Example: parse date string in 'YYYY-MM-DD' format
                try:
                   
                        # For datetime fields or other formats, adapt parsing as needed
                        updated_fields[field] = updated_fields[field]  # Or parse accordingly
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Invalid date format for {field}: {e}")

        model_columns = ContainerDetails.__table__.columns.keys()
        model_columns[-2] = "arrival_on_port"
            
        cleaned_fields = {
            k: v for k, v in updated_fields.items()
            if k in model_columns and k not in {"documents", "remove_doc_ids"}  # exclude ArrivalOn here since it's for Vessal
        }
        # if "arrival_on_port" in cleaned_fields:
        #     cleaned_fields['Arrival_Date'] = cleaned_fields.pop('arrival_on_port') 
        
        # Update container fields
        for key, value in cleaned_fields.items():
            if str(getattr(container, key)) != str(value):
                setattr(container, key, value)



        # Remove selected documents
        docs_to_remove = []
        for doc_id in remove_doc_ids:
            doc = db.query(ContainerDocs).filter_by(docs_id=doc_id, container_id=container_id).first()
            if doc:
                docs_to_remove.append(doc.path)
                db.delete(doc)

        remove_files(docs_to_remove)

        # Save new uploaded documents
        saved_paths = save_uploaded_files(documents, "Shipping")
        for path in saved_paths:
            db.add(ContainerDocs(container_id=container_id, path=path, Type=DocType.D))

        saved_paths = save_uploaded_files(empty_images, "EmptyContainer")
        for path in saved_paths:
            db.add(ContainerDocs(container_id=container_id, path=path, Type=DocType.ED))

        saved_paths = save_uploaded_files(inbound_images, "InBoundContainer")
        for path in saved_paths:
            db.add(ContainerDocs(container_id=container_id, path=path, Type=DocType.AD))

        db.commit()
        return {"message": "Container updated successfully"}    

    @ContainerRouter.patch("/containers/{container_id}/status")
    async def update_container(self, 
        container_id: int,
        update_data: ContainerUpdateSchema = Depends(parse_update_form),
        new_docs: List[UploadFile] = File([]),
        inbound_images: Optional[List[UploadFile]] = File([]),
        empty_images: Optional[List[UploadFile]] = File([]),
        remove_doc_ids: Optional[List[int]] = Form([]),
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
        ):
        # 🔍 Get the container
        container = db.query(ContainerDetails).filter_by(Container_ID=container_id).first()
        # print(container)
        if not container:
            raise HTTPException(status_code=404, detail="Container not found.")

        # 🛠️ Update basic container fields (excluding materials and BL)
        for key, value in update_data.dict(exclude_unset=True, exclude={"materials", "bill_of_landing"}).items():
            setattr(container, key, value)
        container.updated_by = current_user.id

        # 🔁 Update materials (many-to-many)
        if update_data.materials is not None:
            container.materials.clear()
            for entry in update_data.materials:
                material = db.query(Material).filter_by(Id=entry).first()
                if material:
                    container.materials.append(material)

        # 🔄 Update Bill of Landing
        if update_data.bill_of_landing:
            bl_data = update_data.bill_of_landing.dict(exclude_unset=True)
            bl_number = container.BillOfLanding

            existing_bl = db.query(BillOfLanding).filter_by(BillOfLanding=bl_number).first()
            if existing_bl:
                # ── FreeDays conflict check + cascade ──────────────────────
                if 'FreeDays' in bl_data and bl_data['FreeDays'] != existing_bl.FreeDays:
                    children = db.query(ContainerDetails).filter_by(BillOfLanding=existing_bl.BillOfLanding).all()
                    for child in children:
                        if child.FreeDays is not None and existing_bl.FreeDays is not None and child.FreeDays != existing_bl.FreeDays:
                            raise HTTPException(
                                status_code=409,
                                detail="Cannot update Bill of Lading FreeDays: One or more containers have custom FreeDays. Please update individual containers instead."
                            )
                    for child in children:
                        child.FreeDays = bl_data['FreeDays']

                # ── Status conflict check + cascade ────────────────────────
                if 'status' in bl_data and bl_data['status'] != existing_bl.status:
                    children = db.query(ContainerDetails).filter_by(BillOfLanding=existing_bl.BillOfLanding).all()
                    for child in children:
                        if child.status is not None and existing_bl.status is not None and child.status != existing_bl.status:
                            raise HTTPException(
                                status_code=409,
                                detail="Cannot update Bill of Lading status: One or more containers have a custom status. Please update individual containers instead."
                            )
                    for child in children:
                        child.status = bl_data['status']

                for key, value in bl_data.items():
                    setattr(existing_bl, key, value)
                existing_bl.updated_by = current_user.id
            else:
                # Unlikely but safe fallback
                bl_data["created_by"] = current_user.id
                bl_data["updated_by"] = current_user.id
                new_bl = BillOfLanding(**bl_data)
                db.add(new_bl)

        # ❌ Remove selected documents
        if remove_doc_ids:
            remove_paths = []
            for doc_id in remove_doc_ids:
                doc = db.query(ContainerDocs).filter_by(docs_id=doc_id, container_id=container_id).first()
                if doc:
                    remove_paths.append(doc.path)
                    db.delete(doc)
            remove_files(remove_paths)

        # 📁 Save uploaded documents and link
        def save_and_link(files: List[UploadFile], folder: str, doc_type: str):
            saved_paths = save_uploaded_files(files, folder)
            for path in saved_paths:
                db.add(ContainerDocs(container_id=container_id, path=path, Type=doc_type))

        if new_docs:
            save_and_link(new_docs, "Shipping", DocType.D)
        if inbound_images:
            save_and_link(inbound_images, "InBoundContainer", DocType.AD)
        if empty_images:
            save_and_link(empty_images, "EmptyContainer", DocType.ED)

        # 💾 Commit all changes
        db.commit()

        return {"message": "Container updated successfully"}
     
    @ContainerRouter.get("/getAllContainers")
    async def getContainerForREport(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = ( db.query(
            ContainerDetails.Container_ID,
            ContainerDetails.container_no,
            
            ) 
            .filter(ContainerDetails.status != 4 ) 
            ).all() 
        
        # column = ['Container ID','Container No', 'Supplier']
        return json.dumps({ "data": [list(row) for row in data]})
    
    @ContainerRouter.get("/getContainerReports")
    async def get_ContainerReports(self, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        data = ( db.query(
            ReportDetails.report_id,
            ContainerDetails.container_no
            ) 
            .outerjoin(ContainerDetails, ContainerDetails.Container_ID == ReportDetails.container_id) 
            ).all() 
        
        column = ['Report Id','Container No']
        return json.dumps({"column": column, "data": [list(row) for row in data]})
    
    @ContainerRouter.get("/damage-reports")
    async def get_ContainerReports(self, 
                                    report_id: int = Form(None),
                                    offset: int = Query(0, ge=0),
                                    limit: int = Query(500, le=1000),
                                    db: Session = Depends(get_db), 
                                #    current_user: dict = Depends(get_current_user)
                                   ):
        base_query = ( 
            db.query(
                ReportDetails.report_id,
                ContainerDetails.container_no
            ) 
            .outerjoin(ContainerDetails, ContainerDetails.Container_ID == ReportDetails.container_id) 
            )
        
        if report_id:
            base_query = base_query.filter(ReportDetails.report_id == report_id)
            
        total_count = base_query.count()
        results = base_query.offset(offset).limit(limit).all()
        
        reports = []
        for result in results:
            # report = jsonable_encoder(ReportSchema.from_attributes(result))
            formatted_data = {"ReportId": result[0], "ContainerNo": result[1]}
            reports.append(formatted_data)
            
        print(reports)
        print()
        return {
            "total_count": total_count,
            "data": reports
        } 
    
    @ContainerRouter.post("/damage-reports")
    async def submit_damage_report(self,
        data: str = Form(...),
        files: Optional[List[UploadFile]] = File(None),
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)
        ):
        print(data)
        try:
            parsed_data: Dict[str, Any] = json.loads(data)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format in data.")


        container_id = parsed_data.get("container_id")
        products = parsed_data.get("products", [])

        if not container_id:
            raise HTTPException(status_code=422, detail="Missing container_id.")

        # Create the report
        report = ReportDetails(
            container_id=container_id,
            report_date=datetime.utcnow().date()
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        file_index = 0
        files = files or []  # Ensure files is a list

        for prod in products:
            name = prod.get("name")
            quantity = prod.get("quantity")
            reason = prod.get("reason")
            file_count = len(prod.get("files", []))

            if not name or not quantity:
                continue

            # Save product to DB
            damage_product = DamageProduct(
                report_id=report.report_id,
                product_name=name,
                qty=quantity,
                note=reason
            )
            db.add(damage_product)
            db.commit()
            db.refresh(damage_product)

            # Select files for this product
            product_files = files[file_index:file_index + file_count]
            file_index += file_count

            # Save files
            # upload_dir = f"uploads/reports/{report.report_id}/product_{damage_product.id}"
            saved_paths = save_uploaded_files(product_files, "Report")

            # Save image paths to ReportImage
            for path in saved_paths:
                report_image = ReportImage(
                    DMGP_id=str(damage_product.id),
                    path=path
                )
                db.add(report_image)

        db.commit()
        return {"message": "Report submitted", "report_id": report.report_id}

    @ContainerRouter.get("/damage-reports/{report_id}")
    async def get_damage_report(
        self,
        report_id: int,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)
        ):
        report = db.query(ReportDetails).filter(ReportDetails.report_id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        container = db.query(ContainerDetails).filter(ContainerDetails.Container_ID == report.container_id).first()

        products = []
        for dp in db.query(DamageProduct).filter(DamageProduct.report_id == report.report_id).all():
            images = db.query(ReportImage).filter(ReportImage.DMGP_id == str(dp.id)).all()
            products.append({
                "id": dp.id,
                "name": dp.product_name,
                "quantity": dp.qty,
                "reason": dp.note,
                "files": [
                    {
                        "id": img.id,
                        "filename": img.path.split("/")[-1]  # assuming img.path stores full file path or URL
                    }
                    for img in images
                ]
            })

        return {
            "report_id": report_id,
            "containerId": container.Container_ID if container else None,
            "container_number": container.container_no if container else None,
            "products": products
        }
        
    @ContainerRouter.put("/damage-reports/{report_id}")
    async def update_damage_report(self,
        report_id: int,
        request: Request,
        files: Optional[List[UploadFile]] = File(None),
        remove_doc_ids: List[int] = Form([]),
        remove_product_ids: List[int] = Form([]),
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)
        ):
        report = db.query(ReportDetails).filter_by(report_id=report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        form = await request.form()
        try:
            parsed_data: Dict[str, Any] = json.loads(form.get("data", "{}"))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in 'data'")

        new_products = parsed_data.get("products", [])
        container_id = parsed_data.get("container_id")

        files = files or []
        file_index = 0
        paths_to_remove = []

        # print(new_products)
        # Remove specified images
        for doc_id in remove_doc_ids:
            doc = db.query(ReportImage).filter_by(id=doc_id).first()
            if doc:
                paths_to_remove.append(doc.path)
                db.delete(doc)

        # Remove specified products (and their images)
        for prod_id in remove_product_ids:
            product = db.query(DamageProduct).filter_by(id=prod_id, report_id=report_id).first()
            if product:
                images = db.query(ReportImage).filter_by(DMGP_id=product.id).all()
                for img in images:
                    paths_to_remove.append(img.path)
                    db.delete(img)
                db.delete(product)

        # Update report container if changed
        if container_id and report.container_id != container_id:
            report.container_id = container_id
            db.add(report)

        # Add or update products
        for product in new_products:
            
            prod_id = product.get("id")
            name = product.get("name")
            quantity = product.get("quantity")
            reason = product.get("reason")
            file_count = len(product.get("files", []))

            # if not name or not quantity:
                # continue  # Skip invalid entries
            
            # print(prod_id)
            if prod_id:  # Existing product — update
                existing_product = db.query(DamageProduct).filter_by(id=prod_id).first()
                if existing_product:
                    if name is not None:
                        existing_product.product_name = name
                    if quantity is not None:
                        existing_product.qty = quantity
                    if reason is not None:
                        existing_product.note = reason
                    db.add(existing_product)
                    db.commit()

                    # Save new files if any
                    new_files = files[file_index:file_index + file_count]
                    saved_paths = save_uploaded_files(new_files, "Report")
                    for path in saved_paths:
                        db.add(ReportImage(DMGP_id=existing_product.id, path=path))
                    file_index += file_count

            else:  # New product — insert
                new_product = DamageProduct(
                    report_id=report_id,
                    product_name=name,
                    qty=quantity,
                    note=reason
                )
                db.add(new_product)
                db.commit()
                db.refresh(new_product)

                new_files = files[file_index:file_index + file_count]
                saved_paths = save_uploaded_files(new_files, "Report")
                for path in saved_paths:
                    db.add(ReportImage(DMGP_id=new_product.id, path=path))
                file_index += file_count

        db.commit()
        remove_files(paths_to_remove)

        return {"message": "Report updated successfully", "report_id": report_id}

    @ContainerRouter.get("/getReportImage/{image_id}")
    async def get_report_image(self, image_id: int, db: Session = Depends(get_db)):
        image = db.query(ReportImage).filter(ReportImage.id == image_id).first()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        file_path = os.path.normpath(image.path)  # or image.path depending on your schema
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail="File not found on disk")

        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        return FileResponse(
            path=file_path,
            media_type=mime_type,
            filename=os.path.basename(file_path),
            headers={
                "Content-Disposition": f'inline; filename="{os.path.basename(file_path)}"'
            }
        )

    @ContainerRouter.delete("/damage-reports/{report_id}")
    def delete_damage_report(self,
        report_id: int,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)
      ):
        report = db.query(ReportDetails).filter(ReportDetails.report_id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        # Collect image paths for removal from disk
        paths_to_remove: List[str] = []

        # Get all products for the report
        products = db.query(DamageProduct).filter(DamageProduct.report_id==report_id).all()
        for product in products:
            # Get all images for each product
            images = db.query(ReportImage).filter(ReportImage.DMGP_id==product.id).all()
            for img in images:
                paths_to_remove.append(img.path)
                db.delete(img)

            db.delete(product)

        # Delete images directly associated with report (if any)
        other_images = db.query(ReportImage).filter(ReportImage.DMGP_id==report_id).all()
        for img in other_images:
            paths_to_remove.append(img.path)
            db.delete(img)

        # Finally delete the report itself
        db.delete(report)
        db.commit()

        # Remove files from disk
        remove_files(paths_to_remove)

        return {"message": "Report and all related data deleted", "report_id": report_id}

    @ContainerRouter.get("/reports/{report_id}")
    def get_report_pdf(self, report_id: int, db: Session = Depends(get_db)):
        report = db.query(ReportDetails).filter(ReportDetails.report_id==report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        container = db.query(ContainerDetails).filter(ContainerDetails.Container_ID == report.container_id).first()
        products = db.query(DamageProduct).filter(DamageProduct.report_id==report_id).all()
        data = {
            "container_number": container.container_no if container.container_no else "N/A",
            "report_date": report.report_date.strftime("%Y-%m-%d"),
            "products": [
                {
                    "product_name": p.product_name,
                    "qty": p.qty,
                    "note": p.note,
                    "images": [img.path for img in p.images]  # make sure paths are accessible
                }
                for p in products
            ]
        }

        pdf_bytes = generate_damage_report_pdf(data)
        return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers={
            "Content-Disposition": f"inline; filename=damage_report_{report_id}.pdf"
        })
    
    @ContainerRouter.get("/arrived")
    def get_arrived_containers(self,
        
        db: Session = Depends(get_db),
       
        ):
        containers = (
            db.query(ContainerDetails, UnloadVenue.venue.label("venue"), BillOfLanding.ArrivalDate.label("Arrival_Date"))
            .outerjoin(UnloadVenue, ContainerDetails.emptied_at == UnloadVenue.venue_id)
            .outerjoin(BillOfLanding, BillOfLanding.BillOfLanding == ContainerDetails.BillOfLanding)
            .filter(ContainerDetails.status == 3)
        ).all()

        result = []
        for container, venue, Arrival_Date in containers:
            result.append({
                "Container_ID": container.Container_ID,
                "container_no": container.container_no,
                "arrival_on_port": Arrival_Date,
                "venue": venue
            })

        return result

    @ContainerRouter.get("/toPickup")
    def get_toPickup_containers(self, 
        
        db: Session = Depends(get_db),
       
        ):
        containers = (
            db.query(ContainerDetails, UnloadVenue.venue)
            .outerjoin(UnloadVenue, ContainerDetails.emptied_at == UnloadVenue.venue_id)
            
            .filter(ContainerDetails.status == 7)
            
            
        ).all()
        result = []
        for container, venue in containers:
            result.append({
                "Container_ID": container.Container_ID,
                "container_no": container.container_no,
                "emptyDate": container.empty_date,
                "venue": venue
            })

        return result

