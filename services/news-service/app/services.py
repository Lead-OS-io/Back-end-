"""
Business logic for news service
"""
from typing import Optional, List
from uuid import UUID
from sqlmodel import Session, or_, and_
from datetime import datetime
import sqlalchemy as sa

from app.models import News, Banner, AdminNotification, Announcement
from app.schemas import (
    NewsCreate,
    NewsUpdate,
    BannerCreate,
    BannerUpdate,
    AdminNotificationCreate,
    AdminNotificationUpdate,
    AnnouncementCreate,
    AnnouncementUpdate,
)


class NewsService:
    """Service for news operations"""
    
    @staticmethod
    def create_news(db: Session, news_data: NewsCreate) -> News:
        """Create a news article"""
        news = News(**news_data.model_dump())
        db.add(news)
        db.commit()
        db.refresh(news)
        return news
    
    @staticmethod
    def get_news(db: Session, news_id: UUID, tenant_id: UUID) -> Optional[News]:
        """Get news by ID"""
        return db.query(News).filter(
            News.id == news_id,
            News.tenant_id == tenant_id
        ).first()
    
    @staticmethod
    def get_news_by_slug(db: Session, slug: str, tenant_id: UUID) -> Optional[News]:
        """Get news by slug"""
        return db.query(News).filter(
            News.slug == slug,
            News.tenant_id == tenant_id
        ).first()
    
    @staticmethod
    def list_news(
        db: Session,
        tenant_id: UUID,
        is_published: Optional[bool] = None,
        is_featured: Optional[bool] = None,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None
    ) -> tuple[List[News], int]:
        """List news articles with filters"""
        query = db.query(News).filter(News.tenant_id == tenant_id)
        
        if is_published is not None:
            query = query.filter(News.is_published == is_published)
        
        if is_featured is not None:
            query = query.filter(News.is_featured == is_featured)
        
        if category:
            query = query.filter(News.category == category)
        
        if search:
            query = query.filter(
                or_(
                    News.title.ilike(f"%{search}%"),
                    News.summary.ilike(f"%{search}%"),
                    News.content.ilike(f"%{search}%")
                )
            )
        
        total = query.count()
        news = query.order_by(
            News.is_pinned.desc(),
            News.published_at.desc()
        ).offset(skip).limit(limit).all()
        
        return news, total
    
    @staticmethod
    def update_news(db: Session, news: News, news_data: NewsUpdate) -> News:
        """Update news article"""
        update_data = news_data.model_dump(exclude_unset=True)
        
        # If publishing, set published_at
        if update_data.get("is_published") and not news.published_at:
            update_data["published_at"] = datetime.utcnow()
        
        for key, value in update_data.items():
            setattr(news, key, value)
        
        news.modified_at = datetime.utcnow()
        db.add(news)
        db.commit()
        db.refresh(news)
        return news
    
    @staticmethod
    def delete_news(db: Session, news: News):
        """Delete news article"""
        db.delete(news)
        db.commit()
    
    @staticmethod
    def increment_views(db: Session, news: News):
        """Increment views count atomically - a read-then-write here would
        lose increments under concurrent requests."""
        db.execute(
            sa.update(News).where(News.id == news.id).values(views_count=News.views_count + 1)
        )
        db.commit()
        db.refresh(news)


class BannerService:
    """Service for banner operations"""
    
    @staticmethod
    def create_banner(db: Session, banner_data: BannerCreate) -> Banner:
        """Create a banner"""
        banner = Banner(**banner_data.model_dump())
        db.add(banner)
        db.commit()
        db.refresh(banner)
        return banner
    
    @staticmethod
    def get_banner(db: Session, banner_id: UUID, tenant_id: UUID) -> Optional[Banner]:
        """Get banner by ID"""
        return db.query(Banner).filter(
            Banner.id == banner_id,
            Banner.tenant_id == tenant_id
        ).first()
    
    @staticmethod
    def list_banners(
        db: Session,
        tenant_id: UUID,
        is_active: Optional[bool] = None,
        position: Optional[str] = None,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[Banner], int]:
        """List banners with filters"""
        query = db.query(Banner).filter(Banner.tenant_id == tenant_id)
        
        if is_active is not None:
            query = query.filter(Banner.is_active == is_active)
        
        if position:
            query = query.filter(Banner.position == position)
        
        # Filter by schedule
        now = datetime.utcnow()
        query = query.filter(
            or_(
                Banner.start_date == None,
                Banner.start_date <= now
            )
        ).filter(
            or_(
                Banner.end_date == None,
                Banner.end_date >= now
            )
        )
        
        total = query.count()
        banners = query.order_by(Banner.display_order).offset(skip).limit(limit).all()
        
        return banners, total
    
    @staticmethod
    def get_active_banners(
        db: Session,
        tenant_id: UUID,
        position: Optional[str] = None
    ) -> List[Banner]:
        """Get currently active banners"""
        banners, _ = BannerService.list_banners(db, tenant_id, True, position, 0, 100)
        return banners
    
    @staticmethod
    def update_banner(db: Session, banner: Banner, banner_data: BannerUpdate) -> Banner:
        """Update banner"""
        update_data = banner_data.model_dump(exclude_unset=True)
        
        for key, value in update_data.items():
            setattr(banner, key, value)
        
        banner.modified_at = datetime.utcnow()
        db.add(banner)
        db.commit()
        db.refresh(banner)
        return banner
    
    @staticmethod
    def delete_banner(db: Session, banner: Banner):
        """Delete banner"""
        db.delete(banner)
        db.commit()
    
    @staticmethod
    def increment_impressions(db: Session, banner: Banner):
        """Increment impressions count atomically."""
        db.execute(
            sa.update(Banner).where(Banner.id == banner.id).values(impressions_count=Banner.impressions_count + 1)
        )
        db.commit()

    @staticmethod
    def increment_impressions_bulk(db: Session, banner_ids: List[UUID]):
        """One UPDATE for every banner shown in a single response, instead of
        a per-banner commit loop."""
        if not banner_ids:
            return
        db.execute(
            sa.update(Banner).where(Banner.id.in_(banner_ids)).values(impressions_count=Banner.impressions_count + 1)
        )
        db.commit()

    @staticmethod
    def increment_clicks(db: Session, banner: Banner):
        """Increment clicks count atomically."""
        db.execute(
            sa.update(Banner).where(Banner.id == banner.id).values(clicks_count=Banner.clicks_count + 1)
        )
        db.commit()


class AdminNotificationService:
    """Service for admin notifications (public.admin_notifications)"""

    @staticmethod
    def list_notifications(
        db: Session,
        type: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        active: Optional[bool] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[List[AdminNotification], int]:
        query = db.query(AdminNotification)

        if type:
            query = query.filter(AdminNotification.type == type)
        if category:
            query = query.filter(AdminNotification.category == category)
        if priority:
            query = query.filter(AdminNotification.priority == priority)
        if active is not None:
            query = query.filter(AdminNotification.active == active)
        if search:
            query = query.filter(
                or_(
                    AdminNotification.title.ilike(f"%{search}%"),
                    AdminNotification.description.ilike(f"%{search}%"),
                )
            )

        total = query.count()
        items = (
            query.order_by(AdminNotification.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    @staticmethod
    def get_notification(db: Session, notification_id: UUID) -> Optional[AdminNotification]:
        return db.query(AdminNotification).filter(AdminNotification.id == notification_id).first()

    @staticmethod
    def create_notification(
        db: Session, data: AdminNotificationCreate, created_by: UUID
    ) -> AdminNotification:
        now = datetime.utcnow()
        row = AdminNotification(
            **data.model_dump(),
            created_by=created_by,
            timestamp=now,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def update_notification(
        db: Session, row: AdminNotification, data: AdminNotificationUpdate
    ) -> AdminNotification:
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def toggle_notification(db: Session, row: AdminNotification, active: bool) -> AdminNotification:
        row.active = active
        row.updated_at = datetime.utcnow()
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def delete_notification(db: Session, row: AdminNotification):
        db.delete(row)
        db.commit()


class AnnouncementService:
    """
    Service for Desk announcements (public.announcement).

    IMPORTANT:
    - Legacy table has no tenant_id; we still require X-Tenant-Id for request context,
      but we cannot filter by tenant at DB level.
    """

    @staticmethod
    def list_announcements(
        db: Session,
        active: Optional[bool] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[Announcement], int]:
        query = db.query(Announcement)
        if active is not None:
            query = query.filter(Announcement.is_active == active)
        if search:
            query = query.filter(
                or_(
                    Announcement.content.ilike(f"%{search}%"),
                    Announcement.description.ilike(f"%{search}%"),
                )
            )
        total = query.count()
        rows = query.order_by(Announcement.publish_date.desc(), Announcement.id.desc()).offset(skip).limit(limit).all()
        return rows, total

    @staticmethod
    def get_announcement(db: Session, announcement_id: int) -> Optional[Announcement]:
        return db.query(Announcement).filter(Announcement.id == announcement_id).first()

    @staticmethod
    def _next_id(db: Session) -> int:
        # Legacy table has no sequence/default for id.
        val = db.execute(sa.text("SELECT COALESCE(MAX(id), 0) + 1 FROM public.announcement")).scalar()
        try:
            return int(val)
        except Exception:
            return 1

    @staticmethod
    def create_announcement(db: Session, data: AnnouncementCreate, created_by_id: UUID) -> Announcement:
        now = datetime.utcnow()
        new_id = AnnouncementService._next_id(db)
        row = Announcement(
            id=new_id,
            content=data.content,
            description=data.description,
            image=data.image,
            document=data.document,
            publish_date=data.publish_date,
            show_current_date=data.show_current_date,
            is_active=data.is_active,
            created_by_id=created_by_id,
            created_at=now,
            modified_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def update_announcement(db: Session, row: Announcement, data: AnnouncementUpdate) -> Announcement:
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(row, key, value)
        row.modified_at = datetime.utcnow()
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def delete_announcement(db: Session, row: Announcement) -> None:
        db.delete(row)
        db.commit()


