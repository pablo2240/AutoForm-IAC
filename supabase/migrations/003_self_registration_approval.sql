-- ==============================================================================
-- AUTOFORM AI — MIGRACIÓN 003: AUTO-REGISTRO Y APROBACIÓN ADMINISTRATIVA
-- Archivo: supabase/migrations/003_self_registration_approval.sql
-- Modelo de Solicitudes Corporativas con Aprobación Centralizada
-- ==============================================================================

-- 1. Agregar columna de estado de aprobación a public.perfiles_usuario
ALTER TABLE public.perfiles_usuario 
ADD COLUMN IF NOT EXISTS estado_aprobacion TEXT NOT NULL DEFAULT 'aprobado';

-- 2. Asegurar restricción de estados válidos ('pendiente', 'aprobado', 'rechazado')
ALTER TABLE public.perfiles_usuario
DROP CONSTRAINT IF EXISTS check_estado_aprobacion;

ALTER TABLE public.perfiles_usuario
ADD CONSTRAINT check_estado_aprobacion 
CHECK (estado_aprobacion IN ('pendiente', 'aprobado', 'rechazado'));

-- 3. Modificar valor por defecto de 'activo' a false para nuevos registros
ALTER TABLE public.perfiles_usuario 
ALTER COLUMN activo SET DEFAULT false;

-- 4. Índice para optimizar consultas de solicitudes pendientes y directorio
CREATE INDEX IF NOT EXISTS idx_perfiles_usuario_estado
ON public.perfiles_usuario (estado_aprobacion, activo);
