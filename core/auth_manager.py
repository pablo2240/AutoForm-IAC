"""Módulo de autenticación corporativa y seguridad (ADR-0008 / ADR-0010).

Provee:
1. Validación estricta de dominios corporativos autorizados (@iaclatam.com, @iac.com.co) en 3 capas.
2. Integración con Supabase Auth (inicio de sesión, invitaciones oficiales por correo y cierre de sesión).
3. Hashing criptográfico PBKDF2-HMAC-SHA256 como fallback para desarrollo local en SQLite.

Hardening-01 (Ronda Final):
- invitar_usuario_corporativo() requiere el access_token real del solicitante.
- La autorización de admin se verifica contra public.perfiles_usuario con JWT activo.
- Se eliminó el parámetro solicitante_es_admin (booleano de interfaz) — no confiable.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any, Dict, Optional, Set, Tuple

# Expresión regular canónica aprobada (ADR-0010 / Q6)
DOMINIO_REGEX = re.compile(r"^[^@\s]+@(iaclatam\.com|iac\.com\.co)$", re.IGNORECASE)

DOMINIOS_PERMITIDOS: Set[str] = {
    "iac.com.co",
    "iaclatam.com",
}

# Administrador corporativo nominal responsable de AutoForm Excel
ADMIN_CORPORATIVO_NOMINAL = "guillermo.canon@iaclatam.com"


def validar_dominio_corporativo(correo: str) -> bool:
    """Verifica si el correo pertenece exactamente a uno de los dominios corporativos autorizados (Q6).

    Acepta exclusivamente:
    - @iaclatam.com
    - @iac.com.co

    Args:
        correo: Dirección de correo electrónico a validar.

    Returns:
        True si coincide con la expresión regular canónica, False en caso contrario.
    """
    if not correo:
        return False
    return bool(DOMINIO_REGEX.match(correo.strip()))


def validar_formato_correo(correo: str) -> bool:
    """Valida la sintaxis general de una dirección de correo electrónico."""
    patron = r"^[\w\.\+\-]+@[\w\-]+(\.[\w\-]+)+$"
    return bool(re.match(patron, (correo or "").strip()))


def hashear_password(password: str) -> str:
    """Genera un hash seguro de la contraseña usando PBKDF2-HMAC-SHA256 con salt aleatorio (Modo Local).

    Args:
        password: Texto plano de la contraseña.

    Returns:
        String en formato 'salt_hex$hash_hex'.
    """
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")
    salt = os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}${hash_bytes.hex()}"


def verificar_password(password: str, hash_almacenado: str) -> bool:
    """Verifica si la contraseña coincide con el hash almacenado en tiempo constante (Modo Local)."""
    if not password or not hash_almacenado or "$" not in hash_almacenado:
        return False
    try:
        salt_hex, hash_hex = hash_almacenado.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        hash_esperado = bytes.fromhex(hash_hex)
        hash_calculado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(hash_calculado, hash_esperado)
    except Exception:
        return False


def iniciar_sesion(
    correo: str,
    password: str,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """Inicia sesión validando credenciales contra el almacén de identidad configurado.

    Returns:
        Tuple[exito, datos_usuario, tokens_sesion, mensaje]
    """
    correo_limpio = correo.strip().lower()
    if not correo_limpio or not password:
        return False, None, None, "Ingresa tu correo y contraseña corporativa."

    if not validar_dominio_corporativo(correo_limpio):
        return False, None, None, "Acceso restringido: Utiliza un correo oficial @iaclatam.com o @iac.com.co."

    from core import database

    if database.usar_supabase():
        try:
            client_pub = database.obtener_cliente_publico()
            res = client_pub.auth.sign_in_with_password({"email": correo_limpio, "password": password})

            if not res.session or not res.user:
                return False, None, None, "Credenciales incorrectas o cuenta inactiva."

            tokens = {
                "access_token": res.session.access_token,
                "refresh_token": res.session.refresh_token,
                "expires_at": getattr(res.session, "expires_at", None),
                "user_id": res.user.id,
            }

            # Obtener datos de perfil con el cliente autenticado por JWT (Row Level Security activo)
            client_auth = database.obtener_cliente_usuario(tokens["access_token"], tokens["refresh_token"])
            usuario_perfil = database.obtener_usuario_por_correo_db(correo_limpio, client=client_auth)

            # REGLA DE SEGURIDAD ABSOLUTA (Auditoría A-01 / A-02):
            # 1. El perfil DEBE existir en public.perfiles_usuario y tener activo = true.
            # 2. JAMÁS leer es_admin desde user_metadata ni crear perfiles sintéticos con privilegios.
            # 3. Si no existe o está inactivo, rechazar inmediatamente, revocar sesión y no entregar tokens.
            if not usuario_perfil or not usuario_perfil.get("activo"):
                try:
                    client_auth.auth.sign_out()
                except Exception:
                    pass
                return False, None, None, "Credenciales incorrectas o cuenta inactiva."

            # Garantizar que es_admin provenga estrictamente de la columna de BD perfiles_usuario
            usuario_perfil["es_admin"] = bool(usuario_perfil.get("es_admin", False))

            return True, usuario_perfil, tokens, f"¡Bienvenido, {usuario_perfil.get('nombre', '')}!"
        except Exception as exc:
            msg_err = str(exc).lower()
            if "invalid login credentials" in msg_err or "invalid_credentials" in msg_err:
                return False, None, None, "Credenciales incorrectas. Verifica tu contraseña."
            if "email not confirmed" in msg_err:
                return False, None, None, "Tu cuenta no ha confirmado su correo electrónico de invitación."
            print(f"[AutoForm AI Auth] Error en autenticación Supabase: {exc}")
            return False, None, None, "No se pudo conectar al servicio de autenticación corporativa."

    # Modo SQLite (Desarrollo local)
    usuario = database.obtener_usuario_por_correo_db(correo_limpio)
    if not usuario:
        return False, None, None, "Credenciales incorrectas o usuario no autorizado."

    if verificar_password(password, usuario.get("password_hash", "")):
        datos_seguros = dict(usuario)
        datos_seguros.pop("password_hash", None)
        return True, datos_seguros, None, f"¡Bienvenido, {datos_seguros.get('nombre', '')}!"

    return False, None, None, "Credenciales incorrectas."


def cerrar_sesion(tokens: Optional[Dict[str, Any]] = None) -> None:
    """Cierra la sesión del usuario revocando el token si aplica."""
    from core import database
    if database.usar_supabase() and tokens:
        try:
            client = database.obtener_cliente_usuario(tokens.get("access_token"), tokens.get("refresh_token"))
            client.auth.sign_out()
        except Exception as exc:
            print(f"[AutoForm AI Auth] Advertencia al cerrar sesión en Supabase: {exc}")


def _verificar_solicitante_es_admin_activo(
    access_token: str,
) -> Tuple[bool, str, Optional[str]]:
    """Verifica en base de datos que el portador del JWT sea administrador activo.

    Hardening-01: Autorización de invitaciones basada en verificación real contra BD.
    No confía en variables booleanas de interfaz, st.session_state, user_metadata
    ni datos de formularios.

    Args:
        access_token: JWT de acceso del solicitante (no puede ser vacío ni None).

    Returns:
        Tuple[es_valido: bool, mensaje_error: str, user_id: Optional[str]]
        Si es_valido es True, user_id contiene el UUID del administrador verificado.
    """
    if not access_token or not access_token.strip():
        return False, "Se requiere un access_token válido del solicitante.", None

    from core import database

    if not database.usar_supabase():
        # En modo SQLite (desarrollo) no hay JWT real; permitir paso a la lógica SQLite
        return True, "", None

    try:
        # Construir cliente efímero con el JWT del solicitante (RLS activo)
        # No se usa refresh_token aquí porque solo necesitamos verificar el estado
        # del solicitante, no renovar su sesión.
        client_jwt = database.obtener_cliente_usuario(access_token=access_token)

        # Obtener el UID del portador del JWT desde Supabase Auth de forma soportada
        try:
            user_resp = client_jwt.auth.get_user(jwt=access_token)
            if not user_resp or not user_resp.user:
                return False, "Token de solicitante inválido o expirado.", None
            uid_solicitante = user_resp.user.id
        except Exception as exc:
            return False, f"No se pudo verificar el token del solicitante: {exc}", None

        # Consultar directamente public.perfiles_usuario con el JWT (RLS activo).
        # La consulta solo retorna filas si el JWT corresponde exactamente al usuario
        # cuyo id = auth.uid() según la política de RLS.
        try:
            res = (
                client_jwt
                .table("perfiles_usuario")
                .select("id, es_admin, activo")
                .eq("id", uid_solicitante)
                .limit(1)
                .execute()
            )
            perfil = res.data[0] if res.data else None
        except Exception as exc:
            return False, f"Error al consultar perfiles_usuario para verificación de admin: {exc}", None

        if not perfil:
            return False, "El solicitante no tiene perfil corporativo registrado o su cuenta está inactiva.", None

        if not perfil.get("activo"):
            return False, "La cuenta del solicitante está inactiva. No puede realizar invitaciones.", None

        if not perfil.get("es_admin"):
            return False, "Acceso denegado: El solicitante no tiene privilegios de administrador.", None

        # Triple verificación: id en BD == uid del JWT
        if str(perfil.get("id")) != str(uid_solicitante):
            return False, "Inconsistencia de identidad detectada en la verificación de administrador.", None

        return True, "", uid_solicitante

    except database.SesionNoAutenticadaError:
        return False, "Token del solicitante inválido o sesión no autenticada.", None
    except Exception as exc:
        print(f"[AutoForm AI Auth] Error inesperado en _verificar_solicitante_es_admin_activo: {exc}")
        return False, "Error interno al verificar la autorización del solicitante.", None


def invitar_usuario_corporativo(
    correo: str,
    nombre: str,
    cargo: str = "",
    cedula: str = "",
    telefono: str = "",
    direccion: str = "Carrera 63 B # 32 E -25 OFC 206",
    ciudad: str = "Bogotá",
    es_admin: bool = False,
    access_token_solicitante: str = "",
) -> Tuple[bool, str]:
    """Envía una invitación oficial por correo a través de Supabase Auth (ADR-0010 / Q5).

    REGLA DE SEGURIDAD ABSOLUTA (Hardening-01):
    - La autorización NO se verifica con solicitante_es_admin (bool de interfaz).
    - Se verifica directamente contra public.perfiles_usuario usando el JWT del solicitante.
    - El cliente service_role SOLO se construye tras verificación positiva en BD.
    - No se confía en: st.session_state, user_metadata, datos de formularios ni variables booleanas.

    Args:
        correo: Correo corporativo del nuevo usuario a invitar.
        nombre: Nombre completo del nuevo usuario.
        cargo: Cargo del nuevo usuario.
        cedula: Número de cédula.
        telefono: Teléfono de contacto.
        direccion: Dirección corporativa.
        ciudad: Ciudad de operación.
        es_admin: Si el nuevo usuario tendrá rol de administrador.
        access_token_solicitante: JWT vigente del administrador que realiza la invitación.
            Requerido en producción. No puede ser vacío.

    Returns:
        Tuple[exito: bool, mensaje: str]
    """
    from core import database

    if database.usar_supabase():
        # PASO 1 OBLIGATORIO: Verificar que el solicitante es administrador activo en BD.
        # Esta es la única fuente de verdad. No se acepta ningún parámetro booleano externo.
        es_admin_verificado, msg_error, uid_solicitante = _verificar_solicitante_es_admin_activo(
            access_token_solicitante
        )
        if not es_admin_verificado:
            return False, f"Autorización rechazada: {msg_error}"

    correo_limpio = correo.strip().lower()
    nombre_limpio = nombre.strip()

    if not nombre_limpio:
        return False, "El nombre completo es obligatorio."
    if not validar_formato_correo(correo_limpio):
        return False, "El formato de correo no es válido."
    if not validar_dominio_corporativo(correo_limpio):
        return False, "Registro no autorizado. Utiliza un correo corporativo (@iaclatam.com o @iac.com.co)."

    if not database.usar_supabase():
        # En SQLite local se registra con contraseña inicial
        pwd_inicial = "IAC2026*"
        return database.crear_usuario_db(
            nombre=nombre_limpio,
            correo=correo_limpio,
            password=pwd_inicial,
            cargo=cargo,
            cedula=cedula,
            telefono=telefono,
            direccion=direccion,
            ciudad=ciudad,
            es_admin=int(es_admin),
        )

    # PASO 2: Solo después de la verificación positiva, construir cliente service_role
    try:
        admin_client = database.obtener_cliente_admin()

        # PASO 3: Verificar si el correo ya existe en auth.users para evitar creación doble
        user_id: Optional[str] = None
        usuario_preexistente = False
        try:
            users_list = admin_client.auth.admin.list_users()
            for u in (users_list or []):
                if u.email and u.email.lower() == correo_limpio:
                    user_id = u.id
                    usuario_preexistente = True
                    break
        except Exception:
            pass  # Si falla la lista, intentar invite directamente

        if not usuario_preexistente:
            # PASO 4: Enviar invitación oficial (crea el usuario en auth.users)
            res_invite = admin_client.auth.admin.invite_user_by_email(correo_limpio)
            user_id = res_invite.user.id if hasattr(res_invite, "user") and res_invite.user else None

            if not user_id:
                # Segundo intento: buscar si la invitación creó el usuario
                try:
                    users_retry = admin_client.auth.admin.list_users()
                    for u in (users_retry or []):
                        if u.email and u.email.lower() == correo_limpio:
                            user_id = u.id
                            break
                except Exception:
                    pass

        if not user_id:
            return False, "No fue posible generar la invitación de Supabase para este correo."

        # PASO 5: Registrar perfil en tabla perfiles_usuario
        perfil_payload = {
            "id": user_id,
            "nombre": nombre_limpio,
            "cargo": cargo.strip(),
            "cedula": cedula.strip(),
            "telefono": telefono.strip(),
            "correo": correo_limpio,
            "direccion": direccion.strip(),
            "ciudad": ciudad.strip(),
            "es_admin": bool(es_admin),
            "activo": True,
        }
        try:
            admin_client.table("perfiles_usuario").upsert(perfil_payload, on_conflict="id").execute()
        except Exception as exc:
            # Compensación: perfil no creado — registrar estado para recuperación admin
            print(
                f"[AutoForm AI Auth] COMPENSACIÓN REQUERIDA: usuario auth creado (id={user_id}, "
                f"correo={correo_limpio}) pero perfiles_usuario falló: {exc}"
            )
            return (
                False,
                f"El usuario fue creado en Auth pero el perfil no pudo registrarse. "
                f"UUID para recuperación administrativa: {user_id}. Error: {exc}",
            )

        # PASO 6: Sincronizar catálogo de operadores con usuario_id vinculado
        slug_op = re.sub(r"[^\w]+", "_", correo_limpio.split("@")[0]).strip("_")
        try:
            database.guardar_operador_db(
                id_operador=slug_op,
                nombre=nombre_limpio,
                cargo=cargo.strip(),
                cedula=cedula.strip(),
                telefono=telefono.strip(),
                correo=correo_limpio,
                direccion=direccion.strip(),
                ciudad=ciudad.strip(),
                client=admin_client,
                usuario_id=user_id,
            )
        except Exception as exc:
            # Compensación: perfil_usuario creado, pero operadores falló — no es crítico
            print(
                f"[AutoForm AI Auth] COMPENSACIÓN: perfil_usuario creado (id={user_id}) "
                f"pero operadores falló (no crítico): {exc}"
            )
            # No revertimos el perfil; el operador puede crearse después manualmente

        if usuario_preexistente:
            return (
                True,
                f"Perfil actualizado para el usuario existente {correo_limpio}. "
                f"No se reenviará invitación (el usuario ya tiene cuenta activa).",
            )
        return (
            True,
            f"Invitación oficial enviada exitosamente a {correo_limpio}. "
            f"El usuario recibirá un enlace para activar su cuenta.",
        )
    except Exception as exc:
        print(f"[AutoForm AI Auth] Error invitando usuario corporativo: {exc}")
        return False, f"Error al procesar la invitación: {exc}"


def solicitar_recuperacion_password(correo: str) -> Tuple[bool, str]:
    """Inicia el proceso de recuperación de contraseña vía correo oficial de Supabase Auth.

    Reglas de seguridad:
    1. Valida estrictamente el dominio corporativo (@iaclatam.com o @iac.com.co).
    2. Bloquea URLs de redirección que contengan identificadores de proyectos PDF prohibidos.
    3. Respuesta homogénea para evitar ataques de enumeración de usuarios.
    """
    correo_limpio = correo.strip().lower()
    if not correo_limpio:
        return False, "Ingresa tu correo corporativo."

    if not validar_formato_correo(correo_limpio):
        return False, "El formato de correo no es válido."

    if not validar_dominio_corporativo(correo_limpio):
        return False, "Operación no autorizada: Solo se permite la recuperación para correos @iaclatam.com o @iac.com.co."

    from core import database

    if database.usar_supabase():
        redirect_url = os.environ.get("AUTOFORM_EXCEL_REDIRECT_URL", "").strip() or os.environ.get("SUPABASE_URL", "").strip()
        for pdf_ref in database.PROHIBITED_PROJECT_REFS:
            if pdf_ref in redirect_url:
                raise database.ConfiguracionInvalidaError(
                    f"Error de seguridad: La URL de redirección contiene un identificador de proyecto PDF prohibido ('{pdf_ref}')."
                )

        try:
            client_pub = database.obtener_cliente_publico()
            options = {"redirect_to": redirect_url} if redirect_url else None
            client_pub.auth.reset_password_for_email(correo_limpio, options=options)
            return (
                True,
                "Si tu cuenta está registrada en la plataforma corporativa, recibirás un enlace de recuperación en tu correo.",
            )
        except Exception as exc:
            if "PDF" in str(exc) or "ConfiguracionInvalidaError" in str(type(exc)):
                raise
            print(f"[AutoForm AI Auth] Error en reset_password_for_email: {exc}")
            return (
                True,
                "Si tu cuenta está registrada en la plataforma corporativa, recibirás un enlace de recuperación en tu correo.",
            )

    # Modo SQLite (Desarrollo local)
    usuario = database.obtener_usuario_por_correo_db(correo_limpio)
    if not usuario:
        return True, "Si tu cuenta está registrada en la plataforma corporativa, recibirás un enlace de recuperación en tu correo."

    return True, "En desarrollo local con SQLite, solicita al administrador reiniciar tu contraseña directamente."

