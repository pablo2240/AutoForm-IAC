-- ADR-0016: persistencia de la biblioteca de referencias en Supabase.
-- Los formularios de referencia contienen datos reales y el repositorio es público: viven en un
-- bucket privado de Storage y su conocimiento extraído en una tabla con RLS.
-- Migración aditiva y reversible (no modifica tablas existentes).

-- 1. Bucket privado (los objetos se nombran por hash; el nombre real vive en el catálogo).
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('referencias', 'referencias', false, 20971520)
ON CONFLICT (id) DO NOTHING;

-- 2. Catálogo de referencias con el conocimiento extraído (instantánea JSONB).
CREATE TABLE IF NOT EXISTS public.referencias_catalogo (
    clave TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    familia TEXT NOT NULL DEFAULT '',
    hash_contenido TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL DEFAULT 0,
    ruta_storage TEXT NOT NULL,
    fuente TEXT NOT NULL DEFAULT 'referencia',
    confianza REAL NOT NULL DEFAULT 0.75,
    version_extractor TEXT NOT NULL DEFAULT '',
    huella_datos TEXT NOT NULL DEFAULT '',
    conocimiento JSONB NULL,
    tiene_conocimiento BOOLEAN GENERATED ALWAYS AS (conocimiento IS NOT NULL) STORED,
    subido_por UUID NULL REFERENCES public.perfiles_usuario(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT referencias_catalogo_clave_check CHECK (length(clave) BETWEEN 1 AND 400)
);

CREATE INDEX IF NOT EXISTS idx_referencias_catalogo_familia ON public.referencias_catalogo (familia);

CREATE OR REPLACE FUNCTION public.actualizar_referencias_catalogo_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trigger_referencias_catalogo_updated_at ON public.referencias_catalogo;
CREATE TRIGGER trigger_referencias_catalogo_updated_at
BEFORE UPDATE ON public.referencias_catalogo
FOR EACH ROW EXECUTE FUNCTION public.actualizar_referencias_catalogo_timestamp();

ALTER TABLE public.referencias_catalogo ENABLE ROW LEVEL SECURITY;

-- Lectura: cualquier usuario activo (el pipeline la usa en todas las sesiones).
DROP POLICY IF EXISTS "referencias_catalogo_select_activo" ON public.referencias_catalogo;
CREATE POLICY "referencias_catalogo_select_activo"
    ON public.referencias_catalogo FOR SELECT TO authenticated
    USING (public.is_active_user());

-- Escritura: solo administradores activos.
DROP POLICY IF EXISTS "referencias_catalogo_insert_admin" ON public.referencias_catalogo;
CREATE POLICY "referencias_catalogo_insert_admin"
    ON public.referencias_catalogo FOR INSERT TO authenticated
    WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS "referencias_catalogo_update_admin" ON public.referencias_catalogo;
CREATE POLICY "referencias_catalogo_update_admin"
    ON public.referencias_catalogo FOR UPDATE TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

DROP POLICY IF EXISTS "referencias_catalogo_delete_admin" ON public.referencias_catalogo;
CREATE POLICY "referencias_catalogo_delete_admin"
    ON public.referencias_catalogo FOR DELETE TO authenticated
    USING (public.is_admin());

-- 3. Objetos del bucket: lectura para usuarios activos, escritura solo para administradores.
DROP POLICY IF EXISTS "referencias_storage_select_activo" ON storage.objects;
CREATE POLICY "referencias_storage_select_activo"
    ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id = 'referencias' AND public.is_active_user());

DROP POLICY IF EXISTS "referencias_storage_insert_admin" ON storage.objects;
CREATE POLICY "referencias_storage_insert_admin"
    ON storage.objects FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'referencias' AND public.is_admin());

DROP POLICY IF EXISTS "referencias_storage_update_admin" ON storage.objects;
CREATE POLICY "referencias_storage_update_admin"
    ON storage.objects FOR UPDATE TO authenticated
    USING (bucket_id = 'referencias' AND public.is_admin())
    WITH CHECK (bucket_id = 'referencias' AND public.is_admin());

DROP POLICY IF EXISTS "referencias_storage_delete_admin" ON storage.objects;
CREATE POLICY "referencias_storage_delete_admin"
    ON storage.objects FOR DELETE TO authenticated
    USING (bucket_id = 'referencias' AND public.is_admin());
