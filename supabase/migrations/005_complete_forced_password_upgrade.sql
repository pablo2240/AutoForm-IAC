-- ==============================================================================
-- AUTOFORM AI — MIGRACIÓN 005: ACTUALIZACIÓN COMPLETA DE CAMBIO FORZADO DE CONTRASEÑA
-- Archivo: supabase/migrations/005_complete_forced_password_upgrade.sql
-- Adición de debe_cambiar_password y blindaje de trigger de perfiles de usuario
-- ==============================================================================

BEGIN;

-- 1. Preflight de identidad en base de datos
-- Valida singleton de deployment_identity, proyecto objetivo 'nfaxkncrpfrsvzfgczny',
-- preexistencia de columnas requeridas en public.perfiles_usuario,
-- y preexistencia de public.auditoria_autenticacion (que no debe ser tocada).
DO $$
DECLARE
    dep_count INTEGER;
    dep_app TEXT;
    dep_env TEXT;
    dep_ref TEXT;
    cols_encontradas INTEGER;
BEGIN
    -- Comprobar singleton deployment_identity
    SELECT COUNT(*),
           MAX(application_code),
           MAX(environment),
           MAX(project_ref)
    INTO dep_count, dep_app, dep_env, dep_ref
    FROM public.deployment_identity;

    IF dep_count != 1 THEN
        RAISE EXCEPTION 'Preflight de identidad en base de datos falló: deployment_identity contiene % filas (se requiere exactamente 1 singleton).', dep_count;
    END IF;

    IF dep_app != 'autoform-excel' OR dep_env != 'staging' OR dep_ref != 'nfaxkncrpfrsvzfgczny' THEN
        RAISE EXCEPTION 'Preflight de identidad en base de datos falló: discrepancia en deployment_identity (app=%, env=%, ref=%). Proyecto esperado: autoform-excel/staging/nfaxkncrpfrsvzfgczny.', dep_app, dep_env, dep_ref;
    END IF;

    -- Comprobar que existe la tabla de perfiles
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'perfiles_usuario'
    ) THEN
        RAISE EXCEPTION 'Preflight de identidad en base de datos falló: La tabla public.perfiles_usuario no existe en este entorno.';
    END IF;

    -- Comprobar que perfiles_usuario contiene las 5 columnas requeridas antes de reemplazar el trigger
    SELECT COUNT(DISTINCT column_name)
    INTO cols_encontradas
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'perfiles_usuario'
      AND column_name IN ('id', 'correo', 'es_admin', 'activo', 'estado_aprobacion');

    IF cols_encontradas != 5 THEN
        RAISE EXCEPTION 'Preflight de identidad en base de datos falló: public.perfiles_usuario debe contener id, correo, es_admin, activo y estado_aprobacion antes de actualizar el trigger.';
    END IF;

    -- Confirmar que public.auditoria_autenticacion existe y se preserva intacta
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'auditoria_autenticacion'
    ) THEN
        RAISE EXCEPTION 'Preflight de identidad en base de datos falló: La tabla public.auditoria_autenticacion debe existir previamente y preservarse intacta.';
    END IF;
END $$;

-- 2. Agregar columna debe_cambiar_password a public.perfiles_usuario de forma idempotente
ALTER TABLE public.perfiles_usuario
ADD COLUMN IF NOT EXISTS debe_cambiar_password BOOLEAN NOT NULL DEFAULT false;

-- 3. Reemplazar public.proteger_columnas_perfil_usuario() por versión segura:
-- - Sin elevación de privilegios (invocador estándar).
-- - Con SET search_path = '' para blindar la ruta de resolución.
-- - Inicialización fail-closed de roles ante valores NULL.
-- - Inmutabilidad absoluta de id para todos los roles (incluido service_role).
-- - Modificación de correo restringida exclusivamente a service_role (bloqueada para administradores autenticados).
-- - Bloqueo transaccional con pg_advisory_xact_lock(9052026) para proteger al último admin en concurrencia.
-- - Modificación de debe_cambiar_password restringida exclusivamente a service_role.
CREATE OR REPLACE FUNCTION public.proteger_columnas_perfil_usuario()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    is_service_role BOOLEAN;
    caller_is_admin BOOLEAN;
BEGIN
    -- Inicialización fail-closed: si auth.role() o public.is_admin() retornan NULL, no se omiten las restricciones
    is_service_role := COALESCE(auth.role() = 'service_role', false);
    caller_is_admin := CASE
        WHEN is_service_role THEN false
        ELSE COALESCE(public.is_admin(), false)
    END;

    -- 1. Inmutabilidad absoluta de id para cualquier rol, incluido service_role:
    IF NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'Operación denegada: El identificador de cuenta (id) es absolutamente inmutable.';
    END IF;

    -- 2. Regla para correo:
    -- Únicamente modificable por backend autorizado (service_role).
    -- Ningún administrador autenticado puede cambiarlo directamente.
    IF NOT is_service_role THEN
        IF NEW.correo IS DISTINCT FROM OLD.correo THEN
            RAISE EXCEPTION 'Operación denegada: El correo electrónico corporativo solo puede ser modificado por backend autorizado (service_role).';
        END IF;
    END IF;

    -- 3. Regla para debe_cambiar_password:
    -- Ningún token de usuario (ni comercial ni administrador) puede modificar debe_cambiar_password.
    -- Solo el backend con service_role puede conmutar esta bandera.
    IF NOT is_service_role THEN
        IF NEW.debe_cambiar_password IS DISTINCT FROM OLD.debe_cambiar_password THEN
            RAISE EXCEPTION 'Operación denegada: La bandera debe_cambiar_password es un atributo protegido y no puede ser modificada por clientes authenticated. Requiere backend autorizado.';
        END IF;
    END IF;

    -- 4. Protección del último administrador activo con serialización transaccional:
    -- Impide degradar (es_admin=false) o desactivar (activo=false) al último administrador activo.
    -- Bloqueo transaccional para evitar condiciones de carrera entre transacciones concurrentes.
    -- Aplica a todos los roles, incluido service_role: primero debe existir otro administrador activo.
    IF (OLD.es_admin IS TRUE AND OLD.activo IS TRUE) AND (NEW.es_admin IS NOT TRUE OR NEW.activo IS NOT TRUE) THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(9052026);

        IF NOT EXISTS (
            SELECT 1
            FROM public.perfiles_usuario
            WHERE id != OLD.id
              AND es_admin IS TRUE
              AND activo IS TRUE
        ) THEN
            RAISE EXCEPTION 'Operación denegada: No se puede desactivar ni degradar al único administrador activo del sistema. Debe existir otro administrador activo previamente.';
        END IF;
    END IF;

    -- 5. Si el llamante no es service_role ni administrador activo (public.is_admin()), proteger gestión y autorización:
    IF NOT is_service_role AND NOT caller_is_admin THEN
        IF NEW.es_admin IS DISTINCT FROM OLD.es_admin THEN
            RAISE EXCEPTION 'Operación denegada: No tienes permisos para modificar el rol de administrador (es_admin).';
        END IF;
        IF NEW.activo IS DISTINCT FROM OLD.activo THEN
            RAISE EXCEPTION 'Operación denegada: No tienes permisos para modificar el estado de activación (activo).';
        END IF;
        IF NEW.estado_aprobacion IS DISTINCT FROM OLD.estado_aprobacion THEN
            RAISE EXCEPTION 'Operación denegada: No tienes permisos para modificar el estado de aprobación (estado_aprobacion).';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

-- 4. Revocar ejecución pública directa de la función
REVOKE ALL ON FUNCTION public.proteger_columnas_perfil_usuario() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.proteger_columnas_perfil_usuario() FROM anon;
REVOKE ALL ON FUNCTION public.proteger_columnas_perfil_usuario() FROM authenticated;

-- 5. Recrear únicamente el trigger en public.perfiles_usuario
DROP TRIGGER IF EXISTS trigger_proteger_columnas_perfil_usuario ON public.perfiles_usuario;
CREATE TRIGGER trigger_proteger_columnas_perfil_usuario
BEFORE UPDATE ON public.perfiles_usuario
FOR EACH ROW
EXECUTE FUNCTION public.proteger_columnas_perfil_usuario();

-- 6. Comprobaciones Posteriores Reforzadas (Post-Flight Assertions)
-- Confirma que la columna, exactamente una función segura (prosecdef=false) y el trigger quedaron activos.
DO $$
DECLARE
    trigger_activo BOOLEAN;
    fn_count INTEGER;
    is_secdef BOOLEAN;
    col_existe BOOLEAN;
BEGIN
    -- Comprobar existencia de columna debe_cambiar_password
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'perfiles_usuario'
          AND column_name = 'debe_cambiar_password'
    ) INTO col_existe;

    IF NOT col_existe THEN
        RAISE EXCEPTION 'Postflight falló: La columna debe_cambiar_password no se encuentra en public.perfiles_usuario.';
    END IF;

    -- Comprobar que el trigger existe en perfiles_usuario
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.triggers
        WHERE trigger_schema = 'public'
          AND event_object_table = 'perfiles_usuario'
          AND trigger_name = 'trigger_proteger_columnas_perfil_usuario'
    ) INTO trigger_activo;

    IF NOT trigger_activo THEN
        RAISE EXCEPTION 'Postflight falló: El trigger trigger_proteger_columnas_perfil_usuario no está registrado.';
    END IF;

    -- Comprobar que exista exactamente una función public.proteger_columnas_perfil_usuario() y que prosecdef = false
    SELECT COUNT(*), bool_or(prosecdef)
    INTO fn_count, is_secdef
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = 'proteger_columnas_perfil_usuario';

    IF fn_count != 1 THEN
        RAISE EXCEPTION 'Postflight falló: Se esperaba exactamente 1 función public.proteger_columnas_perfil_usuario(), se encontraron %.', fn_count;
    END IF;

    IF is_secdef IS TRUE THEN
        RAISE EXCEPTION 'Postflight falló: La función proteger_columnas_perfil_usuario tiene prosecdef=true (debe ser sin elevación).';
    END IF;
END $$;

COMMIT;
