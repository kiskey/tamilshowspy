from typing import List, Optional, Dict
from pydantic import BaseModel, Field

# Stremio Models
class Manifest(BaseModel):
    id: str = "org.tamilblasters.python"
    version: str = "1.0.0"
    name: str = "TamilBlasters Series"
    description: str = "High-performance Stremio addon for Tamil Web Series from 1TamilBlasters"
    resources: List[str] = ["catalog", "meta", "stream", "search"]
    types: List[str] = ["series"]
    id_prefixes: List[str] = ["tb:"]
    catalogs: List[Dict] = [
        {"type": "series", "id": "tamil-web", "name": "Tamil Web Series"}
    ]

class Meta(BaseModel):
    id: str
    type: str = "series"
    name: str
    poster: Optional[str] = None
    background: Optional[str] = None
    genres: Optional[List[str]] = None
    videos: Optional[List['Video']] = []

class Video(BaseModel):
    id: str
    title: str
    season: int
    episode: int
    released: Optional[str] = None
    overview: Optional[str] = None
    thumbnail: Optional[str] = None

Meta.model_rebuild()

class Stream(BaseModel):
    name: str
    title: str
    url: str  # Magnet link
    behaviorHints: Optional[Dict] = Field(None, alias="behaviorHints")

class StreamsResponse(BaseModel):
    streams: List[Stream] = []

class CatalogResponse(BaseModel):
    metas: List[Meta]

class MetaResponse(BaseModel):
    meta: Meta
