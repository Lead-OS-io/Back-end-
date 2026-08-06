from fastapi import APIRouter

router = APIRouter()
# No public endpoints in clean-slate phase. Tenant CRUD + /resolve +
# /domains/* are archived in app/_archived/cloudflare_domains/.
