from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends, HTTPException, Body, Request
from sqlalchemy.orm import Session
from typing import List

from Model.db import get_db
from Model import LogisticsProvider
from Schema import LogisticsProviderResponseSchema, LogisticsProviderUpdateSchema
from ShippingProvider.Helper.GeneralHelper import day_map, get_days, store_days
from auth.dependencies import get_current_user

SettingRouter = InferringRouter()

@cbv(SettingRouter)
class SettingAPI:
    @SettingRouter.get("/settings/demurrage-days")
    async def get_demurrage_days(self, current_user: dict = Depends(get_current_user)):
        """Returns the static mapping of days to bitmask values."""
        return day_map

    @SettingRouter.get("/settings/logistics-providers", response_model=List[LogisticsProviderResponseSchema])
    async def get_logistics_providers(
        self,
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)
    ):
        """Lists all logistics providers with parsed ExcludingDaysList."""
        providers = db.query(LogisticsProvider).all()
        results = []
        for provider in providers:
            # Parse excluding days list from bitmask
            excluding_list = get_days(provider.ExcludingDays) if provider.ExcludingDays else []
            results.append(
                LogisticsProviderResponseSchema(
                    Id=provider.Id,
                    Name=provider.Name,
                    ExcludingDays=provider.ExcludingDays,
                    FreeDays=provider.FreeDays,
                    ExcludingDaysList=excluding_list
                )
            )
        return results

    @SettingRouter.post("/settings/logistics-providers/{provider_id}", response_model=LogisticsProviderResponseSchema)
    async def update_logistics_provider_settings(
        self,
        provider_id: int,
        data: LogisticsProviderUpdateSchema = Body(...),
        db: Session = Depends(get_db),
        current_user: dict = Depends(get_current_user)
    ):
        """Updates free days and excluding days (either via bitmask integer or list of names)."""
        provider = db.query(LogisticsProvider).filter(LogisticsProvider.Id == provider_id).first()
        if not provider:
            raise HTTPException(status_code=404, detail="Logistics provider not found")

        update_data = data.dict(exclude_unset=True)

        if "FreeDays" in update_data:
            provider.FreeDays = update_data["FreeDays"]

        # If a list of names is provided, convert it to bitmask and set ExcludingDays
        if "ExcludingDaysList" in update_data and update_data["ExcludingDaysList"] is not None:
            try:
                bitmask = store_days(update_data["ExcludingDaysList"])
                provider.ExcludingDays = bitmask
            except KeyError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid day name: {str(e)}. Valid days are: {list(day_map.keys())}"
                )
        elif "ExcludingDays" in update_data:
            provider.ExcludingDays = update_data["ExcludingDays"]

        db.commit()
        db.refresh(provider)

        excluding_list = get_days(provider.ExcludingDays) if provider.ExcludingDays else []
        return LogisticsProviderResponseSchema(
            Id=provider.Id,
            Name=provider.Name,
            ExcludingDays=provider.ExcludingDays,
            FreeDays=provider.FreeDays,
            ExcludingDaysList=excluding_list
        )
