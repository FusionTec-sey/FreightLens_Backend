from datetime import date, time
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from Services.branch_business_date_service import BranchTradingRules


class TradingDateOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    business_date: date
    is_open: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=200)


class BranchSettingsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    timezone_name: str | None = Field(default=None, max_length=100)
    weekday_cutoff: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    weekend_cutoff: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    trading_weekdays: list[int] | None = Field(default=None, max_length=7)
    date_overrides: list[TradingDateOverride] = Field(default_factory=list, max_length=366)

    @field_validator("trading_weekdays", mode="before")
    @classmethod
    def strict_days(cls, value):
        if value is not None and (not isinstance(value, list) or any(type(day) is not int for day in value)):
            raise ValueError("Trading days must be a list of integer weekdays")
        return value

    @model_validator(mode="after")
    def valid_rules(self):
        self.rules()
        if self.trading_weekdays is not None:
            if len(set(self.trading_weekdays)) != len(self.trading_weekdays):
                raise ValueError("Trading days must be unique")
            self.trading_weekdays = sorted(self.trading_weekdays)
        dates = [item.business_date for item in self.date_overrides]
        if len(set(dates)) != len(dates):
            raise ValueError("Each calendar date can have only one override")
        self.date_overrides.sort(key=lambda item: item.business_date)
        return self

    def rules(self):
        return BranchTradingRules(self.timezone_name,
            time.fromisoformat(self.weekday_cutoff) if self.weekday_cutoff else None,
            time.fromisoformat(self.weekend_cutoff) if self.weekend_cutoff else None,
            frozenset(self.trading_weekdays) if self.trading_weekdays is not None else None)

    def missing(self):
        return [field for field in ("timezone_name", "weekday_cutoff", "weekend_cutoff", "trading_weekdays")
                if getattr(self, field) is None]


class BranchSettingsSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, strict=True)
    operation_key: UUID
    config: BranchSettingsConfig

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("Operation key must be nonzero")
        return value


class BranchSettingsRead(BaseModel):
    branch_id: int
    version: int
    status: Literal["NOT_CONFIGURED", "INCOMPLETE", "CONFIGURED"]
    config: BranchSettingsConfig
    missing_fields: list[str]
    operational_activation: Literal[False] = False
