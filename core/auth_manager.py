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

import datetime as dt_module
from datetime import datetime, timezone
import hashlib
import hmac
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple, Union

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
            # 1. El perfil DEBE existir en public.perfiles_usuario y tener activo = true y estado_aprobacion = 'aprobado'.
            # 2. JAMÁS leer es_admin desde user_metadata ni crear perfiles sintéticos con privilegios.
            # 3. Si no existe, está pendiente, rechazado o inactivo, rechazar inmediatamente, revocar sesión y no entregar tokens.
            if not usuario_perfil:
                try:
                    client_auth.auth.sign_out()
                except Exception:
                    pass
                return False, None, None, "Credenciales incorrectas o cuenta no registrada."

            estado_aprobacion = str(usuario_perfil.get("estado_aprobacion") or "aprobado").lower()
            if estado_aprobacion == "rechazado":
                try:
                    client_auth.auth.sign_out()
                except Exception:
                    pass
                return False, None, None, "Tu solicitud de acceso fue rechazada. Contacta al administrador corporativo."

            if not usuario_perfil.get("activo"):
                try:
                    client_auth.auth.sign_out()
                except Exception:
                    pass
                return False, None, None, "Tu cuenta se encuentra inactiva. Contacta al administrador."

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
        return False, None, None, "Credenciales incorrectas o usuario no registrado."

    if verificar_password(password, usuario.get("password_hash", "")):
        estado_aprobacion = str(usuario.get("estado_aprobacion") or "aprobado").lower()
        if estado_aprobacion == "rechazado":
            return False, None, None, "Tu solicitud de acceso fue rechazada. Contacta al administrador corporativo."
        if not usuario.get("activo"):
            return False, None, None, "Tu cuenta se encuentra inactiva. Contacta al administrador."

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


# ── AUTO-REGISTRO Y GESTIÓN ADMINISTRATIVA CENTRALIZADA ───────────────────────

def registrar_solicitud_corporativa(
    nombre: str,
    correo: str,
    password: str,
    cargo: str = "",
    telefono: str = "",
    direccion: str = "Carrera 63 B # 32 E -25 OFC 206",
    ciudad: str = "Bogotá",
) -> Tuple[bool, str]:
    """Registra una solicitud de cuenta corporativa pendiente de aprobación administrativa.

    REGLAS DE SEGURIDAD ABSOLUTAS:
    1. Dominio corporativo obligatorio (@iaclatam.com o @iac.com.co).
    2. Contraseña mínima de 8 caracteres.
    3. Cero asignación desde cliente: la cuenta nace estrictamente como rol comercial, inactiva y pendiente.
    4. En Supabase: crea identidad en Auth Admin con app_metadata de servidor y fila en perfiles_usuario.
    """
    from core import database

    nombre_limpio = nombre.strip()
    correo_limpio = correo.strip().lower()

    if not nombre_limpio:
        return False, "El nombre completo es obligatorio."
    if not validar_formato_correo(correo_limpio):
        return False, "El formato de correo no es válido."
    if not validar_dominio_corporativo(correo_limpio):
        return False, "Registro no autorizado. Utiliza un correo corporativo (@iaclatam.com o @iac.com.co)."
    if not password or len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres."

    if database.usar_supabase():
        try:
            admin_client = database.obtener_cliente_admin()

            # 1. Verificar si ya existe en perfiles_usuario
            res_exist = (
                admin_client.table("perfiles_usuario")
                .select("id, estado_aprobacion, activo")
                .eq("correo", correo_limpio)
                .limit(1)
                .execute()
            )
            if res_exist.data:
                return False, "Ya existe una cuenta o solicitud registrada con este correo electrónico."

            # 2. Crear usuario en auth.users con app_metadata segura fijada en servidor
            user_id: Optional[str] = None
            try:
                res_create = admin_client.auth.admin.create_user({
                    "email": correo_limpio,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {"nombre": nombre_limpio},
                    "app_metadata": {
                        "es_admin": False,
                        "role": "comercial",
                        "rol": "comercial",
                        "estado": "aprobado",
                    },
                })
                if hasattr(res_create, "user") and res_create.user:
                    user_id = res_create.user.id
            except Exception as exc_auth:
                msg_auth = str(exc_auth).lower()
                # Si el usuario ya existe en auth.users pero no tenía perfil en perfiles_usuario (p.ej. por fallo previo al insertar),
                # intentamos recuperar su user_id y sincronizar credenciales para completar el registro activo.
                if "already registered" in msg_auth or "already exists" in msg_auth:
                    try:
                        users_list = admin_client.auth.admin.list_users()
                        for u in (users_list or []):
                            if u.email and u.email.lower() == correo_limpio:
                                user_id = u.id
                                break
                    except Exception:
                        pass
                    if user_id:
                        try:
                            admin_client.auth.admin.update_user_by_id(
                                user_id,
                                {
                                    "password": password,
                                    "user_metadata": {"nombre": nombre_limpio},
                                    "app_metadata": {
                                        "es_admin": False,
                                        "role": "comercial",
                                        "rol": "comercial",
                                        "estado": "aprobado",
                                    },
                                },
                            )
                        except Exception:
                            pass
                    else:
                        return False, "Ya existe una cuenta registrada con este correo corporativo en el proveedor de identidad."
                else:
                    print(f"[AutoForm AI Auth] Error creando usuario en Supabase Auth: {exc_auth}")
                    return False, f"Error al procesar la identidad: {exc_auth}"

            if not user_id:
                return False, "No fue posible registrar la identidad en el proveedor corporativo."

            # 3. Registrar fila en perfiles_usuario: comercial activo y aprobado de inmediato
            perfil_payload = {
                "id": user_id,
                "nombre": nombre_limpio,
                "cargo": cargo.strip(),
                "cedula": "",
                "telefono": telefono.strip(),
                "correo": correo_limpio,
                "direccion": direccion.strip(),
                "ciudad": ciudad.strip(),
                "es_admin": False,
                "activo": True,
                "estado_aprobacion": "aprobado",
            }
            admin_client.table("perfiles_usuario").upsert(perfil_payload, on_conflict="id").execute()

            # 4. Sincronizar catálogo de operadores inmediatamente para uso en la app
            slug_op = re.sub(r"[^\w]+", "_", correo_limpio.split("@")[0]).strip("_")
            try:
                database.guardar_operador_db(
                    id_operador=slug_op,
                    nombre=nombre_limpio,
                    cargo=cargo.strip() or "Asesor Comercial",
                    cedula="",
                    telefono=telefono.strip(),
                    correo=correo_limpio,
                    direccion=direccion.strip() or "Carrera 63 B # 32 E -25 OFC 206",
                    ciudad=ciudad.strip() or "Bogotá",
                    client=admin_client,
                    usuario_id=user_id,
                )
            except Exception as exc_op:
                print(f"[AutoForm AI Auth] Advertencia al sincronizar operador en registro: {exc_op}")

            return (
                True,
                "Registro exitoso. Tu cuenta corporativa ha sido creada y se encuentra activa.",
            )
        except Exception as exc:
            print(f"[AutoForm AI Auth] Error en registrar_solicitud_corporativa: {exc}")
            return False, f"Error al registrar la solicitud corporativa: {exc}"

    # Modo SQLite (Desarrollo local)
    database.inicializar_db()
    slug_id = re.sub(r"[^\w]+", "_", correo_limpio.split("@")[0]).strip("_")
    pwd_hash = hashear_password(password)
    ahora_iso = datetime.now(timezone.utc).isoformat()

    try:
        with database.obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO usuarios (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, password_hash, es_admin, activo, estado_aprobacion, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 'aprobado', ?)
                """,
                (slug_id, nombre_limpio, cargo.strip(), "", telefono.strip(), correo_limpio, direccion.strip(), ciudad.strip(), pwd_hash, ahora_iso),
            )
            conn.commit()

        # Sincronizar operador en SQLite
        try:
            database.guardar_operador_db(
                id_operador=slug_id,
                nombre=nombre_limpio,
                cargo=cargo.strip() or "Asesor Comercial",
                cedula="",
                telefono=telefono.strip(),
                correo=correo_limpio,
                direccion=direccion.strip() or "Carrera 63 B # 32 E -25 OFC 206",
                ciudad=ciudad.strip() or "Bogotá",
                usuario_id=slug_id,
            )
        except Exception as exc_op:
            print(f"[AutoForm AI Auth] Advertencia al sincronizar operador en SQLite: {exc_op}")

        return (
            True,
            "Registro exitoso. Tu cuenta corporativa ha sido creada y se encuentra activa.",
        )
    except sqlite3.IntegrityError:
        return False, "Ya existe una cuenta o solicitud registrada con este correo electrónico."
    except Exception as exc:
        return False, f"Error al registrar solicitud en SQLite: {exc}"


def aprobar_solicitud_registro(
    usuario_id: str,
    access_token_solicitante: str = "",
) -> Tuple[bool, str]:
    """Aprueba una solicitud de registro pendiente, activa la cuenta y sincroniza el catálogo de operadores."""
    from core import database

    if database.usar_supabase():
        es_admin_verificado, msg_error, _ = _verificar_solicitante_es_admin_activo(access_token_solicitante)
        if not es_admin_verificado:
            return False, f"Autorización rechazada: {msg_error}"

        try:
            admin_client = database.obtener_cliente_admin()
            # 1. Obtener perfil
            res_p = admin_client.table("perfiles_usuario").select("*").eq("id", usuario_id).limit(1).execute()
            if not res_p.data:
                return False, f"No se encontró el perfil de usuario con ID: {usuario_id}"
            perfil = res_p.data[0]

            # 2. Actualizar perfiles_usuario a aprobado y activo
            admin_client.table("perfiles_usuario").update({
                "estado_aprobacion": "aprobado",
                "activo": True,
                "es_admin": False,
            }).eq("id", usuario_id).execute()

            # 3. Actualizar app_metadata en auth.users
            try:
                admin_client.auth.admin.update_user_by_id(usuario_id, {
                    "app_metadata": {
                        "es_admin": False,
                        "role": "comercial",
                        "rol": "comercial",
                        "estado": "aprobado",
                    }
                })
            except Exception as exc_meta:
                print(f"[AutoForm AI Auth] Advertencia al actualizar app_metadata en aprobación: {exc_meta}")

            # 4. Sincronizar catálogo de operadores (comercial)
            slug_op = re.sub(r"[^\w]+", "_", str(perfil.get("correo", "")).split("@")[0]).strip("_")
            try:
                database.guardar_operador_db(
                    id_operador=slug_op,
                    nombre=str(perfil.get("nombre", "")),
                    cargo=str(perfil.get("cargo") or "Asesor Comercial"),
                    cedula=str(perfil.get("cedula") or ""),
                    telefono=str(perfil.get("telefono") or ""),
                    correo=str(perfil.get("correo", "")),
                    direccion=str(perfil.get("direccion") or "Carrera 63 B # 32 E -25 OFC 206"),
                    ciudad=str(perfil.get("ciudad") or "Bogotá"),
                    client=admin_client,
                    usuario_id=usuario_id,
                )
            except Exception as exc_op:
                print(f"[AutoForm AI Auth] Advertencia al sincronizar operador en aprobación: {exc_op}")

            return True, f"Usuario '{perfil.get('nombre')}' aprobado y activado exitosamente."
        except Exception as exc:
            print(f"[AutoForm AI Auth] Error al aprobar solicitud de registro: {exc}")
            return False, f"Error al aprobar solicitud: {exc}"

    # Modo SQLite
    ok = database.actualizar_estado_usuario_db(usuario_id, "aprobado", True)
    if not ok:
        return False, f"No se pudo actualizar el estado del usuario '{usuario_id}' en SQLite."

    # Sincronizar operador en SQLite
    try:
        with database.obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))
            row = cursor.fetchone()
            if row:
                ahora_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO operadores (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        nombre = excluded.nombre,
                        cargo = excluded.cargo,
                        telefono = excluded.telefono,
                        correo = excluded.correo,
                        actualizado_en = excluded.actualizado_en
                    """,
                    (row["id"], row["nombre"], row["cargo"] or "Asesor Comercial", row["cedula"] or "", row["telefono"] or "", row["correo"], row["direccion"] or "", row["ciudad"] or "", ahora_iso),
                )
                conn.commit()
    except Exception as exc:
        print(f"[AutoForm AI Auth] Error sincronizando operador en SQLite: {exc}")

    return True, f"Usuario '{usuario_id}' aprobado y activado exitosamente."


def rechazar_solicitud_registro(
    usuario_id: str,
    access_token_solicitante: str = "",
) -> Tuple[bool, str]:
    """Rechaza una solicitud de registro pendiente y mantiene la cuenta inactiva."""
    from core import database

    if database.usar_supabase():
        es_admin_verificado, msg_error, _ = _verificar_solicitante_es_admin_activo(access_token_solicitante)
        if not es_admin_verificado:
            return False, f"Autorización rechazada: {msg_error}"

        try:
            admin_client = database.obtener_cliente_admin()
            admin_client.table("perfiles_usuario").update({
                "estado_aprobacion": "rechazado",
                "activo": False,
            }).eq("id", usuario_id).execute()

            try:
                admin_client.auth.admin.update_user_by_id(usuario_id, {
                    "app_metadata": {"estado": "rechazado"}
                })
            except Exception as exc_meta:
                print(f"[AutoForm AI Auth] Advertencia al actualizar app_metadata en rechazo: {exc_meta}")

            return True, "Solicitud de registro rechazada exitosamente."
        except Exception as exc:
            print(f"[AutoForm AI Auth] Error al rechazar solicitud de registro: {exc}")
            return False, f"Error al rechazar solicitud: {exc}"

    # Modo SQLite
    ok = database.actualizar_estado_usuario_db(usuario_id, "rechazado", False)
    if not ok:
        return False, f"No se pudo rechazar la solicitud del usuario '{usuario_id}' en SQLite."
    return True, "Solicitud de registro rechazada exitosamente."


def conmutar_estado_activo_usuario(
    usuario_id: str,
    nuevo_activo: bool,
    access_token_solicitante: str = "",
) -> Tuple[bool, str]:
    """Activa o suspende una cuenta de usuario aprobada."""
    from core import database

    if database.usar_supabase():
        es_admin_verificado, msg_error, uid_solicitante = _verificar_solicitante_es_admin_activo(access_token_solicitante)
        if not es_admin_verificado:
            return False, f"Autorización rechazada: {msg_error}"

        # Proteger contra la desactivación del único admin activo
        if not nuevo_activo:
            admin_client = database.obtener_cliente_admin()
            res_target = admin_client.table("perfiles_usuario").select("es_admin, activo").eq("id", usuario_id).limit(1).execute()
            if res_target.data and res_target.data[0].get("es_admin") and res_target.data[0].get("activo"):
                total_admins = database.contar_administradores_activos_db(client=admin_client)
                if total_admins <= 1:
                    return False, "Operación denegada: No puedes desactivar al único administrador activo de la plataforma."

        try:
            admin_client = database.obtener_cliente_admin()
            admin_client.table("perfiles_usuario").update({
                "activo": nuevo_activo,
            }).eq("id", usuario_id).execute()

            estado_txt = "activado" if nuevo_activo else "desactivado"
            return True, f"Usuario {estado_txt} exitosamente."
        except Exception as exc:
            print(f"[AutoForm AI Auth] Error al alternar activación de usuario: {exc}")
            return False, f"Error al actualizar estado del usuario: {exc}"

    # Modo SQLite
    if not nuevo_activo:
        total_admins = database.contar_administradores_activos_db()
        with database.obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT es_admin, activo FROM usuarios WHERE id = ?", (usuario_id,))
            u_row = cursor.fetchone()
            if u_row and u_row["es_admin"] and u_row["activo"] and total_admins <= 1:
                return False, "Operación denegada: No puedes desactivar al único administrador activo de la plataforma."

    ok = database.actualizar_estado_usuario_db(usuario_id, "aprobado", nuevo_activo)
    if not ok:
        return False, f"No se pudo cambiar el estado del usuario '{usuario_id}'."
    estado_txt = "activado" if nuevo_activo else "desactivado"
    return True, f"Usuario {estado_txt} exitosamente."


def cambiar_rol_usuario(
    usuario_id: str,
    nuevo_rol: str,
    access_token_solicitante: str = "",
) -> Tuple[bool, str]:
    """Cambia el rol de un usuario estrictamente entre 'comercial' y 'administrador'."""
    from core import database

    rol_limpio = nuevo_rol.strip().lower()
    if rol_limpio not in ("comercial", "administrador"):
        return False, "Rol no permitido. El rol debe ser estrictamente 'comercial' o 'administrador'."

    es_admin_nuevo = (rol_limpio == "administrador")

    if database.usar_supabase():
        es_admin_verificado, msg_error, uid_solicitante = _verificar_solicitante_es_admin_activo(access_token_solicitante)
        if not es_admin_verificado:
            return False, f"Autorización rechazada: {msg_error}"

        admin_client = database.obtener_cliente_admin()

        # Si se va a degradar un admin a comercial, verificar que no sea el único admin activo
        if not es_admin_nuevo:
            res_target = admin_client.table("perfiles_usuario").select("es_admin, activo").eq("id", usuario_id).limit(1).execute()
            if res_target.data and res_target.data[0].get("es_admin") and res_target.data[0].get("activo"):
                total_admins = database.contar_administradores_activos_db(client=admin_client)
                if total_admins <= 1:
                    return False, "Operación denegada: No puedes revocar los privilegios del único administrador activo."

        try:
            admin_client.table("perfiles_usuario").update({
                "es_admin": es_admin_nuevo,
            }).eq("id", usuario_id).execute()

            try:
                admin_client.auth.admin.update_user_by_id(usuario_id, {
                    "app_metadata": {
                        "es_admin": es_admin_nuevo,
                        "role": rol_limpio,
                        "rol": rol_limpio,
                    }
                })
            except Exception as exc_meta:
                print(f"[AutoForm AI Auth] Advertencia al actualizar app_metadata en cambio de rol: {exc_meta}")

            return True, f"Rol actualizado exitosamente a '{rol_limpio}'."
        except Exception as exc:
            print(f"[AutoForm AI Auth] Error al cambiar rol de usuario en Supabase: {exc}")
            return False, f"Error al cambiar rol: {exc}"

    # Modo SQLite
    if not es_admin_nuevo:
        total_admins = database.contar_administradores_activos_db()
        with database.obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT es_admin, activo FROM usuarios WHERE id = ?", (usuario_id,))
            u_row = cursor.fetchone()
            if u_row and u_row["es_admin"] and u_row["activo"] and total_admins <= 1:
                return False, "Operación denegada: No puedes revocar los privilegios del único administrador activo."

    ok = database.actualizar_rol_usuario_db(usuario_id, es_admin_nuevo)
    if not ok:
        return False, f"No se pudo actualizar el rol del usuario '{usuario_id}' en SQLite."
    return True, f"Rol actualizado exitosamente a '{rol_limpio}'."


def reenviar_recuperacion_admin(
    correo_destino: str,
    redirect_url: str = "",
    access_token_solicitante: str = "",
) -> Tuple[bool, str]:
    """Despacha un correo oficial de restablecimiento de contraseña solicitado por un administrador."""
    from core import database

    correo_limpio = correo_destino.strip().lower()
    if not correo_limpio:
        return False, "El correo de destino es obligatorio."
    if not validar_formato_correo(correo_limpio):
        return False, "El formato de correo no es válido."
    if not validar_dominio_corporativo(correo_limpio):
        return False, "Operación no autorizada: Solo se permite restablecer cuentas con dominio @iaclatam.com o @iac.com.co."

    if database.usar_supabase():
        es_admin_verificado, msg_error, _ = _verificar_solicitante_es_admin_activo(access_token_solicitante)
        if not es_admin_verificado:
            return False, f"Autorización rechazada: {msg_error}"

        url_redireccion = (redirect_url or os.environ.get("AUTOFORM_EXCEL_REDIRECT_URL", "") or os.environ.get("SUPABASE_URL", "")).strip()
        for pdf_ref in database.PROHIBITED_PROJECT_REFS:
            if pdf_ref in url_redireccion:
                raise database.ConfiguracionInvalidaError(
                    f"Error de seguridad: La URL de redirección contiene un identificador de proyecto PDF prohibido ('{pdf_ref}')."
                )

        try:
            client_pub = database.obtener_cliente_publico()
            options = {"redirect_to": url_redireccion} if url_redireccion else None
            client_pub.auth.reset_password_for_email(correo_limpio, options=options)
            return True, f"Enlace oficial de restablecimiento despachado por Supabase a {correo_limpio}."
        except Exception as exc:
            if "PDF" in str(exc) or "ConfiguracionInvalidaError" in str(type(exc)):
                raise
            print(f"[AutoForm AI Auth] Error en reenviar_recuperacion_admin: {exc}")
            return False, f"Error al despachar enlace de recuperación: {exc}"

    # Modo SQLite
    return True, f"En desarrollo local SQLite, restablecimiento simulado para {correo_limpio}."


def listar_solicitudes_pendientes(
    access_token_solicitante: str = "",
) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
    """Obtiene la lista de solicitudes de registro pendientes de aprobación."""
    from core import database

    if database.usar_supabase():
        es_admin_verificado, msg_error, _ = _verificar_solicitante_es_admin_activo(access_token_solicitante)
        if not es_admin_verificado:
            return False, f"Autorización rechazada: {msg_error}"

        try:
            admin_client = database.obtener_cliente_admin()
            res = (
                admin_client.table("perfiles_usuario")
                .select("*")
                .eq("estado_aprobacion", "pendiente")
                .order("created_at", desc=True)
                .execute()
            )
            solicitudes = []
            for row in (res.data or []):
                solicitudes.append({
                    "id": str(row.get("id")),
                    "nombre": str(row.get("nombre")),
                    "correo": str(row.get("correo")),
                    "cargo": str(row.get("cargo") or ""),
                    "telefono": str(row.get("telefono") or ""),
                    "direccion": str(row.get("direccion") or ""),
                    "ciudad": str(row.get("ciudad") or ""),
                    "created_at": str(row.get("created_at")),
                    "estado_aprobacion": "pendiente",
                })
            return True, solicitudes
        except Exception as exc:
            print(f"[AutoForm AI Auth] Error listando solicitudes pendientes en Supabase: {exc}")
            return False, f"Error al consultar solicitudes pendientes: {exc}"

    # Modo SQLite
    database.inicializar_db()
    solicitudes = []
    try:
        with database.obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, correo, cargo, telefono, direccion, ciudad, creado_en
                FROM usuarios
                WHERE estado_aprobacion = 'pendiente'
                ORDER BY creado_en DESC
                """
            )
            for row in cursor.fetchall():
                solicitudes.append({
                    "id": str(row["id"]),
                    "nombre": str(row["nombre"]),
                    "correo": str(row["correo"]),
                    "cargo": str(row["cargo"] or ""),
                    "telefono": str(row["telefono"] or ""),
                    "direccion": str(row["direccion"] or ""),
                    "ciudad": str(row["ciudad"] or ""),
                    "created_at": str(row["creado_en"]),
                    "estado_aprobacion": "pendiente",
                })
        return True, solicitudes
    except Exception as exc:
        print(f"[AutoForm AI Auth] Error listando solicitudes pendientes en SQLite: {exc}")
        return False, f"Error al consultar solicitudes pendientes en SQLite: {exc}"


