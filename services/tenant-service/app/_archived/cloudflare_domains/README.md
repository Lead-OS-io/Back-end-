# Archived: Cloudflare domains logic (legacy)

This directory holds the **pre-cleanup** implementation of tenant CRUD +
Cloudflare domain management. It is kept intact (no edits) so we can
restore endpoints when needed.

## Why archived

After the clean-slate spec (2026-08-05), `tenant-service` has only:

- `Tenant` model (no domain/cloudflare fields).
- One consumer that handles `onboarding.pending` and publishes
  `tenant.created`.
- `/health` endpoint.

## What's here

| File | Was | What it contains |
|---|---|---|
| `tenant.py` | `app/models/tenant.py` | Legacy `Tenant` (cloudflare fields) + `TenantDomain` (re-exported from `domain.py` here too if needed) |
| `cloudflare.py` | `app/services/cloudflare.py` | Async HTTP client to Cloudflare API |
| `tenants.py` | `app/services/tenants.py` | Tenant CRUD + domain management logic |
| `schemas.py` | `app/schemas/tenant.py` | Pydantic schemas (Tenant, Domain, requests/responses) |
| `router.py` | `app/router.py` | All HTTP routes (`/tenants`, `/resolve`, `/domains/*`, etc.) |
| `controller.py` | `app/controller.py` | Facade for those routes |

## How to restore

1. Move files back: `mv app/_archived/cloudflare_domains/{tenant,cloudflare,tenants,schemas,router,controller}.py app/<original-location>/`
2. Restore the `Tenant` model fields (cloudflare_*, custom_domain,
   domain_status, settings/branding/limits/features JSON).
3. Restore the `TenantDomain` model from this archive.
4. Add a new Alembic migration that recreates those tables/columns.
5. Restore `domain.py` from git history (`git log --diff-filter=D -- services/tenant-service/app/models/domain.py`).
