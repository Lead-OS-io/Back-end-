"""
API routes for news service
"""
from typing import Optional, Generator
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from app.redis_cache import cached
from sqlmodel import Session
from sqlalchemy import text
import jwt
import math

from app.database import engine
from app.config import settings
from app.services import NewsService, BannerService, AdminNotificationService, AnnouncementService
from app.schemas import (
    NewsCreate, NewsUpdate, NewsResponse, NewsListResponse,
    BannerCreate, BannerUpdate, BannerResponse, BannerListResponse,
    AdminNotificationCreate, AdminNotificationUpdate, AdminNotificationResponse, AdminNotificationToggle,
    AnnouncementCreate, AnnouncementUpdate, AnnouncementResponse,
)

router = APIRouter()


def verify_token(authorization: str = Header(...)):
    """Verify JWT signature and return the payload"""
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")


def get_tenant_id(
    x_tenant_id: str = Header(...),
    token: dict = Depends(verify_token),
) -> UUID:
    """Resolve tenant from X-Tenant-ID and enforce it matches the JWT tenant_id claim."""
    try:
        header_tenant = UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID header")

    token_tenant = token.get("tenant_id")
    if not token_tenant:
        raise HTTPException(status_code=401, detail="Token missing tenant_id")
    if str(header_tenant) != str(token_tenant):
        raise HTTPException(status_code=403, detail="X-Tenant-ID does not match token tenant_id")
    return header_tenant


def get_tenant_db(tenant_id: UUID = Depends(get_tenant_id)) -> Generator[Session, None, None]:
    """Same session as get_db, but scoped to the validated tenant for RLS:
    sets the app.tenant_id GUC read by the policies in db/rls_policies.sql.
    Harmless no-op until that SQL is applied (see db/README.md)."""
    with Session(engine) as session:
        session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        yield session


def require_admin(
    token: dict = Depends(verify_token),
) -> dict:
    """
    Admin-only guard. We accept multiple token shapes used across envs, but
    only claims from the signature-verified token - X-User-Is-Superuser/
    X-User-Is-Staff/X-User-Role-Id are client-supplied headers and were
    previously trusted as a fallback, letting any authenticated caller
    self-declare admin.
    """
    is_superuser = bool(token.get("is_superuser") or token.get("superuser"))
    is_staff = bool(token.get("is_staff") or token.get("staff"))
    role_id = token.get("role_id") or token.get("role") or token.get("rid")

    try:
        role_id_int = int(role_id) if role_id is not None else None
    except Exception:
        role_id_int = None

    if not (is_superuser or is_staff or role_id_int in (1, 2, 3, 4)):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return token


# =============================================================================
# ANNOUNCEMENTS (Desk)
# =============================================================================


@router.get("/api/announcements", response_model=list[AnnouncementResponse])
@cached(ttl=600, prefix="announcements")
def list_announcements(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db),
):
    skip = (page - 1) * size
    rows, _total = AnnouncementService.list_announcements(
        db=db, active=active, search=search, skip=skip, limit=size
    )
    return rows


@router.get("/api/announcements/{announcement_id}", response_model=AnnouncementResponse)
@cached(ttl=600, prefix="announcement_detail")
def get_announcement(
    request: Request,
    announcement_id: int,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db),
):
    row = AnnouncementService.get_announcement(db, announcement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return row


@router.post("/api/announcements", response_model=AnnouncementResponse, status_code=201)
def create_announcement(
    data: AnnouncementCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    sub = token.get("sub")
    try:
        user_id = UUID(str(sub))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token sub")
    return AnnouncementService.create_announcement(db, data, created_by_id=user_id)


@router.put("/api/announcements/{announcement_id}", response_model=AnnouncementResponse)
def update_announcement(
    announcement_id: int,
    data: AnnouncementUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AnnouncementService.get_announcement(db, announcement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return AnnouncementService.update_announcement(db, row, data)


@router.delete("/api/announcements/{announcement_id}", status_code=204)
def delete_announcement(
    announcement_id: int,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AnnouncementService.get_announcement(db, announcement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found")
    AnnouncementService.delete_announcement(db, row)
    return None


@router.patch("/api/announcements/{announcement_id}/publish", response_model=AnnouncementResponse)
def publish_announcement(
    announcement_id: int,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AnnouncementService.get_announcement(db, announcement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return AnnouncementService.update_announcement(db, row, AnnouncementUpdate(is_active=True))


@router.patch("/api/announcements/{announcement_id}/unpublish", response_model=AnnouncementResponse)
def unpublish_announcement(
    announcement_id: int,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AnnouncementService.get_announcement(db, announcement_id)
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return AnnouncementService.update_announcement(db, row, AnnouncementUpdate(is_active=False))


# =============================================================================
# NEWS CRUD ENDPOINTS
# =============================================================================

@router.post("/api/news", response_model=NewsResponse, status_code=201)
def create_news(
    news_data: NewsCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Create a news article"""
    if str(news_data.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=400, detail="Tenant ID mismatch")
    
    news = NewsService.create_news(db, news_data)
    return news


@router.get("/api/news/{news_id}", response_model=NewsResponse)
def get_news(
    request: Request,
    news_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Get news by ID and increment views"""
    news = NewsService.get_news(db, news_id, tenant_id)
    if not news:
        raise HTTPException(status_code=404, detail="News not found")
    
    # Increment views
    NewsService.increment_views(db, news)
    
    return news


@router.get("/api/news/slug/{slug}", response_model=NewsResponse)
def get_news_by_slug(
    request: Request,
    slug: str,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Get news by slug and increment views"""
    news = NewsService.get_news_by_slug(db, slug, tenant_id)
    if not news:
        raise HTTPException(status_code=404, detail="News not found")
    
    # Increment views
    NewsService.increment_views(db, news)
    
    return news


@router.get("/api/news", response_model=NewsListResponse)
@cached(ttl=1800, prefix="news_list")
def list_news(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    is_published: Optional[bool] = Query(None),
    is_featured: Optional[bool] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """List news articles with filters"""
    skip = (page - 1) * size
    news_list, total = NewsService.list_news(
        db, tenant_id, is_published, is_featured, category, skip, size, search
    )
    
    return NewsListResponse(
        items=news_list,
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total > 0 else 0
    )


@router.put("/api/news/{news_id}", response_model=NewsResponse)
def update_news(
    news_id: UUID,
    news_data: NewsUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Update news article"""
    news = NewsService.get_news(db, news_id, tenant_id)
    if not news:
        raise HTTPException(status_code=404, detail="News not found")
    
    updated_news = NewsService.update_news(db, news, news_data)
    return updated_news


@router.delete("/api/news/{news_id}", status_code=204)
def delete_news(
    news_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Delete news article"""
    news = NewsService.get_news(db, news_id, tenant_id)
    if not news:
        raise HTTPException(status_code=404, detail="News not found")
    
    NewsService.delete_news(db, news)
    return None


# =============================================================================
# BANNER CRUD ENDPOINTS
# =============================================================================

@router.post("/api/banners", response_model=BannerResponse, status_code=201)
def create_banner(
    banner_data: BannerCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Create a banner"""
    if str(banner_data.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=400, detail="Tenant ID mismatch")
    
    banner = BannerService.create_banner(db, banner_data)
    return banner


@router.get("/api/banners/{banner_id}", response_model=BannerResponse)
@cached(ttl=600, prefix="banner_detail")
def get_banner(
    request: Request,
    banner_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Get banner by ID"""
    banner = BannerService.get_banner(db, banner_id, tenant_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")
    return banner


@router.get("/api/banners", response_model=BannerListResponse)
@cached(ttl=1800, prefix="banners_list")
def list_banners(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = Query(None),
    position: Optional[str] = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """List banners with filters"""
    skip = (page - 1) * size
    banners, total = BannerService.list_banners(
        db, tenant_id, is_active, position, skip, size
    )
    
    return BannerListResponse(
        items=banners,
        total=total,
        page=page,
        size=size
    )


@router.get("/api/banners/active", response_model=BannerListResponse)
def get_active_banners(
    request: Request,
    position: Optional[str] = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Get currently active banners"""
    banners = BannerService.get_active_banners(db, tenant_id, position)
    BannerService.increment_impressions_bulk(db, [b.id for b in banners])

    return BannerListResponse(
        items=banners,
        total=len(banners),
        page=1,
        size=len(banners)
    )


@router.put("/api/banners/{banner_id}", response_model=BannerResponse)
def update_banner(
    banner_id: UUID,
    banner_data: BannerUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Update banner"""
    banner = BannerService.get_banner(db, banner_id, tenant_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")
    
    updated_banner = BannerService.update_banner(db, banner, banner_data)
    return updated_banner


@router.delete("/api/banners/{banner_id}", status_code=204)
def delete_banner(
    banner_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Delete banner"""
    banner = BannerService.get_banner(db, banner_id, tenant_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")
    
    BannerService.delete_banner(db, banner)
    return None


@router.post("/api/banners/{banner_id}/click", status_code=204)
def track_banner_click(
    banner_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Track banner click"""
    banner = BannerService.get_banner(db, banner_id, tenant_id)
    if not banner:
        raise HTTPException(status_code=404, detail="Banner not found")
    
    BannerService.increment_clicks(db, banner)
    return None


# =============================================================================
# ADMIN NOTIFICATIONS (Desk)
# =============================================================================

@router.get("/api/admin/notifications", response_model=list[AdminNotificationResponse])
@cached(ttl=1800, prefix="admin_notifs_list")
def list_admin_notifications(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    skip = (page - 1) * per_page
    items, _total = AdminNotificationService.list_notifications(
        db=db,
        type=type,
        category=category,
        priority=priority,
        active=active,
        search=search,
        skip=skip,
        limit=per_page,
    )
    return items


@router.post("/api/admin/notifications", response_model=AdminNotificationResponse, status_code=201)
def create_admin_notification(
    data: AdminNotificationCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    sub = token.get("sub")
    try:
        user_id = UUID(str(sub))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token sub")
    return AdminNotificationService.create_notification(db, data, created_by=user_id)


@router.get("/api/admin/notifications/{notification_id}", response_model=AdminNotificationResponse)
@cached(ttl=1800, prefix="admin_notif_detail")
def get_admin_notification(
    request: Request,
    notification_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AdminNotificationService.get_notification(db, notification_id)
    if not row:
        raise HTTPException(status_code=404, detail="Admin notification not found")
    return row


@router.put("/api/admin/notifications/{notification_id}", response_model=AdminNotificationResponse)
def update_admin_notification(
    notification_id: UUID,
    data: AdminNotificationUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AdminNotificationService.get_notification(db, notification_id)
    if not row:
        raise HTTPException(status_code=404, detail="Admin notification not found")
    return AdminNotificationService.update_notification(db, row, data)


@router.delete("/api/admin/notifications/{notification_id}", status_code=204)
def delete_admin_notification(
    notification_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AdminNotificationService.get_notification(db, notification_id)
    if not row:
        raise HTTPException(status_code=404, detail="Admin notification not found")
    AdminNotificationService.delete_notification(db, row)
    return None


@router.patch("/api/admin/notifications/{notification_id}/toggle", response_model=AdminNotificationResponse)
def toggle_admin_notification(
    notification_id: UUID,
    data: AdminNotificationToggle,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(require_admin),
    db: Session = Depends(get_tenant_db),
):
    row = AdminNotificationService.get_notification(db, notification_id)
    if not row:
        raise HTTPException(status_code=404, detail="Admin notification not found")
    return AdminNotificationService.toggle_notification(db, row, active=data.active)


@router.get("/api/admin-notifications/active", response_model=list[AdminNotificationResponse])
@cached(ttl=300, prefix="admin_notifs")
def list_active_admin_notifications_for_users(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    type: Optional[str] = Query(None, description="alert | reminder | news"),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Read-only feed of ACTIVE admin notifications for all authenticated users.
    Used by desk_app dashboard to avoid direct DB access to `public.admin_notifications`.
    """
    items, _total = AdminNotificationService.list_notifications(
        db=db,
        type=type,
        category=None,
        priority=None,
        active=True,
        search=None,
        skip=0,
        limit=limit,
    )
    return items

