# files-service

Propietario de los archivos binarios (avatares, media, assets públicos) y de la
tabla `media_resources`. **No expone endpoints públicos.** Su único router es
`/internal/files/*`, accesible solo desde la red interna de Docker y protegido
por `ServiceTokenMiddleware` (firma con `INTER_SERVICE_SECRET`). El api-gateway
solo conoce `service_routes` para `/api/files` — `/internal/*` nunca se proxifica
al cliente.

## Por qué no hay router público

La superficie de cara al usuario (cliente web, app móvil, etc.) se delega a
`auth-service`. Cuando un usuario quiere subir su avatar o descargar uno, el
cliente habla con `auth-service` (`POST /api/auth/me/avatar`,
`GET /api/auth/me/avatar`); `auth-service`, a su vez, llama a `files-service`
vía `ServiceHttpClient` con un `X-Service-Token` firmado con
`INTER_SERVICE_SECRET`. Es el camino a través del cual se delega toda la
gestión de objetos.

Mantener `files-service` sin router público reduce la superficie de ataque:
los archivos requieren dos saltos autenticados (gateway → auth-service →
files-service) en lugar de uno. Si `files-service` tuviera router público,
cualquier bug en la autorización del gateway le bastaría para filtrar
archivos.

## Storage

Hoy la única implementación de `StorageBackend` es `MinioBackend` (SDK
`minio-py`, S3-compatible). El Protocol vive en `app/storage/base.py` y la
factoría en `app/storage/__init__.py` selecciona el backend según
`STORAGE_BACKEND` (`minio` por defecto; un placeholder `LocalBackend` lanza
`NotImplementedError`). Cuando se requiera S3/GCS/local-disk, se añade una
nueva clase que cumpla el Protocol — el resto del servicio no cambia.

Los buckets se inicializan al arranque (`lifespan`) según `INIT_BUCKETS`
desde cada `services/<svc>/.env` (`INIT_BUCKETS_JSON`). Si MinIO está
caído, `files-service` falla rápido.

## Variables de entorno

Ver `services/files-service/.env.example`.
