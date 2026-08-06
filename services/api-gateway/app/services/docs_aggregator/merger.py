from collections.abc import Mapping

from copy import deepcopy

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import Settings


GATEWAY_OPENAPI_PATH = "/api/openapi.json"
GATEWAY_DOCS_PATH = "/api/docs"
SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>lead-os · api · aggregated</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.onload = () => {{
  window.ui = SwaggerUIBundle({{
    url: "{openapi_url}",
    dom_id: "#swagger-ui",
    deepLinking: true,
  }});
}};
</script>
</body>
</html>
"""


def _merge_schemas(target: dict, source: Mapping[str, object]) -> None:
    schemas = source.get("components", {}).get("schemas") or {}
    target_components = target.setdefault("components", {})
    target_schemas = target_components.setdefault("schemas", {})
    for name, schema in schemas.items():
        target_schemas[name] = schema


def merge_openapi(specs: dict[str, dict]) -> dict:
    base = {
        "openapi": "3.1.0",
        "info": {
            "title": "lead-os api (aggregated)",
            "version": "0.1.0",
            "description": "OpenAPI merged from upstream services. Served by api-gateway.",
        },
        "paths": {},
        "components": {"schemas": {}},
    }
    for service_name, spec in specs.items():
        tag = service_name
        prefix = f"/{tag}"
        for path, methods in (spec.get("paths") or {}).items():
            normalized_path = path[len(prefix):] if path.startswith(prefix) else path
            if not normalized_path.startswith("/"):
                normalized_path = "/" + normalized_path
            existing = base["paths"].get(normalized_path)
            merged_methods: dict = existing or {}
            for method, op in methods.items():
                op = deepcopy(op)
                op.setdefault("tags", []).append(tag)
                if method in merged_methods:
                    op["tags"] = list(
                        dict.fromkeys(merged_methods[method].get("tags", []) + op["tags"])
                    )
                merged_methods[method] = op
            base["paths"][normalized_path] = merged_methods
        _merge_schemas(base, spec)
    return base


async def aggregated_openapi_json(request: Request) -> JSONResponse:
    from app.services.docs_aggregator.fetcher import fetch_openapi_specs

    specs = await fetch_openapi_specs(request)
    merged = merge_openapi(specs)
    return JSONResponse(merged)


async def aggregated_docs_html(request: Request) -> HTMLResponse:
    return HTMLResponse(
        SWAGGER_UI_HTML.format(openapi_url=GATEWAY_OPENAPI_PATH),
    )
