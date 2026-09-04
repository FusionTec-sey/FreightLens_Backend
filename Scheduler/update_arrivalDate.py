# from .Base import scheduler


# from fastapi_utils.cbv import cbv
# from fastapi_utils.inferring_router import InferringRouter
# from fastapi import Depends, HTTPException,  Query
# from sqlalchemy.orm import Session, joinedload
# from typing import List, Optional
# from sqlalchemy import func, desc, case
from Model.db import get_db
from Model import BillOfLanding
# from ..Model.db import get_db
# from ..Model import ContainerDetails, Supplier, LogisticsProvider,  Vessal, BillOfLanding, Consignee, ShippingDocument, ContainerDocs, ReportDetails, DamageProduct, ReportImage
# from Schema import   BillOfLandingInSchema, BillOfLandingWithContainersSchema, ContainerDetailsSchemaWithBl, BillOfLandingUpdateOnlySchema, BillOfLandingListResponse
# from Utils import *

# from auth.dependencies import get_current_user
# from fastapi import  Depends, Body
# from fastapi.responses import FileResponse, StreamingResponse
# import json
# import mimetypes
# from typing import List, Optional
# import os 
from datetime import datetime
# from io 
# from ..ShippingProvider import track_and_trace

# async def get_bls(self,
#         BillOfLandingNo: Optional[str] = Query(None),
#         ConsigneeName: Optional[str] = Query(None),
#         Vessel: Optional[str] = Query(None),
#         SupplierName: Optional[str] = Query(None),
#         Provider: Optional[str] = Query(None),
#         ArrivalDate: Optional[datetime] = Query(None),
#         offset: int = Query(0, ge=0),
#         limit: int = Query(0, le=500),
#         sort_by_arrival: bool = Query(True, description="Sort by ArrivalDate descending if True"),
#         db: Session = Depends(get_db),
#         ):
#         try:
#             query = (
#                 db.query(BillOfLanding)
#                 .options(
#                     joinedload(BillOfLanding.consignee_rel),
#                     joinedload(BillOfLanding.vessel_rel),
#                     joinedload(BillOfLanding.supplier_rel),
#                     joinedload(BillOfLanding.provider_rel),
#                     joinedload(BillOfLanding.doc_rel)
#                 )
#             )

#             # Apply filters
#             if BillOfLandingNo:
#                 query = query.filter(BillOfLanding.BillOfLanding == BillOfLandingNo)

#             if ConsigneeName:
#                 query = query.join(BillOfLanding.consignee_rel).filter(
#                     Consignee.consignee_name.ilike(f"%{ConsigneeName}%")
#                 )

#             if Vessel:
#                 query = query.join(BillOfLanding.vessel_rel).filter(
#                     Vessal.name.ilike(f"%{Vessel}%")
#                 )

#             if SupplierName:
#                 query = query.join(BillOfLanding.supplier_rel).filter(
#                     Supplier.name.ilike(f"%{SupplierName}%")
#                 )

#             if Provider:
#                 query = query.join(BillOfLanding.provider_rel).filter(
#                     LogisticsProvider.name.ilike(f"%{Provider}%")
#                 )

#             if ArrivalDate:
#                 query = query.filter(BillOfLanding.ArrivalDate == ArrivalDate)

#             # Optional sorting
#             if sort_by_arrival:
#                 query = query.order_by(BillOfLanding.ArrivalDate.desc())
#             else:
#                 query = query.order_by(BillOfLanding.ArrivalDate.asc())
                
#             total_count = query.count()
#             # Apply pagination
#             bl_results = query.offset(offset).limit(limit).all()

#             # Construct response with nested containers
#             response = []
#             for bl in bl_results:
#                 containers = (
#                     db.query(ContainerDetails)
#                     .filter(ContainerDetails.BillOfLanding == bl.BillOfLanding)
#                     .options(
#                         joinedload(ContainerDetails.status_rel),
#                         joinedload(ContainerDetails.type_rel),
#                         joinedload(ContainerDetails.emptied_at_rel),
#                         joinedload(ContainerDetails.documents),
#                         joinedload(ContainerDetails.materials)
#                     )
#                     .all()
#                 )

#                 bl_schema = BillOfLandingWithContainersSchema.from_orm_flat(bl)
#                 bl_schema.containers = [ContainerDetailsSchemaWithBl.from_orm_flat(c) for c in containers]
#                 response.append(bl_schema)

#             return {
#                 "total_count": total_count,
#                 "data": response
#             }

#         except Exception as e:
#             raise HTTPException(status_code=500, detail=f"Error fetching Bill of Lading data: {str(e)}")


def updateArrivalDate( ):
   
    query = (
    get_db.query(BillOfLanding)
    .filter(BillOfLanding.ArrivalDate < datetime.now())
    .all()
    )
    print(query)
    # for row in query:
    #     track_and_trace(row)
    
