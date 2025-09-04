from pydantic import BaseModel

class UnloadVenueSchema(BaseModel):
    venue_id: int
    venue: str | None = None

    class Config:
        from_attributes = True
