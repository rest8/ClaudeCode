from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RestaurantInfo:
    omakase_id: str
    name: str
    url: str
    area: Optional[str] = None
    genre: Optional[str] = None
