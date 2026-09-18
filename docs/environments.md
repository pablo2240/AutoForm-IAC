# Matriz Canónica de Entornos Supabase

Este documento registra los proyectos de Supabase asignados a las aplicaciones de IAC Latam.

> **POLÍTICA DE SEGURIDAD ESTRICTA (ADR-0010):**
> Este archivo NO contiene llaves anon, llaves service_role ni contraseñas.
> Todo acceso programático debe realizarse mediante variables de entorno en runtime.

| Aplicación | Entorno | Project Reference | Host Database | Región | Estado |
|---|---|---|---|---|---|
| **AutoForm PDF** | Producción | 	nhedxwbpqihlqbtzudt | db.tnhedxwbpqihlqbtzudt.supabase.co | us-east-1 | Activo / Protegido |
| **AutoForm PDF** | Staging | 
fsijcwkmcvtwsponqsw | db.nfsijcwkmcvtwsponqsw.supabase.co | us-east-1 | Activo / Aislado |
| **AutoForm Excel** | Staging | <PENDIENTE_CREACION_REF> | db.<PENDIENTE_CREACION_REF>.supabase.co | us-east-1 | Pendiente de aprovisionamiento |

## Reglas de Aislamiento
1. **Separación de esquemas y proyectos:** AutoForm Excel y AutoForm PDF jamás deben compartir el mismo PROJECT_REF.
2. **Validación de Identidad:** AutoForm Excel verifica la tabla public.deployment_identity (pplication_code = 'autoform-excel') antes de cualquier migración o rollback.
3. **Allowlist estricta:** La variable de entorno AUTOFORM_EXCEL_STAGING_PROJECT_REF previene ejecuciones accidentales contra los proyectos de PDF.
