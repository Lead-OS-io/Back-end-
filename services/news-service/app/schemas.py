from uuid import UUID
"""
Pydantic schemas for news service
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
# =============================================================================
# NEWS SCHEMAS
# =============================================================================

class NewsBase(BaseModel):
    title: str
    slug: Optional[str] = None
    summary: Optional[str] = None
    content: str
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    author_name: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_featured: Optional[bool] = False
    is_pinned: Optional[bool] = False
    metadata: Optional[Dict[str, Any]] = None


class NewsCreate(NewsBase):
    tenant_id: UUID
    author_id: Optional[UUID] = None


class NewsUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_published: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_pinned: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class NewsResponse(NewsBase):
    id: UUID
    tenant_id: UUID
    author_id: Optional[UUID]
    is_published: bool
    published_at: Optional[datetime]
    views_count: int
    created_at: datetime
    modified_at: datetime
    
    class Config:
        from_attributes = True


class NewsListResponse(BaseModel):
    items: List[NewsResponse]
    total: int
    page: int
    size: int
    pages: int


# =============================================================================
# BANNER SCHEMAS
# =============================================================================

class BannerBase(BaseModel):
    title: str
    description: Optional[str] = None
    image_url: str
    mobile_image_url: Optional[str] = None
    link_url: Optional[str] = None
    link_target: Optional[str] = "_blank"
    position: Optional[str] = "top"
    display_order: Optional[int] = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    target_audience: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class BannerCreate(BannerBase):
    tenant_id: UUID


class BannerUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    mobile_image_url: Optional[str] = None
    link_url: Optional[str] = None
    link_target: Optional[str] = None
    position: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    target_audience: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class BannerResponse(BannerBase):
    id: UUID
    tenant_id: UUID
    is_active: bool
    impressions_count: int
    clicks_count: int
    created_at: datetime
    modified_at: datetime
    
    class Config:
        from_attributes = True


class BannerListResponse(BaseModel):
    items: List[BannerResponse]
    total: int
    page: int
    size: int


# =============================================================================
# ADMIN NOTIFICATIONS (Desk) SCHEMAS
# =============================================================================


class AdminNotificationBase(BaseModel):
    title: str
    description: str
    type: str
    category: str
    priority: str
    icon: str = "bell"
    active: bool = True


class AdminNotificationCreate(AdminNotificationBase):
    pass


class AdminNotificationUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    icon: Optional[str] = None
    active: Optional[bool] = None


class AdminNotificationResponse(AdminNotificationBase):
    id: UUID
    timestamp: datetime
    created_at: datetime
    updated_at: datetime
    created_by: UUID

    class Config:
        from_attributes = True


class AdminNotificationToggle(BaseModel):
    active: bool


# =============================================================================
# ANNOUNCEMENTS (Desk) SCHEMAS
# =============================================================================


class AnnouncementBase(BaseModel):
    content: Optional[str] = None
    description: Optional[str] = None
    image: str
    document: Optional[str] = None
    publish_date: datetime
    show_current_date: bool = True
    is_active: bool = True


class AnnouncementCreate(AnnouncementBase):
    pass


class AnnouncementUpdate(BaseModel):
    content: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    document: Optional[str] = None
    publish_date: Optional[datetime] = None
    show_current_date: Optional[bool] = None
    is_active: Optional[bool] = None


class AnnouncementResponse(AnnouncementBase):
    id: int
    created_by_id: UUID
    created_at: datetime
    modified_at: datetime

    class Config:
        from_attributes = True


