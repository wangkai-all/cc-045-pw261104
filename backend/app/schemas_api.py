"""Pydantic request/response models (API boundary only)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SchemaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class VersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=60)
    note: str = ""
    fields: list[dict[str, Any]] = Field(default_factory=list)


class DraftUpdate(BaseModel):
    fields: list[dict[str, Any]]
    note: Optional[str] = None


class CompareRequest(BaseModel):
    old_version_id: int
    new_version_id: int


class MappingRule(BaseModel):
    action: str
    source: Optional[str] = None
    target: Optional[str] = None
    value: Any = None


class MappingRequest(BaseModel):
    source_version_id: int
    target_version_id: int
    rules: list[MappingRule]
    upload_id: Optional[int] = None
    inline_records: Optional[list[dict[str, Any]]] = None


class MappingGenerateRequest(BaseModel):
    mapping_id: int
