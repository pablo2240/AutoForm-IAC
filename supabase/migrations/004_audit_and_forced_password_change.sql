-- ==============================================================================
-- AUTOFORM AI — MIGRACIÓN 004: AUDITORÍA Y CAMBIO FORZADO DE CONTRASEÑAS
-- Archivo: supabase/migrations/004_audit_and_forced_password_change.sql
-- Control de Auditoría para Reenvíos y Restablecimiento Manual Excepcional
-- ==============================================================================

-- 1. Agregar columna de cambio forzado de contraseña a public.perfiles_usuario
ALTER TABLE public.perfiles_usuario 
ADD COLUMN IF NOT EXISTS debe_cambiar_password BOOLEAN NOT NULL DEFAULT false;

-- 2. Crear tabla de auditoría de autenticación y seguridad
CREATE TABLE IF NOT EXISTS public.auditoria_autenticacion (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo_evento TEXT NOT NULL, -- 'reenvio_recuperacion', 'restablecimiento_manual_excepcional', 'cambio_password_primer_ingreso'
    usuario_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    correo_objetivo TEXT NOT NULL,
    admin_id TEXT NOT NULL,
    admin_correo TEXT NOT NULL,
    motivo TEXT DEFAULT '',
    detalles TEXT DEFAULT '',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- 3. Índices para optimizar consultas de auditoría y rate limiting
CREATE INDEX IF NOT EXISTS idx_auditoria_correo_objetivo 
ON public.auditoria_autenticacion (correo_objetivo);

CREATE INDEX IF NOT EXISTS idx_auditoria_tipo_evento 
ON public.auditoria_autenticacion (tipo_evento, creado_en);

-- 4. Habilitar Row Level Security (RLS)
ALTER TABLE public.auditoria_autenticacion ENABLE ROW LEVEL SECURITY;

-- 5. Políticas de Acceso:
-- Solo administradores corporativos pueden consultar registros de auditoría
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

-- Inserción permitida a través del backend o roles autorizados
DROP POLICY IF EXISTS "Service role y administradores pueden insertar auditoria" ON public.auditoria_autenticacion;
CREATE POLICY "Service role y administradores pueden insertar auditoria"
ON public.auditoria_autenticacion
FOR INSERT
TO authenticated, service_role
WITH CHECK (true);
