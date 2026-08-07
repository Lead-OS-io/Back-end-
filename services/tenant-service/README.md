# tenant-service

Propietario de la entidad `Tenant` y del flujo post-onboarding (Cloudflare
DNS, etc.). **No expone endpoints públicos.** Su `router.py` y
`controller.py` están intencionalmente vacíos.

## Por qué no hay router público

Toda la lógica de tenant que necesita el cliente se hace dentro de un evento
de `auth-service` (`onboarding.pending`) → `tenant-service` consume → emite
`tenant.created` con la fila creada de `Tenant` → `auth-service` cierra el
ciclo activando al usuario. No hay segundo escenario donde un cliente web
toque un endpoint de tenant directamente.

El día que necesitemos exponer APIs de tenant (por ejemplo, panel admin con
CRUD de tenants), el patrón será:

1. Mover la lógica a `services/` (sin tocar el router).
2. Añadir un router interno o exponer los nuevos endpoints a través de
   `auth-service` (siguiendo el mismo modelo de files-service: `auth-service`
   es la cara del cliente).

## Variables de entorno

Ver `services/tenant-service/.env.example`.
