# files-service

Propietario de los archivos binarios (avatares, media, assets públicos) y de la
tabla `media_resources`. Expone **dos routers**:

- `/internal/files/*` — solo para la red interna, protegido por
  `ServiceTokenMiddleware`. Después de este spec, sólo conserva dos endpoints
  de lectura (`GET /users/{user_id}/avatar`, `GET /media/{media_id}/presign`)
  que `auth-service` usa para enriquecer `/me`. **No** expone escritura.
- `/public/files/*` — para clientes a través del `api-gateway`, protegido por
  `PublicAuthMiddleware` que valida `X-User-Id` (que el gateway inyecta
  desde el JWT del usuario) y aplica ownership: cada usuario solo opera
  sobre sus propios recursos. Endpoints:
  - `POST /users/me/avatar` — upload (reemplaza el anterior). Devuelve `MediaRef`.
  - `GET /users/me/avatar` — 302 a URL presignada (TTL = `PRESIGN_TTL_SECONDS`).
  - `DELETE /users/me/avatar` — borra.
  - `GET /media/{media_id}/presign?ttl=N` — 302 a URL presignada; ownership enforced.

## Por qué hay dos routers

`auth-service` ya no es proxy de archivos. El frontend habla directo con
`files-service` (vía gateway) para subir, leer y borrar avatares. La
superficie `/public/*` se mantiene estrecha: solo avatar, validación de
size/mime en el servicio, ownership por `user_id`. No hay admin override
(queda para un plan futuro cuando exista el rol).

`auth-service` conserva una ruta interna mínima para llenar `has_avatar` /
`avatar_url` en las respuestas de `/me`, `/login`, `/refresh`. Esa ruta usa
el `/internal/files/*` de este servicio y `ServiceHttpClient`.

## Storage

Hoy la única implementación de `StorageBackend` es `MinioBackend` (SDK
`minio-py`, S3-compatible). El Protocol vive en `app/storage/base.py` y la
factoría en `app/storage/__init__.py` selecciona el backend según
`STORAGE_BACKEND` (`minio` por defecto; un placeholder `LocalBackend` lanza
`NotImplementedError`).

Los buckets se inicializan al arranque (`lifespan`) según `INIT_BUCKETS`
desde cada `services/<svc>/.env` (`INIT_BUCKETS_JSON`). Si MinIO está
caído, `files-service` falla rápido.

## Eventos

`files-service` publica `user.avatar.changed` y `user.avatar.removed` en el
stream `events:onboarding` después de un upload/delete exitoso del router
público. Consumidores futuros (notification, search index) se suscriben a
ese stream. Si Redis está caído, la publicación se loguea y se descarta —
el upload/delete sigue siendo exitoso (no hay outbox).

## Variables de entorno

Ver `services/files-service/.env.example`. Las relevantes para el router
público: `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`, `PRESIGN_TTL_SECONDS`.
