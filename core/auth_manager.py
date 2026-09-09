"""Módulo de autenticación y seguridad de usuarios (ADR-0008).

Provee:
1. Hashing y verificación criptográfica de contraseñas usando PBKDF2-HMAC-SHA256 (100k iteraciones, salt de 16 bytes).
2. Validación estricta de dominios corporativos autorizados (@iac.com.co, @iaclatam.com).
3. Utilidades de gestión de sesión para Streamlit.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any, Dict, Optional, Set

# Dominios corporativos autorizados para registro
DOMINIOS_PERMITIDOS: Set[str] = {
    "iac.com.co",
    "iaclatam.com",
}


def hashear_password(password: str) -> str:
    """Genera un hash seguro de la contraseña usando PBKDF2-HMAC-SHA256 con salt aleatorio.

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
    """Verifica si la contraseña coincide con el hash almacenado en tiempo constante.

    Args:
        password: Texto plano ingresado por el usuario.
        hash_almacenado: String 'salt_hex$hash_hex' guardado en base de datos.

    Returns:
        True si coincide, False en caso contrario.
    """
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


def validar_dominio_corporativo(correo: str) -> bool:
    """Verifica si el correo pertenece a uno de los dominios corporativos autorizados.

    Args:
        correo: Dirección de correo electrónico a validar.

    Returns:
        True si pertenece a DOMINIOS_PERMITIDOS, False de lo contrario.
    """
    if not correo or "@" not in correo:
        return False
    correo_limpio = correo.strip().lower()
    dominio = correo_limpio.split("@")[-1].strip()
    return dominio in DOMINIOS_PERMITIDOS


def validar_formato_correo(correo: str) -> bool:
    """Valida sintaxis básica de correo electrónico."""
    patron = r"^[\w\.\+\-]+@[\w\-]+(\.[\w\-]+)+$"
    return bool(re.match(patron, (correo or "").strip()))
