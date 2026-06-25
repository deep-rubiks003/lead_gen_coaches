"""Pydantic data models for leads."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class Lead(BaseModel):
    """A single coach lead = a Spur.fit prospect."""

    # identity
    platform: str                      # instagram | tiktok | twitter | reddit
    handle: str                        # @username or u/username
    name: Optional[str] = None
    profile_url: Optional[str] = None

    # raw signal
    bio: str = ""
    followers: int = 0
    website: Optional[str] = None      # linktree / personal site from bio

    # extracted
    email: Optional[str] = None
    email_source: Optional[str] = None  # bio | website | hunter | snov
    email_verified: Optional[bool] = None

    # classification
    role_matched: Optional[str] = None  # which ICP role keyword hit
    country: Optional[str] = None       # US/UK/CA/ZA/AU/NZ
    score: int = 0
    icp_tag: Optional[str] = None       # saas_icp | growth_icp | low_fit

    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def dedup_key(self) -> str:
        return f"{self.platform}:{self.handle.lower().lstrip('@')}"
