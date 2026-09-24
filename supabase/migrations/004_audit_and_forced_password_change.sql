-- ==============================================================================
-- AUTOFORM AI — MIGRACIÓN 004: AUDITORÍA INMUTABLE Y CAMBIO FORZADO DE CONTRASEÑA
-- Archivo: supabase/migrations/004_audit_and_forced_password_change.sql
-- Control de Auditoría Inmutable para Reenvíos y Restablecimiento Manual Excepcional
-- ==============================================================================

-- 1. Agregar columna de cambio forzado de contraseña a public.perfiles_usuario
ALTER TABLE public.perfiles_usuario 
ADD COLUMN IF NOT EXISTS debe_cambiar_password BOOLEAN NOT NULL DEFAULT false;

-- 2. Crear tabla de auditoría de autenticación y seguridad
-- admin_id es UUID con referencia de clave foránea a auth.users(id)
CREATE TABLE IF NOT EXISTS public.auditoria_autenticacion (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo_evento TEXT NOT NULL, -- 'reenvio_recuperacion', 'restablecimiento_manual_excepcional', 'cambio_password_primer_ingreso'
    usuario_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    correo_objetivo TEXT NOT NULL,
    admin_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    admin_correo TEXT NOT NULL,
    motivo TEXT DEFAULT '',
    detalles TEXT DEFAULT '',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Si la columna admin_id existiera previamente como TEXT, convertirla a UUID con FK
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
          AND table_name = 'auditoria_autenticacion' 
          AND column_name = 'admin_id' 
          AND data_type = 'text'
    ) THEN
        ALTER TABLE public.auditoria_autenticacion 
        ALTER COLUMN admin_id TYPE UUID USING (
            CASE 
                WHEN admin_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' 
                THEN admin_id::uuid 
                ELSE NULL 
            END
        );
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints 
            WHERE constraint_name = 'fk_auditoria_admin_id' 
              AND table_name = 'auditoria_autenticacion'
        ) THEN
            ALTER TABLE public.auditoria_autenticacion 
            ADD CONSTRAINT fk_auditoria_admin_id 
            FOREIGN KEY (admin_id) REFERENCES auth.users(id) ON DELETE SET NULL;
        END IF;
    END IF;
END $$;

-- 3. Índices para optimizar consultas de auditoría, FKs y rate limiting
CREATE INDEX IF NOT EXISTS idx_auditoria_correo_objetivo 
ON public.auditoria_autenticacion (correo_objetivo);

CREATE INDEX IF NOT EXISTS idx_auditoria_tipo_evento 
ON public.auditoria_autenticacion (tipo_evento, creado_en);

CREATE INDEX IF NOT EXISTS idx_auditoria_admin_id 
ON public.auditoria_autenticacion (admin_id);

CREATE INDEX IF NOT EXISTS idx_auditoria_usuario_id 
ON public.auditoria_autenticacion (usuario_id);

-- 4. Habilitar Row Level Security (RLS)
ALTER TABLE public.auditoria_autenticacion ENABLE ROW LEVEL SECURITY;

-- 5. Políticas de Acceso Estrictas:
-- a) SELECT: Solo administradores activos pueden consultar registros de auditoría
DROP POLICY IF EXISTS "Solo administradores pueden consultar auditoria" ON public.auditoria_autenticacion;
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

-- b) INSERT: Exclusivo para backend mediante service_role.
-- Ningún usuario 'authenticated' ni 'anon' tiene política de inserción.
DROP POLICY IF EXISTS "Service role y administradores pueden insertar auditoria" ON public.auditoria_autenticacion;
DROP POLICY IF EXISTS "Insercion exclusiva backend service_role" ON public.auditoria_autenticacion;
CREATE POLICY "Insercion exclusiva backend service_role"
ON public.auditoria_autenticacion
FOR INSERT
TO service_role
WITH CHECK (true);

-- c) UPDATE y DELETE: RLS deniega por defecto (sin políticas para authenticated ni anon).
DROP POLICY IF EXISTS "Prohibir update para authenticated" ON public.auditoria_autenticacion;
DROP POLICY IF EXISTS "Prohibir delete para authenticated" ON public.auditoria_autenticacion;

-- 6. Trigger de Inmutabilidad Estricta (Protección en motor de BD contra UPDATE y DELETE)
CREATE OR REPLACE FUNCTION public.proteger_inmutabilidad_auditoria()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Operación denegada: Los registros de public.auditoria_autenticacion son estrictamente inmutables (no se permite UPDATE).';
    ELSIF TG_OP = 'DELETE' THEN
        -- Protección contra DELETE: solo permitir purga higiénica de registros sintéticos de prueba
        -- invocados por service_role durante pruebas automatizadas de Staging
        IF (auth.role() = 'service_role' OR current_user = 'postgres') AND (OLD.correo_objetivo ILIKE 'synth.%') THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Operación denegada: Los registros de public.auditoria_autenticacion son inmutables (no se permite DELETE).';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_proteger_inmutabilidad_auditoria ON public.auditoria_autenticacion;
CREATE TRIGGER trg_proteger_inmutabilidad_auditoria
BEFORE UPDATE OR DELETE ON public.auditoria_autenticacion
FOR EACH ROW
EXECUTE FUNCTION public.proteger_inmutabilidad_auditoria();
