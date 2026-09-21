-- ==============================================================================
-- AUTOFORM AI — MIGRACIÓN INICIAL SUPABASE (PostgreSQL + Auth + RLS)
-- Archivo: supabase/migrations/001_initial_schema.sql
-- Fase de Remediación de Seguridad: ADR-0010
-- Ronda Final de Hardening (Hardening-01 a Hardening-05)
-- ==============================================================================

-- 1. EXTENSIONES REQUERIDAS
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. TABLA: perfiles_empresa (Esquema Híbrido Relacional + JSONB - ADR-0010 / Q1)
CREATE TABLE IF NOT EXISTS public.perfiles_empresa (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,
    nombre_empresa TEXT NOT NULL,
    nit TEXT UNIQUE,
    es_activa BOOLEAN DEFAULT false NOT NULL,
    datos_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Índices de perfiles_empresa
CREATE INDEX IF NOT EXISTS idx_perfiles_empresa_datos_json
    ON public.perfiles_empresa USING GIN (datos_json);

-- Índice parcial único: sólo puede existir un perfil marcado como activo simultáneamente
-- NOTA ARQUITECTÓNICA (ADR-0010 / Decisión Q1):
-- AutoForm Excel opera bajo una arquitectura corporativa mono-empresa (Single-Tenant).
-- Este índice garantiza a nivel de motor PostgreSQL que a lo sumo un solo registro
-- tenga 'es_activa = true' en toda la base de datos.
-- Si en el futuro se requiriera soporte multi-empresa (Multi-Tenant), será mandatorio
-- introducir una entidad 'empresa_tenant_id' y redefinir este índice particionado por tenant.
CREATE UNIQUE INDEX IF NOT EXISTS idx_un_perfil_activo
    ON public.perfiles_empresa (es_activa)
    WHERE es_activa = true;

-- 3. TABLA: perfiles_usuario (Vínculo 1:1 con auth.users de Supabase - ADR-0008 / ADR-0010)
CREATE TABLE IF NOT EXISTS public.perfiles_usuario (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    cargo TEXT DEFAULT '',
    cedula TEXT DEFAULT '',
    telefono TEXT DEFAULT '',
    correo TEXT UNIQUE NOT NULL,
    direccion TEXT DEFAULT 'Carrera 63 B # 32 E -25 OFC 206',
    ciudad TEXT DEFAULT 'Bogotá',
    es_admin BOOLEAN DEFAULT false NOT NULL,
    activo BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    CONSTRAINT check_dominio_corporativo CHECK (correo ~* '^[^@\s]+@(iaclatam\.com|iac\.com\.co)$')
);

CREATE INDEX IF NOT EXISTS idx_perfiles_usuario_correo
    ON public.perfiles_usuario (correo);

-- 4. TABLA: operadores (Catálogo de Asesores Comerciales y Diligenciamiento - ADR-0007 / ADR-0010)
CREATE TABLE IF NOT EXISTS public.operadores (
    id TEXT PRIMARY KEY,
    usuario_id UUID NULL REFERENCES public.perfiles_usuario(id) ON DELETE SET NULL,
    nombre TEXT NOT NULL,
    cargo TEXT DEFAULT '',
    cedula TEXT DEFAULT '',
    telefono TEXT DEFAULT '',
    correo TEXT DEFAULT '',
    direccion TEXT DEFAULT '',
    ciudad TEXT DEFAULT '',
    es_activo BOOLEAN DEFAULT false NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operadores_usuario_id
    ON public.operadores (usuario_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operadores_correo_lower
    ON public.operadores (lower(correo))
    WHERE correo IS NOT NULL AND correo != '';

CREATE INDEX IF NOT EXISTS idx_operadores_activo
    ON public.operadores (es_activo);

-- 5. TABLA: migration_runs (Registro de Auditoría de Lotes de Migración - Hardening-04)
--
-- manifesto_uuids JSONB: Manifiesto inmutable de todos los UUID creados por el lote,
-- organizado por tabla. Permite rollback selectivo sin ambigüedad y trazabilidad por lote.
-- Estructura esperada:
-- {
--   "perfiles_empresa": ["uuid1", ...],
--   "usuarios_auth":    ["uuid1", ...],   -- IDs de auth.users creados
--   "perfiles_usuario": ["uuid1", ...],
--   "operadores":       ["text_id1", ...]  -- TEXT PKs de operadores
-- }
CREATE TABLE IF NOT EXISTS public.migration_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID UNIQUE NOT NULL,
    target_project_ref TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    completed_at TIMESTAMPTZ,
    estado TEXT NOT NULL DEFAULT 'RUNNING',
    perfiles_migrados INTEGER DEFAULT 0 NOT NULL,
    operadores_migrados INTEGER DEFAULT 0 NOT NULL,
    usuarios_invitados INTEGER DEFAULT 0 NOT NULL,
    manifesto_uuids JSONB NOT NULL DEFAULT '{
        "perfiles_empresa": [],
        "usuarios_auth": [],
        "perfiles_usuario": [],
        "operadores": []
    }'::jsonb,
    detalles_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_migration_runs_batch
    ON public.migration_runs (batch_id);
CREATE INDEX IF NOT EXISTS idx_migration_runs_estado
    ON public.migration_runs (estado);

-- 5b. TABLA: deployment_identity (Identidad Canónica de Base de Datos - Aislamiento Estricto)
--
-- Garantiza a nivel de motor de base de datos que ninguna migración, script o cliente
-- opere contra una base de datos errónea o cruzada entre aplicaciones (PDF vs Excel).
CREATE TABLE IF NOT EXISTS public.deployment_identity (
    singleton_id INTEGER PRIMARY KEY DEFAULT 1 CHECK (singleton_id = 1),
    application_code TEXT NOT NULL CHECK (application_code = 'autoform-excel'),
    environment TEXT NOT NULL CHECK (environment IN ('staging', 'production')),
    project_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 6. FUNCIONES DE SEGURIDAD (SECURITY DEFINER CON SET search_path = '')

-- ── 6a. is_active_user(): verifica que el usuario autenticado esté activo (Hardening-02) ──
--
-- REGLA DE SEGURIDAD ABSOLUTA:
-- Un usuario con JWT todavía válido pero con activo = false en public.perfiles_usuario
-- debe obtener CERO filas en todas las consultas PostgREST y no poder realizar
-- ninguna mutación (INSERT, UPDATE, DELETE). Esta función se usa en la cláusula
-- USING de cada política RLS aplicable.
CREATE OR REPLACE FUNCTION public.is_active_user()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
STABLE
AS $$
    SELECT COALESCE(
        (SELECT true
         FROM public.perfiles_usuario u
         WHERE u.id = auth.uid() AND u.activo = true
         LIMIT 1),
        false
    );
$$;

REVOKE ALL ON FUNCTION public.is_active_user() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.is_active_user() FROM anon;
GRANT EXECUTE ON FUNCTION public.is_active_user() TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_active_user() TO service_role;

-- ── 6b. is_admin(): verifica que el usuario autenticado sea admin activo ──
--
-- REGLA: is_admin() exige AMBAS condiciones: es_admin = true AND activo = true.
-- Un administrador desactivado pierde privilegios de forma inmediata aunque
-- su JWT todavía sea válido.
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
STABLE
AS $$
    SELECT COALESCE(
        (SELECT u.es_admin
         FROM public.perfiles_usuario u
         WHERE u.id = auth.uid() AND u.activo = true AND u.es_admin = true
         LIMIT 1),
        false
    );
$$;

-- Revocación de permisos predeterminados e inyección mínima de privilegios
REVOKE ALL ON FUNCTION public.is_admin() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.is_admin() FROM anon;
GRANT EXECUTE ON FUNCTION public.is_admin() TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_admin() TO service_role;

-- ── 6c. validar_dominio_correo_auth(): trigger de dominio en auth.users ──
-- Defensa en Profundidad - Q6
CREATE OR REPLACE FUNCTION public.validar_dominio_correo_auth()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF NEW.email !~* '^[^@\s]+@(iaclatam\.com|iac\.com\.co)$' THEN
        RAISE EXCEPTION
            'Acceso denegado: El correo % no pertenece a los dominios corporativos autorizados de IAC Latam (@iaclatam.com, @iac.com.co)',
            NEW.email;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.validar_dominio_correo_auth() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.validar_dominio_correo_auth() FROM anon;
REVOKE ALL ON FUNCTION public.validar_dominio_correo_auth() FROM authenticated;

DROP TRIGGER IF EXISTS trigger_validar_dominio_correo ON auth.users;
CREATE TRIGGER trigger_validar_dominio_correo
BEFORE INSERT OR UPDATE OF email ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.validar_dominio_correo_auth();

-- ── 6d. proteger_columnas_perfil_usuario(): trigger de inmutabilidad ──
-- Impide escalabilidad de privilegios en perfiles_usuario (Remediación C-02)
CREATE OR REPLACE FUNCTION public.proteger_columnas_perfil_usuario()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    caller_is_admin BOOLEAN;
    jwt_role TEXT;
BEGIN
    caller_is_admin := public.is_admin();

    BEGIN
        jwt_role := coalesce(auth.role(), '');
    EXCEPTION WHEN OTHERS THEN
        jwt_role := '';
    END;

    IF jwt_role = '' THEN
        BEGIN
            jwt_role := coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '');
        EXCEPTION WHEN OTHERS THEN
            jwt_role := '';
        END IF;
    END IF;

    -- Si el llamante no es administrador activo ni service_role, proteger columnas sensibles
    IF NOT caller_is_admin 
       AND current_user != 'service_role' 
       AND jwt_role != 'service_role' THEN
        IF NEW.es_admin IS DISTINCT FROM OLD.es_admin THEN
            RAISE EXCEPTION 'Operación denegada: No tienes permisos para modificar el rol de administrador (es_admin).';
        END IF;
        IF NEW.activo IS DISTINCT FROM OLD.activo THEN
            RAISE EXCEPTION 'Operación denegada: No tienes permisos para modificar el estado de activación (activo).';
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id THEN
            RAISE EXCEPTION 'Operación denegada: El identificador de cuenta (id) es inmutable.';
        END IF;
        IF NEW.correo IS DISTINCT FROM OLD.correo THEN
            RAISE EXCEPTION 'Operación denegada: El correo electrónico corporativo es inmutable por el usuario.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.proteger_columnas_perfil_usuario() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.proteger_columnas_perfil_usuario() FROM anon;
REVOKE ALL ON FUNCTION public.proteger_columnas_perfil_usuario() FROM authenticated;

DROP TRIGGER IF EXISTS trigger_proteger_columnas_perfil_usuario ON public.perfiles_usuario;
CREATE TRIGGER trigger_proteger_columnas_perfil_usuario
BEFORE UPDATE ON public.perfiles_usuario
FOR EACH ROW
EXECUTE FUNCTION public.proteger_columnas_perfil_usuario();

-- ── 6e. actualizar_timestamp_updated_at(): trigger genérico de timestamp ──
CREATE OR REPLACE FUNCTION public.actualizar_timestamp_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.actualizar_timestamp_updated_at() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.actualizar_timestamp_updated_at() FROM anon;

DROP TRIGGER IF EXISTS trigger_perfiles_empresa_updated_at ON public.perfiles_empresa;
CREATE TRIGGER trigger_perfiles_empresa_updated_at
BEFORE UPDATE ON public.perfiles_empresa
FOR EACH ROW
EXECUTE FUNCTION public.actualizar_timestamp_updated_at();

DROP TRIGGER IF EXISTS trigger_perfiles_usuario_updated_at ON public.perfiles_usuario;
CREATE TRIGGER trigger_perfiles_usuario_updated_at
BEFORE UPDATE ON public.perfiles_usuario
FOR EACH ROW
EXECUTE FUNCTION public.actualizar_timestamp_updated_at();

DROP TRIGGER IF EXISTS trigger_operadores_updated_at ON public.operadores;
CREATE TRIGGER trigger_operadores_updated_at
BEFORE UPDATE ON public.operadores
FOR EACH ROW
EXECUTE FUNCTION public.actualizar_timestamp_updated_at();

-- 7. ROW LEVEL SECURITY (RLS) — POLÍTICAS UNIFORMIZADAS CON is_active_user() (Hardening-02)

ALTER TABLE public.perfiles_empresa ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.perfiles_usuario ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.operadores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.migration_runs ENABLE ROW LEVEL SECURITY;

-- ── POLÍTICAS: perfiles_empresa ──────────────────────────────────────────────

-- SELECT: Solo usuarios autenticados con activo = true en BD (is_active_user()).
-- Un usuario con JWT válido pero inactivo obtiene 0 filas.
DROP POLICY IF EXISTS "perfiles_empresa_select_auth" ON public.perfiles_empresa;
CREATE POLICY "perfiles_empresa_select_auth"
    ON public.perfiles_empresa
    FOR SELECT
    TO authenticated
    USING (public.is_active_user());

-- INSERT/UPDATE/DELETE: Exclusivo para administradores activos (is_admin() = activo + es_admin).
DROP POLICY IF EXISTS "perfiles_empresa_admin_modificar" ON public.perfiles_empresa;
CREATE POLICY "perfiles_empresa_admin_modificar"
    ON public.perfiles_empresa
    FOR ALL
    TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

-- ── POLÍTICAS: perfiles_usuario ──────────────────────────────────────────────

-- SELECT: Un usuario activo puede ver únicamente su propio perfil; un admin activo puede ver todos.
-- La condición is_active_user() está embebida en is_admin(), por lo tanto:
-- - usuario inactivo: id = auth.uid() → devolverá su fila, pero activo=false es visible.
-- Para bloquear la lectura también a inactivos agregamos is_active_user() OR is_admin().
DROP POLICY IF EXISTS "perfiles_usuario_select" ON public.perfiles_usuario;
CREATE POLICY "perfiles_usuario_select"
    ON public.perfiles_usuario
    FOR SELECT
    TO authenticated
    USING (
        (id = auth.uid() AND public.is_active_user())
        OR public.is_admin()
    );

-- INSERT: Solo administradores (o service_role vía bypass) pueden registrar nuevos perfiles.
DROP POLICY IF EXISTS "perfiles_usuario_insert_admin" ON public.perfiles_usuario;
CREATE POLICY "perfiles_usuario_insert_admin"
    ON public.perfiles_usuario
    FOR INSERT
    TO authenticated
    WITH CHECK (public.is_admin());

-- UPDATE: Un usuario activo puede actualizar sus propios datos no protegidos.
-- El trigger proteger_columnas_perfil_usuario() bloquea es_admin, activo, id y correo.
DROP POLICY IF EXISTS "perfiles_usuario_update" ON public.perfiles_usuario;
CREATE POLICY "perfiles_usuario_update"
    ON public.perfiles_usuario
    FOR UPDATE
    TO authenticated
    USING (
        (id = auth.uid() AND public.is_active_user())
        OR public.is_admin()
    )
    WITH CHECK (
        (id = auth.uid() AND public.is_active_user())
        OR public.is_admin()
    );

-- DELETE: Solo administradores activos.
DROP POLICY IF EXISTS "perfiles_usuario_delete_admin" ON public.perfiles_usuario;
CREATE POLICY "perfiles_usuario_delete_admin"
    ON public.perfiles_usuario
    FOR DELETE
    TO authenticated
    USING (public.is_admin());

-- ── POLÍTICAS: operadores ────────────────────────────────────────────────────

-- SELECT: Solo usuarios autenticados con activo = true.
-- Un usuario inactivo no puede ver el catálogo de operadores.
DROP POLICY IF EXISTS "operadores_select_auth" ON public.operadores;
CREATE POLICY "operadores_select_auth"
    ON public.operadores
    FOR SELECT
    TO authenticated
    USING (public.is_active_user());

-- INSERT: Exclusivo para administradores activos.
DROP POLICY IF EXISTS "operadores_insert_admin" ON public.operadores;
CREATE POLICY "operadores_insert_admin"
    ON public.operadores
    FOR INSERT
    TO authenticated
    WITH CHECK (public.is_admin());

-- UPDATE: Solo el operador vinculado a su propia cuenta (usuario_id = auth.uid()) y activo,
-- o un administrador activo.
DROP POLICY IF EXISTS "operadores_update_dueno_o_admin" ON public.operadores;
CREATE POLICY "operadores_update_dueno_o_admin"
    ON public.operadores
    FOR UPDATE
    TO authenticated
    USING (
        (usuario_id = auth.uid() AND public.is_active_user())
        OR public.is_admin()
    )
    WITH CHECK (
        (usuario_id = auth.uid() AND public.is_active_user())
        OR public.is_admin()
    );

-- DELETE: Exclusivo para administradores activos.
-- Un operador comercial nunca puede eliminar registros del catálogo.
DROP POLICY IF EXISTS "operadores_delete_admin" ON public.operadores;
CREATE POLICY "operadores_delete_admin"
    ON public.operadores
    FOR DELETE
    TO authenticated
    USING (public.is_admin());

-- ── POLÍTICAS: migration_runs ────────────────────────────────────────────────

-- Exclusivo para administradores activos (auditoría de lotes de migración).
-- service_role bypassa RLS por diseño de Supabase.
DROP POLICY IF EXISTS "migration_runs_admin" ON public.migration_runs;
CREATE POLICY "migration_runs_admin"
    ON public.migration_runs
    FOR ALL
    TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

-- ── POLÍTICAS: deployment_identity ───────────────────────────────────────────

ALTER TABLE public.deployment_identity ENABLE ROW LEVEL SECURITY;

-- Lectura abierta para verificar identidad previa a cualquier operación
DROP POLICY IF EXISTS "deployment_identity_select" ON public.deployment_identity;
CREATE POLICY "deployment_identity_select"
    ON public.deployment_identity
    FOR SELECT
    TO authenticated, anon
    USING (true);

-- Prohibición total de mutaciones vía cliente (solo DDL / migraciones)
DROP POLICY IF EXISTS "deployment_identity_no_mutations" ON public.deployment_identity;
CREATE POLICY "deployment_identity_no_mutations"
    ON public.deployment_identity
    FOR ALL
    TO authenticated, anon
    USING (false)
    WITH CHECK (false);

