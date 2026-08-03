"""
Business logic for users service
"""
from typing import Optional, List
from uuid import UUID
from sqlmodel import Session, or_, and_, func
from datetime import datetime

from app.models import User, AgentSetting, UserRequest
from app.schemas import UserCreate, UserUpdate


_PRIVILEGED_USER_FIELDS = ("is_staff", "is_superuser", "role_id", "permissions")


class UserService:
    """Service for user operations"""

    @staticmethod
    def create_user(db: Session, user_data: UserCreate, is_admin: bool = False) -> User:
        """Create a new user. Only an admin caller may set role_id/permissions -
        a non-admin request silently gets the default (non-privileged) values."""
        data = user_data.model_dump()
        if not is_admin:
            for field in _PRIVILEGED_USER_FIELDS:
                data.pop(field, None)
        user = User(**data)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def get_user(db: Session, user_id: UUID, tenant_id: UUID) -> Optional[User]:
        """Get user by ID"""
        return db.query(User).filter(
            User.id == user_id,
            User.tenant_id == tenant_id
        ).first()
    
    @staticmethod
    def get_user_by_email(db: Session, email: str, tenant_id: UUID) -> Optional[User]:
        """Get user by email"""
        return db.query(User).filter(
            User.email == email,
            User.tenant_id == tenant_id
        ).first()
    
    @staticmethod
    def list_users(
        db: Session,
        tenant_id: UUID,
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_superuser: Optional[bool] = None
    ) -> tuple[List[User], int]:
        """List users with pagination and filtering"""
        query = db.query(User).filter(User.tenant_id == tenant_id)
        
        if is_active is not None:
            query = query.filter(User.is_active == is_active)
            
        if is_superuser is not None:
            if is_superuser:
                # Super admins are users with is_superuser=True OR role_id=1
                query = query.filter(
                    or_(
                        User.is_superuser == True,
                        User.role_id == 1
                    )
                )
            else:
                # Agents are users who are NOT super admins
                query = query.filter(
                    and_(
                        User.is_superuser == False,
                        or_(User.role_id != 1, User.role_id.is_(None))
                    )
                )

        if search:
            query = query.filter(
                or_(
                    User.email.ilike(f"%{search}%"),
                    User.first_name.ilike(f"%{search}%"),
                    User.last_name.ilike(f"%{search}%"),
                    User.npn.ilike(f"%{search}%")
                )
            )
        
        total = query.count()
        users = query.offset(skip).limit(limit).all()
        
        return users, total
    
    @staticmethod
    def update_user(db: Session, user: User, user_data: UserUpdate, is_admin: bool = False) -> User:
        """Update user. Only an admin caller may change role_id/is_staff/
        is_superuser/permissions - a non-admin request has those silently
        dropped instead of applied, so a regular user can't escalate themself."""
        update_data = user_data.model_dump(exclude_unset=True)
        update_data.pop("opt_in_notes", None)
        if not is_admin:
            for field in _PRIVILEGED_USER_FIELDS:
                update_data.pop(field, None)

        for key, value in update_data.items():
            if hasattr(User, key):
                setattr(user, key, value)

        user.modified_at = datetime.utcnow()
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def delete_user(db: Session, user: User):
        """Delete user (soft delete by setting is_active = False)"""
        user.is_active = False
        user.modified_at = datetime.utcnow()
        db.add(user)
        db.commit()


class AgentSettingService:
    """Service for agent settings operations"""
    
    @staticmethod
    def get_or_create(db: Session, user_id: UUID, tenant_id: UUID) -> AgentSetting:
        """Get or create agent settings"""
        setting = db.query(AgentSetting).filter(
            AgentSetting.user_id == user_id,
            AgentSetting.tenant_id == tenant_id
        ).first()
        
        if not setting:
            setting = AgentSetting(
                user_id=user_id,
                tenant_id=tenant_id,
                settings={}
            )
            db.add(setting)
            db.commit()
            db.refresh(setting)
        
        return setting
    
    @staticmethod
    def update_settings(db: Session, setting: AgentSetting, new_settings: dict) -> AgentSetting:
        """Update agent settings"""
        setting.settings = new_settings
        setting.modified_at = datetime.utcnow()
        db.add(setting)
        db.commit()
        db.refresh(setting)
        return setting


class UserRequestService:
    """Service for user requests operations (Nest)"""
    
    @staticmethod
    def create_request(
        db: Session,
        user_id: UUID,
        tenant_id: UUID,
        request_type: str,
        data: dict,
        created_by_id: Optional[UUID] = None,
        notes: Optional[str] = None
    ) -> UserRequest:
        """Create a new user request"""
        request = UserRequest(
            user_id=user_id,
            tenant_id=tenant_id,
            request_type=request_type,
            data=data,
            created_by_id=created_by_id or user_id,
            notes=notes,
            status="pending"
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        return request
    
    @staticmethod
    def list_requests(
        db: Session,
        user_id: UUID,
        tenant_id: UUID,
        request_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[UserRequest], int]:
        """List user requests"""
        query = db.query(UserRequest).filter(
            UserRequest.user_id == user_id,
            UserRequest.tenant_id == tenant_id
        )
        
        if request_type:
            query = query.filter(UserRequest.request_type == request_type)
        
        if status:
            query = query.filter(UserRequest.status == status)
        
        total = query.count()
        requests = query.order_by(UserRequest.created_at.desc()).offset(skip).limit(limit).all()
        
        return requests, total
    
    @staticmethod
    def update_request(
        db: Session,
        request: UserRequest,
        data: Optional[dict] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
        reviewed_by_id: Optional[UUID] = None
    ) -> UserRequest:
        """Update a user request"""
        if data:
            request.data = data
        if status:
            request.status = status
            if status in ["approved", "rejected"]:
                request.reviewed_at = datetime.utcnow()
        if notes:
            request.notes = notes
        if reviewed_by_id:
            request.reviewed_by_id = reviewed_by_id
        
        request.modified_at = datetime.utcnow()
        db.add(request)
        db.commit()
        db.refresh(request)
        return request



