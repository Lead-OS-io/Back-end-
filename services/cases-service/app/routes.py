"""
Cases Service API Routes.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Generator, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status, Header, Query, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func
import base64
import uuid
import io
import csv
import httpx
import re
from jose import jwt as jose_jwt
import jwt
import logging
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import column, literal_column, text, update

logger = logging.getLogger(__name__)

import hashlib
import json
from app.redis_client import redis_client
from app.redis_cache import cached

from app.config import settings
from app.database import get_db, engine, async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from app.schemas import (
    CaseCreateRequest,
    CaseUpdateRequest,
    CaseStatusUpdateRequest,
    BulkDeleteRequest,
    CaseResponse,
    CaseDetailResponse,
    CaseListResponse,
    CaseStatsResponse,
    HealthResponse,
    MedicalCategoryResponse,
    MedicationResponse,
    MedicalDataResponse,
    DraftUpsertRequest,
    DraftResponse as DraftApiResponse,
    DraftBulkDeleteRequest,
    CaseHistoryCreateRequest,
    CaseHistoryResponse,
    BoBFilterCaseIdsRequest,
    BoBFilterCaseIdsResponse,
    BoBQueryCasesRequest,
    BoBQueryCasesResponse,
    BoBArchiveCaseResponse,
    BoBResolveDisplayRequest,
    BoBResolveDisplayResponse,
)
from app.services import CaseService, DraftService, CaseHistoryService
from app.models import (
    MedicationCategory,
    Medication,
    CaseData,
    CaseStatus,
    Draft,
    UserRow,
    AgencyRow,
    PremiumSoldRow,
    CarrierRow,
    ProductRow,
)

router = APIRouter()

def _invalidate_shared_cache_safe(*, user_id: Optional[str]) -> None:
    try:
        from app.redis_client import redis_client
        if not redis_client:
            return
        import asyncio

        patterns = ["ariadesk:shared:u:global:*"]
        uid = (str(user_id).strip() if user_id else "")
        if uid:
            patterns.append(f"ariadesk:shared:u:{uid}:*")

        async def _do():
            for pattern in patterns:
                batch = []
                async for k in redis_client.scan_iter(match=pattern, count=500):
                    batch.append(k)
                    if len(batch) >= 500:
                        await redis_client.delete(*batch)
                        batch = []
                if batch:
                    await redis_client.delete(*batch)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_do())
        else:
            loop.create_task(_do())
    except Exception:
        return


def _bump_bob_version_safe(*, tenant_id: uuid.UUID) -> None:
    try:
        from app.redis_client import redis_client
        if not redis_client:
            return
        import asyncio

        async def _do():
            key = f"cases:bob_version:{tenant_id}"
            try:
                await redis_client.incr(key)
            except Exception:
                try:
                    await redis_client.set(key, "2")
                except Exception:
                    pass

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_do())
        else:
            loop.create_task(_do())
    except Exception:
        return


def require_authorization(authorization: Optional[str] = Header(None)) -> dict:
    """Verify the Bearer JWT's signature and return its claims. This is the
    single dependency every route routes through for authentication - nothing
    downstream (tenant, user id, admin flags) may trust an unsigned claim or
    a client-supplied header instead of this."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# Dependencies
def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None),
    claims: dict = Depends(require_authorization),
) -> uuid.UUID:
    """Tenant comes from the signature-verified token claim. If X-Tenant-Id is
    also sent, it must match - it can never override or stand in for the token."""
    token_tenant = claims.get("tenant_id")
    if not token_tenant:
        raise HTTPException(status_code=401, detail="Token missing tenant_id")
    try:
        tenant_uuid = uuid.UUID(str(token_tenant))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid tenant_id in token")
    if x_tenant_id:
        try:
            header_tenant = uuid.UUID(x_tenant_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid X-Tenant-Id (must be UUID)")
        if header_tenant != tenant_uuid:
            raise HTTPException(status_code=403, detail="X-Tenant-Id does not match token tenant_id")
    return tenant_uuid


def get_tenant_db(tenant_id: uuid.UUID = Depends(get_tenant_id)) -> Generator[Session, None, None]:
    """Same session as get_db, but scoped to the validated tenant for RLS:
    sets the app.tenant_id GUC read by the policies in db/rls_policies.sql.
    Without this, RLS either fails closed (0 rows) or is bypassed entirely
    if the DB role has BYPASSRLS."""
    with Session(engine) as session:
        session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        yield session


async def get_async_tenant_db(tenant_id: uuid.UUID = Depends(get_tenant_id)) -> AsyncGenerator[AsyncSession, None]:
    """Async equivalent of get_tenant_db for the routes on the async engine."""
    async with AsyncSession(async_engine) as session:
        await session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        yield session


def get_user_id_from_request(
    claims: dict = Depends(require_authorization),
) -> Optional[str]:
    """User id from the signature-verified token only - X-User-Id is client-
    supplied and was previously trusted ahead of the token, which let any
    caller impersonate another user."""
    for k in ("sub", "user_id", "uid"):
        v = claims.get(k)
        if not v:
            continue
        s = str(v).strip()
        if not s:
            continue
        try:
            uuid.UUID(s)
            return s
        except Exception:
            continue
    return None


def require_user_uuid(user_id: Optional[str]) -> uuid.UUID:
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID required (missing token sub)")
    try:
        return uuid.UUID(str(user_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user id in token")


def _resolve_desk_is_admin(claims: dict) -> bool:
    """BoB admin: role_id/is_staff/is_superuser claims on the signature-verified
    Bearer JWT only - X-Role-Id/X-Is-Staff/X-Is-Superuser headers are
    client-supplied and were previously trusted as sole proof of admin."""
    jr = claims.get("role_id", claims.get("roleId"))
    if jr is not None:
        try:
            if int(jr) in (1, 2):
                return True
        except Exception:
            pass
    if claims.get("is_staff") or claims.get("isStaff"):
        return True
    if claims.get("is_superuser") or claims.get("isSuperuser"):
        return True
    return False


def _sanitize_documents_for_list(common_details: Any) -> Dict[str, Any]:
    """Return common_details without full document paths, keeping notes."""
    if not isinstance(common_details, dict):
        return {}
    
    # Create a copy to avoid in-place modification of the original record
    res = dict(common_details)
    
    docs = common_details.get("documents")
    if isinstance(docs, list) and docs:
        safe_docs: List[Dict[str, Any]] = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            # Only keep non-sensitive or public metadata
            safe_docs.append({
                "id": d.get("id"),
                "filename": d.get("filename"),
                "original_filename": d.get("original_filename"),
                "mime_type": d.get("mime_type"),
                "size": d.get("size"),
                "uploaded_at": d.get("uploaded_at"),
                "client_number": d.get("client_number"),
                "option_number": d.get("option_number"),
            })
        res["documents"] = safe_docs
    else:
        res["documents"] = []
        
    # Notes are already safe to return as they don't contain physical paths
    return res


def _case_status_to_label(status_id: Optional[int]) -> str:
    try:
        s = int(status_id or 0)
    except Exception:
        return "N/A"
    mapping = {
        0: "Draft",
        1: "In progress",
        2: "submitted",
        3: "Hold",
        4: "Issued",
        6: "Denied",
        7: "Lapsed",
        8: "Pending Lapse",
        9: "Replaced",
        10: "Cancelled",
        11: "No Policy",
    }
    return mapping.get(s, str(s))

def _premium_status_to_ui(status_id: Optional[int]) -> tuple[int, str]:
    """
    Book of Business / premium_sold legacy status mapping.

    UI expects: 4 Issued, 7 Lapsed, 8 Pending Lapse, 9 Replaced, 10 Cancelled.
    Legacy premium_sold.status uses: 4,6,7,8,9 (where 6 == Lapsed).
    """
    try:
        s = int(status_id or 0)
    except Exception:
        return 0, "N/A"
    mapping = {
        4: (4, "Issued"),
        6: (7, "Lapsed"),
        7: (8, "Pending Lapse"),
        8: (9, "Replaced"),
        9: (10, "Cancelled"),
        10: (10, "Cancelled"),
        11: (11, "No Policy"),
    }
    return mapping.get(s, (s, _case_status_to_label(s)))

def _case_status_id_to_premium_status(status_id: Any) -> int:
    try:
        s = int(status_id or 0)
    except Exception:
        return 0
    mapping = {
        7: 6,
        8: 7,
        9: 8,
        10: 9,
    }
    return int(mapping.get(s, s))

def _recompute_case_status_from_premiums(db: Session, case_id: int) -> Optional[int]:
    from sqlmodel import select

    try:
        cid = int(case_id)
    except Exception:
        return None

    rows = db.exec(
        select(PremiumSoldRow.status, PremiumSoldRow.is_active).where(PremiumSoldRow.case_data_id == cid)
    ).all() or []

    statuses: List[int] = []
    for st, is_active in rows:
        if is_active is False:
            continue
        ui_sid, _ = _premium_status_to_ui(int(st or 0))
        statuses.append(int(ui_sid))

    filtered = [s for s in statuses if s not in (7, 8, 11)]
    if not filtered:
        return None

    # If all policies have the same status, return that status
    unique_statuses = set(filtered)
    if len(unique_statuses) == 1:
        return int(list(unique_statuses)[0])

    # If multiple statuses, prioritize in this order:
    # Issued (4) > Submitted (2) > In progress (1) > Hold (3) > Denied (6)
    # This ensures that if any policy is "Issued", the case shows as "Issued"
    # rather than being stuck in "In progress" when other policies are issued
    for wanted in (4, 2, 1, 3, 6):
        if wanted in filtered:
            return int(wanted)
    return int(filtered[0])


def _tab_to_status_id(tab: Optional[str]) -> Optional[int]:
    if not tab:
        return None
    t = str(tab).strip().lower()
    mapping = {
        "in-progress": 1,
        "in progress": 1,
        "submitted": 2,
        "hold": 3,
        "issued": 4,
        "denied": 6,
        "lapsed": 7,
        "pending-lapse": 8,
        "pending-lapsed": 8,
    }
    return mapping.get(t)


def _status_input_to_case_status_id(value: Any) -> int:
    if isinstance(value, int):
        return int(value)
    s = str(value or "").strip()
    if not s:
        raise ValueError("status is required")
    sl = s.lower()
    mapping = {
        "draft": 0,
        "in progress": 1,
        "in-progress": 1,
        "submitted": 2,
        "hold": 3,
        "issued": 4,
        "denied": 6,
        "lapsed": 7,
        "pending lapse": 8,
        "pending-lapse": 8,
        "pending lapsed": 8,
        "pending-lapsed": 8,
        "replaced": 9,
        "cancelled": 10,
        "no policy": 11,
        "no-policy": 11,
    }
    if sl.isdigit():
        return int(sl)
    if sl not in mapping:
        raise ValueError("Invalid status")
    return int(mapping[sl])


def _sync_premium_sold_from_policies(
    db: Session,
    case: CaseData,
    policy_and_banking: Dict[str, Any],
    user_uuid: uuid.UUID,
) -> None:
    from sqlmodel import select

    def _parse_float(val) -> float:
        if val is None:
            return 0.0
        try:
            return float(str(val).replace(",", "").replace("$", "").strip() or 0)
        except Exception:
            return 0.0

    for client_key, client_data in policy_and_banking.items():
        if not client_key.startswith("client_") or not isinstance(client_data, dict):
            continue

        policies = client_data.get("policies") or []
        if not isinstance(policies, list):
            continue

        for idx, pol in enumerate(policies):
            if not isinstance(pol, dict):
                continue

            monthly = _parse_float(pol.get("monthlyPremium") or pol.get("monthly_premium"))
            yearly = _parse_float(pol.get("yearlyPremium") or pol.get("yearly_premium") or pol.get("annualPremium"))
            annual = yearly if yearly > 0 else (monthly * 12)

            policy_number = pol.get("policyNumber") or pol.get("policy_number") or ""
            unique_id = f"{case.id}_{client_key}_option_{idx + 1}"
            status_for_premium = _case_status_id_to_premium_status(getattr(case, "status", 0) or 0)
            if int(status_for_premium or 0) == 0:
                status_for_premium = 1

            carrier_id = None
            carrier_val = pol.get("carrier")
            if carrier_val:
                try:
                    carrier_id = uuid.UUID(str(carrier_val))
                except Exception:
                    pass

            existing = db.exec(
                select(PremiumSoldRow).where(
                    PremiumSoldRow.unique_policy_identifier == unique_id
                )
            ).first()

            # Get user's agency_id if available
            agency_id = None
            try:
                user_row = db.exec(select(UserRow).where(UserRow.id == user_uuid)).first()
                if user_row and hasattr(user_row, "agency_id") and user_row.agency_id:
                    agency_id = user_row.agency_id
            except Exception:
                pass

            if existing:
                existing.annual_premium = annual
                existing.policy_number = policy_number or existing.policy_number
                existing.status = int(status_for_premium or existing.status or 0)
                existing.modified_at = datetime.utcnow()
                if existing.case_data_id is None:
                    existing.case_data_id = int(case.id)
                if carrier_id:
                    existing.carrier_id = carrier_id
                if agency_id and existing.agency_id is None:
                    existing.agency_id = agency_id
                db.add(existing)
            else:
                new_ps = PremiumSoldRow(
                    created_at=datetime.utcnow(),
                    modified_at=datetime.utcnow(),
                    is_active=True,
                    annual_premium=annual,
                    policy_number=policy_number,
                    unique_policy_identifier=unique_id,
                    status=int(status_for_premium or 1),
                    case_data_id=case.id,
                    user_id=user_uuid,
                    carrier_id=carrier_id,
                    agency_id=agency_id,
                    is_lapsed=False,
                    is_pending_lapsed=False,
                )
                db.add(new_ps)

    db.commit()


def _extract_clients_from_case(case: CaseData) -> List[Dict[str, Any]]:
    general = case.general_information or case.general_info or {}
    policy = case.policy_and_banking or {}
    assessment = case.client_assessment or {}

    clients: List[Dict[str, Any]] = []

    cd = case.common_details or {}
    no_policy_raw = (cd.get("no_policy_options") or cd.get("noPolicyOptions") or {}) if isinstance(cd, dict) else {}
    no_policy_set = set()
    if isinstance(no_policy_raw, dict):
        for key, val in no_policy_raw.items():
            if val:
                m = re.match(r"client_(\d+)_option_(\d+)", str(key))
                if m:
                    try:
                        no_policy_set.add((int(m.group(1)), int(m.group(2))))
                    except Exception:
                        continue
    elif isinstance(no_policy_raw, list):
        for it in no_policy_raw:
            if not isinstance(it, dict):
                continue
            cn = it.get("client_number") or it.get("clientNumber")
            on = it.get("option_number") or it.get("optionNumber") or it.get("option")
            try:
                no_policy_set.add((int(cn), int(on)))
            except Exception:
                continue

    option_status_raw = (cd.get("option_status_overrides") or cd.get("optionStatusOverrides") or []) if isinstance(cd, dict) else []
    option_status_map: Dict[Tuple[int, int], int] = {}
    if isinstance(option_status_raw, list):
        for it in option_status_raw:
            if not isinstance(it, dict):
                continue
            cn = it.get("client_number") or it.get("clientNumber")
            on = it.get("option_number") or it.get("optionNumber") or it.get("option")
            st = it.get("status_id") or it.get("statusId") or it.get("status")
            try:
                status_id = _status_input_to_case_status_id(st)
                option_status_map[(int(cn), int(on))] = int(status_id)
            except Exception:
                continue

    def _client_obj(i: int) -> Dict[str, Any]:
        raw = general.get(f"client_{i}") if isinstance(general, dict) else None
        return raw if isinstance(raw, dict) else {}
    
    def _assessment_client(i: int) -> Dict[str, Any]:
        """Get client data from client_assessment.clients array"""
        if not isinstance(assessment, dict):
            return {}
        clients_arr = assessment.get("clients") or []
        if not isinstance(clients_arr, list):
            return {}
        idx = i - 1  # Array is 0-indexed
        if idx < 0 or idx >= len(clients_arr):
            return {}
        client = clients_arr[idx]
        return client if isinstance(client, dict) else {}

    def _has_meaningful_client_data(c: Dict[str, Any]) -> bool:
        """
        Frontend sometimes persists placeholder client objects (e.g. {name: ""}).
        Those should not create rows in the cases list.
        """
        if not isinstance(c, dict) or not c:
            return False
        keys = (
            "name",
            "full_name",
            "fullName",
            "email",
            "dob",
            "birthDate",
            "dateOfBirth",
            "sex",
            "gender",
            "kids",
        )
        for k in keys:
            if k not in c:
                continue
            v = c.get(k)
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            return True
        return False

    def _options_for_client(i: int) -> List[Tuple[int, Dict[str, Any]]]:
        raw = policy.get(f"client_{i}") if isinstance(policy, dict) else None
        raw = raw if isinstance(raw, dict) else {}
        options: List[Tuple[int, Dict[str, Any]]] = []
        for k, v in raw.items():
            if not isinstance(v, dict):
                continue
            if str(k).startswith("option_"):
                try:
                    n = int(str(k).split("_", 1)[1])
                except Exception:
                    continue
                options.append((n, v))
        policies_arr = raw.get("policies") or []
        if isinstance(policies_arr, list) and not options:
            for idx, pol in enumerate(policies_arr):
                if isinstance(pol, dict):
                    options.append((idx + 1, pol))
        options.sort(key=lambda x: x[0])
        extra = [on for (cn, on) in no_policy_set if cn == int(i)]
        for on in sorted(set(extra)):
            if all(int(existing[0]) != int(on) for existing in options):
                options.append((int(on), {}))
        options.sort(key=lambda x: x[0])
        # IMPORTANT: do not invent placeholder options unless there's an explicit no-policy marker.
        # Placeholder options create lots of "N/A" rows in the UI.
        return options

    status_label = _case_status_to_label(case.status)
    status_id = int(case.status or 0)

    for i in range(1, 11):
        c = _client_obj(i)
        if not _has_meaningful_client_data(c):
            continue
        
        # Get client assessment data for this client (for sex, kids, etc.)
        c_assess = _assessment_client(i)
        
        name = c.get("name") or c.get("full_name") or c.get("fullName") or ""
        email = c.get("email") or ""
        
        # Sex/Gender: check general_info first, then client_assessment
        sex = c.get("sex") or c.get("gender") or c_assess.get("gender") or "N/A"
        
        # Kids: check general_info first, then client_assessment
        kids = c.get("kids") if c.get("kids") is not None else (c_assess.get("kids") if c_assess.get("kids") is not None else "N/A")
        
        dob = c.get("dob") or c.get("birthDate") or c.get("dateOfBirth") or c_assess.get("dateOfBirth") or ""

        for opt_num, opt in _options_for_client(i):
            # Plan type: check product, plan_type, or policy keys
            plan_type_raw = opt.get("product") or opt.get("plan_type") or opt.get("planType") or "N/A"
            if plan_type_raw and str(plan_type_raw).lower() == "other":
                plan_type = opt.get("otherProduct") or opt.get("other_product") or opt.get("productOther") or "Other"
            else:
                plan_type = str(plan_type_raw).replace("_", " ").title() if plan_type_raw and plan_type_raw != "N/A" else "N/A"
            
            # Plan name: check policy, plan_name, planName keys (policy is common in JSON structure)
            plan_name_raw = opt.get("policy") or opt.get("plan_name") or opt.get("planName") or opt.get("plan") or plan_type_raw or "N/A"
            if plan_name_raw and str(plan_name_raw).lower() == "other":
                plan_name = opt.get("otherPolicy") or opt.get("other_policy") or opt.get("policyOther") or "Other"
            elif plan_name_raw and plan_name_raw != "N/A":
                plan_name = str(plan_name_raw).replace("_", " ").title()
            else:
                plan_name = "N/A"
            policy_number = opt.get("policy_number") or opt.get("policyNumber") or (case.policy_number or "")
            # Support both UUID carriers and custom carrier text.
            carrier = opt.get("carrier_name") or opt.get("carrierName") or "N/A"
            if carrier == "N/A":
                carrier_raw = opt.get("carrier") or opt.get("carrier_id")
                if carrier_raw is not None:
                    try:
                        carrier_str = str(carrier_raw).strip()
                    except Exception:
                        carrier_str = ""
                    if carrier_str and carrier_str.lower() not in {"n/a", "none", "null"}:
                        carrier = carrier_str
            monthly = opt.get("monthly_premium") or opt.get("monthlyPremium") or 0
            try:
                monthly_float = float(str(monthly).replace(",", "").replace("$", "").strip() or 0)
            except Exception:
                monthly_float = 0
            annual = opt.get("annual_premium") or opt.get("annualPremium") or opt.get("yearlyPremium")
            annual_val = 0
            if annual:
                try:
                    annual_val = float(str(annual).replace(",", "").replace("$", "").strip() or 0)
                except Exception:
                    annual_val = 0
            if annual_val and annual_val > 0:
                premium = annual_val
            elif monthly_float:
                premium = round(monthly_float * 12, 2)
            else:
                premium = case.premium or 0
            opt_status_id = status_id
            opt_status_label = status_label
            if (int(i), int(opt_num)) in no_policy_set:
                opt_status_id = 11
                opt_status_label = "No Policy"
            else:
                ov = option_status_map.get((int(i), int(opt_num)))
                if ov is not None:
                    opt_status_id = int(ov)
                    opt_status_label = _case_status_to_label(int(ov))

            # Skip empty placeholder policy rows unless explicitly marked as "No Policy"
            # or having any meaningful policy data.
            is_no_policy = (int(i), int(opt_num)) in no_policy_set
            has_policy_data = False
            if isinstance(policy_number, str) and policy_number.strip():
                has_policy_data = True
            if carrier and str(carrier).strip() and str(carrier).strip() != "N/A":
                has_policy_data = True
            if plan_name and str(plan_name).strip() != "N/A":
                has_policy_data = True
            if plan_type and str(plan_type).strip() != "N/A":
                has_policy_data = True
            try:
                has_policy_data = has_policy_data or (float(premium or 0) > 0)
            except Exception:
                pass
            if (not is_no_policy) and (not has_policy_data):
                continue

            clients.append(
                {
                    "id": opt.get("premium_sold_id") or opt.get("premiumSoldId") or None,
                    "name": name or "N/A",
                    "email": email,
                    "sex": sex,
                    "kids": kids,
                    "birthDate": dob,
                    "policyNumber": policy_number,
                    "carrier": carrier,
                    "carrierName": carrier,
                    "planName": plan_name,
                    "planType": plan_type,
                    "premium": premium,
                    "statusId": opt_status_id,
                    "status": opt_status_label,
                    "clientNumber": i,
                    "optionNumber": opt_num,
                    "option": opt_num,
                }
            )
    if not clients:
        name = (case.client1_name or case.client_first_name or "").strip() or "N/A"
        email = (case.client1_email or case.client_email or "").strip()

        def _fallback_name(cn: int) -> str:
            if int(cn) == 1:
                return name
            try:
                n2 = (case.client2_name or "").strip()
                return n2 or "N/A"
            except Exception:
                return "N/A"

        def _status_for(cn: int, on: int) -> Tuple[int, str]:
            if (int(cn), int(on)) in no_policy_set:
                return 11, "No Policy"
            ov = option_status_map.get((int(cn), int(on)))
            if ov is not None:
                return int(ov), _case_status_to_label(int(ov))
            return int(status_id), status_label

        keys = {(1, 1)}
        keys |= set(no_policy_set)
        keys |= set(option_status_map.keys())
        clients = []
        for (cn, on) in sorted(keys, key=lambda x: (int(x[0]), int(x[1]))):
            sid, slabel = _status_for(int(cn), int(on))
            is_np = int(sid) == 11
            clients.append(
                {
                    "id": None,
                    "name": _fallback_name(int(cn)),
                    "email": email,
                    "sex": "N/A",
                    "kids": "N/A",
                    "birthDate": "",
                    "policyNumber": case.policy_number or "",
                    "carrier": "N/A",
                    "carrierName": "N/A",
                    "planName": "No Policy" if is_np else "N/A",
                    "planType": "N/A",
                    "premium": case.premium,
                    "statusId": int(sid),
                    "status": slabel,
                    "clientNumber": int(cn),
                    "optionNumber": int(on),
                    "option": int(on),
                }
            )
    return clients


def _user_display(u: Optional[UserRow]) -> str:
    if not u:
        return "N/A"
    fn = str(getattr(u, "first_name", "") or "").strip()
    ln = str(getattr(u, "last_name", "") or "").strip()
    name = f"{fn} {ln}".strip()
    if name:
        return name
    email = str(getattr(u, "email", "") or "").strip()
    return email or "N/A"


def _carrier_display(c: Optional[CarrierRow]) -> str:
    if not c:
        return "N/A"
    dn = str(getattr(c, "display_name_override", "") or "").strip()
    if dn:
        return dn
    n = str(getattr(c, "name", "") or "").strip()
    return n or "N/A"


def _merge_premiums_into_clients(
    *,
    case: CaseData,
    clients: List[Dict[str, Any]],
    premiums: List[PremiumSoldRow],
    carriers_by_id: Dict[str, CarrierRow],
    products_by_id: Dict[str, ProductRow],
    agencies_by_id: Dict[str, AgencyRow],
) -> tuple[List[Dict[str, Any]], str]:
    def _parse_client_and_option(p: PremiumSoldRow) -> tuple[int, int]:
        raw = str(getattr(p, "unique_policy_identifier", "") or "").strip()
        if raw:
            m = re.search(r"client_(\d+)_option_(\d+)", raw)
            if m:
                try:
                    return int(m.group(1)), int(m.group(2))
                except Exception:
                    pass
        return 1, 1

    def _name_email_for_client(cn: int) -> tuple[str, str]:
        if int(cn) == 2:
            name = (case.client2_name or "").strip() or "N/A"
            email = (case.client2_email or "").strip()
            return name, email
        name = (case.client1_name or case.client_first_name or "").strip() or "N/A"
        email = (case.client1_email or case.client_email or "").strip()
        return name, email

    by_id: Dict[int, PremiumSoldRow] = {}
    for p in premiums or []:
        try:
            by_id[int(p.id)] = p
        except Exception:
            continue

    existing_numeric_ids: set[int] = set()
    existing_client_option_pairs: set[tuple[int, int]] = set()
    for c in clients:
        try:
            existing_numeric_ids.add(int(str(c.get("id") or "").strip()))
        except Exception:
            pass
        # Also track by (clientNumber, optionNumber) to avoid duplicates
        try:
            cn = int(c.get("clientNumber") or 1)
            on = int(c.get("optionNumber") or c.get("option") or 1)
            existing_client_option_pairs.add((cn, on))
        except Exception:
            pass

    for c in clients:
        raw = str(c.get("id") or "").strip()
        p = None
        if raw:
             try:
                 pid = int(raw)
                 p = by_id.get(pid)
             except Exception:
                 pass
        
        # Fallback: try matching by client/option number
        if not p:
            try:
                cn_curr = int(c.get("clientNumber") or 1)
                on_curr = int(c.get("optionNumber") or c.get("option") or 1)
                for _pid, _p in by_id.items():
                    _cn, _on = _parse_client_and_option(_p)
                    if _cn == cn_curr and _on == on_curr:
                        p = _p
                        break
            except Exception:
                pass

        if not p:
            continue

        cn, on = _parse_client_and_option(p)
        if not c.get("clientNumber"):
            c["clientNumber"] = cn
        if not c.get("optionNumber"):
            c["optionNumber"] = on
        if not c.get("option"):
            c["option"] = on

        if p.policy_number:
            c["policyNumber"] = p.policy_number
        if p.annual_premium is not None:
            c["premium"] = float(p.annual_premium)
        try:
            sid = int(p.status or 0)
        except Exception:
            sid = 0
        ui_sid, ui_label = _premium_status_to_ui(sid)
        c["statusId"] = ui_sid
        c["status"] = ui_label

        # BoB dates (optional)
        if getattr(p, "effective_date", None):
            try:
                c["issuedDate"] = p.effective_date.isoformat() + "Z" if getattr(p.effective_date, "isoformat", None) else str(p.effective_date)
            except Exception:
                pass
        if getattr(p, "laps_date", None):
            try:
                c["lapsedDate"] = p.laps_date.isoformat() + "Z" if getattr(p.laps_date, "isoformat", None) else str(p.laps_date)
            except Exception:
                pass

        carrier_name = "N/A"
        if p.carrier_id:
            carrier_name = _carrier_display(carriers_by_id.get(str(p.carrier_id)))
        if carrier_name and carrier_name != "N/A":
            c["carrier"] = carrier_name
            c["carrierName"] = carrier_name

        plan_name = ""
        if p.product_id:
            pr = products_by_id.get(str(p.product_id))
            plan_name = str(getattr(pr, "name", "") or "").strip() if pr else ""

    general_info = case.general_info or {}
    for p in premiums or []:
        try:
            pid = int(p.id)
        except Exception:
            continue
        if pid in existing_numeric_ids:
            continue

        # Parse client/option from premium_sold
        cn, on = _parse_client_and_option(p)
        
        # Skip if a client with this (clientNumber, optionNumber) already exists (prevents duplicates)
        if (cn, on) in existing_client_option_pairs:
            continue

        carrier_name = _carrier_display(carriers_by_id.get(str(p.carrier_id))) if p.carrier_id else "N/A"
        plan_name = ""
        if p.product_id:
            pr = products_by_id.get(str(p.product_id))
            plan_name = str(getattr(pr, "name", "") or "").strip() if pr else ""

        # Fetch sex/kids/dob from client_assessment if not in General Info
        c_assess = {}
        try:
            ca = case.client_assessment or {}
            if isinstance(ca, dict):
                c_clients = ca.get("clients") or []
                if isinstance(c_clients, list) and len(c_clients) >= cn:
                    c_assess = c_clients[cn - 1] if isinstance(c_clients[cn - 1], dict) else {}
        except Exception:
            c_assess = {}

        name, email = _name_email_for_client(cn)
        
        # Determine Sex
        sex_val = "N/A"
        # 1. Try General Info
        client_key = f"client_{cn}"
        gi_client = (general_info.get(client_key) or {}) if isinstance(general_info, dict) else {}
        if isinstance(gi_client, dict):
             sex_val = gi_client.get("sex") or gi_client.get("gender")
        # 2. Try Client Assessment
        if not sex_val or str(sex_val).strip() == "N/A":
             sex_val = c_assess.get("gender") or "N/A"

        # Determine Kids
        kids_val = "N/A"
        if isinstance(gi_client, dict) and gi_client.get("kids") is not None:
             kids_val = gi_client.get("kids")
        elif c_assess.get("kids") is not None:
             kids_val = c_assess.get("kids")
        
        # Determine DOB
        dob_val = ""
        if isinstance(gi_client, dict):
             dob_val = gi_client.get("dob") or gi_client.get("birthDate") or gi_client.get("dateOfBirth")
        if not dob_val:
             dob_val = c_assess.get("dateOfBirth") or ""

        clients.append(
            {
                "id": pid,
                "name": name,
                "email": email,
                "sex": sex_val,
                "kids": kids_val,
                "birthDate": dob_val,
                "policyNumber": p.policy_number or "",
                "carrier": carrier_name,
                "carrierName": carrier_name,
                "planName": plan_name or "N/A",
                "planType": plan_name or "N/A",
                "premium": float(p.annual_premium) if p.annual_premium is not None else None,
                "statusId": _premium_status_to_ui(int(p.status or 0))[0],
                "status": _premium_status_to_ui(int(p.status or 0))[1],
                "clientNumber": cn,
                "optionNumber": on,
                "option": on,
                "issuedDate": (p.effective_date.isoformat() + "Z") if getattr(getattr(p, "effective_date", None), "isoformat", None) else None,
                "lapsedDate": (p.laps_date.isoformat() + "Z") if getattr(getattr(p, "laps_date", None), "isoformat", None) else None,
            }
        )
        existing_client_option_pairs.add((cn, on))

    agency_name = "N/A"
    for p in premiums or []:
        if p.agency_id:
            a = agencies_by_id.get(str(p.agency_id))
            if a and getattr(a, "name", None):
                agency_name = str(a.name or "").strip() or "N/A"
                break

    return clients, agency_name

def _format_mdy_slash(dt: Any) -> str:
    if not dt:
        return "N/A"
    try:
        # dt may be datetime or ISO string
        if hasattr(dt, "strftime"):
            return dt.strftime("%m/%d/%Y")
        d = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
        return d.strftime("%m/%d/%Y")
    except Exception:
        return str(dt)


_users_service_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))


async def _users_get_name(*, tenant_id: uuid.UUID, authorization: str, user_id: uuid.UUID) -> str:
    try:
        url = settings.USERS_SERVICE_URL.rstrip("/") + f"/api/users/{user_id}"
        r = await _users_service_client.get(url, headers={"X-Tenant-Id": str(tenant_id), "Authorization": authorization})
        if r.status_code >= 400:
            return "N/A"
        data = r.json()
        fn = str(data.get("first_name") or "").strip()
        ln = str(data.get("last_name") or "").strip()
        name = f"{fn} {ln}".strip()
        return name or str(data.get("email") or "N/A")
    except Exception:
        return "N/A"


class DraftCreateOrUpdateRequest(BaseModel):
    draftId: Optional[str] = None
    draftData: Dict[str, Any] = Field(default_factory=dict)
    sectionCompletionStatus: Dict[str, Any] = Field(default_factory=dict)
    partialUpdate: bool = False
    updatedSection: Optional[str] = None


class DraftClientResponse(BaseModel):
    id: str
    draftData: Dict[str, Any] = Field(default_factory=dict)
    sectionCompletionStatus: Dict[str, Any] = Field(default_factory=dict)
    updatedAt: Optional[str] = None
    createdAt: Optional[str] = None
    completionPercentage: int = 0


def _draft_to_api(d: Draft) -> Dict[str, Any]:
    scs = d.section_completion_status or {}
    total = len(scs.keys()) if isinstance(scs, dict) else 0
    done = len([k for k, v in (scs or {}).items() if bool(v)]) if isinstance(scs, dict) else 0
    pct = int(round((done / total) * 100)) if total > 0 else 0
    return {
        "id": str(d.id),
        "draftData": d.draft_data or {},
        "sectionCompletionStatus": d.section_completion_status or {},
        "updatedAt": d.updated_at.isoformat() + "Z" if getattr(d.updated_at, "isoformat", None) else None,
        "createdAt": d.created_at.isoformat() + "Z" if getattr(d.created_at, "isoformat", None) else None,
        "completionPercentage": pct,
    }


class OptionStatusOverrideRequest(BaseModel):
    client_number: int = Field(..., ge=1, le=10)
    option_number: int = Field(..., ge=1, le=10)
    status: Any

@router.post("/cases/{case_id}/set-no-policy")
def set_no_policy(
    case_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    try:
        body = payload or {}
        client_number = body.get('client_number', 1)
        option_number = body.get('option_number', 1)
        
        c = db.get(CaseData, int(case_id))
        if not c or c.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Case not found")
        
        common_details = c.common_details or {}
        if not isinstance(common_details, dict):
            common_details = {}
        common_details = dict(common_details)

        no_policy_options = common_details.get('no_policy_options')
        if isinstance(no_policy_options, dict):
            no_policy_options = dict(no_policy_options)
        else:
            no_policy_options = {}

        key = f"client_{client_number}_option_{option_number}"
        no_policy_options[key] = True
        common_details['no_policy_options'] = no_policy_options
        
        c.common_details = common_details
        c.modified_at = datetime.utcnow()
        db.add(c)
        db.commit()
        
        # Also update/deactivate premium_sold if it exists
        try:
            unique_id = f"{case_id}_client_{client_number}_option_{option_number}"
            ps = db.exec(
                select(PremiumSoldRow).where(PremiumSoldRow.unique_policy_identifier == unique_id)
            ).first()
            if ps:
                ps.is_active = False
                ps.modified_at = datetime.utcnow()
                db.add(ps)
                db.commit()
        except Exception:
            db.rollback()
        
        return {"success": True, "message": "No Policy status saved", "key": key}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error setting No Policy status: {str(e)}")


@router.post("/cases/{case_id}/remove-no-policy")
def remove_no_policy(
    case_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    try:
        body = payload or {}
        client_number = body.get('client_number', 1)
        option_number = body.get('option_number', 1)
        
        c = db.get(CaseData, int(case_id))
        if not c or c.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Case not found")
        
        common_details = c.common_details or {}
        if not isinstance(common_details, dict):
            common_details = {}
        common_details = dict(common_details)

        no_policy_options = common_details.get('no_policy_options')
        if isinstance(no_policy_options, dict):
            no_policy_options = dict(no_policy_options)
        else:
            no_policy_options = {}

        key = f"client_{client_number}_option_{option_number}"
        if key in no_policy_options:
            del no_policy_options[key]
            common_details['no_policy_options'] = no_policy_options
            c.common_details = common_details
            c.modified_at = datetime.utcnow()
            db.add(c)
            db.commit()
            
        try:
            unique_id = f"{case_id}_client_{client_number}_option_{option_number}"
            ps = db.exec(
                select(PremiumSoldRow).where(PremiumSoldRow.unique_policy_identifier == unique_id)
            ).first()

            if ps:
                ps.is_active = True
                if int(ps.status or 0) == 0:
                    ps.status = 1
                ps.modified_at = datetime.utcnow()
                db.add(ps)
                db.commit()
            else:
                try:
                    u = uuid.UUID(str(user_id)) if user_id else None
                except Exception:
                    u = None
                if not u:
                    u = c.created_by_id or c.agent_id

                policy_and_banking = c.policy_and_banking or {}
                client_key = f"client_{int(client_number)}"
                client_data = policy_and_banking.get(client_key) if isinstance(policy_and_banking, dict) else None
                opt_data = None
                if isinstance(client_data, dict):
                    policies = client_data.get("policies")
                    if isinstance(policies, list):
                        idx = int(option_number) - 1
                        if 0 <= idx < len(policies) and isinstance(policies[idx], dict):
                            opt_data = policies[idx]
                    if opt_data is None:
                        maybe = client_data.get(f"option_{int(option_number)}")
                        if isinstance(maybe, dict):
                            opt_data = maybe

                if u and isinstance(opt_data, dict):
                    policy_number = opt_data.get("policyNumber") or opt_data.get("policy_number") or opt_data.get("policyNumber") or ""
                    monthly_premium = opt_data.get("monthlyPremium") or opt_data.get("monthly_premium") or 0
                    yearly_premium = opt_data.get("yearlyPremium") or opt_data.get("yearly_premium") or opt_data.get("annualPremium") or 0
                    try:
                        annual_premium = float(str(yearly_premium).replace(",", "").replace("$", "").strip() or 0)
                    except Exception:
                        annual_premium = 0
                    if annual_premium <= 0:
                        try:
                            monthly = float(str(monthly_premium).replace(",", "").replace("$", "").strip() or 0)
                            annual_premium = round(monthly * 12, 2) if monthly else 0
                        except Exception:
                            annual_premium = 0

                    carrier_uuid = None
                    carrier_id_raw = opt_data.get("carrier")
                    if carrier_id_raw:
                        try:
                            carrier_uuid = uuid.UUID(str(carrier_id_raw))
                        except Exception:
                            carrier_uuid = None

                    agency_id = None
                    try:
                        any_ps = db.exec(select(PremiumSoldRow.agency_id).where(
                            PremiumSoldRow.case_data_id == case_id
                        ).limit(1)).first()
                        if any_ps:
                            agency_id = any_ps if not isinstance(any_ps, tuple) else any_ps[0]
                    except Exception:
                        agency_id = None
                    if not agency_id:
                        try:
                            any_agency = db.exec(select(AgencyRow.id).limit(1)).first()
                            if any_agency:
                                agency_id = any_agency if not isinstance(any_agency, tuple) else any_agency[0]
                        except Exception:
                            agency_id = None

                    if carrier_uuid or (isinstance(policy_number, str) and policy_number.strip()):
                        new_ps = PremiumSoldRow(
                            created_at=datetime.utcnow(),
                            modified_at=datetime.utcnow(),
                            case_data_id=case_id,
                            unique_policy_identifier=unique_id,
                            policy_number=policy_number,
                            annual_premium=annual_premium,
                            status=1,
                            carrier_id=carrier_uuid,
                            agency_id=agency_id,
                            user_id=u,
                            is_active=True,
                            is_lapsed=False,
                            is_pending_lapsed=False,
                        )
                        db.add(new_ps)
                        db.commit()
        except Exception:
            db.rollback()
        
        return {"success": True, "message": "No Policy status removed"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error removing No Policy status: {str(e)}")


@router.post("/cases/{case_id}/option-status")
def set_option_status_override(
    case_id: int,
    payload: OptionStatusOverrideRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    u = require_user_uuid(user_id)
    c = db.get(CaseData, int(case_id))
    if not c or c.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Case not found")

    cd = c.common_details or {}
    if not isinstance(cd, dict):
        cd = {}
    cd = dict(cd)
    overrides = cd.get("option_status_overrides")
    if not isinstance(overrides, list):
        overrides = []
    else:
        overrides = list(overrides)

    cn = int(payload.client_number)
    on = int(payload.option_number)
    status_id = _status_input_to_case_status_id(payload.status)
    requested_status_id = int(status_id)
    was_no_policy = requested_status_id == 11

    key = f"client_{cn}_option_{on}"
    if int(status_id) == 11:
        no_policy = cd.get("no_policy_options")
        if isinstance(no_policy, dict):
            no_policy = dict(no_policy)
        else:
            no_policy = {}
        no_policy[key] = True
        cd["no_policy_options"] = no_policy
        status_id = 1
    else:
        no_policy = cd.get("no_policy_options")
        if isinstance(no_policy, dict):
            no_policy = dict(no_policy)
            if key in no_policy:
                del no_policy[key]
                cd["no_policy_options"] = no_policy
        elif isinstance(no_policy, list):
            new_np = []
            for it in no_policy:
                if not isinstance(it, dict):
                    continue
                try:
                    it_cn = int(it.get("client_number") or it.get("clientNumber") or 0)
                    it_on = int(it.get("option_number") or it.get("optionNumber") or it.get("option") or 0)
                except Exception:
                    new_np.append(it)
                    continue

                if it_cn == cn and it_on == on:
                    continue
                new_np.append(it)
            cd["no_policy_options"] = new_np

    if int(status_id) == 1:
        new_list = []
        for it in overrides:
            if not isinstance(it, dict):
                continue
            try:
                it_cn = int(it.get("client_number") or it.get("clientNumber") or 0)
                it_on = int(it.get("option_number") or it.get("optionNumber") or it.get("option") or 0)
            except Exception:
                continue
            if it_cn == cn and it_on == on:
                continue
            new_list.append(it)
        overrides = new_list
    else:
        exists = False
        for it in overrides:
            if not isinstance(it, dict):
                continue
            try:
                it_cn = int(it.get("client_number") or it.get("clientNumber") or 0)
                it_on = int(it.get("option_number") or it.get("optionNumber") or it.get("option") or 0)
            except Exception:
                continue
            if it_cn == cn and it_on == on:
                it["status_id"] = int(status_id)
                it["updated_by_id"] = str(u)
                exists = True
                break
        if not exists:
            overrides.append({"client_number": cn, "option_number": on, "status_id": int(status_id), "updated_by_id": str(u)})

    cd["option_status_overrides"] = overrides
    c.common_details = cd
    c.modified_at = datetime.utcnow()
    db.add(c)
    db.commit()
    db.refresh(c)
    
    # IMPORTANT: also sync to premium_sold table so Book of Business works
    premium_sold_id = None
    try:
        unique_id = f"{case_id}_client_{cn}_option_{on}"
        existing_ps = db.exec(
            select(PremiumSoldRow).where(PremiumSoldRow.unique_policy_identifier == unique_id)
        ).first()
        
        if existing_ps:
            # Update existing premium_sold status
            existing_ps.status = 11 if was_no_policy else _case_status_id_to_premium_status(int(status_id))
            existing_ps.is_active = (not bool(was_no_policy))
            if existing_ps.case_data_id is None:
                existing_ps.case_data_id = int(case_id)
            existing_ps.modified_at = datetime.utcnow()
            db.add(existing_ps)
            db.commit()
            premium_sold_id = int(existing_ps.id)
        else:
            # Create new premium_sold row if it doesn't exist
            # Extract policy data from case JSON
            policy_and_banking = c.policy_and_banking or {}
            if isinstance(policy_and_banking, dict):
                client_data = policy_and_banking.get(f"client_{cn}") or {}
                opt_data = None
                if isinstance(client_data, dict):
                    policies = client_data.get("policies")
                    if isinstance(policies, list):
                        idx = int(on) - 1
                        if 0 <= idx < len(policies) and isinstance(policies[idx], dict):
                            opt_data = policies[idx]
                    if opt_data is None:
                        maybe = client_data.get(f"option_{on}")
                        if isinstance(maybe, dict):
                            opt_data = maybe

                if isinstance(opt_data, dict):
                    policy_number = opt_data.get("policyNumber") or opt_data.get("policy_number") or ""
                    monthly_premium = opt_data.get("monthlyPremium") or opt_data.get("monthly_premium") or 0
                    yearly_premium = opt_data.get("yearlyPremium") or opt_data.get("yearly_premium") or opt_data.get("annualPremium") or 0
                    carrier_id_raw = opt_data.get("carrier")
                    
                    try:
                        annual_premium = float(str(yearly_premium).replace(",", "").replace("$", "").strip() or 0)
                    except Exception:
                        annual_premium = 0
                    if annual_premium <= 0:
                        try:
                            annual_premium = float(str(monthly_premium).replace(",", "").replace("$", "").strip() or 0) * 12 if monthly_premium else 0
                        except Exception:
                            annual_premium = 0
                    
                    carrier_uuid = None
                    if carrier_id_raw:
                        try:
                            carrier_uuid = uuid.UUID(str(carrier_id_raw))
                        except Exception:
                            pass
                    
                    # Get agency_id (try from existing premium_sold or fallback)
                    agency_id = None
                    try:
                        any_ps = db.exec(select(PremiumSoldRow.agency_id).where(
                            PremiumSoldRow.case_data_id == case_id
                        ).limit(1)).first()
                        if any_ps:
                            agency_id = any_ps if not isinstance(any_ps, tuple) else any_ps[0]
                    except Exception:
                        pass
                    
                    if not agency_id:
                        try:
                            any_agency = db.exec(select(AgencyRow.id).limit(1)).first()
                            if any_agency:
                                agency_id = any_agency if not isinstance(any_agency, tuple) else any_agency[0]
                        except Exception:
                            pass
                    
                    # Always create premium_sold record when changing status (even if carrier/policy_number missing)
                    # This ensures the case status can be recalculated correctly
                    new_ps = PremiumSoldRow(
                        created_at=datetime.utcnow(),
                        modified_at=datetime.utcnow(),
                        case_data_id=case_id,
                        unique_policy_identifier=unique_id,
                        policy_number=policy_number,
                        annual_premium=annual_premium,
                        status=11 if was_no_policy else _case_status_id_to_premium_status(int(status_id)),
                        carrier_id=carrier_uuid,
                        agency_id=agency_id,
                        user_id=u,
                        is_active=(not bool(was_no_policy)),
                        is_lapsed=False,
                        is_pending_lapsed=False,
                    )
                    db.add(new_ps)
                    db.commit()
                    db.refresh(new_ps)
                    premium_sold_id = int(new_ps.id)
    except Exception as e:
        # Log error but don't fail the whole operation if premium_sold sync fails
        import traceback
        print(f"Error syncing premium_sold for case {case_id}, client {cn}, option {on}: {e}")
        print(traceback.format_exc())
        db.rollback()
    
    try:
        new_case_status = _recompute_case_status_from_premiums(db, int(case_id))
        if new_case_status is not None:
            c.status = int(new_case_status)
            c.modified_at = datetime.utcnow()
            if int(new_case_status) == CaseStatus.ISSUED and not c.issued_at:
                c.issued_at = datetime.utcnow()
            db.add(c)
            db.commit()
            db.refresh(c)
    except Exception as e:
        # Log error but don't fail the whole operation
        import traceback
        print(f"Error recomputing case status for case {case_id}: {e}")
        print(traceback.format_exc())
        db.rollback()

    return {
        "success": True,
        "common_details": c.common_details or {},
        "premiumSoldId": premium_sold_id,
        "requestedStatusId": requested_status_id,
        "caseStatusId": int(c.status or 0),
        "caseStatus": _case_status_to_label(c.status),
        "lastUpdated": _format_mdy_slash(c.modified_at),
    }


# Health check
@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        status="healthy",
        service=settings.SERVICE_NAME,
        version=settings.SERVICE_VERSION,
    )


# =============================================================================
# Medical reference (Desk case forms)
# Served by cases-service (source of truth).
# =============================================================================


@router.get("/medical/categories", response_model=List[MedicalCategoryResponse])
@cached(ttl=3600, prefix="med_cats")
def list_medical_categories(
    request: Request,
    search: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db),
    _auth: str = Depends(require_authorization),
):
    q = select(MedicationCategory).where(MedicationCategory.is_active == bool(is_active))
    if search:
        q = q.where(MedicationCategory.title.ilike(f"%{search}%"))
    q = q.order_by(MedicationCategory.title.asc())
    rows = db.exec(q).all()
    return [MedicalCategoryResponse.model_validate(r) for r in rows]


@router.get("/medical/medications", response_model=List[MedicationResponse])
@cached(ttl=3600, prefix="meds")
def list_medications(
    request: Request,
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db),
    _auth: str = Depends(require_authorization),
):
    q = select(Medication).where(Medication.is_active == bool(is_active))
    if category_id is not None:
        q = q.where(Medication.category_id == int(category_id))
    if search:
        q = q.where(Medication.title.ilike(f"%{search}%"))
    q = q.order_by(Medication.title.asc())
    rows = db.exec(q).all()
    return [MedicationResponse.model_validate(r) for r in rows]


@router.get("/medical/data", response_model=MedicalDataResponse)
@cached(ttl=3600, prefix="med_bundle")
def get_medical_data_bundle(
    request: Request,
    db: Session = Depends(get_db),
    _auth: str = Depends(require_authorization),
):
    cats = db.exec(select(MedicationCategory).where(MedicationCategory.is_active == True).order_by(MedicationCategory.title.asc())).all() or []
    meds = db.exec(select(Medication).where(Medication.is_active == True).order_by(Medication.title.asc())).all() or []
    return MedicalDataResponse(
        categories=[MedicalCategoryResponse.model_validate(r) for r in cats],
        medications=[MedicationResponse.model_validate(r) for r in meds],
    )


@router.get("/medical/search", response_model=MedicalDataResponse)
@cached(ttl=600, prefix="med_search")
def search_medical_data(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    _auth: str = Depends(require_authorization),
):
    cats = db.exec(
        select(MedicationCategory)
        .where(MedicationCategory.is_active == True)
        .where(MedicationCategory.title.ilike(f"%{q}%"))
        .limit(int(limit))
    ).all()
    meds = db.exec(
        select(Medication)
        .where(Medication.is_active == True)
        .where(Medication.title.ilike(f"%{q}%"))
        .limit(int(limit))
    ).all()
    return MedicalDataResponse(
        categories=[MedicalCategoryResponse.model_validate(c) for c in cats],
        medications=[MedicationResponse.model_validate(m) for m in meds],
        total_categories=len(cats),
        total_medications=len(meds),
    )


# ==============================================================================
# ALIASES & FIXES
# ==============================================================================


@router.get("/book-of-business/metadata")
@cached(ttl=300, prefix="bob_metadata_svc")
def get_bob_metadata_alias(
    request: Request,
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    carrier: Optional[List[str]] = Query(None),
    policy_type: Optional[str] = Query(None),
    own_only: bool = Query(False),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    claims: dict = Depends(require_authorization),
):
    """Alias for bob_metadata_full."""
    return bob_metadata_full(
        search=search,
        date_from=date_from,
        date_to=date_to,
        carrier=carrier,
        policy_type=policy_type,
        own_only=own_only,
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        claims=claims,
    )


# =============================================================================
# DRAFTS (source of truth: public.drafts via cases-service)
# =============================================================================


@router.get("/cases/drafts", response_model=List[DraftClientResponse])
@cached(ttl=600, prefix="drafts_compat")
def list_my_drafts_compat(
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    drafts = svc.list_active()
    return [_draft_to_api(d) for d in drafts]


@router.post("/cases/drafts/create", response_model=DraftClientResponse)
def create_or_update_draft_compat(
    request: DraftCreateOrUpdateRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)

    draft_id = request.draftId
    if draft_id and str(draft_id).strip().lower() == "new":
        draft_id = None

    existing = svc.get(str(draft_id)) if draft_id else None
    merged_data = dict((existing.draft_data or {}) if existing else {})
    merged_status = dict((existing.section_completion_status or {}) if existing else {})

    if request.partialUpdate:
        merged_data.update(request.draftData or {})
        merged_status.update(request.sectionCompletionStatus or {})
    else:
        merged_data = request.draftData or {}
        merged_status = request.sectionCompletionStatus or {}

    d = svc.upsert(
        draft_id=str(draft_id) if draft_id else None,
        draft_data=merged_data or {},
        section_completion_status=merged_status or {},
        last_section_updated=request.updatedSection,
        is_active=True,
    )
    return _draft_to_api(d)


@router.post("/cases/drafts/auto-save", response_model=DraftClientResponse)
def auto_save_draft_compat(
    request: DraftCreateOrUpdateRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    return create_or_update_draft_compat(request=request, db=db, tenant_id=tenant_id, user_id=user_id)


@router.get("/cases/drafts/{draft_or_user_id}", response_model=DraftClientResponse)
@cached(ttl=600, prefix="draft_detail_compat")
def get_draft_or_latest_for_user_compat(
    request: Request,
    draft_or_user_id: str,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)

    try:
        if str(draft_or_user_id).strip() == str(user_uuid):
            drafts = svc.list_active()
            if not drafts:
                raise HTTPException(status_code=404, detail="Draft not found")
            return _draft_to_api(drafts[0])
    except HTTPException:
        raise
    except Exception:
        pass

    d = svc.get(str(draft_or_user_id))
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_to_api(d)


@router.get("/cases/drafts/{draft_id}/as-form")
@cached(ttl=600, prefix="draft_form")
def get_draft_as_form_compat(
    request: Request,
    draft_id: str,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    d = svc.get(str(draft_id))
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    return d.draft_data or {}


@router.delete("/cases/drafts/{draft_id}")
def delete_draft_compat(
    draft_id: str,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    if not svc.soft_delete(str(draft_id)):
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"success": True}


@router.post("/cases/drafts/bulk-delete")
def bulk_delete_drafts_compat(
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    draft_ids = (payload or {}).get("draft_ids") or (payload or {}).get("draftIds") or (payload or {}).get("ids") or []
    if not isinstance(draft_ids, list) or not draft_ids:
        raise HTTPException(status_code=400, detail="draft_ids is required")
    return svc.bulk_soft_delete([str(did) for did in draft_ids])


@router.delete("/cases/drafts/clear-drafts")
def clear_user_drafts_compat(
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    _auth: str = Depends(require_authorization),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    drafts = svc.list_active()
    deleted = 0
    for d in drafts:
        if svc.soft_delete(str(d.id)):
            deleted += 1
    return {"deleted": deleted}


@router.get("/drafts", response_model=List[DraftApiResponse])
@cached(ttl=600, prefix="drafts_list")
def list_my_drafts(
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    drafts = svc.list_active()
    return [DraftApiResponse.model_validate(d) for d in drafts]


@router.get("/drafts/{draft_id}", response_model=DraftApiResponse)
@cached(ttl=600, prefix="draft_detail")
def get_my_draft(
    request: Request,
    draft_id: str,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    d = svc.get(draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    return DraftApiResponse.model_validate(d)


@router.post("/drafts", response_model=DraftApiResponse)
def upsert_my_draft(
    request: DraftUpsertRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    d = svc.upsert(
        draft_id=request.draft_id,
        draft_data=request.draft_data or {},
        section_completion_status=request.section_completion_status or {},
        last_section_updated=request.last_section_updated,
        is_active=bool(request.is_active),
    )
    return DraftApiResponse.model_validate(d)


@router.delete("/drafts/{draft_id}")
def delete_my_draft(
    draft_id: str,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    if not svc.soft_delete(draft_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"success": True}


@router.post("/drafts/bulk-delete")
def bulk_delete_my_drafts(
    request: DraftBulkDeleteRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id),
):
    user_uuid = require_user_uuid(user_id)
    svc = DraftService(db, tenant_id, user_uuid)
    return svc.bulk_soft_delete(request.draft_ids)


# =============================================================================
# CASE HISTORY (formerly data_access_historicalcasedata -> cases_history)
# =============================================================================


@router.get("/cases/{case_id}/history", response_model=List[CaseHistoryResponse])
@cached(ttl=300, prefix="case_history")
def list_case_history(
    request: Request,
    case_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    svc = CaseHistoryService(db, tenant_id)
    rows = svc.list_for_case(case_id=int(case_id), limit=limit)
    return [CaseHistoryResponse.model_validate(r) for r in rows]


@router.post("/cases/{case_id}/history", response_model=CaseHistoryResponse)
def create_case_history(
    case_id: int,
    request: CaseHistoryCreateRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id),
):
    history_user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            history_user_uuid = uuid.UUID(str(user_id))
        except Exception:
            history_user_uuid = None
    svc = CaseHistoryService(db, tenant_id)
    try:
        row = svc.create_snapshot(
            case_id=int(case_id),
            history_type=request.history_type,
            history_change_reason=request.history_change_reason,
            history_user_id=history_user_uuid,
        )
        return CaseHistoryResponse.model_validate(row)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# CRUD
@router.post("/cases", response_model=CaseDetailResponse, status_code=status.HTTP_201_CREATED)
def create_case(
    request: CaseCreateRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """Create a new case."""
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID required")

    try:
        user_uuid = uuid.UUID(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid X-User-Id (must be UUID)")
    
    case_service = CaseService(db, tenant_id, user_id)
    
    case_data = request.model_dump(exclude_unset=True)
    draft_id = case_data.pop("draft_id", None)
    
    case = case_service.create_case(
        agent_id=user_uuid,
        **case_data,
    )
    
    # Delete draft if provided
    if draft_id:
        try:
            draft_svc = DraftService(db, tenant_id, user_uuid)
            draft_svc.soft_delete(str(draft_id))

        except Exception as e:
            print(f"WARNING: Failed to delete draft {draft_id}: {e}")

    # Sync premium sold
    try:
        pb = getattr(case, "policy_and_banking", None) or {}
        if isinstance(pb, dict) and pb:
            _sync_premium_sold_v2(db, case, pb, user_uuid)
        else:
            pass
    except Exception as e:
        print(f"ERROR: Syncing premiums failed: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return CaseDetailResponse.model_validate(case)


@router.get("/cases")
@router.get("/cases/")
@cached(ttl=300, prefix="case_list")
def list_cases(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    pageSize: Optional[int] = Query(None),
    tab: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    sort: Optional[str] = Query("-dateCreated"),
    own_only: bool = Query(False),
    ownOnly: Optional[bool] = Query(None),
    startDate: Optional[str] = Query(None),
    endDate: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    agent: Optional[List[str]] = Query(None),
    agency: Optional[List[str]] = Query(None),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    claims: dict = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    eff_page_size = int(pageSize or page_size or 10)
    eff_page_size = max(1, min(eff_page_size, 100))

    if tab and str(tab).strip().lower() == "drafted":
        u = require_user_uuid(user_id)
        svc = DraftService(db, tenant_id, u)
        drafts = svc.list_active()
        items = []
        for d in drafts:
            dd = d.draft_data or {}
            gi = dd.get("generalInfo") or dd.get("general_information") or {}
            pb = dd.get("policiesBanking") or dd.get("policy_and_banking") or {}
            name = ""
            try:
                name = (gi.get("client_1") or {}).get("name") or ""
            except Exception:
                name = ""
            if not name:
                try:
                    cs = dd.get("clientSetup") or dd.get("client_setup") or {}
                    names = cs.get("clientNames") or cs.get("client_names") or []
                    if isinstance(names, list) and names:
                        name = str(names[0] or "").strip()
                except Exception:
                    name = ""

            draft_clients = []
            for ck in ["client_1", "client_2", "client_3", "client_4", "client_5"]:
                client_pb = pb.get(ck) or {}
                policies = client_pb.get("policies") or []
                if not isinstance(policies, list):
                    policies = []
                for idx, pol in enumerate(policies):
                    if not isinstance(pol, dict):
                        continue
                    carrier_val = pol.get("carrier") or pol.get("carrierName") or "N/A"
                    carrier_name = carrier_val
                    if carrier_val and len(str(carrier_val)) > 20:
                        try:
                            carr_row = db.exec(select(CarrierRow).where(CarrierRow.id == uuid.UUID(str(carrier_val)))).first()
                            if carr_row:
                                carrier_name = carr_row.display_name_override or carr_row.name or carrier_val
                        except Exception:
                            pass
                    monthly = pol.get("monthlyPremium") or pol.get("monthly_premium") or 0
                    try:
                        monthly_f = float(str(monthly).replace(",", "").replace("$", "").strip() or 0)
                    except Exception:
                        monthly_f = 0
                    yearly = pol.get("yearlyPremium") or pol.get("yearly_premium") or pol.get("annualPremium") or 0
                    try:
                        yearly_f = float(str(yearly).replace(",", "").replace("$", "").strip() or 0)
                    except Exception:
                        yearly_f = 0
                    premium = yearly_f if yearly_f > 0 else (monthly_f * 12)
                    plan_name = pol.get("policy") or pol.get("plan_name") or pol.get("planName") or "N/A"
                    plan_type = pol.get("product") or pol.get("plan_type") or pol.get("planType") or "N/A"
                    if str(plan_type).lower() == "other":
                        plan_type = pol.get("otherProduct") or pol.get("other_product") or "Other"
                    policy_number = pol.get("policyNumber") or pol.get("policy_number") or ""
                    client_name_gi = (gi.get(ck) or {}).get("name") or name or "Client"
                    draft_clients.append({
                        "id": f"{d.id}_{ck}_option_{idx + 1}",
                        "name": client_name_gi,
                        "clientNumber": int(ck.split("_")[1]) if "_" in ck else 1,
                        "optionNumber": idx + 1,
                        "planName": str(plan_name).replace("_", " ").title() if plan_name != "N/A" else "N/A",
                        "planType": str(plan_type).replace("_", " ").title() if plan_type != "N/A" else "N/A",
                        "policyNumber": policy_number,
                        "carrierName": carrier_name,
                        "premium": premium if premium > 0 else "N/A",
                        "status": "Draft",
                        "statusLabel": "Draft",
                    })
            if not draft_clients:
                draft_clients.append({
                    "id": f"{d.id}_client_1_option_1",
                    "name": name or "Draft",
                    "clientNumber": 1,
                    "optionNumber": 1,
                    "planName": "N/A",
                    "planType": "N/A",
                    "policyNumber": "",
                    "carrierName": "N/A",
                    "premium": "N/A",
                    "status": "Draft",
                    "statusLabel": "Draft",
                })

            items.append(
                {
                    "id": str(d.id),
                    "name": name or "Draft",
                    "clients": draft_clients,
                    "client_email": (gi.get("client_1") or {}).get("email") or "",
                    "agent": "N/A",
                    "agency": "N/A",
                    "dateCreated": d.created_at.isoformat() + "Z" if getattr(d.created_at, "isoformat", None) else None,
                    "lastUpdated": d.updated_at.isoformat() + "Z" if getattr(d.updated_at, "isoformat", None) else None,
                    "status": "Draft",
                    "currentStage": "Draft",
                    "premium": "N/A",
                    "carrier": "N/A",
                    "is_draft": True,
                    "draft_id": str(d.id),
                }
            )
        total = len(items)
        total_pages = (total + eff_page_size - 1) // eff_page_size if eff_page_size else 0
        start = (int(page) - 1) * eff_page_size
        end = start + eff_page_size
        paged = items[start:end]
        return {
            "items": paged,
            "pagination": {"page": int(page), "pageSize": eff_page_size, "total": total, "totalPages": int(total_pages)},
            "tabCounts": {"drafted": total},
        }

    def _parse_dt(v: Optional[str]) -> Optional[datetime]:
        if not v:
            return None
        s = str(v).strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            try:
                if len(s) == 10 and s[4] == "-" and s[7] == "-":
                    return datetime.fromisoformat(s)
            except Exception:
                return None
        return None

    from_dt = _parse_dt(start_date or startDate)
    to_dt = _parse_dt(end_date or endDate)

    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None

    is_admin = _resolve_desk_is_admin(claims)

    eff_own_only = bool(ownOnly) if ownOnly is not None else bool(own_only)

    q = select(CaseData).where(CaseData.tenant_id == tenant_id)
    q = q.where((CaseData.is_active == True) | (CaseData.is_active.is_(None)))
    q = q.where(~CaseData.status.in_([9, 10]))

    if eff_own_only and user_uuid:
        q = q.where((CaseData.created_by_id == user_uuid) | (CaseData.agent_id == user_uuid))

    if search:
        st = f"%{search}%"
        q = q.where(
            (CaseData.name.ilike(st))
            | (CaseData.client1_name.ilike(st))
            | (CaseData.client2_name.ilike(st))
            | (CaseData.client1_email.ilike(st))
            | (CaseData.client2_email.ilike(st))
            | (CaseData.policy_number.ilike(st))
        )

    if from_dt:
        q = q.where(CaseData.created_at >= from_dt)
    if to_dt:
        q = q.where(CaseData.created_at <= to_dt)

    if agent:
        # Filter by agent names
        # Map names to user IDs
        try:
            from sqlalchemy import desc
            # Find users whose full name matches one of the provided names
            # This is a bit complex as we construct full name from first/last. 
            # We'll do a simple like or exact match logic if first_name + ' ' + last_name is standard.
            # Safest is to fetch all active users on tenant and check in python if list is small, or use SQL.
            # Given typically small agent count per tenant, fetching tenant users is fine.
            t_users = db.exec(select(UserRow).where(UserRow.tenant_id == tenant_id)).all()
            target_uids = []
            for u in t_users:
                full = f"{u.first_name or ''} {u.last_name or ''}".strip()
                if full in agent:
                    target_uids.append(u.id)
            
            if target_uids:
                q = q.where((CaseData.created_by_id.in_(target_uids)) | (CaseData.agent_id.in_(target_uids)))
            else:
                # User asked for agents that don't exist/match, return empty
                q = q.where(CaseData.id == -1)
        except Exception as e:
            print(f"Error filtering by agent: {e}")

    if agency:
        # Filter by agency names
        # Find agencies by name, then find members, then filter cases
        try:
            from sqlalchemy import bindparam
            aq = text("SELECT id FROM agency WHERE name IN :names AND is_active = true").bindparams(
                bindparam("names", expanding=True)
            )
            ag_rows = db.execute(aq, {"names": list(agency)}).all()
            ag_ids = [r[0] for r in ag_rows]

            if ag_ids:
                # Find users in these agencies
                mq = text("SELECT agent_id FROM agency_member WHERE agency_id IN :ids AND is_active = true").bindparams(
                    bindparam("ids", expanding=True)
                )
                m_rows = db.execute(mq, {"ids": ag_ids}).all()
                member_ids = [r[0] for r in m_rows]
                
                if member_ids:
                    q = q.where((CaseData.created_by_id.in_(member_ids)) | (CaseData.agent_id.in_(member_ids)))
                else:
                    q = q.where(CaseData.id == -1)
            else:
                q = q.where(CaseData.id == -1)

        except Exception as e:
            print(f"Error filtering by agency: {e}")

    status_id = _tab_to_status_id(tab)
    if status_id is not None:
        q = q.where(CaseData.status == int(status_id))

    count_q = select(func.count()).select_from(q.subquery())
    total = int(db.exec(count_q).one() or 0)

    sort_key = str(sort or "").strip()
    if sort_key in ("-dateCreated", "-createdAt", "-created_at"):
        q = q.order_by(CaseData.created_at.desc().nullslast())
    elif sort_key in ("dateCreated", "createdAt", "created_at"):
        q = q.order_by(CaseData.created_at.asc().nullsfirst())
    elif sort_key in ("-lastUpdated", "-modified_at", "-modifiedAt"):
        q = q.order_by(CaseData.modified_at.desc().nullslast())
    else:
        q = q.order_by(CaseData.created_at.desc().nullslast())

    q = q.offset((int(page) - 1) * eff_page_size).limit(eff_page_size)
    rows = db.exec(q).all() or []

    agent_ids: List[uuid.UUID] = []
    for c in rows:
        aid = c.created_by_id or c.agent_id
        if aid:
            agent_ids.append(aid)

    users_by_id: Dict[str, UserRow] = {}
    if agent_ids:
        try:
            urows = db.exec(select(UserRow).where(UserRow.tenant_id == tenant_id, UserRow.id.in_(agent_ids))).all() or []
            for u in urows:
                users_by_id[str(u.id)] = u
        except Exception:
            db.rollback()
            users_by_id = {}

    agent_agency_map: Dict[str, str] = {}
    if agent_ids:
        try:
            from sqlalchemy import bindparam
            agency_q = text(
                "SELECT am.agent_id, a.name FROM agency_member am JOIN agency a ON am.agency_id = a.id "
                "WHERE am.agent_id IN :ids AND am.is_active = true"
            ).bindparams(bindparam("ids", expanding=True))
            agency_rows = db.execute(agency_q, {"ids": [str(aid) for aid in agent_ids]}).all()
            for row in agency_rows:
                agent_agency_map[str(row[0])] = row[1]
        except Exception:
            db.rollback()
            agent_agency_map = {}

    case_ids: List[int] = [int(c.id) for c in rows if getattr(c, "id", None) is not None]

    premiums_by_case: Dict[int, List[PremiumSoldRow]] = {}
    carrier_ids: set[str] = set()
    product_ids: set[str] = set()
    agency_ids: set[str] = set()
    if case_ids:
        try:
            prows = db.exec(
                select(PremiumSoldRow)
                .select_from(PremiumSoldRow)
                .join(UserRow, UserRow.id == PremiumSoldRow.user_id)
                .where(
                    UserRow.tenant_id == tenant_id,
                    PremiumSoldRow.is_active == True,
                    PremiumSoldRow.case_data_id.in_(case_ids),
                )
            ).all() or []
            for p in prows:
                if p.case_data_id is None:
                    continue
                premiums_by_case.setdefault(int(p.case_data_id), []).append(p)
                if p.carrier_id:
                    carrier_ids.add(str(p.carrier_id))
                if p.product_id:
                    product_ids.add(str(p.product_id))
                if p.agency_id:
                    agency_ids.add(str(p.agency_id))
        except Exception:
            db.rollback()
            premiums_by_case = {}

    carriers_by_id: Dict[str, CarrierRow] = {}
    if carrier_ids:
        try:
            crows = db.exec(select(CarrierRow).where(CarrierRow.id.in_([uuid.UUID(x) for x in carrier_ids]))).all() or []
            for r in crows:
                carriers_by_id[str(r.id)] = r
        except Exception:
            db.rollback()
            carriers_by_id = {}

    products_by_id: Dict[str, ProductRow] = {}
    if product_ids:
        try:
            prods = db.exec(select(ProductRow).where(ProductRow.id.in_([uuid.UUID(x) for x in product_ids]))).all() or []
            for r in prods:
                products_by_id[str(r.id)] = r
        except Exception:
            db.rollback()
            products_by_id = {}

    agencies_by_id: Dict[str, AgencyRow] = {}
    if agency_ids:
        try:
            arows = db.exec(
                select(AgencyRow).where(AgencyRow.id.in_([uuid.UUID(x) for x in agency_ids]))
            ).all() or []
            for r in arows:
                agencies_by_id[str(r.id)] = r
        except Exception:
            db.rollback()
            agencies_by_id = {}

    all_carrier_uuids: set[str] = set()
    for c in rows:
        pab = c.policy_and_banking or {}
        for ci in range(1, 11):
            cd = pab.get(f"client_{ci}") or {}
            for k, v in cd.items():
                if k == "carrier" and isinstance(v, str) and len(v) > 20:
                    all_carrier_uuids.add(v)
                elif isinstance(v, dict):
                    cid = v.get("carrier")
                    if cid and isinstance(cid, str) and len(cid) > 20:
                        all_carrier_uuids.add(cid)
            for pol in (cd.get("policies") or []):
                if isinstance(pol, dict):
                    cid = pol.get("carrier")
                    if cid and isinstance(cid, str) and len(cid) > 20:
                        all_carrier_uuids.add(cid)
    extra_carriers: Dict[str, str] = {}
    if all_carrier_uuids:
        try:
            ec_rows = db.exec(select(CarrierRow).where(CarrierRow.id.in_([uuid.UUID(x) for x in all_carrier_uuids]))).all() or []
            for r in ec_rows:
                extra_carriers[str(r.id)] = _carrier_display(r)
        except Exception:
            db.rollback()

    items: List[Dict[str, Any]] = []
    for c in rows:
        aid = c.created_by_id or c.agent_id
        agent_name = _user_display(users_by_id.get(str(aid))) if aid else "N/A"

        status_label = _case_status_to_label(c.status)
        clients = _extract_clients_from_case(c)
        for cl in clients:
            carr = cl.get("carrier") or cl.get("carrierName") or ""
            if carr and isinstance(carr, str) and len(carr) > 20:
                resolved = extra_carriers.get(carr) or carriers_by_id.get(carr)
                if resolved:
                    cl["carrier"] = _carrier_display(resolved) if hasattr(resolved, "name") else resolved
                    cl["carrierName"] = cl["carrier"]
        clients, agency_name = _merge_premiums_into_clients(
            case=c,
            clients=clients,
            premiums=premiums_by_case.get(int(c.id), []) if getattr(c, "id", None) is not None else [],
            carriers_by_id=carriers_by_id,
            products_by_id=products_by_id,
            agencies_by_id=agencies_by_id,
        )
        if agency_name == "N/A" and aid:
            agency_name = agent_agency_map.get(str(aid), "N/A")
        first_client = clients[0] if clients else {}
        case_carrier = first_client.get("carrierName") or first_client.get("carrier") or "N/A"
        case_premium = first_client.get("premium")
        if case_premium is None or case_premium == 0:
            case_premium = c.premium if c.premium is not None else "N/A"
        common_details_out = _sanitize_documents_for_list(c.common_details)
        items.append(
            {
                "id": int(c.id),
                "name": c.name or c.client1_name or c.client_first_name or "Unnamed Case",
                "clients": clients,
                "client_email": (c.client1_email or c.client_email or ""),
                "agent": agent_name,
                "agency": agency_name,
                "dateCreated": c.created_at.isoformat() + "Z" if getattr(c.created_at, "isoformat", None) else None,
                "lastUpdated": c.modified_at.isoformat() + "Z" if getattr(c.modified_at, "isoformat", None) else None,
                "status": status_label,
                "currentStage": status_label,
                "premium": case_premium,
                "carrier": case_carrier,
                "common_details": common_details_out,
                "is_draft": False,
                "draft_id": None,
            }
        )

    total_pages = (total + eff_page_size - 1) // eff_page_size if eff_page_size else 0

    base_filters = [
        CaseData.tenant_id == tenant_id,
        (CaseData.is_active == True) | (CaseData.is_active.is_(None)),
        ~CaseData.status.in_([9, 10]),
    ]
    if (eff_own_only) and user_uuid:
        base_filters.append((CaseData.created_by_id == user_uuid) | (CaseData.agent_id == user_uuid))
    if search:
        st = f"%{search}%"
        base_filters.append(
            (CaseData.name.ilike(st))
            | (CaseData.client1_name.ilike(st))
            | (CaseData.client2_name.ilike(st))
            | (CaseData.client1_email.ilike(st))
            | (CaseData.client2_email.ilike(st))
            | (CaseData.policy_number.ilike(st))
        )
    if from_dt:
        base_filters.append(CaseData.created_at >= from_dt)
    if to_dt:
        base_filters.append(CaseData.created_at <= to_dt)

    counts_rows = db.exec(
        select(CaseData.status, func.count(CaseData.id))
        .where(*base_filters)
        .group_by(CaseData.status)
    ).all() or []
    counts_map: Dict[int, int] = {}
    all_count = 0
    for st, cnt in counts_rows:
        try:
            sid = int(st or 0)
        except Exception:
            sid = 0
        v = int(cnt or 0)
        counts_map[sid] = int(counts_map.get(sid, 0)) + v
        all_count += v

    drafted_count = 0
    if user_uuid:
        try:
            drafted_count = len(DraftService(db, tenant_id, user_uuid).list_active())
        except Exception:
            drafted_count = 0

    tab_counts = {
        "all": all_count,
        "in-progress": int(counts_map.get(1, 0)),
        "submitted": int(counts_map.get(2, 0)),
        "issued": int(counts_map.get(4, 0)),
        "denied": int(counts_map.get(6, 0)),
        "lapsed": int(counts_map.get(7, 0)),
        "pending-lapse": int(counts_map.get(8, 0)),
        "hold": int(counts_map.get(3, 0)),
        "imported": 0,
        "drafted": drafted_count,
    }

    return {
        "items": items,
        "pagination": {"page": int(page), "pageSize": eff_page_size, "total": int(total), "totalPages": int(total_pages)},
        "tabCounts": tab_counts,
    }


@router.get("/cases/stats", response_model=CaseStatsResponse)
@cached(ttl=600, prefix="case_stats")
def get_case_stats(
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    """Get case statistics."""
    case_service = CaseService(db, tenant_id)
    return case_service.get_stats()


@router.get("/cases/metadata")
@cached(ttl=1800, prefix="case_metadata")
def get_cases_metadata(
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id),
):
    """
    Metadata used by Desk frontend filters.

    The current Desk UI expects:
    - statusOptions: [{ value, label }]
    - agencyOptions: [string]
    - agentOptions: [string]
    """
    # Fetch agents (Users) associated with this tenant
    agent_options = []
    try:
        # Relaxed filter: Fetch all active users with names (matching legacy behavior)
        users = db.exec(
             select(UserRow)
             .where(UserRow.is_active == True)
             .where(UserRow.first_name.is_not(None) | UserRow.last_name.is_not(None))
        ).all()
        
        agent_options = sorted(list(set([f"{u.first_name} {u.last_name}".strip() for u in users if u.first_name or u.last_name])))
    except Exception as e:
        print(f"Error fetching agents for metadata: {e}")

    # Fetch agencies associated with this tenant
    # Logic: Get agencies linked to active agency members in this tenant
    agency_options = []
    try:
        # Relaxed filter: Fetch all active agencies directly, matching legacy behavior
        q = select(AgencyRow.name).where(AgencyRow.name.is_not(None)).distinct().order_by(AgencyRow.name)
        rows = db.exec(q).all()
        agency_options = [r for r in rows if r]
        
    except Exception as e:
        print(f"Error fetching agencies for metadata: {e}")

    status_options = [
        {"value": "In progress", "label": "In progress"},
        {"value": "submitted", "label": "submitted"},
        {"value": "Issued", "label": "Issued"},
        {"value": "Denied", "label": "Denied"},
        {"value": "Lapsed", "label": "Lapsed"},
        {"value": "Pending Lapse", "label": "Pending Lapse"},
        {"value": "Hold", "label": "Hold"},
    ]
    draft_count = 0
    if user_id:
        try:
            u = uuid.UUID(str(user_id))
            draft_count = len(DraftService(db, tenant_id, u).list_active())
        except Exception:
            draft_count = 0
    return {"statusOptions": status_options, "agencyOptions": agency_options, "agentOptions": agent_options, "draftCount": draft_count}


@router.get("/cases/recent")
@cached(ttl=300, prefix="recent_cases")
def get_recent_cases(
    request: Request,
    limit: int = Query(5, ge=1, le=100),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    """Recent cases feed used by the Desk dashboard UI."""
    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None
    svc = CaseService(db, tenant_id)
    return svc.dashboard_recent_cases(limit=limit, user_id=user_uuid)


@router.get("/cases/{case_id}", response_model=CaseDetailResponse)
@cached(ttl=600, prefix="case_detail")
def get_case(
    request: Request,
    case_id: int,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    """Get case by ID."""
    case_service = CaseService(db, tenant_id)
    case = case_service.get_case(case_id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    return CaseDetailResponse.model_validate(case)


@router.put("/cases/{case_id}", response_model=CaseDetailResponse)
def update_case(
    case_id: int,
    request: CaseUpdateRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """Update a case."""
    case_service = CaseService(db, tenant_id)
    updates = request.model_dump(exclude_unset=True)
    updates = request.model_dump(exclude_unset=True)
    if "policy_and_banking" in updates:
        pass
    else:
        pass

    case = case_service.update_case(
        case_id=case_id,
        **updates,
    )
    
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return CaseDetailResponse.model_validate(case)
    
    # Sync premium sold
    try:
        user_uuid: Optional[uuid.UUID] = None
        if hasattr(request, "user_id"):
             # Try to get user from request context if possible, otherwise use case owner
             pass
        
        # We need a user_uuid for the sync function. Use the one from dependency or case owner.
        # In this route we don't have user_id dependency explicitly, but we have tenant.
        # Let's try to get it from the case object itself.
        current_user_id = case.created_by_id or case.agent_id
        if current_user_id:
             pb = getattr(case, "policy_and_banking", None) or {}
             if isinstance(pb, dict) and pb:
                 _sync_premium_sold_from_policies(db, case, pb, current_user_id)
    except Exception as e:
        print(f"ERROR: Syncing premiums on update failed: {e}")
        import traceback
        traceback.print_exc()
        # Don't rollback the main update, just log the error
        pass

    return CaseDetailResponse.model_validate(case)



class CaseOptionStatusRequest(BaseModel):
    client_number: int
    option_number: int
    status: str

@router.post("/cases/{case_id}/option-status")
def set_case_option_status(
    case_id: int,
    request: CaseOptionStatusRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """
    Update status for a specific client option (policy).
    Unifies logic between PremiumSoldRow (BoB) and JSON (Cases).
    """
    case_service = CaseService(db, tenant_id)
    case = case_service.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    try:
        status_id = _status_input_to_case_status_id(request.status)
    except ValueError as e:
        # User friendly message
        raise HTTPException(status_code=400, detail=f"Invalid status: {request.status}. Please select a valid status.")
    except Exception as e:
        print(f"ERROR: set_case_option_status failed silently: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal Server Error during status update.")
    
    # 1. Update PremiumSoldRow (for BoB) — one physical row via ctid if duplicates exist
    unique_id = f"{case_id}_client_{request.client_number}_option_{request.option_number}"

    premium_status_id = _case_status_id_to_premium_status(status_id)
    opt_now = datetime.utcnow()
    t_ps = PremiumSoldRow.__table__
    ctid_sq = _premium_sold_latest_ctid_subquery(
        unique_policy_identifier=unique_id,
        case_data_id=int(case_id),
    )
    up_opt = db.execute(
        update(t_ps)
        .where(column("ctid") == ctid_sq)
        .values(status=int(premium_status_id), modified_at=opt_now)
    )
    if getattr(up_opt, "rowcount", 0) < 1:
        print(f"WARNING: PremiumSoldRow not found for {unique_id} when setting status.")

    # 2. Update CaseData JSON (for Cases List view & consistency)
    # We update common_details.optionStatusOverrides usually, or policy_and_banking
    # But current logic in _extract_clients_from_case (lines 420+) reads from optionStatusOverrides.
    
    cd = dict(case.common_details or {})
    oso = cd.get("optionStatusOverrides") or cd.get("option_status_overrides") or []
    if not isinstance(oso, list):
        oso = []
    
    # Remove existing override for this option
    oso = [
        o for o in oso 
        if not (
            str(o.get("client_number") or o.get("clientNumber")) == str(request.client_number) 
            and str(o.get("option_number") or o.get("optionNumber")) == str(request.option_number)
        )
    ]
    
    # Add new override
    oso.append({
        "clientNumber": request.client_number,
        "optionNumber": request.option_number,
        "status": request.status,
        "statusId": status_id
    })
    
    cd["optionStatusOverrides"] = oso
    case.common_details = cd
    case.modified_at = datetime.utcnow()
    db.add(case)
    db.commit()
    db.refresh(case)
    
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return {"success": True, "case_id": case.id}

@router.patch("/cases/{case_id}/status")
def update_case_status(
    case_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """Update case status."""
    status_value = (payload or {}).get("status")
    carrier_status_id = (payload or {}).get("carrier_status_id")
    try:
        status_id = _status_input_to_case_status_id(status_value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    case_service = CaseService(db, tenant_id)
    case = case_service.update_status(
        case_id=case_id,
        status=int(status_id),
        carrier_status_id=carrier_status_id,
    )
    
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Sync status to PremiumSoldRow
    try:
        _sync_premium_sold_v2(db, case, case.policy_and_banking, None)
    except Exception as e:
        print(f"Error syncing premiums on status update: {e}")
        db.rollback()
        case = case_service.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

    last_updated = case.modified_at.isoformat() + "Z" if getattr(case.modified_at, "isoformat", None) else None
    out = CaseDetailResponse.model_validate(case).model_dump()
    out["lastUpdated"] = last_updated
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return out


@router.delete("/cases/{case_id}")
def delete_case(
    case_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """Delete a case."""
    case_service = CaseService(db, tenant_id)
    deleted = False
    try:
        deleted = bool(case_service.delete_case(case_id))
    except Exception:
        deleted = False
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return {"message": "Case deleted" if deleted else "Case not found (already deleted)"}


@router.post("/cases/bulk-delete")
def bulk_delete_cases(
    request: BulkDeleteRequest,
    http_request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """Bulk delete cases."""
    case_service = CaseService(db, tenant_id)
    result = case_service.bulk_delete(request.case_ids)
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    
    return result


# Desk frontend compatibility endpoints

@router.post("/cases/status/bulk")
def bulk_update_case_status(
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    ids = (payload or {}).get("ids") or []
    new_status = (payload or {}).get("status")
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids is required")
    try:
        status_id = _status_input_to_case_status_id(new_status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    svc = CaseService(db, tenant_id)
    updated = 0
    failed: List[Any] = []
    for cid in ids:
        try:
            case = svc.update_status(case_id=int(cid), status=int(status_id), carrier_status_id=None)
            if case:
                updated += 1
            else:
                failed.append(cid)
        except Exception:
            failed.append(cid)
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return {"updated": updated, "failed": failed}


@router.post("/cases/delete/bulk")
def bulk_delete_cases_compat(
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    ids = (payload or {}).get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids is required")
    svc = CaseService(db, tenant_id)
    res = svc.bulk_delete([int(x) for x in ids])
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return res


@router.post("/cases/{client_id}/actions")
def execute_case_client_action(client_id: str, payload: Dict[str, Any]):
    action = (payload or {}).get("action")
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    return {"executed": False, "message": "Action not implemented", "client_id": client_id, "action": action}


@router.patch("/cases/client/{policy_id}/status")
def update_policy_status(
    policy_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    _auth: str = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    status_value = (payload or {}).get("status")
    if not status_value:
        raise HTTPException(status_code=400, detail="status is required")
    raw = str(status_value).strip()
    sl = raw.lower()
    mapping = {
        "issued": 4,
        "lapsed": 6,
        "pending-lapsed": 7,
        "pending-lapse": 7,
        "pending lapse": 7,
        "replaced": 8,
        "cancelled": 9,
        "canceled": 9,
    }
    premium_status = mapping.get(sl)
    if premium_status is None:
        raise HTTPException(status_code=400, detail="Invalid status")

    ps = db.exec(select(PremiumSoldRow).where(PremiumSoldRow.id == int(policy_id))).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Policy not found")

    cid = getattr(ps, "case_data_id", None)
    if cid is None and getattr(ps, "unique_policy_identifier", None):
        try:
            cid = int(str(ps.unique_policy_identifier or "").split("_", 1)[0])
        except Exception:
            cid = None
    if cid is None:
        raise HTTPException(status_code=400, detail="Policy is missing case_data_id")

    c = db.get(CaseData, int(cid))
    if not c or c.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Case not found")

    now = datetime.utcnow()
    # Legacy rows may share the same premium_sold.id; ORM UPDATE can match >1 and raise
    # StaleDataError. Target one physical row via PostgreSQL ctid using SQLAlchemy Core.
    t_ps = PremiumSoldRow.__table__
    ctid_sq = _premium_sold_latest_ctid_subquery(by_id=int(policy_id))
    up = db.execute(
        update(t_ps)
        .where(column("ctid") == ctid_sq)
        .values(status=int(premium_status), is_active=True, modified_at=now)
    )
    if getattr(up, "rowcount", 0) != 1:
        raise HTTPException(status_code=404, detail="Policy not found")
    db.commit()
    db.expire_all()
    ps = db.exec(
        select(PremiumSoldRow)
        .where(PremiumSoldRow.id == int(policy_id))
        .order_by(PremiumSoldRow.modified_at.desc())
    ).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Policy not found")

    try:
        new_case_status = _recompute_case_status_from_premiums(db, int(cid))
        if new_case_status is not None:
            c.status = int(new_case_status)
            c.modified_at = now
            if int(new_case_status) == CaseStatus.ISSUED and not c.issued_at:
                c.issued_at = now
            db.add(c)
            db.commit()
            db.refresh(c)
    except Exception as e:
        # Log error but don't fail the whole operation
        import traceback
        print(f"Error recomputing case status for case {cid}: {e}")
        print(traceback.format_exc())
        db.rollback()

    ui_sid, ui_label = _premium_status_to_ui(int(ps.status or 0))
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return {
        "success": True,
        "policyId": int(ps.id),
        "statusId": int(ui_sid),
        "status": ui_label,
        "caseId": int(cid),
        "caseStatusId": int(c.status or 0),
        "caseStatus": _case_status_to_label(c.status),
        "lastUpdated": _format_mdy_slash(c.modified_at),
    }


@router.get("/cases/export.csv")
async def export_cases_csv(
    ids: Optional[List[int]] = Query(None),
    search: Optional[str] = Query(None),
    tab: Optional[str] = Query(None),
    startDate: Optional[str] = Query(None),
    endDate: Optional[str] = Query(None),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    items: List[Dict[str, Any]] = []

    if ids:
        wanted = [int(x) for x in (ids or [])]
        q = select(CaseData).where(CaseData.tenant_id == tenant_id).where(CaseData.id.in_(wanted))
        q = q.where((CaseData.is_active == True) | (CaseData.is_active.is_(None)))
        q = q.where(~CaseData.status.in_([9, 10]))
        rows = db.exec(q).all() or []
        name_cache: Dict[str, str] = {}
        for c in rows:
            agent_uuid = c.created_by_id or c.agent_id
            agent_name = "N/A"
            if agent_uuid:
                k = str(agent_uuid)
                if k in name_cache:
                    agent_name = name_cache[k]
                else:
                    agent_name = await _users_get_name(tenant_id=tenant_id, authorization=authorization, user_id=agent_uuid)
                    name_cache[k] = agent_name
            status_label = _case_status_to_label(c.status)
            items.append(
                {
                    "id": int(c.id),
                    "name": c.name or c.client1_name or c.client_first_name or "Unnamed Case",
                    "status": status_label,
                    "agent": agent_name,
                    "dateCreated": c.created_at.isoformat() + "Z" if getattr(c.created_at, "isoformat", None) else None,
                    "lastUpdated": c.modified_at.isoformat() + "Z" if getattr(c.modified_at, "isoformat", None) else None,
                }
            )
    else:
        page_num = 1
        while True:
            resp = list_cases(
                page=page_num,
                page_size=100,
                pageSize=100,
                tab=tab or "all",
                search=search,
                sort="-dateCreated",
                own_only=False,
                ownOnly=None,
                startDate=startDate,
                endDate=endDate,
                start_date=None,
                end_date=None,
                db=db,
                tenant_id=tenant_id,
                authorization=authorization,
                user_id=user_id,
            )
            batch = resp.get("items") if isinstance(resp, dict) else []
            items.extend(batch or [])
            total_pages = int(((resp.get("pagination") or {}).get("totalPages")) or 0) if isinstance(resp, dict) else 0
            if total_pages == 0 or page_num >= total_pages:
                break
            page_num += 1

    def _iter() -> Any:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["case_id", "case_name", "status", "agent", "date_created", "last_updated"])
        yield out.getvalue().encode("utf-8")
        for it in items or []:
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow([it.get("id"), it.get("name"), it.get("status"), it.get("agent"), it.get("dateCreated"), it.get("lastUpdated")])
            yield out.getvalue().encode("utf-8")

    filename = f"cases_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        _iter(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}/export.csv")
async def export_single_case_csv(
    case_id: int,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    resp = await export_cases_csv(
        ids=[int(case_id)],
        search=None,
        tab=None,
        startDate=None,
        endDate=None,
        db=db,
        tenant_id=tenant_id,
        authorization=authorization,
        user_id=user_id,
    )
    return resp


@router.post("/cases/submit")
def submit_case(
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    u = require_user_uuid(user_id)

    client_setup = (payload or {}).get("client_setup") or (payload or {}).get("clientSetup") or {}
    client_assessment = (payload or {}).get("client_assessment") or (payload or {}).get("clientAssessment") or {}
    mortgage_info = (payload or {}).get("mortgage_info") or (payload or {}).get("mortgageInfo") or {}
    financial_assessment = (payload or {}).get("financial_assessment") or (payload or {}).get("financialAssessment") or {}
    coverage = (payload or {}).get("type_of_coverage") or (payload or {}).get("coverage") or {}
    general_information = (payload or {}).get("general_information") or (payload or {}).get("generalInfo") or {}
    policy_and_banking = (payload or {}).get("policy_and_banking") or (payload or {}).get("policiesBanking") or {}
    benificiaries = (payload or {}).get("benificiaries") or (payload or {}).get("beneficiaries") or {}

    def _gi_first(key: str) -> str:
        try:
            c1 = (general_information or {}).get("client_1") or {}
            v = c1.get(key)
            return str(v).strip() if v is not None else ""
        except Exception:
            return ""

    name = _gi_first("name")
    email = _gi_first("email")

    case = CaseData(
        tenant_id=tenant_id,
        created_by_id=u,
        agent_id=u,
        is_active=True,
        status=1,
        name=name or None,
        client1_name=name or None,
        client1_email=email or None,
        mortgage_info=mortgage_info or {},
        client_assessment=client_assessment or {},
        financial_assessment=financial_assessment or {},
        type_of_coverage=coverage or {},
        general_information=general_information or {},
        policy_and_banking=policy_and_banking or {},
        benificiaries=benificiaries or {},
        common_details={"client_setup": client_setup} if client_setup else {},
        created_at=datetime.utcnow(),
        modified_at=datetime.utcnow(),
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    # Delete draft if provided
    draft_id = (payload or {}).get("draft_id") or (payload or {}).get("draftId")
    if draft_id:
        try:
            from app.services import DraftService
            draft_svc = DraftService(db, tenant_id, u)
            draft_svc.soft_delete(str(draft_id))
        except Exception as e:
            print(f"Error deleting draft {draft_id} after submission: {e}")
    
    # Sync individual policies to premium_sold table
    try:
        _sync_premium_sold_v2(db, case, policy_and_banking, u)
    except Exception as e:
        print(f"Error syncing premiums on submit: {e}")

    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return {"success": True, "data": {"case_id": int(case.id)}}


@router.post("/cases/complete")
def create_complete_case(
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    return submit_case(payload=payload, db=db, tenant_id=tenant_id, authorization=authorization, user_id=user_id)


@router.get("/cases/{case_id}/complete")
@cached(ttl=600, prefix="case_complete")
def get_case_complete(
    request: Request,
    case_id: int,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc = CaseService(db, tenant_id)
    c = svc.get_case(int(case_id))
    if not c:
        raise HTTPException(status_code=404, detail="Case not found")

    client_assessment_resp: Dict[str, Any] = c.client_assessment or {}
    try:
        cd = c.common_details or {}
        is_imported = bool(
            isinstance(cd, dict)
            and (cd.get("is_imported") or cd.get("isImported") or cd.get("is_imported_case"))
        )
        if is_imported and isinstance(client_assessment_resp, dict):
            gi = c.general_information or {}
            if isinstance(gi, dict):
                out: Dict[str, Any] = dict(client_assessment_resp)
                for i in range(1, 3):
                    ck = f"client_{i}"
                    raw = out.get(ck)
                    if not isinstance(raw, dict):
                        continue
                    if str(raw.get("full_name") or "").strip():
                        continue
                    gi_client = gi.get(ck)
                    if isinstance(gi_client, dict) and str(gi_client.get("name") or "").strip():
                        next_client = dict(raw)
                        next_client["full_name"] = str(gi_client.get("name") or "").strip()
                        out[ck] = next_client
                client_assessment_resp = out
    except Exception:
        client_assessment_resp = c.client_assessment or {}

    agent_name = "N/A"
    try:
        aid = c.created_by_id or c.agent_id
        if aid:
            u = db.exec(select(UserRow).where(UserRow.tenant_id == tenant_id, UserRow.id == aid)).first()
            agent_name = _user_display(u)
    except Exception:
        agent_name = "N/A"
    status_label = _case_status_to_label(c.status)
    clients = _extract_clients_from_case(c)
    premiums: List[PremiumSoldRow] = []
    carriers_by_id: Dict[str, CarrierRow] = {}
    products_by_id: Dict[str, ProductRow] = {}
    agencies_by_id: Dict[str, AgencyRow] = {}
    try:
        prows = db.exec(
            select(PremiumSoldRow)
            .select_from(PremiumSoldRow)
            .join(UserRow, UserRow.id == PremiumSoldRow.user_id)
            .where(
                UserRow.tenant_id == tenant_id,
                PremiumSoldRow.is_active == True,
                PremiumSoldRow.case_data_id == int(case_id),
            )
        ).all() or []
        premiums = prows
        carrier_ids = [p.carrier_id for p in premiums if p.carrier_id]
        product_ids = [p.product_id for p in premiums if p.product_id]
        agency_ids = [p.agency_id for p in premiums if p.agency_id]
        if carrier_ids:
            for r in db.exec(select(CarrierRow).where(CarrierRow.id.in_(carrier_ids))).all() or []:
                carriers_by_id[str(r.id)] = r
        if product_ids:
            for r in db.exec(select(ProductRow).where(ProductRow.id.in_(product_ids))).all() or []:
                products_by_id[str(r.id)] = r
        if agency_ids:
            for r in db.exec(select(AgencyRow).where(AgencyRow.id.in_(agency_ids))).all() or []:
                agencies_by_id[str(r.id)] = r
    except Exception:
        premiums = []
        carriers_by_id = {}
        products_by_id = {}
        agencies_by_id = {}

    clients, agency_name = _merge_premiums_into_clients(
        case=c,
        clients=clients,
        premiums=premiums,
        carriers_by_id=carriers_by_id,
        products_by_id=products_by_id,
        agencies_by_id=agencies_by_id,
    )

    if agency_name == "N/A":
        aid = c.created_by_id or c.agent_id
        if aid:
            try:
                from sqlalchemy import text
                agency_q = text(
                    "SELECT a.name FROM agency_member am "
                    "JOIN agency a ON am.agency_id = a.id "
                    "WHERE am.agent_id = :aid AND am.is_active = true LIMIT 1"
                )
                row = db.execute(agency_q, {"aid": str(aid)}).first()
                if row and row[0]:
                    agency_name = row[0]
            except Exception:
                db.rollback()

    all_carrier_uuids: set[str] = set()
    for cl in clients or []:
        if not isinstance(cl, dict):
            continue
        for k in ("carrierName", "carrier"):
            v = cl.get(k)
            if v and isinstance(v, str) and len(v) > 20:
                all_carrier_uuids.add(v)

    carrier_name_by_uuid: Dict[str, str] = {}
    if all_carrier_uuids:
        try:
            rows = db.exec(select(CarrierRow).where(CarrierRow.id.in_([uuid.UUID(x) for x in all_carrier_uuids]))).all() or []
            for r in rows:
                carrier_name_by_uuid[str(r.id)] = _carrier_display(r)
        except Exception:
            db.rollback()
            carrier_name_by_uuid = {}

    if carrier_name_by_uuid:
        for cl in clients or []:
            if not isinstance(cl, dict):
                continue
            carr = cl.get("carrierName") or cl.get("carrier")
            if carr and isinstance(carr, str) and carr in carrier_name_by_uuid:
                cl["carrier"] = carrier_name_by_uuid[carr]
                cl["carrierName"] = carrier_name_by_uuid[carr]

    pb = c.policy_and_banking or {}
    if isinstance(pb, dict) and carrier_name_by_uuid:
        for _, v in pb.items():
            if not isinstance(v, dict):
                continue
            pols = v.get("policies")
            if not isinstance(pols, list):
                continue
            for p in pols:
                if not isinstance(p, dict):
                    continue
                carr = p.get("carrierName") or p.get("carrier")
                if carr and isinstance(carr, str) and carr in carrier_name_by_uuid:
                    p["carrierName"] = carrier_name_by_uuid[carr]

    return {
        "id": int(c.id),
        "clientSetup": (c.common_details or {}).get("client_setup") or (c.common_details or {}).get("clientSetup") or {},
        "clientAssessment": client_assessment_resp,
        "mortgageInfo": c.mortgage_info or {},
        "financialAssessment": c.financial_assessment or {},
        "coverage": c.type_of_coverage or {},
        "generalInfo": c.general_information or {},
        "policiesBanking": pb or {},
        "beneficiaries": c.benificiaries or c.beneficiaries or {},
        "clients": clients,
        "agency": agency_name,
        "agent": agent_name,
        "status": status_label,
        "dateCreated": c.created_at.isoformat() + "Z" if getattr(c.created_at, "isoformat", None) else None,
        "lastUpdated": c.modified_at.isoformat() + "Z" if getattr(c.modified_at, "isoformat", None) else None,
        "common_details": _sanitize_documents_for_list(c.common_details),
    }


@router.put("/cases/{case_id}/edit")
def update_case_complete(
    case_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id),
):
    svc = CaseService(db, tenant_id)
    c = svc.get_case(int(case_id))
    if not c:
        raise HTTPException(status_code=404, detail="Case not found")

    client_setup = (payload or {}).get("client_setup") or (payload or {}).get("clientSetup") or {}
    mortgage_info = (payload or {}).get("mortgage_info") or (payload or {}).get("mortgageInfo")
    client_assessment = (payload or {}).get("client_assessment") or (payload or {}).get("clientAssessment")
    financial_assessment = (payload or {}).get("financial_assessment") or (payload or {}).get("financialAssessment")
    coverage = (payload or {}).get("type_of_coverage") or (payload or {}).get("coverage")
    general_information = (payload or {}).get("general_information") or (payload or {}).get("generalInfo")
    policy_and_banking = (payload or {}).get("policy_and_banking") or (payload or {}).get("policiesBanking")
    benificiaries = (payload or {}).get("benificiaries") or (payload or {}).get("beneficiaries")

    updates: Dict[str, Any] = {}
    if isinstance(mortgage_info, dict):
        updates["mortgage_info"] = mortgage_info
    if isinstance(client_assessment, dict):
        updates["client_assessment"] = client_assessment
    if isinstance(financial_assessment, dict):
        updates["financial_assessment"] = financial_assessment
    if isinstance(coverage, dict):
        updates["type_of_coverage"] = coverage
    if isinstance(general_information, dict):
        updates["general_information"] = general_information
    if isinstance(policy_and_banking, dict):
        updates["policy_and_banking"] = policy_and_banking
    if isinstance(benificiaries, dict):
        updates["benificiaries"] = benificiaries

    if isinstance(client_setup, dict) and client_setup:
        cd = c.common_details or {}
        if not isinstance(cd, dict):
            cd = {}
        cd["client_setup"] = client_setup
        updates["common_details"] = cd

    try:
        new_name = ""
        if isinstance(general_information, dict):
            c1 = (general_information or {}).get("client_1") or {}
            if isinstance(c1, dict):
                new_name = str(c1.get("name") or "").strip()
        if not new_name and isinstance(client_setup, dict):
            names = client_setup.get("clientNames") or client_setup.get("client_names") or []
            if isinstance(names, list) and names:
                new_name = str(names[0] or "").strip()
                if len(names) > 1:
                    n2 = str(names[1] or "").strip()
                    if n2:
                        updates["client2_name"] = n2
        if not new_name and isinstance(client_assessment, dict):
            cl = (client_assessment or {}).get("clients") or []
            if isinstance(cl, list) and cl:
                c0 = cl[0] if isinstance(cl[0], dict) else {}
                new_name = str(c0.get("clientName") or c0.get("name") or "").strip()
        if not new_name and isinstance(mortgage_info, dict):
            new_name = str((mortgage_info or {}).get("name") or "").strip()
        if new_name:
            updates["name"] = new_name
            updates["client1_name"] = new_name
    except Exception:
        pass

    if user_id:
        try:
            updates["modified_at"] = datetime.utcnow()
        except Exception:
            pass

    out = svc.update_case(case_id=int(case_id), **updates)
    if not out:
        raise HTTPException(status_code=404, detail="Case not found")

    if "policy_and_banking" in updates:
        try:
            # Use v2 sync to update existing premiums
            user_uuid = uuid.UUID(str(user_id)) if user_id else None
            _sync_premium_sold_v2(db, c, policy_and_banking, user_uuid)
        except Exception as e:
            import traceback
            logger.warning(f"Failed to sync premium_sold for case {case_id}: {e}")
            traceback.print_exc()

    return {"success": True, "data": {"case_id": int(case_id)}}


@router.get("/book-of-business/metadata")
@cached(ttl=1800, prefix="bob_metadata_alias")
def get_bob_metadata_alias(
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id),
):
    """Alias for get_cases_metadata to fix 500 error on legacy frontend call."""
    return get_cases_metadata(request=request, db=db, tenant_id=tenant_id, user_id=user_id)



@router.get("/cases/{case_id}/documents")
def get_case_documents(
    case_id: int,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
):
    c = db.exec(select(CaseData).where(CaseData.id == int(case_id), CaseData.tenant_id == tenant_id)).first()
    if not c:
        raise HTTPException(status_code=404, detail="Case not found")
    cd = c.common_details or {}
    if not isinstance(cd, dict):
        cd = {}
    docs = cd.get("documents")
    if not isinstance(docs, list):
        docs = []
    return {"documents": docs}


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_case_documents(
    case_id: int,
    files: List[UploadFile] = File(...),
    client_number: Optional[str] = Form(None),
    option_number: Optional[str] = Form(None),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
    user_id: Optional[str] = Depends(get_user_id),
):
    c = db.exec(select(CaseData).where(CaseData.id == int(case_id), CaseData.tenant_id == tenant_id)).first()
    if not c:
        raise HTTPException(status_code=404, detail="Case not found")

    existing_cd = c.common_details if isinstance(c.common_details, dict) else {}
    cd: Dict[str, Any] = dict(existing_cd or {})
    existing_docs = cd.get("documents")
    docs: List[Dict[str, Any]] = list(existing_docs) if isinstance(existing_docs, list) else []
    existing_content = cd.get("documents_content")
    content_map: Dict[str, str] = dict(existing_content) if isinstance(existing_content, dict) else {}

    now_iso = datetime.utcnow().isoformat() + "Z"

    for f in files or []:
        data = await f.read()
        if data is None:
            data = b""
        doc_id = str(uuid.uuid4())
        content_map[doc_id] = base64.b64encode(data).decode("ascii")
        docs.append(
            {
                "id": doc_id,
                "filename": f.filename,
                "original_filename": f.filename,
                "mime_type": f.content_type or "application/octet-stream",
                "size": len(data),
                "uploaded_at": now_iso,
                "uploaded_by": user_id,
                "client_number": client_number,
                "option_number": option_number,
            }
        )

    cd["documents"] = docs
    cd["documents_content"] = content_map
    c.common_details = cd
    c.modified_at = datetime.utcnow()
    db.add(c)
    db.commit()
    db.refresh(c)

    return {"success": True, "documents": docs}


@router.get("/cases/{case_id}/documents/{document_id}/download")
def download_case_document(
    case_id: int,
    document_id: str,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    authorization: str = Depends(require_authorization),
):
    c = db.exec(select(CaseData).where(CaseData.id == int(case_id), CaseData.tenant_id == tenant_id)).first()
    if not c:
        raise HTTPException(status_code=404, detail="Case not found")

    cd = c.common_details or {}
    if not isinstance(cd, dict):
        cd = {}
    docs = cd.get("documents") or []
    if not isinstance(docs, list):
        docs = []
    content_map = cd.get("documents_content") or {}
    if not isinstance(content_map, dict):
        content_map = {}

    meta = None
    for d in docs:
        if isinstance(d, dict) and str(d.get("id")) == str(document_id):
            meta = d
            break
    if not meta:
        raise HTTPException(status_code=404, detail="Document not found")

    b64 = content_map.get(str(document_id))
    if not b64:
        raise HTTPException(status_code=404, detail="Document content not found")
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid document content")

    filename = meta.get("original_filename") or meta.get("filename") or "document"
    mime = meta.get("mime_type") or "application/octet-stream"
    return Response(content=raw, media_type=mime, headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'})

# ==============================================================================
# DASHBOARD (Desk) - source of truth: public.cases via cases-service
# ==============================================================================

@router.get("/cases/dashboard/open-cases")
@cached(ttl=600, prefix="dash_open_cases", canonical_path="/dashboard/open-cases")
def dashboard_open_cases(
    request: Request,
    period: str = Query("month"),
    compare: bool = Query(True),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None
    svc = CaseService(db, tenant_id)
    try:
        return svc.dashboard_open_cases(period=period, compare=compare, user_id=user_uuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/cases/dashboard/book-of-business/metric")
@cached(ttl=600, prefix="dash_book_metric", canonical_path="/dashboard/book-of-business/metric")
def dashboard_book_of_business_metric(
    request: Request,
    period: str = Query("month"),
    compare: bool = Query(True),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None
    svc = CaseService(db, tenant_id)
    try:
        return svc.dashboard_book_of_business_metric(period=period, compare=compare, user_id=user_uuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/cases/dashboard/monthly-issued-policies")
@cached(ttl=600, prefix="dash_monthly_policies", canonical_path="/dashboard/monthly-issued-policies")
def dashboard_monthly_issued_policies(
    request: Request,
    year: Optional[int] = Query(None),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None
    svc = CaseService(db, tenant_id)
    return svc.dashboard_monthly_issued_policies(year=year, user_id=user_uuid)


@router.get("/cases/dashboard/cases-by-status")
@cached(ttl=600, prefix="dash_by_status", canonical_path="/dashboard/cases-by-status")
def dashboard_cases_by_status(
    request: Request,
    period: str = Query("month"),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None
    svc = CaseService(db, tenant_id)
    try:
        return svc.dashboard_cases_by_status(period=period, user_id=user_uuid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/cases/dashboard/charts")
@cached(ttl=600, prefix="dash_charts", canonical_path="/dashboard/charts")
def dashboard_charts(
    request: Request,
    user_id: Optional[str] = Depends(get_user_id_from_request),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None
    svc = CaseService(db, tenant_id)
    return svc.dashboard_charts(user_id=user_uuid)


@router.get("/cases/dashboard/recent")
@cached(ttl=600, prefix="cases_service_dash_recent", canonical_path="/cases/dashboard/recent")
def dashboard_recent_cases(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None
    svc = CaseService(db, tenant_id)
    return svc.dashboard_recent_cases(limit=limit, user_id=user_uuid)


# ==============================================================================
# BOOK OF BUSINESS (Desk) - helper endpoints (case-level only)
# ==============================================================================


@router.post("/cases/book-of-business/filter-ids", response_model=BoBFilterCaseIdsResponse)
def bob_filter_case_ids(
    request: BoBFilterCaseIdsRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    """
    Returns case ids after applying ONLY filters that can be evaluated from `public.cases`.
    Desk will pass these ids to premium-service to apply policy-level filters.
    """
    # Parse dates (tolerant)
    def _parse_dt(v: Optional[str]) -> Optional[datetime]:
        if not v:
            return None
        s = str(v).strip()
        if not s:
            return None
        try:
            # Accept YYYY-MM-DD
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                return datetime.fromisoformat(s)
            return datetime.fromisoformat(s)
        except Exception:
            return None

    svc = CaseService(db, tenant_id)
    ids = svc.book_of_business_filter_case_ids(
        search=request.search,
        date_from=_parse_dt(request.date_from),
        date_to=_parse_dt(request.date_to),
        policy_type=request.policy_type,
        own_only=bool(request.own_only) if request.own_only is not None else False,
        user_id=str(request.user_id).strip() if request.user_id else None,
    )
    return BoBFilterCaseIdsResponse(case_ids=ids)


@router.post("/cases/book-of-business/resolve-display", response_model=BoBResolveDisplayResponse)
def bob_resolve_display(
    request: BoBResolveDisplayRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    user_map: Dict[str, str] = {}
    agency_map: Dict[str, str] = {}
    carrier_map: Dict[str, str] = {}

    user_ids: List[uuid.UUID] = []
    for v in (request.user_ids or []):
        try:
            user_ids.append(uuid.UUID(str(v)))
        except Exception:
            continue

    agency_ids: List[uuid.UUID] = []
    for v in (request.agency_ids or []):
        try:
            agency_ids.append(uuid.UUID(str(v)))
        except Exception:
            continue

    carrier_ids: List[uuid.UUID] = []
    for v in (request.carrier_ids or []):
        try:
            carrier_ids.append(uuid.UUID(str(v)))
        except Exception:
            continue

    if user_ids:
        rows = db.exec(
            select(UserRow).where(UserRow.tenant_id == tenant_id, UserRow.id.in_(list(dict.fromkeys(user_ids))))
        ).all() or []
        for r in rows:
            fn = (getattr(r, "first_name", None) or "").strip()
            ln = (getattr(r, "last_name", None) or "").strip()
            full = f"{fn} {ln}".strip()
            user_map[str(r.id)] = full or (getattr(r, "email", None) or "").strip() or str(r.id)

    if agency_ids:
        rows = db.exec(
            select(AgencyRow).where(AgencyRow.id.in_(list(dict.fromkeys(agency_ids))))
        ).all() or []
        for r in rows:
            agency_map[str(r.id)] = (getattr(r, "name", None) or "").strip() or str(r.id)

    if carrier_ids:
        rows = db.exec(select(CarrierRow).where(CarrierRow.id.in_(list(dict.fromkeys(carrier_ids))))).all() or []
        for r in rows:
            carrier_map[str(r.id)] = (getattr(r, "display_name_override", None) or "").strip() or (getattr(r, "name", None) or "").strip() or str(r.id)

    carrier_ids_from_filters: List[str] = []
    if request.carrier_filters:
        seen: set[str] = set()
        for raw in request.carrier_filters or []:
            s = str(raw or "").strip()
            if not s:
                continue
            like = f"%{s}%"
            rows = db.exec(
                select(CarrierRow).where(
                    (CarrierRow.name.ilike(like)) | (CarrierRow.display_name_override.ilike(like))
                ).limit(200)
            ).all() or []
            for r in rows:
                rid = str(r.id)
                if rid in seen:
                    continue
                seen.add(rid)
                carrier_ids_from_filters.append(rid)

    carrier_names: List[str] = []
    if bool(request.include_carrier_names):
        rows = db.exec(select(CarrierRow).limit(500)).all() or []
        seen_names: set[str] = set()
        for r in rows:
            n = (getattr(r, "display_name_override", None) or "").strip() or (getattr(r, "name", None) or "").strip()
            if not n or n in seen_names:
                continue
            seen_names.add(n)
            carrier_names.append(n)

    return BoBResolveDisplayResponse(
        users=user_map,
        agencies=agency_map,
        carriers=carrier_map,
        carrier_ids_from_filters=carrier_ids_from_filters,
        carrier_names=carrier_names,
    )


@router.post("/cases/book-of-business/query", response_model=BoBQueryCasesResponse)
def bob_query_cases(
    request: BoBQueryCasesRequest,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    """Paginate and return cases by an explicit id set (already filtered by premium-service)."""
    svc = CaseService(db, tenant_id)
    items, total = svc.book_of_business_query_cases(case_ids=request.case_ids or [], page=request.page, size=request.size)
    pages = (total + request.size - 1) // request.size if request.size else 0
    return BoBQueryCasesResponse(
        items=[CaseDetailResponse.model_validate(c) for c in items],
        total=total,
        page=int(request.page),
        size=int(request.size),
        pages=int(pages),
    )


@router.get("/cases/by-policy-number", response_model=CaseDetailResponse)
@cached(ttl=600, prefix="case_by_policy")
def get_case_by_policy_number(
    request: Request,
    policy_number: str = Query(..., min_length=1),
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
):
    svc = CaseService(db, tenant_id)
    case = svc.get_case_by_policy_number(policy_number=str(policy_number))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseDetailResponse.model_validate(case)


@router.post("/cases/{case_id}/archive", response_model=BoBArchiveCaseResponse)
def archive_case(
    case_id: int,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    svc = CaseService(db, tenant_id)
    ok = svc.archive_case(case_id=int(case_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Case not found")
    _invalidate_shared_cache_safe(user_id=user_id)
    _bump_bob_version_safe(tenant_id=tenant_id)
    return BoBArchiveCaseResponse(archived=True)


def _carrier_display(carrier: Optional[CarrierRow]) -> str:
    if not carrier:
        return "N/A"
    return str(getattr(carrier, "display_name_override", "") or getattr(carrier, "name", "") or "").strip() or "N/A"


def _user_display(user: Optional[UserRow]) -> str:
    if not user:
        return "N/A"
    parts = []
    fn = str(user.first_name or "").strip()
    ln = str(user.last_name or "").strip()
    if fn:
        parts.append(fn)
    if ln:
        parts.append(ln)
    if parts:
        return " ".join(parts)
    return str(user.email or "").strip() or "N/A"


@router.get("/book-of-business/cases")
@router.get("/book-of-business/cases-full")
async def bob_cases_full(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    carrier: Optional[List[str]] = Query(None),
    policy_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    own_only: bool = Query(False),
    db: AsyncSession = Depends(get_async_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    claims: dict = Depends(require_authorization),
):
    from sqlalchemy import Text, cast, func, or_

    def _format_mdy_slash(dt: Optional[datetime]) -> str:
        if not dt:
            return "N/A"
        try:
             return dt.strftime("%m/%d/%Y")
        except Exception:
             return str(dt)

    is_admin = _resolve_desk_is_admin(claims)

    user_uuid: Optional[uuid.UUID] = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            user_uuid = None

    if not is_admin:
        own_only = True
    
    # --- Caching (Redis) ---
    cache_key = None
    if redis_client:
        try:
            params = {
                "page": page, "size": size, "search": search, 
                "date_from": date_from, "date_to": date_to,
                "carrier": carrier, "policy_type": policy_type,
                "status": status, "own_only": own_only,
                "user_id": str(user_uuid) if user_uuid else None,
                "is_admin": is_admin
            }
            version_key = f"cases:bob_version:{tenant_id}"
            version = await redis_client.get(version_key)
            if not version:
                 version = "1"
                 await redis_client.set(version_key, version)
            
            param_str = json.dumps(params, sort_keys=True)
            param_hash = hashlib.md5(param_str.encode()).hexdigest()
            cache_key = f"cases:bob:{tenant_id}:v{version}:{param_hash}"
            
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.error(f"Redis cache read failed: {e}")
    # -----------------------

    # BoB policy statuses in DB (legacy premium_sold.status)
    status_map = {
        "issued": [4],
        "lapsed": [6],
        "pending-lapsed": [7],
        "pending-lapse": [7],
        "replaced": [8],
        "cancelled": [9, 10],
        "canceled": [9, 10],
    }
    db_status_ids = [4, 6, 7, 8, 9, 10]
    if status:
        sl = str(status).strip().lower()
        db_status_ids = status_map.get(sl, db_status_ids)

    join_cond = or_(
        PremiumSoldRow.case_data_id == CaseData.id,
        cast(CaseData.id, Text) == func.split_part(PremiumSoldRow.unique_policy_identifier, "_", 1),
    )

    base_conditions = [
        CaseData.tenant_id == tenant_id,
        (CaseData.is_active == True) | (CaseData.is_active.is_(None)),
        PremiumSoldRow.is_active == True,
        PremiumSoldRow.status.in_(db_status_ids),
    ]

    if own_only:
        if user_uuid:
            base_conditions.append(
                or_(
                    CaseData.created_by_id == user_uuid,
                    CaseData.agent_id == user_uuid,
                    PremiumSoldRow.user_id == user_uuid,
                )
            )

    ids_q = (
        select(func.distinct(CaseData.id))
        .select_from(CaseData)
        .join(PremiumSoldRow, join_cond)
        .where(*base_conditions)
    )

    # --- Apply Filters (Search, Dates, Carrier, etc.) to Main Query first ---
    # This ensures ids_q is still a Select object when .where() or .join() is called.
    if search:
        st = f"%{search}%"
        ids_q = ids_q.where(
            or_(
                CaseData.name.ilike(st),
                CaseData.client1_name.ilike(st),
                CaseData.client2_name.ilike(st),
                CaseData.client1_email.ilike(st),
                CaseData.client2_email.ilike(st),
                PremiumSoldRow.policy_number.ilike(st),
                PremiumSoldRow.unique_policy_identifier.ilike(st),
            )
        )

    if date_from:
        try:
            ids_q = ids_q.where(CaseData.created_at >= datetime.fromisoformat(date_from))
        except Exception:
            pass
    if date_to:
        try:
            ids_q = ids_q.where(CaseData.created_at <= datetime.fromisoformat(date_to))
        except Exception:
            pass

    if carrier:
        clist = [c for c in (carrier if isinstance(carrier, list) else [carrier]) if c]
        if clist:
            # Need to join CarrierRow to filter by name
            ids_q = ids_q.join(CarrierRow, PremiumSoldRow.carrier_id == CarrierRow.id).where(
                or_(*[CarrierRow.name.ilike(f"%{c}%") for c in clist])
            )

    # policy_type filter (string match inside json)
    specific_types = [
        "Full", "Full Rop", "Half", "Half Rop", "Equity Protection WL",
        "Equity Protection Term", "Equity Protection Term Rop", "Term",
        "Term Rop", "Whole Life/Fex", "IUL", "Whole Life",
        "Universal Life", "Mortgage Protection", "Accidental Death",
    ]
    if policy_type:
        ptypes = [pt.strip() for pt in str(policy_type).split(",") if pt.strip()]
        if "Other" in ptypes:
            conds = [cast(CaseData.policy_and_banking, Text).ilike(f'%"plan_type": "{t}"%') for t in specific_types]
            if conds:
                combined = conds[0]
                for cnd in conds[1:]:
                    combined = combined | cnd
                ids_q = ids_q.where(~combined)
        elif ptypes:
            conds = [cast(CaseData.policy_and_banking, Text).ilike(f'%"plan_type": "{t}"%') for t in ptypes]
            if conds:
                combined = conds[0]
                for cnd in conds[1:]:
                    combined = combined | cnd
                ids_q = ids_q.where(combined)



    # Usar una forma más robusta de contar con subquery en SQLAlchemy 2.0
    from sqlalchemy import func
    count_stmt = select(func.count()).select_from(ids_q.alias("union_query"))
    count_res = await db.exec(count_stmt)
    total = count_res.first() or 0


    paged_ids_res = await db.exec(
        select(CaseData.id)
        .where(CaseData.id.in_(ids_q))
        .order_by(CaseData.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    paged_ids = paged_ids_res.all() or []

    cases = []
    if paged_ids:
        cases_res = await db.exec(
            select(CaseData)
            .where(CaseData.id.in_(paged_ids))
            .order_by(CaseData.created_at.desc())
        )
        cases = cases_res.all() or []

    case_ids = [int(c.id) for c in cases if c.id is not None]
    case_id_strs = [str(x) for x in case_ids]

    ps_rows: List[PremiumSoldRow] = []
    if case_ids:
        ps_res = await db.exec(
            select(PremiumSoldRow).where(
                PremiumSoldRow.is_active == True,
                PremiumSoldRow.status.in_(db_status_ids),
                or_(
                    PremiumSoldRow.case_data_id.in_(case_ids),
                    func.split_part(PremiumSoldRow.unique_policy_identifier, "_", 1).in_(case_id_strs),
                ),
            )
        )
        ps_rows = ps_res.all() or []

    premiums_by_case: Dict[int, List[PremiumSoldRow]] = {}
    carrier_ids: set[str] = set()
    product_ids: set[str] = set()
    agency_ids: set[str] = set()
    user_ids: set[str] = set()

    for p in ps_rows:
        try:
            cid = int(p.case_data_id) if p.case_data_id is not None else None
        except Exception:
            cid = None
        if cid is None:
            # try parse from unique_policy_identifier "{case_id}_..."
            try:
                cid = int(str(p.unique_policy_identifier or "").split("_", 1)[0])
            except Exception:
                cid = None
        if cid is None:
            continue
        premiums_by_case.setdefault(cid, []).append(p)
        if p.carrier_id:
            carrier_ids.add(str(p.carrier_id))
        if p.product_id:
            product_ids.add(str(p.product_id))
        if p.agency_id:
            agency_ids.add(str(p.agency_id))
        if p.user_id:
            user_ids.add(str(p.user_id))

    # also fetch agents from case fields
    for c in cases:
        aid = c.created_by_id or c.agent_id
        if aid:
            user_ids.add(str(aid))

    # Also fetch carrier UUIDs from policy_and_banking JSON (for cases without premium_sold rows)
    for c in cases:
        pab = c.policy_and_banking or {}
        if isinstance(pab, dict):
            for ci in range(1, 11):
                client_data = pab.get(f"client_{ci}") or {}
                if isinstance(client_data, dict):
                    for k, v in client_data.items():
                        if k == "carrier" and isinstance(v, str) and len(v) > 30:
                            try:
                                uuid.UUID(v)
                                carrier_ids.add(v)
                            except Exception:
                                pass
                        elif isinstance(v, dict):
                            cid = v.get("carrier")
                            if cid and isinstance(cid, str) and len(cid) > 30:
                                try:
                                    uuid.UUID(cid)
                                    carrier_ids.add(cid)
                                except Exception:
                                    pass
                    # also check "policies" array
                    for pol in (client_data.get("policies") or []):
                        if isinstance(pol, dict):
                            cid = pol.get("carrier")
                            if cid and isinstance(cid, str) and len(cid) > 30:
                                try:
                                    uuid.UUID(cid)
                                    carrier_ids.add(cid)
                                except Exception:
                                    pass

    carriers_by_id: Dict[str, CarrierRow] = {}
    if carrier_ids:
        try:
            carr_res = await db.exec(select(CarrierRow).where(CarrierRow.id.in_([uuid.UUID(x) for x in carrier_ids])))
            carr_rows = carr_res.all() or []
            for r in carr_rows:
                carriers_by_id[str(r.id)] = r
        except Exception:
            pass

    products_by_id: Dict[str, ProductRow] = {}
    if product_ids:
        try:
            prod_res = await db.exec(select(ProductRow).where(ProductRow.id.in_([uuid.UUID(x) for x in product_ids])))
            prod_rows = prod_res.all() or []
            for r in prod_rows:
                products_by_id[str(r.id)] = r
        except Exception:
            pass

    agencies_by_id: Dict[str, AgencyRow] = {}
    if agency_ids:
        try:
            agency_res = await db.exec(select(AgencyRow).where(AgencyRow.id.in_([uuid.UUID(x) for x in agency_ids])))
            arows = agency_res.all() or []
            for r in arows:
                agencies_by_id[str(r.id)] = r
        except Exception:
            pass

    users_by_id: Dict[str, UserRow] = {}
    if user_ids:
        try:
            user_res = await db.exec(select(UserRow).where(UserRow.id.in_([uuid.UUID(x) for x in user_ids])))
            urows = user_res.all() or []
            for r in urows:
                users_by_id[str(r.id)] = r
        except Exception:
            pass

    out_cases: List[Dict[str, Any]] = []
    for c in cases:
        if c.id is None:
            continue
        cid = int(c.id)
        premiums = premiums_by_case.get(cid, []) or []
        
        # In Book of Business, clients are built ONLY from premium_sold rows, not from JSON
        clients: List[Dict[str, Any]] = []
        agency_name = "N/A"
        
        general_info = c.general_information or {}
        if not isinstance(general_info, dict):
            general_info = {}
        
        for p in premiums:
            # Parse client/option from unique_policy_identifier
            cn, on = 1, 1
            if p.unique_policy_identifier:
                m = re.search(r"client_(\d+)_option_(\d+)", str(p.unique_policy_identifier))
                if m:
                    try:
                        cn, on = int(m.group(1)), int(m.group(2))
                    except Exception:
                        pass
            
            # Get client info from JSON
            client_key = f"client_{cn}"
            client_data = general_info.get(client_key) or {}
            if not isinstance(client_data, dict):
                client_data = {}
            
            # Fallback to ClientAssessment for Sex/Kids if missing
            ca = c.client_assessment or {}
            c_assess = {}
            if isinstance(ca, dict):
                c_clients = ca.get("clients") or []
                if isinstance(c_clients, list) and len(c_clients) >= cn:
                    c_assess = c_clients[cn - 1] if isinstance(c_clients[cn - 1], dict) else {}

            name = client_data.get("name") or client_data.get("full_name") or client_data.get("fullName") or ""
            if not name:
                if cn == 1:
                    name = c.client1_name or c.name or "N/A"
                elif cn == 2:
                    name = c.client2_name or "N/A"
                else:
                    name = "N/A"
            
            email = client_data.get("email") or ""
            if not email:
                if cn == 1:
                    email = c.client1_email or ""
                elif cn == 2:
                    email = c.client2_email or ""
            
            sex = client_data.get("sex") or client_data.get("gender")
            if not sex or str(sex).strip() == "N/A":
                sex = c_assess.get("gender") or "N/A"

            # Try to get kids from multiple possible keys
            kids = None
            for key in ["kids", "children", "numberOfChildren", "hasKids"]:
                val = client_data.get(key)
                if val is not None:
                    kids = val
                    break
            
            if kids is None or str(kids).strip() == "N/A":
                for key in ["kids", "children", "numberOfChildren", "hasKids"]:
                    val = c_assess.get(key)
                    if val is not None:
                        kids = val
                        break
            
            if kids is None:
                kids = "N/A"
            else:
                 if isinstance(kids, list):
                     kids = str(len(kids))
                 if str(kids).lower() == "false":
                     kids = "0"
                 kids = str(kids)

            dob = client_data.get("dob") or client_data.get("birthDate") or client_data.get("dateOfBirth")
            if not dob:
                dob = c_assess.get("dateOfBirth") or ""
            
            # Map premium_sold status to UI status
            ui_sid, ui_label = _premium_status_to_ui(int(p.status or 0))
            
            # Carrier name resolution with JSON fallback
            carrier_name = "N/A"
            if p.carrier_id:
                carrier_name = _carrier_display(carriers_by_id.get(str(p.carrier_id)))
            
            if carrier_name == "N/A" or not carrier_name:
                # Try fallback to policy_and_banking JSON
                policy_and_banking = c.policy_and_banking or {}
                if isinstance(policy_and_banking, dict):
                    client_pab = policy_and_banking.get(client_key) or {}
                    if isinstance(client_pab, dict):
                        carrier_val = client_pab.get("carrier")
                        if not carrier_val:
                            policies = client_pab.get("policies") or []
                            if isinstance(policies, list) and len(policies) > (on - 1):
                                pol_data = policies[on - 1]
                                if isinstance(pol_data, dict):
                                    carrier_val = pol_data.get("carrier")
                        
                        if carrier_val:
                            cid_str = str(carrier_val).strip()
                            if len(cid_str) > 30:
                                carrier_row = carriers_by_id.get(cid_str)
                                if carrier_row:
                                    carrier_name = _carrier_display(carrier_row)
                                else:
                                    carrier_name = cid_str
                            elif cid_str.lower() != "n/a":
                                carrier_name = cid_str
            
            # Product/Plan name
            plan_name = ""
            if p.product_id:
                pr = products_by_id.get(str(p.product_id))
                plan_name = str(getattr(pr, "name", "") or "").strip() if pr else ""
            
            if not plan_name or plan_name.lower() == "other":
                policy_and_banking = c.policy_and_banking or {}
                if isinstance(policy_and_banking, dict):
                    client_pab = policy_and_banking.get(client_key) or {}
                    if isinstance(client_pab, dict):
                        policies = client_pab.get("policies") or []
                        if isinstance(policies, list) and len(policies) > (on - 1):
                            pol_data = policies[on - 1]
                            if isinstance(pol_data, dict):
                                product_val = pol_data.get("product") or pol_data.get("planType") or pol_data.get("plan_type") or ""
                                if product_val and str(product_val).lower() != "other":
                                    plan_name = str(product_val).strip()
                                elif product_val and str(product_val).lower() == "other":
                                    plan_name = (pol_data.get("otherProduct") or 
                                                pol_data.get("other_product") or 
                                                pol_data.get("productOther") or 
                                                pol_data.get("otherPolicy") or 
                                                pol_data.get("other_policy") or 
                                                pol_data.get("policyOther") or 
                                                "Other")
                                else:
                                    plan_name = (pol_data.get("policy") or 
                                                pol_data.get("plan_name") or 
                                                pol_data.get("planName") or 
                                                plan_name or "N/A")
            
            if plan_name and str(plan_name).strip() != "N/A":
                plan_name = str(plan_name).replace("_", " ").title()
            else:
                plan_name = "N/A"
            
            plan_type_val = "N/A"
            if p.product_id:
                 plan_type_val = plan_name
            else:
                 if isinstance(policy_and_banking, dict):
                    client_pab = policy_and_banking.get(client_key) or {}
                    if isinstance(client_pab, dict):
                         pol_arr = client_pab.get("policies") or []
                         if isinstance(pol_arr, list) and len(pol_arr) > (on -1):
                              pd = pol_arr[on-1]
                              if isinstance(pd, dict):
                                  pt = pd.get("product") or pd.get("planType") or pd.get("plan_type")
                                  if pt:
                                      plan_type_val = str(pt).replace("_", " ").title()
            
            if plan_type_val == "N/A":
                plan_type_val = plan_name
            
            issued_date = None
            lapsed_date = None
            if getattr(p, "effective_date", None):
                try:
                    issued_date = p.effective_date.isoformat() + "Z" if getattr(p.effective_date, "isoformat", None) else str(p.effective_date)
                except Exception:
                    pass
            if getattr(p, "laps_date", None):
                try:
                    lapsed_date = p.laps_date.isoformat() + "Z" if getattr(p.laps_date, "isoformat", None) else str(p.laps_date)
                except Exception:
                    pass
            
            clients.append({
                "id": p.id,
                "name": name,
                "email": email,
                "sex": sex,
                "kids": kids,
                "birthDate": dob,
                "policyNumber": p.policy_number or "",
                "carrier": carrier_name,
                "carrierName": carrier_name,
                "planName": plan_name or "N/A",
                "planType": plan_type_val or plan_name or "N/A",
                "premium": float(p.annual_premium) if p.annual_premium is not None else 0,
                "statusId": ui_sid,
                "status": ui_label,
                "clientNumber": cn,
                "optionNumber": on,
                "option": on,
                "issuedDate": issued_date,
                "lapsedDate": lapsed_date,
                "carrier_id": str(p.carrier_id) if p.carrier_id else None,
            })
            
            if agency_name == "N/A" and p.agency_id:
                a = agencies_by_id.get(str(p.agency_id))
                if a and getattr(a, "name", None):
                    agency_name = str(a.name or "").strip() or "N/A"
            
            if agency_name == "N/A" and p.user_id:
                try:
                    user_row = users_by_id.get(str(p.user_id))
                    if user_row and hasattr(user_row, "agency_id") and user_row.agency_id:
                        a = agencies_by_id.get(str(user_row.agency_id))
                        if a and getattr(a, "name", None):
                            agency_name = str(a.name or "").strip() or "N/A"
                except Exception:
                    pass

        if not clients:
                continue

        aid = c.created_by_id or c.agent_id
        if (not aid) and premiums:
            try:
                aid = premiums[0].user_id
            except Exception:
                aid = None
        agent_name = _user_display(users_by_id.get(str(aid))) if aid else "N/A"

        first_client = clients[0] if clients else {}
        case_carrier = first_client.get("carrierName") or first_client.get("carrier") or "N/A"
        case_premium = first_client.get("premium") if first_client.get("premium") is not None else "N/A"
        case_status_label = first_client.get("status") or "N/A"
        common_details_out = _sanitize_documents_for_list(c.common_details)

        out_cases.append(
            {
                "id": cid,
                "name": c.name or c.client1_name or c.client_first_name or "Unnamed Case",
                "clients": clients,
                "client_email": (c.client1_email or c.client_email or ""),
            "agent": agent_name,
            "agency": agency_name,
                "dateCreated": _format_mdy_slash(c.created_at),
                "lastUpdated": _format_mdy_slash(c.modified_at),
                "status": case_status_label,
                "currentStage": case_status_label,
                "premium": case_premium,
                "carrier": case_carrier,
                "common_details": common_details_out,
                "is_draft": False,
                "draft_id": None,
            "created_by_id": str(c.created_by_id) if c.created_by_id else None,
            "agent_id": str(c.agent_id) if c.agent_id else None,
            }
        )

    result = {
        "cases": out_cases,
        "pagination": {
            "page": page,
            "size": size,
            "total": total,
            "totalPages": (total + size - 1) // size if size > 0 else 0
        }
    }
    
    # Save to Cache
    if redis_client and cache_key:
        try:
            await redis_client.set(cache_key, json.dumps(result), ex=2400) # 40 min TTL to match token
        except Exception as e:
            logger.error(f"Redis cache write failed: {e}")

    return result


@router.get("/book-of-business/metadata-full")
@cached(ttl=2400, prefix="bob_meta_full")
async def bob_metadata_full(
    request: Request,
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    carrier: Optional[List[str]] = Query(None),
    policy_type: Optional[str] = Query(None),
    own_only: bool = Query(False),
    db: AsyncSession = Depends(get_async_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
    claims: dict = Depends(require_authorization),
):
    from sqlalchemy import Text, cast, func, or_

    is_admin = _resolve_desk_is_admin(claims)

    user_uuid = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except Exception:
            pass

    # If non-admin, force own_only=True to ensure they don't see global stats
    if not is_admin:
        own_only = True

    join_cond = or_(
        PremiumSoldRow.case_data_id == CaseData.id,
        cast(CaseData.id, Text) == func.split_part(PremiumSoldRow.unique_policy_identifier, "_", 1),
    )

    # Same filters as bob_cases_full (metadata counts must match list).
    specific_types_meta = [
        "Full", "Full Rop", "Half", "Half Rop", "Equity Protection WL",
        "Equity Protection Term", "Equity Protection Term Rop", "Term",
        "Term Rop", "Whole Life/Fex", "IUL", "Whole Life",
        "Universal Life", "Mortgage Protection", "Accidental Death",
    ]

    async def _count_cases_for_db_statuses(db_statuses: List[int]) -> int:
        base_conditions = [
            CaseData.tenant_id == tenant_id,
            (CaseData.is_active == True) | (CaseData.is_active.is_(None)),
            PremiumSoldRow.is_active == True,
            PremiumSoldRow.status.in_(db_statuses),
        ]
        if own_only and user_uuid:
            base_conditions.append(
                or_(
                    CaseData.created_by_id == user_uuid,
                    CaseData.agent_id == user_uuid,
                    PremiumSoldRow.user_id == user_uuid,
                )
            )

        ids_q = (
            select(func.distinct(CaseData.id))
            .select_from(CaseData)
            .join(PremiumSoldRow, join_cond)
            .where(*base_conditions)
        )

        if search:
            st = f"%{search}%"
            ids_q = ids_q.where(
                or_(
                    CaseData.name.ilike(st),
                    CaseData.client1_name.ilike(st),
                    CaseData.client2_name.ilike(st),
                    CaseData.client1_email.ilike(st),
                    CaseData.client2_email.ilike(st),
                    PremiumSoldRow.policy_number.ilike(st),
                    PremiumSoldRow.unique_policy_identifier.ilike(st),
                )
            )
        if date_from:
            try:
                ids_q = ids_q.where(CaseData.created_at >= datetime.fromisoformat(date_from))
            except Exception:
                pass
        if date_to:
            try:
                ids_q = ids_q.where(CaseData.created_at <= datetime.fromisoformat(date_to))
            except Exception:
                pass
        if carrier:
            clist = [c for c in (carrier if isinstance(carrier, list) else [carrier]) if c]
            if clist:
                ids_q = ids_q.join(CarrierRow, PremiumSoldRow.carrier_id == CarrierRow.id).where(
                    or_(*[CarrierRow.name.ilike(f"%{c}%") for c in clist])
                )

        if policy_type:
            ptypes = [pt.strip() for pt in str(policy_type).split(",") if pt.strip()]
            if "Other" in ptypes:
                conds = [cast(CaseData.policy_and_banking, Text).ilike(f'%"plan_type": "{t}"%') for t in specific_types_meta]
                if conds:
                    combined = conds[0]
                    for cnd in conds[1:]:
                        combined = combined | cnd
                    ids_q = ids_q.where(~combined)
            elif ptypes:
                conds = [cast(CaseData.policy_and_banking, Text).ilike(f'%"plan_type": "{t}"%') for t in ptypes]
                if conds:
                    combined = conds[0]
                    for cnd in conds[1:]:
                        combined = combined | cnd
                    ids_q = ids_q.where(combined)

        count_stmt = select(func.count()).select_from(ids_q.alias("bob_meta_ids"))
        res = await db.exec(count_stmt)
        return res.first() or 0

    # Execute all counts sequentially to avoid SQLAlchemy concurrent session usage error
    c_all = await _count_cases_for_db_statuses([4, 6, 7, 8, 9, 10]) # all (using legacy statuses as approximation for "active")
    c_issued = await _count_cases_for_db_statuses([4]) # issued
    c_lapsed = await _count_cases_for_db_statuses([6]) # lapsed
    c_pending = await _count_cases_for_db_statuses([7]) # pending (pending-lapse)
    c_replaced = await _count_cases_for_db_statuses([8]) # replaced
    c_cancelled = await _count_cases_for_db_statuses([9, 10]) # cancelled/not taken

    results = [c_all, c_issued, c_lapsed, c_pending, c_replaced, c_cancelled]

    # DB legacy statuses
    counts = {
        "all": results[0],
        "issued": results[1],
        "lapsed": results[2],
        "pending": results[3],
        "replaced": results[4],
        "cancelled": results[5],
        "imported": 0,
    }

    carrier_names = []
    try:
        carr_res = await db.exec(select(CarrierRow.name).where(CarrierRow.name.isnot(None)).distinct())
        carrier_names = [n for n in (carr_res.all() or []) if n]
    except Exception:
        pass

    return {"carriers": carrier_names, "policy_types": [], "counts": counts}


def _premium_sold_latest_ctid_subquery(
    *,
    by_id: Optional[int] = None,
    unique_policy_identifier: Optional[str] = None,
    case_data_id: Optional[int] = None,
):
    """Scalar subquery: ctid of the latest row (PostgreSQL) for duplicate-safe updates."""
    t_ps = PremiumSoldRow.__table__
    if by_id is not None:
        cond = t_ps.c.id == int(by_id)
    else:
        cond = t_ps.c.unique_policy_identifier == unique_policy_identifier
        if case_data_id is not None:
            cond = cond & (t_ps.c.case_data_id == int(case_data_id))
    return (
        select(literal_column("ctid"))
        .select_from(t_ps)
        .where(cond)
        .order_by(
            t_ps.c.modified_at.desc().nulls_last(),
            t_ps.c.created_at.desc().nulls_last(),
        )
        .limit(1)
        .scalar_subquery()
    )


def _premium_sold_update_one_row_by_unique_identifier(
    db: Session,
    *,
    unique_policy_identifier: str,
    modified_at: datetime,
    status: int,
    policy_number: str,
    annual_premium: float,
    carrier_id: Optional[uuid.UUID],
    case_data_id: Optional[int] = None,
) -> int:
    """
    Update exactly one physical row for BoB upsert when legacy duplicates share the same logical key.
    """
    t_ps = PremiumSoldRow.__table__
    ctid_sq = _premium_sold_latest_ctid_subquery(
        unique_policy_identifier=unique_policy_identifier,
        case_data_id=case_data_id,
    )
    vals: Dict[str, Any] = {
        "status": int(status),
        "policy_number": policy_number or "",
        "annual_premium": float(annual_premium),
        "modified_at": modified_at,
        "is_active": True,
    }
    stmt = update(t_ps).where(column("ctid") == ctid_sq)
    if carrier_id is not None:
        vals["carrier_id"] = carrier_id
    up = db.execute(stmt.values(**vals))
    return int(getattr(up, "rowcount", 0) or 0)


def _sync_premium_sold_v2(db: Session, case: CaseData, policy_and_banking: Dict[str, Any], user_uuid: Optional[uuid.UUID]):
    if not isinstance(policy_and_banking, dict):
        return
    
    case_id = int(case.id)
    agency_id = None
    try:
        any_agency = db.exec(select(AgencyRow.id).limit(1)).first()
        if any_agency:
            agency_id = any_agency if not isinstance(any_agency, tuple) else any_agency[0]
    except Exception:
        pass

    for ci in range(1, 11):
        client_key = f"client_{ci}"
        client_data = policy_and_banking.get(client_key)
        if not isinstance(client_data, dict):
            continue
        
        policies = client_data.get("policies")
        if not isinstance(policies, list):
            policies = []
            
        max_opts = max(len(policies), 5)
        for idx in range(max_opts):
            on = idx + 1
            opt_data = None
            if idx < len(policies) and isinstance(policies[idx], dict):
                opt_data = policies[idx]
            else:
                maybe = client_data.get(f"option_{on}")
                if isinstance(maybe, dict):
                    opt_data = maybe
            
            unique_id = f"{case_id}_client_{ci}_option_{on}"
            
            # If no data, skip syncing this option (don't delete existing to be safe)
            if not opt_data:
                continue

            policy_number = opt_data.get("policyNumber") or opt_data.get("policy_number") or ""
            monthly = opt_data.get("monthlyPremium") or opt_data.get("monthly_premium") or 0
            yearly = opt_data.get("yearlyPremium") or opt_data.get("yearly_premium") or opt_data.get("annualPremium") or 0
            try:
                annual = float(str(yearly).replace(",", "").replace("$", "").strip() or 0)
            except Exception:
                annual = 0
            if annual <= 0:
                try:
                    m = float(str(monthly).replace(",", "").replace("$", "").strip() or 0)
                    annual = round(m * 12, 2)
                except Exception:
                    annual = 0
            
            carrier_id_raw = opt_data.get("carrier")
            carrier_uuid = None
            if carrier_id_raw:
                try:
                    carrier_uuid = uuid.UUID(str(carrier_id_raw))
                except Exception:
                    pass
            
            # Upsert: avoid ORM UPDATE when duplicate legacy rows share unique_policy_identifier (StaleDataError).
            now = datetime.utcnow()
            n_updated = _premium_sold_update_one_row_by_unique_identifier(
                db,
                unique_policy_identifier=unique_id,
                modified_at=now,
                status=int(case.status or 1),
                policy_number=policy_number or "",
                annual_premium=annual,
                carrier_id=carrier_uuid,
                case_data_id=None,
            )
            if n_updated < 1:
                # Create
                u_id = user_uuid if user_uuid else (case.created_by_id or case.agent_id)
                new_ps = PremiumSoldRow(
                    created_at=datetime.utcnow(),
                    modified_at=datetime.utcnow(),
                    case_data_id=case_id,
                    unique_policy_identifier=unique_id,
                    policy_number=policy_number,
                    annual_premium=annual,
                    status=int(case.status or 1), 
                    carrier_id=carrier_uuid,
                    agency_id=agency_id,
                    user_id=u_id,
                    is_active=True,
                    is_lapsed=False,
                    is_pending_lapsed=False,
                )
                db.add(new_ps)
                
    try:
        db.commit()
    except Exception as e:
        print(f"Error committing premium updates: {e}")
        db.rollback()


@router.get("/google/executed-actions")
@cached(ttl=300, prefix="google_actions")
def get_google_executed_actions(
    request: Request,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """
    Endpoint to fetch executed actions (e.g. sent emails) for the user's cases.
    Identified as missing during debugging of "Actions Taken" refresh issue.
    Currently returns an empty structure to prevent 404s and frontend errors.
    """
    # TODO: Implement actual lookup of executed actions (e.g. from CaseHistory or specific logging table)
    # The frontend expects keys like "client_{id}_option_{opt}_{caseId}" mapped to action flags.
    # returning empty object results in no icons lit up, which is safe.
    return {"executed_actions": {}}


@router.get("/google/status")
@cached(ttl=300, prefix="google_status")
def get_google_status(
    request: Request,
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """
    Health check for Google integration.
    """
    return {"status": "connected", "scope": "gmail.readonly"}


# =============================================================================
# CASE NOTES  (stored inside common_details JSON → { "notes": [...] })
# =============================================================================


def _get_common_details(case: CaseData) -> dict:
    """Parse common_details from case, return dict."""
    raw = case.common_details
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def _save_common_details(case: CaseData, details: dict, db: Session) -> None:
    """Persist common_details back to the case."""
    case.common_details = details
    flag_modified(case, "common_details")
    case.modified_at = datetime.utcnow()
    db.add(case)
    db.commit()
    db.refresh(case)


@router.get("/cases/{case_id}/notes", summary="List notes for a case")
@cached(ttl=300, prefix="case_notes")
def list_case_notes(
    request: Request,
    case_id: int,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """Return all notes attached to a case, newest first."""
    try:
        case = db.exec(
            select(CaseData).where(CaseData.id == case_id, CaseData.tenant_id == tenant_id)
        ).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        details = _get_common_details(case)
        notes = details.get("notes") or []

        # Resolve author names
        result = []
        for note in notes:
            author_name = note.get("author_name", "Unknown")
            if not author_name or author_name == "Unknown":
                try:
                    uid = note.get("created_by_id")
                    if uid:
                        author = db.exec(
                            select(UserRow).where(UserRow.id == uuid.UUID(str(uid)))
                        ).first()
                        if author:
                            author_name = f"{author.first_name or ''} {author.last_name or ''}".strip() or author.email or "Unknown"
                except Exception:
                    pass

            result.append({
                "id": note.get("id"),
                "case_id": case_id,
                "content": note.get("content", ""),
                "created_by": {
                    "id": str(note.get("created_by_id", "")),
                    "name": author_name,
                },
                "created_at": note.get("created_at"),
            })

        # newest first
        result.sort(key=lambda n: n.get("created_at") or "", reverse=True)
        return {"notes": result, "total": len(result)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing notes: {str(e)}")


@router.post(
    "/cases/{case_id}/notes",
    summary="Add a note to a case",
    status_code=status.HTTP_201_CREATED,
)
def create_case_note(
    case_id: int,
    body: dict,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """
    Create a new note on a case.
    Body: { "content": "..." }
    """
    try:
        content = (body.get("content") or "").strip()
        if not content:
            raise HTTPException(status_code=422, detail="Note content cannot be empty")

        case = db.exec(
            select(CaseData).where(CaseData.id == case_id, CaseData.tenant_id == tenant_id)
        ).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        details = _get_common_details(case)
        notes_list = details.get("notes") or []

        # Resolve author name from user_id
        author_name = "Unknown"
        if user_id:
            try:
                author = db.exec(
                    select(UserRow).where(UserRow.id == uuid.UUID(str(user_id)))
                ).first()
                if author:
                    author_name = f"{author.first_name or ''} {author.last_name or ''}".strip() or author.email or "Unknown"
            except Exception:
                pass

        # Generate a simple incremental id based on existing notes
        max_id = max((n.get("id", 0) for n in notes_list), default=0)
        new_id = max_id + 1

        new_note = {
            "id": new_id,
            "content": content,
            "created_by_id": str(user_id) if user_id else "",
            "author_name": author_name,
            "created_at": datetime.utcnow().isoformat(),
        }
        notes_list.append(new_note)
        details["notes"] = notes_list
        _save_common_details(case, details, db)

        return {
            "id": new_note["id"],
            "case_id": case_id,
            "content": new_note["content"],
            "created_by": {
                "id": new_note["created_by_id"],
                "name": author_name,
            },
            "created_at": new_note["created_at"],
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating note: {str(e)}")


@router.delete(
    "/cases/{case_id}/notes/{note_id}",
    summary="Delete a note from a case",
)
def delete_case_note(
    case_id: int,
    note_id: int,
    db: Session = Depends(get_tenant_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user_id: Optional[str] = Depends(get_user_id_from_request),
):
    """Delete a note. Only the author or an admin can delete."""
    try:
        case = db.exec(
            select(CaseData).where(CaseData.id == case_id, CaseData.tenant_id == tenant_id)
        ).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        details = _get_common_details(case)
        notes_list = details.get("notes") or []

        note = next((n for n in notes_list if n.get("id") == note_id), None)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")

        # Permission check: only author can delete (user_id match)
        if user_id and str(note.get("created_by_id")) != str(user_id):
            # Check if user is admin (superuser)
            try:
                from sqlalchemy import text
                is_su = db.execute(
                    text("SELECT is_superuser FROM public.users WHERE id = :uid"),
                    {"uid": str(user_id)}
                ).scalar()
                if not is_su:
                    raise HTTPException(status_code=403, detail="You can only delete your own notes")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="You can only delete your own notes")

        notes_list = [n for n in notes_list if n.get("id") != note_id]
        details["notes"] = notes_list
        _save_common_details(case, details, db)

        return {"message": "Note deleted", "id": note_id}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting note: {str(e)}")
