from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class AppPageOut(BaseModel):
    """A registry page as offered to the Menu Designer dropdown."""
    page_key: str
    route: str
    title: str
    default_icon: Optional[str] = None
    group_key: Optional[str] = None
    permission_codes: List[str] = Field(default_factory=list)
    module_codes: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PageGroupOut(BaseModel):
    """A default sidebar folder offered by the registry."""
    group_key: str
    label: str
    icon: Optional[str] = None
    sort_order: int = 0


class PageRegistryResponse(BaseModel):
    pages: List[AppPageOut] = Field(default_factory=list)
    groups: List[PageGroupOut] = Field(default_factory=list)
    # The nesting the sidebar can render, so the designer enforces the same
    # limit the save endpoint does instead of keeping its own copy.
    max_menu_depth: int = 3
    max_menu_items: int = 300


class MenuNodeOut(BaseModel):
    """One node of the menu tree served to a signed-in user."""
    id: Optional[int] = None
    page_key: Optional[str] = None
    label: str
    icon: Optional[str] = None
    route: Optional[str] = None
    is_separator: bool = False
    permission_codes: List[str] = Field(default_factory=list)
    module_codes: List[str] = Field(default_factory=list)
    locked: bool = False
    children: List["MenuNodeOut"] = Field(default_factory=list)


MenuNodeOut.model_rebuild()


class MyMenuResponse(BaseModel):
    menu: List[MenuNodeOut] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)
    # True when no admin has arranged a menu yet and the tree was derived from
    # the page registry. The designer uses this to offer "start from default".
    is_default: bool = False


class MenuSummaryOut(BaseModel):
    """A row in the Menu Designer's list of menus."""
    id: int
    # Menus belong to one organisation while roles are shared across them, so the
    # owning organisation is spelled out rather than inferred from the session.
    org_id: Optional[int] = None
    org_name: Optional[str] = None
    # True when the menu serves its roles in every company, not just its own.
    is_shared: bool = False
    name: str
    description: Optional[str] = None
    item_count: int = 0
    page_count: int = 0
    unmapped_page_count: int = 0
    # Roles served this menu. Empty means the menu reaches nobody.
    role_ids: List[int] = Field(default_factory=list)
    role_names: List[str] = Field(default_factory=list)
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


class MenuCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    # Start from the registry-derived default rather than an empty tree.
    seed_from_default: bool = True

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A menu needs a name")
        return cleaned


class MenuUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    # Replaces the whole assignment. A role listed here is moved off whatever
    # menu previously claimed it, so a role is never served two menus.
    role_ids: Optional[List[int]] = None
    # Platform administrators only: share this menu with every company.
    is_shared: Optional[bool] = None


class MenuDetailOut(BaseModel):
    """One menu with its rows, for the designer."""
    id: int
    org_id: Optional[int] = None
    org_name: Optional[str] = None
    is_shared: bool = False
    name: str
    description: Optional[str] = None
    role_ids: List[int] = Field(default_factory=list)
    items: List["MenuItemOut"] = Field(default_factory=list)


class MenuItemOut(BaseModel):
    """A stored menu row, unfiltered, for the designer."""
    id: int
    parent_id: Optional[int] = None
    label: str
    icon: Optional[str] = None
    page_key: Optional[str] = None
    is_separator: bool = False
    sort_order: int = 0
    is_active: bool = True
    show_when_locked: bool = False

    class Config:
        from_attributes = True


class MenuItemSaveIn(BaseModel):
    """One item in a full-menu save.

    ``temp_id`` is client-generated and referenced by ``parent_temp_id``, so the
    whole tree arrives in a single request and is written in one transaction.
    """
    temp_id: str = Field(min_length=1, max_length=64)
    parent_temp_id: Optional[str] = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=100)
    icon: Optional[str] = Field(default=None, max_length=50)
    page_key: Optional[str] = Field(default=None, max_length=60)
    # A section heading: no route, no children.
    is_separator: bool = False
    sort_order: int = 0
    is_active: bool = True
    show_when_locked: bool = False

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Every menu item needs a label")
        return cleaned


class MenuSaveRequest(BaseModel):
    items: List[MenuItemSaveIn] = Field(default_factory=list)


class OrgMenuSummaryOut(BaseModel):
    """One organisation's menu state, for the platform-admin overview."""
    org_id: int
    org_name: str
    is_active: bool = True
    menu_count: int = 0
    # Roles in this organisation that have a menu assigned to them.
    assigned_role_count: int = 0
    item_count: int = 0
    # False means the organisation has designed no menus and is served the
    # shipped layout, which keeps up with newly released screens.
    is_custom: bool = False
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class RoleVisibilityOut(BaseModel):
    """Which registry pages one role may see, for the designer's role preview.

    The designer filters its unsaved draft against ``allowed_page_keys``, so an
    admin can spot "this role would see an empty menu" before saving.
    """
    role_id: int
    role_name: str
    is_platform_admin: bool = False
    allowed_page_keys: List[str] = Field(default_factory=list)


MenuDetailOut.model_rebuild()
