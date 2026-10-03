"""Customer identity only; no inferred consent, credit, tax or duplicate merge."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CustomerContact(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)
    kind: Literal['PHONE', 'EMAIL']
    value: str = Field(min_length=3, max_length=160)
    label: str = Field(default='', max_length=60)
    primary: bool = False

    @model_validator(mode='after')
    def valid_contact(self):
        if any(ord(char) < 32 or ord(char) == 127 for char in self.value + self.label):
            raise ValueError('Contact details cannot contain control characters')
        if self.kind == 'EMAIL':
            parts = self.value.split('@')
            if len(parts) != 2 or not all(parts) or '.' not in parts[1] or any(c.isspace() for c in self.value):
                raise ValueError('Enter an email address')
        elif not all(c in '+0123456789 ()-.' for c in self.value) or not 5 <= sum(c.isdigit() for c in self.value) <= 20:
            raise ValueError('Enter a phone number including its country code where known')
        return self


class CustomerIdentityInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, strict=True)
    name: str = Field(min_length=1, max_length=160)
    kind: Literal['PERSON', 'BUSINESS']
    contacts: list[CustomerContact] = Field(min_length=1, max_length=16)

    @field_validator('name')
    @classmethod
    def printable_name(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Customer name cannot contain control characters')
        return value

    @model_validator(mode='after')
    def primary_contact(self):
        if sum(contact.primary for contact in self.contacts) != 1:
            raise ValueError('Choose exactly one primary contact')
        keys = [(contact.kind, contact.value.casefold()) for contact in self.contacts]
        if len(keys) != len(set(keys)):
            raise ValueError('Repeated contacts in one profile are not allowed')
        return self


class CustomerIdentityRead(CustomerIdentityInput):
    customer_key: UUID
    version: int


class CustomerCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    expected_version: int = Field(ge=0, le=0, strict=True)
    profile: CustomerIdentityInput


class CustomerCreated(BaseModel):
    customer_key: UUID
    version: Literal[1]
    replayed: bool
    search_indexed: bool = False


class CustomerSearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    search: str = Field(min_length=1, max_length=160)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=25, ge=1, le=100)
