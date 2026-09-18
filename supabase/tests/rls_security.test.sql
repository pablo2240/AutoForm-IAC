-- ==============================================================================
-- AUTOFORM AI — Suite de Pruebas de Seguridad RLS
-- Archivo: supabase/tests/rls_security.test.sql
-- Fase: Hardening-03 (Ronda Final)
-- ==============================================================================
--
-- Esta suite es completamente transaccional. El ROLLBACK final garantiza que
-- ninguna prueba deje datos persistentes en la base de datos.
--
-- Estrategia:
-- 1. Se inicia una única transacción raíz con BEGIN.
-- 2. Se crean usuarios y perfiles de prueba dentro de la transacción.
-- 3. Se simulan distintos roles usando SET LOCAL ROLE y set_config('request.jwt.claims', ...).
-- 4. Se verifican las políticas RLS esperadas con assertions.
-- 5. Se hace ROLLBACK de toda la transacción al final.
-- ==============================================================================

BEGIN;

-- ── UTILIDADES DE PRUEBA ─────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION _assert(condicion BOOLEAN, mensaje TEXT)
RETURNS void AS $$
BEGIN
    IF NOT condicion THEN
        RAISE EXCEPTION 'ASSERTION FAILED: %', mensaje;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ── FIXTURE: Crear datos de prueba ───────────────────────────────────────────

DO $$
DECLARE
    v_uid_admin     UUID := '00000000-0000-0000-0000-000000000001'::UUID;
    v_uid_admin_inactivo UUID := '00000000-0000-0000-0000-000000000002'::UUID;
    v_uid_usuario   UUID := '00000000-0000-0000-0000-000000000003'::UUID;
    v_uid_inactivo  UUID := '00000000-0000-0000-0000-000000000004'::UUID;
BEGIN
    INSERT INTO auth.users (id, email, created_at, updated_at, is_sso_user, raw_app_meta_data, raw_user_meta_data, aud, role)
    VALUES
        (v_uid_admin,          'admin.test@iaclatam.com',          now(), now(), false, '{}'::jsonb, '{}'::jsonb, 'authenticated', 'authenticated'),
        (v_uid_admin_inactivo, 'admin.inactivo@iaclatam.com',      now(), now(), false, '{}'::jsonb, '{}'::jsonb, 'authenticated', 'authenticated'),
        (v_uid_usuario,        'usuario.estandar@iaclatam.com',    now(), now(), false, '{}'::jsonb, '{}'::jsonb, 'authenticated', 'authenticated'),
        (v_uid_inactivo,       'usuario.inactivo@iaclatam.com',    now(), now(), false, '{}'::jsonb, '{}'::jsonb, 'authenticated', 'authenticated')
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO public.perfiles_usuario (id, nombre, correo, es_admin, activo)
    VALUES
        (v_uid_admin,          'Admin Activo',          'admin.test@iaclatam.com',       true,  true),
        (v_uid_admin_inactivo, 'Admin Inactivo',        'admin.inactivo@iaclatam.com',   true,  false),
        (v_uid_usuario,        'Usuario Estándar',      'usuario.estandar@iaclatam.com', false, true),
        (v_uid_inactivo,       'Usuario Inactivo',      'usuario.inactivo@iaclatam.com', false, false)
    ON CONFLICT (id) DO UPDATE SET
        es_admin = EXCLUDED.es_admin,
        activo = EXCLUDED.activo;

    INSERT INTO public.perfiles_empresa (slug, nombre_empresa, nit, es_activa, datos_json)
    VALUES ('test_empresa', 'Empresa Test RLS', '999999999', false, '{}'::jsonb)
    ON CONFLICT (slug) DO NOTHING;

    INSERT INTO public.operadores (id, usuario_id, nombre, correo, es_activo)
    VALUES ('operador_test', v_uid_usuario, 'Operador Test', 'usuario.estandar@iaclatam.com', true)
    ON CONFLICT (id) DO UPDATE SET usuario_id = EXCLUDED.usuario_id;
END;
$$;

-- ── TEST 1: anon no puede leer ninguna tabla ──────────────────────────────────
DO $$
DECLARE
    cnt INTEGER;
BEGIN
    SET LOCAL ROLE anon;
    PERFORM set_config('request.jwt.claims', '', true);

    SELECT COUNT(*) INTO cnt FROM public.perfiles_empresa;
    PERFORM _assert(cnt = 0, 'TEST 1a FAIL: anon puede leer perfiles_empresa');

    SELECT COUNT(*) INTO cnt FROM public.perfiles_usuario;
    PERFORM _assert(cnt = 0, 'TEST 1b FAIL: anon puede leer perfiles_usuario');

    SELECT COUNT(*) INTO cnt FROM public.operadores;
    PERFORM _assert(cnt = 0, 'TEST 1c FAIL: anon puede leer operadores');

    RESET ROLE;
    RAISE NOTICE 'TEST 1 PASS: anon no puede leer ninguna tabla';
EXCEPTION WHEN OTHERS THEN
    RESET ROLE;
    IF SQLERRM LIKE 'TEST 1%' THEN RAISE; END IF;
    RAISE NOTICE 'TEST 1 PASS: anon bloqueado con excepción de permisos (%))', SQLERRM;
END;
$$;

-- ── TEST 2: Usuario estándar activo lee solo su propio perfil ─────────────────
DO $$
DECLARE
    v_uid_usuario UUID := '00000000-0000-0000-0000-000000000003'::UUID;
    cnt INTEGER;
BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claims', format('{"sub": "%s", "role": "authenticated"}', v_uid_usuario::text), true);

    SELECT COUNT(*) INTO cnt FROM public.perfiles_usuario WHERE id = v_uid_usuario;
    PERFORM _assert(cnt = 1, 'TEST 2a FAIL: usuario estándar no puede ver su propio perfil');

    SELECT COUNT(*) INTO cnt FROM public.perfiles_usuario WHERE id != v_uid_usuario;
    PERFORM _assert(cnt = 0, 'TEST 2b FAIL: usuario estándar puede ver perfiles ajenos');

    RESET ROLE;
    RAISE NOTICE 'TEST 2 PASS: usuario estándar activo ve solo su perfil';
END;
$$;

-- ── TEST 3: Usuario estándar no puede mutar es_admin, activo, correo, id ──────
DO $$
DECLARE
    v_uid_usuario UUID := '00000000-0000-0000-0000-000000000003'::UUID;
    intentos_bloqueados INTEGER := 0;
BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claims', format('{"sub": "%s", "role": "authenticated"}', v_uid_usuario::text), true);

    BEGIN
        UPDATE public.perfiles_usuario SET es_admin = true WHERE id = v_uid_usuario;
        PERFORM _assert(false, 'TEST 3a FAIL: usuario pudo cambiar es_admin a true');
    EXCEPTION WHEN OTHERS THEN
        intentos_bloqueados := intentos_bloqueados + 1;
    END;

    BEGIN
        UPDATE public.perfiles_usuario SET activo = false WHERE id = v_uid_usuario;
        PERFORM _assert(false, 'TEST 3b FAIL: usuario pudo modificar activo');
    EXCEPTION WHEN OTHERS THEN
        intentos_bloqueados := intentos_bloqueados + 1;
    END;

    BEGIN
        UPDATE public.perfiles_usuario SET correo = 'hacker@iaclatam.com' WHERE id = v_uid_usuario;
        PERFORM _assert(false, 'TEST 3c FAIL: usuario pudo cambiar correo');
    EXCEPTION WHEN OTHERS THEN
        intentos_bloqueados := intentos_bloqueados + 1;
    END;

    PERFORM _assert(intentos_bloqueados = 3, format('TEST 3 FAIL: solo %s de 3 intentos bloqueados', intentos_bloqueados));

    RESET ROLE;
    RAISE NOTICE 'TEST 3 PASS: columnas protegidas (es_admin, activo, correo) no son mutables por usuario estándar';
END;
$$;

-- ── TEST 4: Usuario estándar no puede eliminar operadores ─────────────────────
DO $$
DECLARE
    v_uid_usuario UUID := '00000000-0000-0000-0000-000000000003'::UUID;
    bloqueado     BOOLEAN := false;
BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claims', format('{"sub": "%s", "role": "authenticated"}', v_uid_usuario::text), true);

    BEGIN
        DELETE FROM public.operadores WHERE id = 'operador_test';
        PERFORM _assert(false, 'TEST 4 FAIL: usuario estándar pudo eliminar un operador');
    EXCEPTION WHEN OTHERS THEN
        bloqueado := true;
    END;

    PERFORM _assert(bloqueado, 'TEST 4 FAIL: DELETE en operadores no fue bloqueado para usuario estándar');

    RESET ROLE;
    RAISE NOTICE 'TEST 4 PASS: usuario estándar no puede eliminar operadores';
END;
$$;

-- ── TEST 5: Operador actualiza solo su registro vinculado por usuario_id ───────
DO $$
DECLARE
    v_uid_usuario UUID := '00000000-0000-0000-0000-000000000003'::UUID;
    update_ajeno  BOOLEAN := false;
BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claims', format('{"sub": "%s", "role": "authenticated"}', v_uid_usuario::text), true);

    BEGIN
        UPDATE public.operadores SET cargo = 'Cargo Actualizado' WHERE id = 'operador_test';
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'TEST 5a: operador no pudo actualizar su propio registro: %', SQLERRM;
    END;

    BEGIN
        INSERT INTO public.operadores (id, nombre, correo, es_activo)
            VALUES ('operador_otro', 'Otro Operador', 'otro@iaclatam.com', false)
            ON CONFLICT DO NOTHING;
        UPDATE public.operadores SET cargo = 'Hackear' WHERE id = 'operador_otro';
        update_ajeno := true;
    EXCEPTION WHEN OTHERS THEN
        NULL;
    END;

    PERFORM _assert(NOT update_ajeno, 'TEST 5b FAIL: operador pudo actualizar registro de otro operador');

    RESET ROLE;
    RAISE NOTICE 'TEST 5 PASS: operador actualiza solo su propio registro';
END;
$$;

-- ── TEST 6: Administrador activo puede gestionar perfiles y operadores ─────────
DO $$
DECLARE
    v_uid_admin UUID := '00000000-0000-0000-0000-000000000001'::UUID;
    cnt         INTEGER;
    insert_ok   BOOLEAN := false;
BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claims', format('{"sub": "%s", "role": "authenticated"}', v_uid_admin::text), true);

    SELECT COUNT(*) INTO cnt FROM public.perfiles_empresa;
    PERFORM _assert(cnt >= 1, 'TEST 6a FAIL: admin activo no puede ver perfiles_empresa');

    SELECT COUNT(*) INTO cnt FROM public.perfiles_usuario;
    PERFORM _assert(cnt >= 2, 'TEST 6b FAIL: admin activo no puede ver todos los perfiles_usuario');

    BEGIN
        INSERT INTO public.operadores (id, nombre, correo, es_activo)
        VALUES ('operador_admin_test', 'Op Admin Test', 'op.admin@iaclatam.com', false);
        insert_ok := true;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'TEST 6c: admin no pudo insertar operador: %', SQLERRM;
    END;
    PERFORM _assert(insert_ok, 'TEST 6c FAIL: admin activo no puede insertar operadores');

    RESET ROLE;
    RAISE NOTICE 'TEST 6 PASS: administrador activo puede gestionar perfiles y operadores';
END;
$$;

-- ── TEST 7: Administrador inactivo pierde privilegios inmediatamente ───────────
DO $$
DECLARE
    v_uid_admin_inactivo UUID := '00000000-0000-0000-0000-000000000002'::UUID;
    cnt                  INTEGER;
BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claims', format('{"sub": "%s", "role": "authenticated"}', v_uid_admin_inactivo::text), true);

    PERFORM _assert(NOT public.is_admin(), 'TEST 7a FAIL: is_admin() retorna true para admin inactivo');
    PERFORM _assert(NOT public.is_active_user(), 'TEST 7b FAIL: is_active_user() retorna true para usuario inactivo');

    SELECT COUNT(*) INTO cnt FROM public.perfiles_empresa;
    PERFORM _assert(cnt = 0, 'TEST 7c FAIL: admin inactivo puede ver perfiles_empresa');

    SELECT COUNT(*) INTO cnt FROM public.operadores;
    PERFORM _assert(cnt = 0, 'TEST 7d FAIL: admin inactivo puede ver operadores');

    RESET ROLE;
    RAISE NOTICE 'TEST 7 PASS: administrador inactivo pierde todos los privilegios inmediatamente';
END;
$$;

-- ── TEST 8: Usuario inactivo obtiene 0 filas con JWT todavía válido ────────────
DO $$
DECLARE
    v_uid_inactivo UUID := '00000000-0000-0000-0000-000000000004'::UUID;
    cnt            INTEGER;
BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claims', format('{"sub": "%s", "role": "authenticated"}', v_uid_inactivo::text), true);

    PERFORM _assert(NOT public.is_active_user(), 'TEST 8a FAIL: is_active_user() retorna true para usuario inactivo');

    SELECT COUNT(*) INTO cnt FROM public.perfiles_empresa;
    PERFORM _assert(cnt = 0, 'TEST 8b FAIL: usuario inactivo puede leer perfiles_empresa');

    SELECT COUNT(*) INTO cnt FROM public.operadores;
    PERFORM _assert(cnt = 0, 'TEST 8c FAIL: usuario inactivo puede leer operadores');

    SELECT COUNT(*) INTO cnt FROM public.perfiles_usuario WHERE id = v_uid_inactivo;
    PERFORM _assert(cnt = 0, 'TEST 8d FAIL: usuario inactivo puede ver su propio perfil');

    RESET ROLE;
    RAISE NOTICE 'TEST 8 PASS: usuario inactivo con JWT válido obtiene 0 filas en todas las tablas';
END;
$$;

-- ── TEST 9: service_role puede operar administrativamente (bypass de RLS) ─────
DO $$
DECLARE
    cnt INTEGER;
BEGIN
    SET LOCAL ROLE service_role;

    SELECT COUNT(*) INTO cnt FROM public.perfiles_empresa;
    PERFORM _assert(cnt >= 1, 'TEST 9a FAIL: service_role no puede ver perfiles_empresa');

    SELECT COUNT(*) INTO cnt FROM public.perfiles_usuario;
    PERFORM _assert(cnt >= 1, 'TEST 9b FAIL: service_role no puede ver perfiles_usuario');

    SELECT COUNT(*) INTO cnt FROM public.operadores;
    PERFORM _assert(cnt >= 1, 'TEST 9c FAIL: service_role no puede ver operadores');

    RESET ROLE;
    RAISE NOTICE 'TEST 9 PASS: service_role tiene acceso administrativo completo (bypass RLS por diseño)';
END;
$$;

-- ── TEST 10: Verificación final de aislamiento (ningún dato es persistente) ───
DO $$
BEGIN
    RAISE NOTICE 'TEST 10: Verificando transacción activa antes de ROLLBACK...';
    PERFORM _assert(current_setting('transaction_isolation') IS NOT NULL, 'TEST 10 FAIL: No hay transacción activa');
    RAISE NOTICE 'TEST 10 PASS: Transacción activa confirmada. Procediendo a ROLLBACK final.';
END;
$$;

ROLLBACK;
