from pydantic import BaseModel


class SalesBranchChoice(BaseModel):
    id: int
    code: str
    name: str


class SalesProductChoice(BaseModel):
    image_signed_url: str | None = None
    id: int
    sku: str
    name: str
    policy_version: int
    base_unit: str | None
    units: list[str]
    quantity_step: str | None
