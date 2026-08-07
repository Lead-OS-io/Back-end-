"""Internal router for files-service. Mounted at /internal/files/*. Not reachable
through the api-gateway (gateway routes only /api/<service>/ prefixes)."""
from fastapi import APIRouter

router = APIRouter()
