"""
News service models (shared public schema).
"""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import SQLModel, Field, Column, JSON


class News(SQLModel, table=True):
    """
    News articles (Hub's news.py)
    """
    __tablename__ = "news"
    
    # Primary key
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Tenant isolation
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", nullable=False, index=True)
    
    # Content
    title: str = Field(max_length=255, nullable=False)
    slug: Optional[str] = Field(default=None, max_length=255, index=True)
    summary: Optional[str] = Field(default=None)
    content: str = Field(nullable=False)
    
    # Media
    image_url: Optional[str] = Field(default=None, max_length=500)
    video_url: Optional[str] = Field(default=None, max_length=500)
    
    # Author
    author_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    author_name: Optional[str] = Field(default=None, max_length=255)
    
    # Publishing
    is_published: bool = Field(default=False, nullable=False)
    published_at: Optional[datetime] = Field(default=None)
    
    # Visibility
    is_featured: bool = Field(default=False)
    is_pinned: bool = Field(default=False)
    
    # Categorization
    category: Optional[str] = Field(default=None, max_length=100)
    tags: Optional[str] = Field(default=None, max_length=500)  # Comma-separated tags
    
    # Metrics
    views_count: int = Field(default=0)
    
    # Metadata
    # 'metadata' es reservado en SQLAlchemy/SQLModel.
    # Usamos atributo `metadata_` pero la columna sigue llamándose "metadata".
    metadata_: Optional[dict] = Field(default=None, sa_column=Column("metadata", JSON))
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

class Banner(SQLModel, table=True):
    """
    Promotional banners (Hub's banner.py)
    """
    __tablename__ = "banners"
    
    # Primary key
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Tenant isolation
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", nullable=False, index=True)
    
    # Content
    title: str = Field(max_length=255, nullable=False)
    description: Optional[str] = Field(default=None)
    
    # Media
    image_url: str = Field(max_length=500, nullable=False)
    mobile_image_url: Optional[str] = Field(default=None, max_length=500)  # Optional mobile version
    
    # Link
    link_url: Optional[str] = Field(default=None, max_length=500)
    link_target: str = Field(default="_blank", max_length=20)  # _blank, _self
    
    # Display settings
    position: Optional[str] = Field(default=None, max_length=50)  # top, bottom, sidebar, modal
    display_order: int = Field(default=0)
    
    # Status
    is_active: bool = Field(default=True, nullable=False)
    
    # Schedule
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)
    
    # Audience targeting (optional)
    target_audience: Optional[dict] = Field(default=None, sa_type=JSON)  # Flexible targeting rules
    
    # Metrics
    impressions_count: int = Field(default=0)
    clicks_count: int = Field(default=0)
    
    # Metadata
    metadata_: Optional[dict] = Field(default=None, sa_column=Column("metadata", JSON))
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class AdminNotification(SQLModel, table=True):
    """
    Admin-managed system notifications for Desk.

    NOTE: table is global (no tenant_id column).
    """
    __tablename__ = "admin_notifications"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    title: str = Field(max_length=255, nullable=False, index=True)
    description: str = Field(nullable=False)
    type: str = Field(max_length=50, nullable=False, index=True)      # news, reminder, alert
    category: str = Field(max_length=50, nullable=False, index=True)  # System, Feature, Warning, Error, Low
    priority: str = Field(max_length=20, nullable=False, index=True)  # low, medium, high
    icon: str = Field(max_length=50, nullable=False, default="bell")

    active: bool = Field(default=True, nullable=False, index=True)

    timestamp: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)

    created_by: uuid.UUID = Field(nullable=False, index=True)


class Announcement(SQLModel, table=True):
    """
    Desk announcements (legacy table renamed): public.announcement

    NOTE:
    - This table does NOT have tenant_id in the legacy schema.
    - news-service is the only service allowed to read/write it.
    """

    __tablename__ = "announcement"
    __table_args__ = {"schema": "public"}

    id: Optional[int] = Field(default=None, primary_key=True)

    created_at: datetime
    modified_at: datetime

    content: Optional[str] = None
    is_active: bool = True

    image: str
    created_by_id: uuid.UUID
    publish_date: datetime
    show_current_date: bool = True

    description: Optional[str] = None
    document: Optional[str] = None

