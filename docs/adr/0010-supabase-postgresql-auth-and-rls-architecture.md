# ADR 0010: Supabase PostgreSQL, Authentication and Row Level Security Architecture

## Context
AutoForm AI was originally built with SQLite (`config/empresa.db`) as its canonical single source of truth (**ADR-0008**). While SQLite provided zero-latency local operations and simple transactions, production deployment at IAC Latam across multiple cloud containers and commercial agents introduced operational limitations:
1. Concurrency locks and ephemeral filesystem restarts in containerized cloud environments (e.g. Streamlit Community Cloud, Azure App Services) could cause data divergence or file locking.
2. User management relied on local PBKDF2 hashes in SQLite without central session management, enterprise password recovery, or official email verification.
3. Access control at the database layer was non-existent; all connected processes had unrestricted read/write access to SQLite.

To scale the platform securely, IAC Latam decided to migrate canonical data storage and user authentication to **Supabase** (managed PostgreSQL with built-in Supabase Auth and Row Level Security). SQLite is retained strictly as a transition and local development fallback (`APP_ENVIRONMENT=development`).

---

## Decisions

### 1. Hybrid Relational + JSONB Schema for `perfiles_empresa` (Q1)
Rather than flattening 40+ nested tax, legal, and financial attributes into hundreds of sparse columns, `perfiles_empresa` adopts a hybrid schema:
- **Relational Columns**: Key identifiers and query fields required for business rules and indexing:
  - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
  - `slug TEXT UNIQUE NOT NULL` (e.g., `'principal'`)
  - `nombre_empresa TEXT NOT NULL`
  - `nit TEXT UNIQUE`
  - `es_activa BOOLEAN DEFAULT false NOT NULL`
  - `created_at TIMESTAMPTZ` / `updated_at TIMESTAMPTZ`
- **JSONB Document Storage**:
  - `datos_json JSONB NOT NULL` housing the full 3-level taxonomy (`empresa`, `representante_legal`, `financiero`).
  - GIN indexing: `CREATE INDEX idx_perfiles_empresa_datos_json ON perfiles_empresa USING GIN (datos_json);`.
  - Partial Unique Index guaranteeing strictly one active profile:
    `CREATE UNIQUE INDEX idx_un_perfil_activo ON perfiles_empresa (es_activa) WHERE es_activa = true;`.
  - **Single-Tenant Invariant Justification**: In AutoForm AI's enterprise model, each deployment instance represents a single corporate entity (IAC Latam). While multiple profiles may exist for history, audit, or secondary branches, exactly ONE profile must be designated as active at any given moment (`es_activa = true`). This invariant ensures deterministic, unambiguous resolution of company data during automated spreadsheet filling pipelines.

### 2. Official Python Client (`supabase-py`) and Versioned Migrations (Q2)
- Application runtime connects via `supabase-py` (`supabase>=2.0.0`), utilizing PostgREST and Gotrue client interfaces.
- Schemas and DDL are versioned as standard SQL in `supabase/migrations/001_initial_schema.sql` and applied via Supabase CLI or SQL Editor.
- The SQLite-to-Supabase migration script uses `supabase-py` with administrative service role privileges under strict confirmation guards.

### 3. Strict 3-Client Architecture & Fail-Closed Session Quarantine (Q3 / C-01)
To ensure zero privilege leakage in Streamlit's multi-threaded model:
1. `obtener_cliente_publico()`:
   - Initialized with `SUPABASE_ANON_KEY` without session tokens.
   - Restricted strictly to unauthenticated auth entrypoints (login, password reset).
   - RLS strictly rejects queries to protected data tables (`perfiles_empresa`, `operadores`, `perfiles_usuario`).
2. `obtener_cliente_usuario(access_token, refresh_token)`:
   - Instantiated ephemerally per user session with the user's JWT tokens (`client.auth.set_session(access_token, refresh_token)`).
   - Scoped strictly to Row Level Security (RLS) policies.
   - Never cached globally across users in memory.
3. `obtener_cliente_admin()`:
   - Utilizes `SUPABASE_SERVICE_ROLE_KEY`.
   - Quarantined strictly to server-side migration scripts, data seeding, and administrator-triggered email invitations.
   - Never exposed to the frontend, browser, UI components, or client error messages.
   - **Zero Automatic Fallback**: `_obtener_cliente_activo()` never returns the admin client implicitly.
   - In production (`APP_ENVIRONMENT=production`), unauthenticated requests to protected data raise `SesionNoAutenticadaError` (Fail-Closed).
4. Streamlit Session Quarantine & Lifecycle (A-02 / A-03):
   - `st.session_state` stores minimal tokens: `access_token`, `refresh_token`, `expires_at`, `id`, and verified profile data.
   - **Token Refresh**: When `expires_at - 300 <= now` (5 minutes before expiration), the session is atomically refreshed via Gotrue `refresh_session()`. If refresh fails, the session is purged immediately.
   - **Inactive Account Eviction**: On each rerun, if the user account is marked `activo = false` or deleted from `perfiles_usuario`, the session is terminated and redirected to Gatekeeper.
   - Logout invokes `supabase.auth.sign_out()`, purges all session keys, and forces a clean application rerun.

### 4. Fail-Closed Production Stance (Q4)
- When `APP_ENVIRONMENT=production`:
  - Supabase is the sole, mandatory Single Source of Truth.
  - If `SUPABASE_URL` or `SUPABASE_ANON_KEY` are missing, or if Supabase is unreachable, the application stops cleanly (`st.stop()`) and presents a secure, user-friendly error message.
  - **No silent or automatic fallback to SQLite is permitted in production.**
- When `APP_ENVIRONMENT=development`:
  - Local SQLite (`config/empresa.db`) is explicitly permitted for offline development when `USE_SQLITE=true`.

### 5. Official Supabase Email Invitations & Safe Migration Protocol (Q5 / M-01 / M-02 / M-03 / M-04)
- Public autonomous registration is permanently disabled.
- Existing and new corporate accounts are provisioned via official Supabase email invitations (`auth.admin.invite_user_by_email`).
- Each user establishes their own password via Supabase's secure token exchange. No PBKDF2 password hashes are migrated or shared.
- Migration scripts and logs are strictly forbidden from outputting recovery links, temporary passwords, or tokens.
- **Safe Execution Protocol (`migrate_sqlite_to_supabase.py`)**:
  - Deprecation and permanent rejection of the unsafe `--live` flag.
  - Mandatory `--execute --confirm-project <project_ref>` requiring exact match with `SUPABASE_URL`.
  - Batch UUID tracking registered into PostgreSQL audit table `public.migration_runs`.
  - Granular selective rollback via `--rollback-batch <batch_id>`.
  - PII masking: all console reports mask emails (e.g. `a***o@iaclatam.com`).
  - Test persona exclusion: `pepito_perez` is strictly excluded from Supabase migration.
  - Invitation holding: by default, user invitations remain held and require explicit authorization via `--enviar-invitaciones`.

### 6. Three-Layer Corporate Domain Whitelisting (Q6)
User email addresses are restricted strictly to authorized corporate domains:
- `@iaclatam.com`
- `@iac.com.co`
Canonical Regular Expression:
```regex
^[^@\s]+@(iaclatam\.com|iac\.com\.co)$
```
Enforced across 3 independent defense layers:
1. **Frontend**: Streamlit UI form validation before submission.
2. **Backend**: Python `core/auth_manager.validar_dominio_corporativo()`.
3. **Database**: PostgreSQL trigger on `auth.users` and check constraint on `public.perfiles_usuario` to block unauthorized signups via external SDKs.

---

## Consequences

### Positive
- Enterprise-grade ACID persistence in PostgreSQL with automatic cloud backups.
- Centralized user identity, password resets, and session lifecycle managed by Supabase Auth.
- Defense-in-depth security via Row Level Security (RLS) ensuring commercial agents only access authorized resources.
- Immutable corporate profile protection: standard users can read profiles for form diligence, but only administrators (`public.is_admin()`) can modify institutional data.
- Zero credential leakage during migration.

### Negative
- Requires valid network connectivity to Supabase in production mode.
- Initial user transition requires all operators to accept their Supabase email invitation to establish their production password.
