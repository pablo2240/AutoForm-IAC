-- ADR-0013: catálogo compartido de perfiles de diligenciamiento.
-- Esta migración es aditiva y no elimina perfiles existentes ni ejecuta despliegues.

ALTER TABLE public.perfiles_empresa
    ADD COLUMN IF NOT EXISTS tipo_perfil TEXT NOT NULL DEFAULT 'EMPRESA',
    ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'ACTIVO',
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS creado_por UUID NULL REFERENCES public.perfiles_usuario(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS actualizado_por UUID NULL REFERENCES public.perfiles_usuario(id) ON DELETE SET NULL;

ALTER TABLE public.perfiles_empresa
    DROP CONSTRAINT IF EXISTS perfiles_empresa_tipo_perfil_check,
    ADD CONSTRAINT perfiles_empresa_tipo_perfil_check
        CHECK (tipo_perfil IN ('PERSONA', 'EMPRESA', 'CONTRATISTA')),
    DROP CONSTRAINT IF EXISTS perfiles_empresa_estado_check,
    ADD CONSTRAINT perfiles_empresa_estado_check
        CHECK (estado IN ('ACTIVO', 'ARCHIVADO')),
    DROP CONSTRAINT IF EXISTS perfiles_empresa_version_check,
    ADD CONSTRAINT perfiles_empresa_version_check CHECK (version >= 1);

-- "es_activa" queda como compatibilidad histórica, pero deja de ser decisión global.
DROP INDEX IF EXISTS public.idx_un_perfil_activo;

CREATE TABLE IF NOT EXISTS public.preferencias_perfil_usuario (
    usuario_id UUID PRIMARY KEY REFERENCES public.perfiles_usuario(id) ON DELETE CASCADE,
    perfil_predeterminado_id UUID NULL REFERENCES public.perfiles_empresa(id) ON DELETE SET NULL,
    actualizado_por UUID NULL REFERENCES public.perfiles_usuario(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS public.auditoria_perfiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NULL REFERENCES public.perfiles_empresa(id) ON DELETE SET NULL,
    actor_id UUID NULL REFERENCES public.perfiles_usuario(id) ON DELETE SET NULL,
    operacion TEXT NOT NULL CHECK (operacion IN ('CREAR', 'ACTUALIZAR', 'ARCHIVAR', 'ELIMINAR')),
    version_anterior INTEGER NULL,
    version_nueva INTEGER NULL,
    resumen_cambios TEXT NOT NULL DEFAULT '',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_perfiles_empresa_estado_nombre
    ON public.perfiles_empresa (estado, nombre_empresa);
CREATE INDEX IF NOT EXISTS idx_auditoria_perfiles_profile_fecha
    ON public.auditoria_perfiles (profile_id, creado_en DESC);

-- Cada cuenta existente recibe una preferencia individual hacia el perfil principal
-- solamente cuando dicho perfil existe. No se altera ningún dato del perfil.
INSERT INTO public.preferencias_perfil_usuario
    (usuario_id, perfil_predeterminado_id, actualizado_por)
SELECT u.id, p.id, NULL
FROM public.perfiles_usuario u
CROSS JOIN public.perfiles_empresa p
WHERE u.activo = true AND p.slug = 'principal' AND p.estado = 'ACTIVO'
ON CONFLICT (usuario_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.proteger_catalogo_perfiles()
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
    jwt_role := COALESCE(auth.role(), (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role'), '');

    IF TG_OP = 'INSERT' THEN
        IF NOT caller_is_admin AND jwt_role <> 'service_role' THEN
            IF NEW.creado_por IS DISTINCT FROM auth.uid() OR NEW.actualizado_por IS DISTINCT FROM auth.uid() THEN
                RAISE EXCEPTION 'El actor creador del perfil debe corresponder a la sesión autenticada.';
            END IF;
            IF NEW.estado <> 'ACTIVO' THEN
                RAISE EXCEPTION 'Solo un administrador puede crear un perfil archivado.';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    IF NOT caller_is_admin AND jwt_role <> 'service_role' THEN
        IF NEW.creado_por IS DISTINCT FROM OLD.creado_por THEN
            RAISE EXCEPTION 'El creador del perfil es inmutable.';
        END IF;
        IF NEW.estado IS DISTINCT FROM OLD.estado THEN
            RAISE EXCEPTION 'Solo un administrador puede archivar o reactivar perfiles.';
        END IF;
        IF NEW.actualizado_por IS DISTINCT FROM auth.uid() THEN
            RAISE EXCEPTION 'El editor del perfil debe corresponder a la sesión autenticada.';
        END IF;
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'La versión del perfil debe incrementarse exactamente en una unidad.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.auditar_catalogo_perfiles()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO public.auditoria_perfiles (profile_id, actor_id, operacion, version_nueva, resumen_cambios)
        VALUES (NEW.id, NEW.actualizado_por, 'CREAR', NEW.version, 'Perfil creado');
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO public.auditoria_perfiles (profile_id, actor_id, operacion, version_anterior, version_nueva, resumen_cambios)
        VALUES (
            NEW.id,
            NEW.actualizado_por,
            CASE WHEN NEW.estado = 'ARCHIVADO' AND OLD.estado = 'ACTIVO' THEN 'ARCHIVAR' ELSE 'ACTUALIZAR' END,
            OLD.version,
            NEW.version,
            CASE WHEN NEW.estado = 'ARCHIVADO' AND OLD.estado = 'ACTIVO' THEN 'Perfil archivado' ELSE 'Datos fijos actualizados' END
        );
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trigger_proteger_catalogo_perfiles ON public.perfiles_empresa;
CREATE TRIGGER trigger_proteger_catalogo_perfiles
BEFORE INSERT OR UPDATE ON public.perfiles_empresa
FOR EACH ROW EXECUTE FUNCTION public.proteger_catalogo_perfiles();

DROP TRIGGER IF EXISTS trigger_auditar_catalogo_perfiles ON public.perfiles_empresa;
CREATE TRIGGER trigger_auditar_catalogo_perfiles
AFTER INSERT OR UPDATE ON public.perfiles_empresa
FOR EACH ROW EXECUTE FUNCTION public.auditar_catalogo_perfiles();

CREATE OR REPLACE FUNCTION public.actualizar_preferencia_perfil_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trigger_preferencias_perfil_updated_at ON public.preferencias_perfil_usuario;
CREATE TRIGGER trigger_preferencias_perfil_updated_at
BEFORE UPDATE ON public.preferencias_perfil_usuario
FOR EACH ROW EXECUTE FUNCTION public.actualizar_preferencia_perfil_timestamp();

ALTER TABLE public.preferencias_perfil_usuario ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auditoria_perfiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "perfiles_empresa_admin_modificar" ON public.perfiles_empresa;
DROP POLICY IF EXISTS "perfiles_empresa_insert_activo" ON public.perfiles_empresa;
CREATE POLICY "perfiles_empresa_insert_activo"
    ON public.perfiles_empresa FOR INSERT TO authenticated
    WITH CHECK (public.is_active_user() AND creado_por = auth.uid() AND actualizado_por = auth.uid() AND estado = 'ACTIVO');

DROP POLICY IF EXISTS "perfiles_empresa_update_activo" ON public.perfiles_empresa;
CREATE POLICY "perfiles_empresa_update_activo"
    ON public.perfiles_empresa FOR UPDATE TO authenticated
    USING (public.is_active_user())
    WITH CHECK (public.is_active_user() AND actualizado_por = auth.uid());

DROP POLICY IF EXISTS "perfiles_empresa_delete_admin" ON public.perfiles_empresa;
CREATE POLICY "perfiles_empresa_delete_admin"
    ON public.perfiles_empresa FOR DELETE TO authenticated
    USING (public.is_admin());

DROP POLICY IF EXISTS "preferencias_perfil_select_propietario" ON public.preferencias_perfil_usuario;
CREATE POLICY "preferencias_perfil_select_propietario"
    ON public.preferencias_perfil_usuario FOR SELECT TO authenticated
    USING ((usuario_id = auth.uid() AND public.is_active_user()) OR public.is_admin());

DROP POLICY IF EXISTS "preferencias_perfil_insert_propietario" ON public.preferencias_perfil_usuario;
CREATE POLICY "preferencias_perfil_insert_propietario"
    ON public.preferencias_perfil_usuario FOR INSERT TO authenticated
    WITH CHECK (usuario_id = auth.uid() AND actualizado_por = auth.uid() AND public.is_active_user());

DROP POLICY IF EXISTS "preferencias_perfil_update_propietario" ON public.preferencias_perfil_usuario;
CREATE POLICY "preferencias_perfil_update_propietario"
    ON public.preferencias_perfil_usuario FOR UPDATE TO authenticated
    USING (usuario_id = auth.uid() AND public.is_active_user())
    WITH CHECK (usuario_id = auth.uid() AND actualizado_por = auth.uid() AND public.is_active_user());

DROP POLICY IF EXISTS "auditoria_perfiles_select_admin" ON public.auditoria_perfiles;
CREATE POLICY "auditoria_perfiles_select_admin"
    ON public.auditoria_perfiles FOR SELECT TO authenticated
    USING (public.is_admin());

-- Las inserciones de auditoría sólo se producen mediante trigger SECURITY DEFINER.
