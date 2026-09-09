# ADR 0008: User Authentication, Gatekeeper Shield & Role-Based Access Control

## Context
Following the implementation of the Operator Catalog (**ADR-0007**), AutoForm AI enabled dynamic persona diligence so that sales executives and administrators (e.g. Antonio Prieto) can populate commercial contact sections. However, the system lacked an authentication layer:
- Any visitor with network access to the Streamlit app could view all institutional data (NIT, bank accounts, balance sheets with $16B+ in assets, legal representative ID).
- Any visitor could freely edit or overwrite corporate records without auditing.
- Operator attribution relied solely on an unauthenticated dropdown in the sidebar.

A secure, zero-friction authentication and access control model was required, tailored for corporate intranet usage in Colombia (IAC Latam).

---

## Decisions

### 1. Canonical User Table with Cryptographic Hashing (`usuarios`)
A dedicated table is established in the canonical SQLite database (`config/empresa.db`):
```sql
CREATE TABLE IF NOT EXISTS usuarios (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    cargo TEXT,
    cedula TEXT,
    telefono TEXT,
    correo TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    es_admin INTEGER DEFAULT 0,
    activo INTEGER DEFAULT 1,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usuarios_correo ON usuarios(correo);
```

### 2. Native PBKDF2-HMAC-SHA256 Cryptography
To eliminate external binary compilation dependencies (`bcrypt`/`argon2`) that could fail across Windows environments and cloud runtimes:
- Passwords are salted with 16 bytes of cryptographically secure random bytes (`os.urandom(16)`).
- Derived via `hashlib.pbkdf2_hmac("sha256", password, salt, 100_000)`.
- Serialized as `salt_hex$hash_hex` with constant-time verification (`hmac.compare_digest`).

### 3. Corporate Domain Enforcement
Self-registration is restricted strictly to authorized corporate email domains:
```python
DOMINIOS_PERMITIDOS = {"iac.com.co", "iaclatam.com"}
```
Attempts to register outside these domains are rejected with a generic security notice without revealing domain whitelists.

### 4. Direct 1:1 Fusion with Operator Domain (ADR-0007 Reusability)
The authenticated user is directly mapped to the `OperadorActivo`:
- `responsable_nombre` = `usuario["nombre"]`
- `responsable_cargo` = `usuario["cargo"]`
- `responsable_cedula` = `usuario["cedula"]`
- `responsable_telefono` = `usuario["telefono"]`
- `responsable_correo` = `usuario["correo"]`

This completely eliminates operator dropdown manual selection and preserves 100% of the tested domain isolation and pipeline fusion mechanics.

### 5. Gatekeeper Shield UX
When `st.session_state.get("usuario_activo")` is unset:
- The entire sidebar, document previewer, and form uploader are completely blocked and hidden.
- A clean, centered Gatekeeper card is presented with "Iniciar Sesión" and "Registrarse" tabs styled with the official IAC palette.
- Once authenticated, the full app unlocks and displays an active session banner with `👤 [Nombre] | [Cargo] | 🚪 Cerrar Sesión`.

### 6. Role-Based Access Control (RBAC Foundation)
- `es_admin = 1`: Authorized to modify institutional company data (balances, banks, tax info) and manage user accounts.
- `es_admin = 0`: Standard commercial agent; has shared read-only access to corporate profiles for diligence and full access to upload and fill forms with their own commercial identity.

---

## Consequences

### Positive
- Total protection of corporate financial and legal representative data against unauthorized visitors.
- Automatic, friction-free attribution: whoever logs in is guaranteed to be the diligence operator on generated forms.
- Zero external package dependencies (pure standard library cryptography).
- Forward-compatible RBAC model without requiring future schema migrations.

### Negative
- Sessions are stored in Streamlit memory per browser tab; a hard browser refresh (F5) requires re-entering credentials (accepted as a security feature for sensitive banking/legal assets).
