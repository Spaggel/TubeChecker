from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class ChannelCreate(BaseModel):
    channel_id: str
    name: Optional[str] = None
    start_date: Optional[datetime] = None
    download_dir: Optional[str] = None
    quality: str = "best"
    format: str = "any"
    enabled: bool = True
    include_shorts: bool = False


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[datetime] = None
    download_dir: Optional[str] = None
    quality: Optional[str] = None
    format: Optional[str] = None
    enabled: Optional[bool] = None
    include_shorts: Optional[bool] = None


class ChannelOut(BaseModel):
    id: int
    channel_id: str
    name: str
    start_date: Optional[datetime] = None
    download_dir: Optional[str] = None
    quality: str = "best"
    format: str = "any"
    enabled: bool
    include_shorts: bool = False
    last_checked: Optional[datetime] = None
    created_at: datetime
    video_count: int = 0
    latest_video_date: Optional[datetime] = None

    model_config = {"from_attributes": True}


class VideoOut(BaseModel):
    id: int
    channel_id: int
    video_id: str
    title: str
    published_at: datetime
    sent_at: datetime
    status: str
    error: Optional[str] = None
    channel_name: Optional[str] = None
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ChannelExport(BaseModel):
    channel_id: str
    name: str
    start_date: Optional[datetime] = None
    download_dir: Optional[str] = None
    quality: str = "best"
    format: str = "any"
    enabled: bool = True
    include_shorts: bool = False


class ChannelImportRequest(BaseModel):
    channels: List[ChannelExport]


class ChannelImportResult(BaseModel):
    added: int
    skipped: int
    errors: List[str] = []


class SettingsOut(BaseModel):
    metube_url: str
    check_interval: int
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""


class SettingsUpdate(BaseModel):
    metube_url: Optional[str] = None
    check_interval: Optional[int] = None
    jellyfin_url: Optional[str] = None
    jellyfin_api_key: Optional[str] = None
