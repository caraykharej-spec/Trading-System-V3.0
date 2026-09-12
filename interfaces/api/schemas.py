from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AssistantQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=256)


class ApiErrorSchema(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ApiErrorSchema


class HealthSchema(BaseModel):
    status: str
    mode: str
    version: str
