-- ==============================================================================
-- AUTOFORM AI — IDENTIDAD DE DESPLIEGUE STAGING (ADR-0010)
-- Archivo: supabase/migrations/002_staging_deployment_identity.sql
-- Inserción única e inmutable de la identidad canónica de AutoForm Excel Staging.
-- ==============================================================================

INSERT INTO public.deployment_identity (
    singleton_id,
    application_code,
    environment,
    project_ref
)
VALUES (
    1,
    'autoform-excel',
    'staging',
    'nfaxkncrpfrsvzfgczny'
);
