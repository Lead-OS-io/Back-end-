-- =============================================================================
-- Row Level Security (RLS) — aislamiento por tenant
-- =============================================================================
-- Modelo: DB única, aislamiento a nivel motor por columna tenant_id.
-- Postgres rechaza filas de otro tenant aunque el código de la app falle.
--
-- APLICAR MANUALMENTE. Este archivo NO lo ejecuta la aplicación.
-- Orden: 1) aplicar este SQL  2) activar el wiring `SET app.tenant_id` en la app
-- (ver db/README.md)  3) probar aislamiento con 2 tenants.
--
-- ⚠️ SUPABASE: el `service_role` (y cualquier rol con BYPASSRLS, p.ej. el owner
--    postgres) IGNORA RLS. La app DEBE conectarse con un rol SIN BYPASSRLS para
--    que las políticas apliquen. Ver README.
--
-- La política usa el GUC de sesión `app.tenant_id`, que la app setea por
-- transacción con `SET LOCAL app.tenant_id = '<uuid>'`. Si el GUC no está
-- seteado, `current_setting('app.tenant_id', true)` devuelve NULL y la política
-- no deja ver ninguna fila (fail-closed).
-- =============================================================================

-- Tablas con tenant_id (aislar):
--   users, auth_refresh_tokens, google_oauth_tokens,
--   agent_settings, user_requests,
--   news, announcement, banners, admin_notifications,
--   files, tenant_domains
--
-- Globales (NO aislar): tenants (registro), auth_login_attempts (log de seguridad).

DO $$
DECLARE
    t text;
    tenant_tables text[] := ARRAY[
        'users',
        'auth_refresh_tokens',
        'google_oauth_tokens',
        'agent_settings',
        'user_requests',
        'news',
        'announcement',
        'banners',
        'admin_notifications',
        'files',
        'tenant_domains'
    ];
BEGIN
    FOREACH t IN ARRAY tenant_tables LOOP
        -- Saltar si la tabla no existe todavía
        IF to_regclass('public.' || t) IS NULL THEN
            RAISE NOTICE 'Tabla public.% no existe, se omite', t;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        -- FORCE: aplica RLS también al owner de la tabla (no al service_role de Supabase)
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);

        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON public.%I', t);
        EXECUTE format($f$
            CREATE POLICY tenant_isolation ON public.%I
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        $f$, t);

        RAISE NOTICE 'RLS activado en public.%', t;
    END LOOP;
END $$;

-- =============================================================================
-- ROLLBACK (si necesitas desactivar RLS)
-- =============================================================================
-- DO $$
-- DECLARE t text;
--   tenant_tables text[] := ARRAY['users','auth_refresh_tokens','google_oauth_tokens',
--     'agent_settings','user_requests','news','announcement','banners',
--     'admin_notifications','files','tenant_domains'];
-- BEGIN
--   FOREACH t IN ARRAY tenant_tables LOOP
--     IF to_regclass('public.'||t) IS NULL THEN CONTINUE; END IF;
--     EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON public.%I', t);
--     EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t);
--   END LOOP;
-- END $$;

-- =============================================================================
-- DROP de tablas de dominios eliminados del código (DECISIÓN TUYA — comentado)
-- =============================================================================
-- El código ya no usa estas tablas (agencies, cases, carriers, premium, mailing,
-- calendar, hierarchy, etc.). Descoméntalo SOLO cuando confirmes que no hay datos
-- que conservar. Respaldar antes con pg_dump si aplica.
--
-- DROP TABLE IF EXISTS public.agency_member_carrier CASCADE;
-- DROP TABLE IF EXISTS public.agency_member CASCADE;
-- DROP TABLE IF EXISTS public.agency_hierarchy CASCADE;
-- DROP TABLE IF EXISTS public.agency_performance CASCADE;
-- DROP TABLE IF EXISTS public.agencies_users CASCADE;
-- DROP TABLE IF EXISTS public.agencies CASCADE;
-- DROP TABLE IF EXISTS public.cases_history CASCADE;
-- DROP TABLE IF EXISTS public.case_email_history CASCADE;
-- DROP TABLE IF EXISTS public.drafts CASCADE;
-- DROP TABLE IF EXISTS public.cases CASCADE;
-- DROP TABLE IF EXISTS public.premium_sold CASCADE;
-- DROP TABLE IF EXISTS public.premium_records CASCADE;
-- DROP TABLE IF EXISTS public.premium_reports CASCADE;
-- DROP TABLE IF EXISTS public.carrier_products CASCADE;
-- DROP TABLE IF EXISTS public.carrier_statuses CASCADE;
-- DROP TABLE IF EXISTS public.underwriting_products CASCADE;
-- DROP TABLE IF EXISTS public.underwriting_carriers CASCADE;
-- DROP TABLE IF EXISTS public.carriers CASCADE;
-- DROP TABLE IF EXISTS public.products CASCADE;
-- DROP TABLE IF EXISTS public.medications CASCADE;
-- DROP TABLE IF EXISTS public.medication_categories CASCADE;
-- DROP TABLE IF EXISTS public.calendar CASCADE;
-- DROP TABLE IF EXISTS public.user_hierarchy CASCADE;
-- DROP TABLE IF EXISTS public.lead_opt_ins CASCADE;
-- DROP TABLE IF EXISTS public.suppression_list CASCADE;
-- DROP TABLE IF EXISTS public.sending_ips CASCADE;
-- DROP TABLE IF EXISTS public.data_access_emailhistory CASCADE;
-- DROP TABLE IF EXISTS public.email_logs CASCADE;
-- DROP TABLE IF EXISTS public.email_templates CASCADE;
-- DROP TABLE IF EXISTS public.google_gmail_tokens CASCADE;
-- DROP TABLE IF EXISTS public.google_executed_actions CASCADE;
