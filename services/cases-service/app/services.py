"""
Cases Service Business Logic.
"""
import logging
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
import uuid

from sqlmodel import Session, select, func
from sqlalchemy import Table, MetaData, select as sa_select, insert as sa_insert, update as sa_update

from app.models import CaseData, CaseStatus, Draft, CaseHistory

logger = logging.getLogger(__name__)


class CaseService:
    """Case management service."""
    
    def __init__(self, db: Session, tenant_id: uuid.UUID, user_id: Optional[str] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
    
    def create_case(
        self,
        agent_id: uuid.UUID,
        **case_data,
    ) -> CaseData:
        """Create a new case."""
        case = CaseData(
            tenant_id=self.tenant_id,
            agent_id=agent_id,
            status=CaseStatus.DRAFT,
            created_at=datetime.utcnow(),
            modified_at=datetime.utcnow(),
            **case_data,
        )
        
        self.db.add(case)
        self.db.commit()
        self.db.refresh(case)
        
        logger.info(f"Created case {case.id} for tenant {self.tenant_id}")
        return case
    
    def get_case(self, case_id: int) -> Optional[CaseData]:
        """Get case by ID."""
        case = self.db.get(CaseData, case_id)
        if case and case.tenant_id == self.tenant_id:
            return case
        return None
    
    def update_case(
        self,
        case_id: int,
        **updates,
    ) -> Optional[CaseData]:
        """Update a case."""
        from sqlalchemy.orm.attributes import flag_modified
        
        case = self.get_case(case_id)
        if not case:
            return None
        
        # Lista de campos JSON que necesitan flag_modified para que SQLAlchemy detecte cambios
        json_fields = {'common_details', 'general_information', 'mortgage_info', 'client_assessment', 
                       'financial_assessment', 'type_of_coverage', 'policy_and_banking', 'benificiaries'}
        
        for key, value in updates.items():
            if value is not None and hasattr(case, key):
                setattr(case, key, value)
                # Forzar que SQLAlchemy detecte el cambio en campos JSON
                if key in json_fields:
                    flag_modified(case, key)
        
        case.modified_at = datetime.utcnow()
        
        self.db.add(case)
        self.db.commit()
        self.db.refresh(case)
        
        return case
    
    def update_status(
        self,
        case_id: int,
        status: int,
        carrier_status_id: Optional[int] = None,
    ) -> Optional[CaseData]:
        """Update case status."""
        case = self.get_case(case_id)
        if not case:
            return None

        case.status = status
        if carrier_status_id is not None:
            case.carrier_status_id = carrier_status_id
        
        # Update timestamps based on status
        now = datetime.utcnow()
        case.modified_at = now
        
        if status == CaseStatus.SUBMITTED and not case.submitted_at:
            case.submitted_at = now
        elif status == CaseStatus.ISSUED and not case.issued_at:
            case.issued_at = now
        
        self.db.add(case)
        self.db.commit()
        self.db.refresh(case)

        return case
    
    def delete_case(self, case_id: int) -> bool:
        """Delete a case."""
        case = self.get_case(case_id)
        if not case:
            return False
        
        self.db.delete(case)
        self.db.commit()
        
        logger.info(f"Deleted case {case_id}")
        return True
    
    def bulk_delete(self, case_ids: List[int]) -> Dict[str, Any]:
        """Bulk delete cases."""
        deleted = 0
        failed = []
        
        for case_id in case_ids:
            if self.delete_case(case_id):
                deleted += 1
            else:
                failed.append(case_id)
        
        return {
            "deleted": deleted,
            "failed": failed,
        }
    
    def list_cases(
        self,
        page: int = 1,
        page_size: int = 50,
        status: Optional[int] = None,
        agent_id: Optional[uuid.UUID] = None,
        carrier_id: Optional[int] = None,
        search: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        order_by: str = "created_at",
        order_dir: str = "desc",
    ) -> tuple[List[CaseData], int]:
        """List cases with filters and pagination."""
        query = select(CaseData).where(CaseData.tenant_id == self.tenant_id)
        
        if status is not None:
            query = query.where(CaseData.status == status)
        if agent_id:
            query = query.where(CaseData.agent_id == agent_id)
        if carrier_id:
            query = query.where(CaseData.carrier_id == carrier_id)
        if start_date:
            query = query.where(CaseData.created_at >= start_date)
        if end_date:
            query = query.where(CaseData.created_at <= end_date)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (CaseData.client_first_name.ilike(search_term)) |
                (CaseData.client_last_name.ilike(search_term)) |
                (CaseData.client_email.ilike(search_term)) |
                (CaseData.policy_number.ilike(search_term))
            )
        
        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.exec(count_query).one()
        
        # Order - whitelist, since order_by is client-supplied and getattr()
        # on an arbitrary column name can hit a non-sortable attribute.
        _SORTABLE_COLUMNS = {
            "created_at": CaseData.created_at,
            "modified_at": CaseData.modified_at,
            "status": CaseData.status,
            "policy_number": CaseData.policy_number,
            "client1_name": CaseData.client1_name,
        }
        order_column = _SORTABLE_COLUMNS.get(order_by, CaseData.created_at)
        if order_dir == "desc":
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column.asc())
        
        # Paginate
        query = query.offset((page - 1) * page_size).limit(page_size)
        
        cases = self.db.exec(query).all()
        return cases, total

    # ==========================================================================
    # BOOK OF BUSINESS (Desk) - case-level filters only
    # ==========================================================================

    def book_of_business_filter_case_ids(
        self,
        *,
        search: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        policy_type: Optional[str] = None,
        own_only: bool = False,
        user_id: Optional[str] = None,
        limit: int = 50000,
    ) -> List[int]:
        """
        Returns case ids filtered only by fields stored on `public.cases`.
        Note: policy status/carrier filters come from premium-service.
        """
        from sqlalchemy import Text, cast

        q = select(CaseData.id).where(CaseData.tenant_id == self.tenant_id)

        # Desk behavior: treat NULL is_active as visible
        q = q.where((CaseData.is_active == True) | (CaseData.is_active.is_(None)))

        if date_from:
            q = q.where(CaseData.created_at >= date_from)
        if date_to:
            q = q.where(CaseData.created_at <= date_to)

        if own_only and user_id:
            try:
                uid = uuid.UUID(str(user_id))
                q = q.where((CaseData.created_by_id == uid) | (CaseData.agent_id == uid))
            except Exception:
                pass

        if search:
            st = f"%{search}%"
            q = q.where(
                (CaseData.name.ilike(st))
                | (CaseData.client1_name.ilike(st))
                | (CaseData.client2_name.ilike(st))
                | (CaseData.client1_email.ilike(st))
                | (CaseData.client2_email.ilike(st))
                | (CaseData.policy_number.ilike(st))
                | (cast(CaseData.general_information, Text).ilike(st))
            )

        # Policy type filter: legacy implementation does a text search inside policy_and_banking JSON
        if policy_type:
            pts = [p.strip() for p in str(policy_type).split(",") if p.strip()]
            if pts:
                # "Other" means not in a known list; keep parity with desk router
                specific_policy_types = [
                    "Full",
                    "Full Rop",
                    "Half",
                    "Half Rop",
                    "Equity Protection WL",
                    "Equity Protection Term",
                    "Equity Protection Term Rop",
                    "Term",
                    "Term Rop",
                    "Whole Life/Fex",
                    "IUL",
                    "Whole Life",
                    "Universal Life",
                    "Mortgage Protection",
                    "Accidental Death",
                ]
                pb_text = cast(CaseData.policy_and_banking, Text)

                if "Other" in pts:
                    # Exclude known policy types
                    known_conds = [pb_text.ilike(f'%"plan_type": "{t}"%') for t in specific_policy_types]
                    combined = known_conds[0]
                    for c in known_conds[1:]:
                        combined = combined | c
                    q = q.where(~combined)
                else:
                    conds = [pb_text.ilike(f'%"plan_type": "{t}"%') for t in pts]
                    combined = conds[0]
                    for c in conds[1:]:
                        combined = combined | c
                    q = q.where(combined)

        q = q.limit(max(1, min(int(limit), 50000)))
        rows = self.db.exec(q).all() or []
        return [int(r) for r in rows if r is not None]

    def book_of_business_query_cases(
        self,
        *,
        case_ids: List[int],
        page: int = 1,
        size: int = 10,
    ) -> tuple[List[CaseData], int]:
        """Paginate cases by id set (ordering by modified_at desc)."""
        if not case_ids:
            return [], 0

        page = max(1, int(page or 1))
        size = max(1, min(int(size or 10), 100))

        base = (
            select(CaseData)
            .where(CaseData.tenant_id == self.tenant_id)
            .where(CaseData.id.in_(case_ids))
        )

        # Total count
        count_q = select(func.count()).select_from(base.subquery())
        total = int(self.db.exec(count_q).one() or 0)

        # Order & paginate
        q = base.order_by(CaseData.modified_at.desc().nullslast(), CaseData.created_at.desc().nullslast())
        q = q.offset((page - 1) * size).limit(size)
        items = self.db.exec(q).all() or []
        return items, total

    def get_case_by_policy_number(self, *, policy_number: str) -> Optional[CaseData]:
        """Lookup by normalized policy_number (spaces/hyphens-insensitive)."""
        pn = (policy_number or "").strip()
        if not pn:
            return None
        norm = pn.upper().replace(" ", "").replace("-", "")
        q = select(CaseData).where(
            CaseData.tenant_id == self.tenant_id,
            func.upper(func.replace(func.replace(CaseData.policy_number, " ", ""), "-", "")) == norm,
        )
        return self.db.exec(q).first()

    def archive_case(self, *, case_id: int) -> bool:
        """Soft archive case (is_active=False)."""
        case = self.get_case(int(case_id))
        if not case:
            return False
        case.is_active = False
        case.modified_at = datetime.utcnow()
        self.db.add(case)
        self.db.commit()
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get case statistics."""
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)
        
        # Total
        total = self.db.exec(
            select(func.count()).where(CaseData.tenant_id == self.tenant_id)
        ).one()
        
        # By status
        status_counts = self.db.exec(
            select(CaseData.status, func.count())
            .where(CaseData.tenant_id == self.tenant_id)
            .group_by(CaseData.status)
        ).all()
        
        by_status = {str(s): c for s, c in status_counts}
        
        # This month
        this_month = self.db.exec(
            select(func.count()).where(
                CaseData.tenant_id == self.tenant_id,
                CaseData.created_at >= month_start,
            )
        ).one()
        
        # Last month
        last_month = self.db.exec(
            select(func.count()).where(
                CaseData.tenant_id == self.tenant_id,
                CaseData.created_at >= last_month_start,
                CaseData.created_at < month_start,
            )
        ).one()
        
        return {
            "total": total,
            "by_status": by_status,
            "by_carrier": {},  # Would need carrier data
            "this_month": this_month,
            "last_month": last_month,
        }

    # ==========================================================================
    # DASHBOARD QUERIES (source of truth: public.cases)
    # ==========================================================================

    def dashboard_open_cases(
        self,
        period: str = "month",
        compare: bool = True,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Open cases metric used by Desk dashboard.

        Notes:
        - Uses CaseData.status == 1 as "open / in progress" (legacy Desk behavior).
        - Restricts by tenant_id and optionally by created_by_id.
        """
        if period not in ("month", "week"):
            raise ValueError("period must be 'month' or 'week'")

        now = datetime.utcnow()
        current_period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if period == "week":
            days_since_monday = now.weekday()
            current_period_start = now - timedelta(days=days_since_monday)
            current_period_start = current_period_start.replace(hour=0, minute=0, second=0, microsecond=0)
        previous_period_start = (
            (current_period_start - timedelta(days=1)).replace(day=1)
            if period == "month"
            else current_period_start - timedelta(weeks=1)
        )

        base_filters = [
            CaseData.tenant_id == self.tenant_id,
            CaseData.is_active == True,
            CaseData.status == 1,
        ]
        if user_id:
            base_filters.append(CaseData.created_by_id == user_id)

        total_open_cases = self.db.exec(select(func.count(CaseData.id)).where(*base_filters)).one() or 0

        change_value = 0.0
        change_direction = "increase"
        if compare:
            current_filters = [
                CaseData.tenant_id == self.tenant_id,
                CaseData.is_active == True,
                CaseData.status == 1,
                CaseData.created_at >= current_period_start,
            ]
            previous_filters = [
                CaseData.tenant_id == self.tenant_id,
                CaseData.is_active == True,
                CaseData.status == 1,
                CaseData.created_at >= previous_period_start,
                CaseData.created_at < current_period_start,
            ]
            if user_id:
                current_filters.append(CaseData.created_by_id == user_id)
                previous_filters.append(CaseData.created_by_id == user_id)

            current_period_cases = self.db.exec(select(func.count(CaseData.id)).where(*current_filters)).one() or 0
            previous_period_cases = self.db.exec(select(func.count(CaseData.id)).where(*previous_filters)).one() or 0

            if previous_period_cases > 0:
                change_value = ((current_period_cases - previous_period_cases) / previous_period_cases) * 100
                change_direction = "increase" if change_value >= 0 else "decrease"
            elif current_period_cases > 0:
                change_value = 100.0
                change_direction = "increase"

        return {
            "total": int(total_open_cases),
            "change": {"value": round(abs(change_value), 2), "direction": change_direction},
            "asOf": now.replace(microsecond=0).isoformat() + "Z",
        }

    def dashboard_book_of_business_metric(
        self,
        period: str = "month",
        compare: bool = True,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Book of Business metric used by Desk dashboard.

        Legacy behavior (Desk): uses CaseData.status in (4,7,8) and sums counts.
        Optimized: Grouping queries to reduce calls from 9 to exactly 3.
        """
        if period not in ("month", "week"):
            raise ValueError("period must be 'month' or 'week'")

        now = datetime.utcnow()
        current_period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if period == "week":
            days_since_monday = now.weekday()
            current_period_start = now - timedelta(days=days_since_monday)
            current_period_start = current_period_start.replace(hour=0, minute=0, second=0, microsecond=0)
        previous_period_start = (
            (current_period_start - timedelta(days=1)).replace(day=1)
            if period == "month"
            else current_period_start - timedelta(weeks=1)
        )

        # 1. Total counts globally (1 query using GROUP BY)
        q_totals = (
            select(CaseData.status, func.count(CaseData.id).label("count"))
            .where(
                CaseData.tenant_id == self.tenant_id,
                CaseData.is_active == True,
                CaseData.status.in_([4, 7, 8])
            )
        )
        if user_id:
            q_totals = q_totals.where(CaseData.created_by_id == user_id)
        
        rows_totals = self.db.exec(q_totals.group_by(CaseData.status)).all()
        totals_map = {int(r.status): int(r.count) for r in rows_totals}
        
        issued = totals_map.get(4, 0)
        lapsed = totals_map.get(7, 0)
        pending_lapsed = totals_map.get(8, 0)
        total = issued + lapsed + pending_lapsed

        change_value = 0.0
        change_direction = "increase"
        if compare:
            # 2. Current period counts (1 query using GROUP BY)
            q_curr = (
                select(CaseData.status, func.count(CaseData.id).label("count"))
                .where(
                    CaseData.tenant_id == self.tenant_id,
                    CaseData.is_active == True,
                    CaseData.status.in_([4, 7, 8]),
                    CaseData.created_at >= current_period_start
                )
            )
            if user_id:
                q_curr = q_curr.where(CaseData.created_by_id == user_id)
            rows_curr = self.db.exec(q_curr.group_by(CaseData.status)).all()
            cur_total = sum(int(r.count) for r in rows_curr)

            # 3. Previous period counts (1 query using GROUP BY)
            q_prev = (
                select(CaseData.status, func.count(CaseData.id).label("count"))
                .where(
                    CaseData.tenant_id == self.tenant_id,
                    CaseData.is_active == True,
                    CaseData.status.in_([4, 7, 8]),
                    CaseData.created_at >= previous_period_start,
                    CaseData.created_at < current_period_start
                )
            )
            if user_id:
                q_prev = q_prev.where(CaseData.created_by_id == user_id)
            rows_prev = self.db.exec(q_prev.group_by(CaseData.status)).all()
            prev_total = sum(int(r.count) for r in rows_prev)

            if prev_total > 0:
                change_value = ((cur_total - prev_total) / prev_total) * 100
                change_direction = "increase" if change_value >= 0 else "decrease"
            elif cur_total > 0:
                change_value = 100.0
                change_direction = "increase"

        return {
            "total": int(total),
            "change": {"value": round(abs(change_value), 2), "direction": change_direction},
            "asOf": now.replace(microsecond=0).isoformat() + "Z",
            "issued": int(issued),
            "lapsed": int(lapsed),
            "pendingLapsed": int(pending_lapsed),
        }

    def dashboard_monthly_issued_policies(
        self,
        year: Optional[int] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        if year is None:
            year = datetime.utcnow().year
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)

        q = (
            select(
                func.date_trunc("month", CaseData.created_at).label("month"),
                func.count(CaseData.id).label("value"),
            )
            .where(
                CaseData.tenant_id == self.tenant_id,
                CaseData.is_active == True,
                CaseData.status == 4,
                CaseData.created_at >= start_date,
                CaseData.created_at <= end_date,
            )
            .group_by(func.date_trunc("month", CaseData.created_at))
            .order_by(func.date_trunc("month", CaseData.created_at))
        )
        if user_id:
            q = q.where(CaseData.created_by_id == user_id)
        rows = self.db.exec(q).all()

        month_data = {row.month.strftime("%b"): int(row.value) for row in rows}
        all_months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        series = [{"month": m, "value": int(month_data.get(m, 0))} for m in all_months]
        return {"year": int(year), "series": series}

    def dashboard_cases_by_status(
        self,
        period: str = "month",
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        if period not in ("month", "week"):
            raise ValueError("period must be 'month' or 'week'")

        now = datetime.utcnow()
        period_start = now - timedelta(days=30 if period == "month" else 7)
        excluded = [9, 10]

        base_filters = [
            CaseData.tenant_id == self.tenant_id,
            CaseData.is_active == True,
            CaseData.created_at >= period_start,
            CaseData.status.notin_(excluded),
        ]
        if user_id:
            base_filters.append(CaseData.created_by_id == user_id)

        total = int(self.db.exec(select(func.count(CaseData.id)).where(*base_filters)).one() or 0)

        q = (
            select(CaseData.status, func.count(CaseData.id).label("value"))
            .where(*base_filters)
            .group_by(CaseData.status)
            .order_by(func.count(CaseData.id).desc())
        )
        rows = self.db.exec(q).all()

        status_mapping = {
            1: {"label": "In Progress", "color": "#ff6b35"},
            2: {"label": "Submitted", "color": "#465fff"},
            3: {"label": "Hold", "color": "#d1d5db"},
            4: {"label": "Issued", "color": "#10b981"},
            5: {"label": "Hold", "color": "#d1d5db"},
            6: {"label": "Denied", "color": "#ef4444"},
            7: {"label": "Lapsed", "color": "#8b5cf6"},
            8: {"label": "Pending Lapse", "color": "#f59e0b"},
        }

        statuses = []
        for row in rows:
            status_id = int(row.status)
            info = status_mapping.get(status_id, {"label": f"Status {status_id}", "color": "#6b7280"})
            statuses.append({"label": info["label"], "value": int(row.value), "color": info["color"]})

        return {"total": total, "statuses": statuses, "asOf": now.replace(microsecond=0).isoformat() + "Z"}

    def dashboard_charts(
        self,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Charts endpoint (bar + donut) used by Desk dashboard.
        """
        now = datetime.utcnow()
        start_date = now - timedelta(days=365)

        bar_q = (
            select(
                func.date_trunc("month", CaseData.created_at).label("month"),
                func.count(CaseData.id).label("value"),
            )
            .where(
                CaseData.tenant_id == self.tenant_id,
                CaseData.is_active == True,
                CaseData.status == 4,
                CaseData.created_at >= start_date,
            )
            .group_by(func.date_trunc("month", CaseData.created_at))
            .order_by(func.date_trunc("month", CaseData.created_at))
        )
        donut_q = (
            select(CaseData.status, func.count(CaseData.id).label("value"))
            .where(
                CaseData.tenant_id == self.tenant_id,
                CaseData.is_active == True,
            )
            .group_by(CaseData.status)
            .order_by(func.count(CaseData.id).desc())
        )
        if user_id:
            bar_q = bar_q.where(CaseData.created_by_id == user_id)
            donut_q = donut_q.where(CaseData.created_by_id == user_id)

        bar_rows = self.db.exec(bar_q).all()
        donut_rows = self.db.exec(donut_q).all()

        bar_data = []
        for r in bar_rows:
            month_name = r.month.strftime("%b")
            month_label = r.month.strftime("%B")
            bar_data.append({"month": month_name, "value": int(r.value), "label": month_label})

        # Reuse same label mapping as Desk
        status_mapping = {
            1: {"label": "In Progress", "color": "#465fff"},
            2: {"label": "Submitted", "color": "#F59E0B"},
            3: {"label": "Hold", "color": "#EF4444"},
            4: {"label": "Issued", "color": "#10B981"},
            5: {"label": "Hold", "color": "#EF4444"},
            6: {"label": "Denied", "color": "#DC2626"},
            7: {"label": "Lapsed", "color": "#D97706"},
            8: {"label": "Pending Lapse", "color": "#D97706"},
        }

        donut_data = []
        for r in donut_rows:
            sid = int(r.status) if r.status is not None else 0
            info = status_mapping.get(sid, {"label": str(sid), "color": "#6B7280"})
            donut_data.append({"label": info["label"], "value": int(r.value), "color": info["color"]})

        return {"data": {"barData": bar_data, "donutData": donut_data}}

    def dashboard_recent_cases(
        self,
        limit: int = 20,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Minimal payload for dashboard reminders.
        """
        limit = max(1, min(int(limit or 20), 100))
        q = (
            select(
                CaseData.id, 
                CaseData.name, 
                CaseData.created_at,
                CaseData.status,
                CaseData.client1_name,
                CaseData.client1_email
            )
            .where(CaseData.tenant_id == self.tenant_id, CaseData.is_active == True)
            .order_by(CaseData.created_at.desc())
            .limit(limit)
        )
        if user_id:
            q = q.where(CaseData.created_by_id == user_id)
        rows = self.db.exec(q).all()
        items = []
        for r in rows:
            items.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "created_at": (r.created_at.isoformat() if getattr(r.created_at, "isoformat", None) else None),
                    "status": r.status,
                    "client1_name": r.client1_name,
                    "client1_email": r.client1_email,
                }
            )
        return {"items": items}


class DraftService:
    """Draft persistence (source of truth: public.drafts)."""

    _TABLE_CACHE: Dict[int, Table] = {}

    def __init__(self, db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _drafts_table(self) -> Table:
        bind = self.db.get_bind()
        key = id(bind)
        t = self._TABLE_CACHE.get(key)
        if t is not None:
            return t
        md = MetaData()
        t = Table("drafts", md, schema="public", autoload_with=bind)
        self._TABLE_CACHE[key] = t
        return t

    def _legacy_schema(self) -> bool:
        t = self._drafts_table()
        return "tenant_id" not in {c.name for c in t.columns}

    def _parse_jsonish(self, v: Any) -> Any:
        if v is None:
            return {}
        if isinstance(v, (dict, list)):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return {}
            try:
                return json.loads(s)
            except Exception:
                return {}
        return {}

    def _row_to_draft(self, row: Dict[str, Any]) -> Draft:
        return Draft(
            id=str(row.get("id")),
            tenant_id=self.tenant_id,
            user_id=row.get("user_id") or self.user_id,
            draft_data=self._parse_jsonish(row.get("draft_data")),
            section_completion_status=self._parse_jsonish(row.get("section_completion_status")),
            created_at=row.get("created_at") or datetime.utcnow(),
            updated_at=row.get("updated_at") or datetime.utcnow(),
            expires_at=row.get("expires_at") or (datetime.utcnow() + timedelta(days=30)),
            version=int(row.get("version") or 1),
            is_active=bool(row.get("is_active", True)),
            last_section_updated=row.get("last_section_updated"),
        )

    def _filter_values(self, t: Table, values: Dict[str, Any]) -> Dict[str, Any]:
        cols = {c.name for c in t.columns}
        return {k: v for k, v in (values or {}).items() if k in cols}

    def list_active(self) -> List[Draft]:
        if not self._legacy_schema():
            q = (
                select(Draft)
                .where(
                    Draft.tenant_id == self.tenant_id,
                    Draft.user_id == self.user_id,
                    Draft.is_active == True,  # noqa: E712
                )
                .order_by(Draft.updated_at.desc())
            )
            return self.db.exec(q).all()

        t = self._drafts_table()
        q = sa_select(t).where(t.c.user_id == self.user_id)
        if "is_active" in t.c:
            q = q.where(t.c.is_active == True)  # noqa: E712
        if "updated_at" in t.c:
            q = q.order_by(t.c.updated_at.desc())
        rows = self.db.execute(q).mappings().all()
        return [self._row_to_draft(dict(r)) for r in rows]

    def get(self, draft_id: str) -> Optional[Draft]:
        if not self._legacy_schema():
            d = self.db.get(Draft, draft_id)
            if not d:
                return None
            if d.tenant_id != self.tenant_id or d.user_id != self.user_id:
                return None
            if not d.is_active:
                return None
            return d

        t = self._drafts_table()
        q = sa_select(t).where(t.c.id == str(draft_id), t.c.user_id == self.user_id)
        if "is_active" in t.c:
            q = q.where(t.c.is_active == True)  # noqa: E712
        row = self.db.execute(q).mappings().first()
        if not row:
            return None
        return self._row_to_draft(dict(row))

    def upsert(
        self,
        *,
        draft_id: Optional[str],
        draft_data: Dict[str, Any],
        section_completion_status: Dict[str, Any],
        last_section_updated: Optional[str],
        is_active: bool,
    ) -> Draft:
        if not self._legacy_schema():
            d: Optional[Draft] = None
            if draft_id:
                d = self.get(draft_id)

            if not d:
                d = Draft(
                    id=draft_id or str(uuid.uuid4()),
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    draft_data=draft_data or {},
                    section_completion_status=section_completion_status or {},
                    is_active=bool(is_active),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    version=1,
                    last_section_updated=last_section_updated,
                )
                self.db.add(d)
                self.db.commit()
                self.db.refresh(d)
                return d

            d.draft_data = draft_data or {}
            d.section_completion_status = section_completion_status or {}
            d.is_active = bool(is_active)
            d.bump(last_section_updated=last_section_updated)
            self.db.add(d)
            self.db.commit()
            self.db.refresh(d)
            return d

        t = self._drafts_table()
        now = datetime.utcnow()
        expires_at = now + timedelta(days=30)
        did = str(draft_id or uuid.uuid4())

        existing = None
        if draft_id:
            q = sa_select(t).where(t.c.id == did, t.c.user_id == self.user_id)
            existing = self.db.execute(q).mappings().first()

        if not existing:
            values = {
                "id": did,
                "user_id": self.user_id,
                "draft_data": draft_data or {},
                "section_completion_status": section_completion_status or {},
                "created_at": now,
                "updated_at": now,
                "expires_at": expires_at,
                "version": 1,
                "is_active": bool(is_active),
                "last_section_updated": last_section_updated,
            }
            stmt = sa_insert(t).values(**self._filter_values(t, values))
            self.db.execute(stmt)
            self.db.commit()
        else:
            next_version = None
            if "version" in t.c:
                try:
                    next_version = int(existing.get("version") or 0) + 1
                except Exception:
                    next_version = 1

            values = {
                "draft_data": draft_data or {},
                "section_completion_status": section_completion_status or {},
                "updated_at": now,
                "expires_at": expires_at,
                "is_active": bool(is_active),
                "last_section_updated": last_section_updated,
            }
            if next_version is not None:
                values["version"] = next_version

            stmt = sa_update(t).where(t.c.id == did, t.c.user_id == self.user_id).values(**self._filter_values(t, values))
            self.db.execute(stmt)
            self.db.commit()

        row = self.db.execute(sa_select(t).where(t.c.id == did, t.c.user_id == self.user_id)).mappings().first()
        if not row:
            return Draft(
                id=did,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                draft_data=draft_data or {},
                section_completion_status=section_completion_status or {},
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
                version=1,
                is_active=bool(is_active),
                last_section_updated=last_section_updated,
            )
        return self._row_to_draft(dict(row))

    def soft_delete(self, draft_id: str) -> bool:
        if not self._legacy_schema():
            d = self.get(draft_id)
            if not d:
                return False
            d.is_active = False
            d.bump()
            self.db.add(d)
            self.db.commit()
            return True

        t = self._drafts_table()
        now = datetime.utcnow()
        values = {"is_active": False, "updated_at": now, "expires_at": now + timedelta(days=30)}
        stmt = sa_update(t).where(t.c.id == str(draft_id), t.c.user_id == self.user_id).values(**self._filter_values(t, values))
        res = self.db.execute(stmt)
        self.db.commit()
        return bool(getattr(res, "rowcount", 0))

    def bulk_soft_delete(self, draft_ids: List[str]) -> Dict[str, Any]:
        deleted = 0
        failed: List[str] = []
        for did in draft_ids or []:
            if self.soft_delete(str(did)):
                deleted += 1
            else:
                failed.append(str(did))
        return {"deleted": deleted, "failed": failed}


class CaseHistoryService:
    """Case history (source of truth: public.cases_history via cases-service)."""

    def __init__(self, db: Session, tenant_id: uuid.UUID):
        self.db = db
        self.tenant_id = tenant_id

    def _get_case(self, case_id: int) -> Optional[CaseData]:
        case = self.db.get(CaseData, case_id)
        if not case or case.tenant_id != self.tenant_id:
            return None
        return case

    def list_for_case(self, case_id: int, limit: int = 100) -> List[CaseHistory]:
        limit = max(1, min(int(limit or 100), 500))
        q = (
            select(CaseHistory)
            .where(CaseHistory.id == int(case_id))
            .order_by(CaseHistory.history_date.desc())
            .limit(limit)
        )
        return self.db.exec(q).all()

    def create_snapshot(
        self,
        *,
        case_id: int,
        history_type: str,
        history_change_reason: Optional[str],
        history_user_id: Optional[uuid.UUID],
    ) -> CaseHistory:
        case = self._get_case(case_id)
        if not case:
            raise ValueError("Case not found")

        now = datetime.utcnow()

        # Ensure history_id is always present even if the legacy table lacks a sequence.
        next_history_id = int(
            self.db.exec(select(func.coalesce(func.max(CaseHistory.history_id), 0) + 1)).one() or 1
        )

        row = CaseHistory(
            id=int(case.id),
            history_id=next_history_id,
            created_at=case.created_at or now,
            modified_at=case.modified_at or now,
            name=case.name,
            date=getattr(case, "date", None) or date.today(),
            mortgage_info=getattr(case, "mortgage_info", None) or {},
            client_assessment=getattr(case, "client_assessment", None) or {},
            financial_assessment=getattr(case, "financial_assessment", None) or {},
            type_of_coverage=getattr(case, "type_of_coverage", None) or {},
            general_information=getattr(case, "general_information", None) or {},
            policy_and_banking=getattr(case, "policy_and_banking", None) or {},
            benificiaries=getattr(case, "benificiaries", None) or {},
            common_details=getattr(case, "common_details", None) or {},
            status=int(getattr(case, "status", 0) or 0),
            is_active=bool(getattr(case, "is_active", True)),
            history_date=now,
            history_change_reason=history_change_reason,
            history_type=(history_type or "~")[:1],
            created_by_id=getattr(case, "created_by_id", None),
            history_user_id=history_user_id,
            is_completed=bool(getattr(case, "is_completed", False)),
            approved_policy_doc=getattr(case, "approved_policy_doc", None),
            policy_approval_confirmation_send=bool(getattr(case, "policy_approval_confirmation_send", False)),
            policy_doc=getattr(case, "policy_doc", None),
            policy_number=getattr(case, "policy_number", None),
            policy_submit_confirmation_send=bool(getattr(case, "policy_submit_confirmation_send", False)),
            tag=getattr(case, "tag", None),
            client1_dob=getattr(case, "client1_dob", None),
            client1_email=getattr(case, "client1_email", None),
            client1_name=getattr(case, "client1_name", None),
            client2_dob=getattr(case, "client2_dob", None),
            client2_email=getattr(case, "client2_email", None),
            client2_name=getattr(case, "client2_name", None),
            have_two_clients=bool(getattr(case, "have_two_clients", False)),
        )

        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
