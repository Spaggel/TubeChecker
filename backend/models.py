from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from .database import Base


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    start_date = Column(DateTime, nullable=True)
    download_dir = Column(String, nullable=True)  # None = use channel name
    quality = Column(String, default="best", nullable=False)
    format = Column(String, default="any", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_checked = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    videos = relationship("Video", back_populates="channel", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False)
    video_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    published_at = Column(DateTime, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String, default="sent", nullable=False)  # sent | failed
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)      # auto-retries completed
    next_retry_at = Column(DateTime, nullable=True)               # None = no pending auto-retry

    channel = relationship("Channel", back_populates="videos")


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
