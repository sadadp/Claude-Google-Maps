"""Modelos de dominio compartidos (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class LeadStatus(StrEnum):
    PENDING = "PENDING"
    GENERATED = "GENERATED"
    SENT = "SENT"
    REJECTED = "REJECTED"


class Review(BaseModel):
    author: str = "Cliente de Google"
    rating: int = Field(ge=1, le=5)
    text: str
    relative_time: str | None = None


class Business(BaseModel):
    """Negocio normalizado, independiente de la fuente (Places API o gosom)."""

    place_id: str
    name: str
    phone: str  # formato internacional, p.ej. "+52 222 123 4567"
    address: str
    rating: float = Field(ge=0, le=5)
    review_count: int = Field(ge=0)
    website: str | None = None
    category: str | None = None
    maps_uri: str | None = None
    opening_hours: list[str] = Field(default_factory=list)
    top_reviews: list[Review] = Field(default_factory=list, max_length=3)

    @field_validator("name", "address")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def phone_digits(self) -> str:
        """Número en E.164 sin '+', tal como lo esperan wa.me y Evolution API."""
        return "".join(ch for ch in self.phone if ch.isdigit())


class Lead(BaseModel):
    place_id: str
    name: str
    phone: str
    rating: float
    review_count: int
    address: str
    preview_url: str | None = None
    status: LeadStatus = LeadStatus.PENDING
    contacted_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None


class PipelineResult(BaseModel):
    name: str
    phone: str
    rating: float
    review_count: int
    status: LeadStatus
    preview_url: str | None = None
    note: str = ""
