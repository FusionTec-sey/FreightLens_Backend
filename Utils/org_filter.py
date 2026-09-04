from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Query

class OrgContext(BaseModel):
    current_org_id: int
    allowed_org_ids: List[int]
    is_root: bool
    selected_org_id: Optional[int] = None

    @property
    def org_id(self) -> int:
        return self.selected_org_id or self.current_org_id

def apply_org_filter(query: Query, model, org_context: OrgContext) -> Query:
    """
    Applies multi-tenant row-level filtering to a SQLAlchemy query.
    - If user is Root Org and selected a specific org: filters by that selected_org_id.
    - If user is Root Org and selected 'All': filters by all allowed_org_ids.
    - If user is Sub-Org: filters strictly by their allowed_org_ids.
    """
    if not hasattr(model, "org_id"):
        return query

    if org_context.selected_org_id:
        return query.filter(model.org_id == org_context.selected_org_id)
    
    return query.filter(model.org_id.in_(org_context.allowed_org_ids))
