-- ==============================================================================
-- AUTOFORM AI — MIGRACIÓN 006: RECONCILIACIÓN Y HARDENING DE ESQUEMA DE AUDITORÍA
-- Archivo: supabase/migrations/006_reconcile_audit_schema.sql
-- Reconciliación idempotente del esquema de public.auditoria_autenticacion:
-- - admin_id UUID NOT NULL con FK única fk_auditoria_admin_id (ON DELETE RESTRICT)
-- - CHECK chk_auditoria_tipo_evento para los 3 eventos oficiales
-- - Inmutabilidad estricta sin elevación de privilegios
-- ==============================================================================

BEGIN;

-- 1. Preflight de identidad en base de datos
DO $$
DECLARE
    dep_count INTEGER;
    dep_app TEXT;
    dep_env TEXT;
    dep_ref TEXT;
BEGIN
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

    -- Confirmar que public.auditoria_autenticacion existe previamente
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'auditoria_autenticacion'
    ) THEN
        RAISE EXCEPTION 'Preflight falló: La tabla public.auditoria_autenticacion no existe para reconciliación.';
    END IF;
END $$;

-- 2. Reconciliación de columna admin_id: UUID NOT NULL
DO $$
BEGIN
    -- Si hubiese filas con admin_id nulo de pruebas históricas, asignar a usuario existente o fallar
    -- Asegurar tipo UUID
    ALTER TABLE public.auditoria_autenticacion
    ALTER COLUMN admin_id SET NOT NULL;
EXCEPTION
    WHEN others THEN
        RAISE EXCEPTION 'Error al establecer NOT NULL en admin_id de auditoria_autenticacion: %', SQLERRM;
END $$;

-- 3. Limpieza de FKs previas/duplicadas en admin_id y creación de restricción canónica única
DO $$
DECLARE
    c_rec RECORD;
BEGIN
    FOR c_rec IN (
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.table_name = 'auditoria_autenticacion'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = 'admin_id'
    ) LOOP
        EXECUTE format('ALTER TABLE public.auditoria_autenticacion DROP CONSTRAINT IF EXISTS %I;', c_rec.constraint_name);
    END LOOP;
END $$;

ALTER TABLE public.auditoria_autenticacion
ADD CONSTRAINT fk_auditoria_admin_id
FOREIGN KEY (admin_id) REFERENCES auth.users(id) ON DELETE RESTRICT;

-- 4. Reconciliación de restricción CHECK para los 3 eventos oficiales
ALTER TABLE public.auditoria_autenticacion
DROP CONSTRAINT IF EXISTS chk_auditoria_tipo_evento;

ALTER TABLE public.auditoria_autenticacion
ADD CONSTRAINT chk_auditoria_tipo_evento
CHECK (
    tipo_evento IN (
        'reenvio_recuperacion',
        'restablecimiento_manual_excepcional',
        'cambio_password_primer_ingreso'
    )
);

-- 5. Reconciliación de Políticas RLS:
-- Habilitar Row Level Security
ALTER TABLE public.auditoria_autenticacion ENABLE ROW LEVEL SECURITY;

-- Eliminar dinámicamente todas las políticas existentes SOLO de public.auditoria_autenticacion
DO $$
DECLARE
    pol RECORD;
BEGIN
    FOR pol IN (
        SELECT policyname
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'auditoria_autenticacion'
    ) LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.auditoria_autenticacion;', pol.policyname);
    END LOOP;
END $$;

-- Recrear únicamente la política SELECT para administradores activos
CREATE POLICY "Solo administradores pueden consultar auditoria"
ON public.auditoria_autenticacion
FOR SELECT
TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.perfiles_usuario
        WHERE perfiles_usuario.id = auth.uid()
          AND perfiles_usuario.es_admin = true
          AND perfiles_usuario.activo = true
    )
);

-- 6. Reemplazo de función de inmutabilidad:
-- - Sin elevación de privilegios (invocador estándar)
-- - Con SET search_path = ''
-- - Autorización de purga sintética exclusivamente por claim (auth.role() = 'service_role')
CREATE OR REPLACE FUNCTION public.proteger_inmutabilidad_auditoria()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Operación denegada: Los registros de public.auditoria_autenticacion son estrictamente inmutables (no se permite UPDATE).';
    ELSIF TG_OP = 'DELETE' THEN
        -- Purga higiénica permitida exclusivamente a backend autorizado sobre fixtures synth.%
        IF (auth.role() = 'service_role') AND (OLD.correo_objetivo ILIKE 'synth.%') THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Operación denegada: Los registros de public.auditoria_autenticacion son inmutables (no se permite DELETE).';
    END IF;
    RETURN NULL;
END;
$$;

-- Revocación de permisos de ejecución pública
REVOKE ALL ON FUNCTION public.proteger_inmutabilidad_auditoria() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.proteger_inmutabilidad_auditoria() FROM anon;
REVOKE ALL ON FUNCTION public.proteger_inmutabilidad_auditoria() FROM authenticated;

-- Recrear el trigger en la tabla de auditoría
DROP TRIGGER IF EXISTS trg_proteger_inmutabilidad_auditoria ON public.auditoria_autenticacion;
CREATE TRIGGER trg_proteger_inmutabilidad_auditoria
BEFORE UPDATE OR DELETE ON public.auditoria_autenticacion
FOR EACH ROW
EXECUTE FUNCTION public.proteger_inmutabilidad_auditoria();

-- 7. Comprobaciones Posteriores (Post-Flight Assertions)
DO $$
DECLARE
    rls_activo BOOLEAN;
    total_politicas INTEGER;
    pol_rec RECORD;
    is_not_null BOOLEAN;
    total_fks_admin INTEGER;
    fks_validas_admin INTEGER;
    chk_def TEXT;
    literales_eventos TEXT[];
    fn_count INTEGER;
    is_secdef BOOLEAN;
    fn_search_path_ok BOOLEAN;
    trg_activo BOOLEAN;
BEGIN
    -- 7.1 Validar RLS habilitado en public.auditoria_autenticacion
    SELECT COALESCE(c.relrowsecurity, false)
    INTO rls_activo
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'auditoria_autenticacion';

    IF NOT rls_activo THEN
        RAISE EXCEPTION 'Postflight falló: Row Level Security (RLS) no está habilitado en public.auditoria_autenticacion.';
    END IF;

    -- Validar que exista exactamente una política en public.auditoria_autenticacion
    SELECT COUNT(*)
    INTO total_politicas
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'auditoria_autenticacion';

    IF total_politicas != 1 THEN
        RAISE EXCEPTION 'Postflight falló: Se esperaba exactamente 1 política total en public.auditoria_autenticacion, se encontraron %.', total_politicas;
    END IF;

    -- Validar que la única política sea exactamente la política SELECT administrativa oficial
    SELECT policyname, roles, cmd, qual
    INTO pol_rec
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'auditoria_autenticacion';

    IF pol_rec.policyname != 'Solo administradores pueden consultar auditoria' THEN
        RAISE EXCEPTION 'Postflight falló: La política existente se llama "%", se esperaba "Solo administradores pueden consultar auditoria".', pol_rec.policyname;
    END IF;

    IF pol_rec.cmd != 'SELECT' THEN
        RAISE EXCEPTION 'Postflight falló: El comando de la política es "%", se esperaba "SELECT".', pol_rec.cmd;
    END IF;

    IF NOT ('authenticated' = ANY(pol_rec.roles) AND array_length(pol_rec.roles, 1) = 1) THEN
        RAISE EXCEPTION 'Postflight falló: Los roles de la política son %, se esperaba exclusivamente {authenticated}.', pol_rec.roles;
    END IF;

    IF pol_rec.qual !~* 'auth\.uid\(\)'
       OR pol_rec.qual !~* 'perfiles_usuario'
       OR pol_rec.qual !~* 'es_admin\s*=\s*true'
       OR pol_rec.qual !~* 'activo\s*=\s*true' THEN
        RAISE EXCEPTION 'Postflight falló: La cláusula USING de la política no valida la condición de administrador activo (auth.uid, es_admin=true y activo=true): %', pol_rec.qual;
    END IF;

    -- 7.2 Validar NOT NULL en admin_id
    SELECT (is_nullable = 'NO')
    INTO is_not_null
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'auditoria_autenticacion'
      AND column_name = 'admin_id';

    IF NOT is_not_null THEN
        RAISE EXCEPTION 'Postflight falló: La columna admin_id debe ser NOT NULL.';
    END IF;

    -- 7.3 Validar exactamente una FK sobre admin_id, dirigida a auth.users(id) con ON DELETE RESTRICT
    SELECT COUNT(*)
    INTO total_fks_admin
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace tn ON t.relnamespace = tn.oid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
    WHERE tn.nspname = 'public'
      AND t.relname = 'auditoria_autenticacion'
      AND c.contype = 'f'
      AND a.attname = 'admin_id';

    IF total_fks_admin != 1 THEN
        RAISE EXCEPTION 'Postflight falló: Se esperaba exactamente 1 clave foránea en admin_id, se encontraron %.', total_fks_admin;
    END IF;

    SELECT COUNT(*)
    INTO fks_validas_admin
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace tn ON t.relnamespace = tn.oid
    JOIN pg_class ft ON c.confrelid = ft.oid
    JOIN pg_namespace ftn ON ft.relnamespace = ftn.oid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
    WHERE tn.nspname = 'public'
      AND t.relname = 'auditoria_autenticacion'
      AND c.contype = 'f'
      AND a.attname = 'admin_id'
      AND ftn.nspname = 'auth'
      AND ft.relname = 'users'
      AND c.confdeltype = 'r';

    IF fks_validas_admin != 1 THEN
        RAISE EXCEPTION 'Postflight falló: La clave foránea en admin_id debe referenciar auth.users(id) con ON DELETE RESTRICT.';
    END IF;

    -- 7.4 Validar que chk_auditoria_tipo_evento acepte exactamente los tres eventos oficiales y ningún valor extra
    SELECT pg_get_constraintdef(c.oid)
    INTO chk_def
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    JOIN pg_namespace tn ON t.relnamespace = tn.oid
    WHERE tn.nspname = 'public'
      AND t.relname = 'auditoria_autenticacion'
      AND c.conname = 'chk_auditoria_tipo_evento'
      AND c.contype = 'c';

    IF chk_def IS NULL THEN
        RAISE EXCEPTION 'Postflight falló: La restricción chk_auditoria_tipo_evento no está registrada.';
    END IF;

    IF chk_def NOT LIKE '%tipo_evento%' THEN
        RAISE EXCEPTION 'Postflight falló: chk_auditoria_tipo_evento no opera sobre la columna tipo_evento: %', chk_def;
    END IF;

    SELECT ARRAY_AGG(m[1] ORDER BY m[1])
    INTO literales_eventos
    FROM regexp_matches(chk_def, '''([^'']+)''', 'g') AS m;

    IF literales_eventos != ARRAY['cambio_password_primer_ingreso', 'reenvio_recuperacion', 'restablecimiento_manual_excepcional'] THEN
        RAISE EXCEPTION 'Postflight falló: chk_auditoria_tipo_evento debe aceptar exactamente los tres eventos oficiales y ningún valor extra. Encontrados: % (def: %)', literales_eventos, chk_def;
    END IF;

    -- 7.5 Validar función de inmutabilidad sin elevación de privilegios (prosecdef = false) y con SET search_path = ''
    SELECT COUNT(*),
           bool_or(p.prosecdef),
           bool_and(('search_path=' = ANY(p.proconfig)) OR (pg_get_functiondef(p.oid) LIKE '%search_path%'))
    INTO fn_count, is_secdef, fn_search_path_ok
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = 'proteger_inmutabilidad_auditoria';

    IF fn_count != 1 THEN
        RAISE EXCEPTION 'Postflight falló: Se esperaba exactamente 1 función public.proteger_inmutabilidad_auditoria(), se encontraron %.', fn_count;
    END IF;

    IF is_secdef IS TRUE THEN
        RAISE EXCEPTION 'Postflight falló: La función proteger_inmutabilidad_auditoria tiene prosecdef=true (debe ser sin elevación).';
    END IF;

    IF fn_search_path_ok IS NOT TRUE THEN
        RAISE EXCEPTION 'Postflight falló: La función proteger_inmutabilidad_auditoria debe conservar SET search_path = ''''.';
    END IF;

    -- 7.6 Validar trigger activo
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.triggers
        WHERE trigger_schema = 'public'
          AND event_object_table = 'auditoria_autenticacion'
          AND trigger_name = 'trg_proteger_inmutabilidad_auditoria'
    ) INTO trg_activo;

    IF NOT trg_activo THEN
        RAISE EXCEPTION 'Postflight falló: El trigger trg_proteger_inmutabilidad_auditoria no está registrado.';
    END IF;
END $$;

COMMIT;
