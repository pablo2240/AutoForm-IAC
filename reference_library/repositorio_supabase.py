"""Repositorio remoto de referencias sobre Supabase (Storage privado + tabla con RLS).

Todas las operaciones usan el cliente del usuario (JWT en ``st.session_state``): las políticas RLS
de la migración 009 son las que deciden quién lee (usuarios activos) y quién escribe
(administradores). Este módulo nunca usa la clave de servicio.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

from reference_library.remote import EntradaRemota

BUCKET = "referencias"
TABLA = "referencias_catalogo"
COLUMNAS_ENTRADA = (
    "clave, nombre, familia, hash_contenido, fuente, confianza, version_extractor, huella_datos, tiene_conocimiento"
)
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def ruta_de_almacenamiento(clave: str) -> str:
    """Nombre de objeto seguro y estable (los nombres reales pueden tener tildes, espacios o paréntesis)."""
    extension = PurePosixPath(clave).suffix.lower() or ".xlsx"
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:32] + extension


def _a_entrada(fila: Dict[str, Any]) -> EntradaRemota:
    return EntradaRemota(
        clave=str(fila["clave"]),
        nombre=str(fila["nombre"]),
        familia=str(fila.get("familia") or ""),
        hash_contenido=str(fila["hash_contenido"]),
        fuente=str(fila.get("fuente") or "referencia"),
        confianza=float(fila.get("confianza") or 0.75),
        version_extractor=str(fila.get("version_extractor") or ""),
        huella_datos=str(fila.get("huella_datos") or ""),
        tiene_conocimiento=bool(fila.get("tiene_conocimiento")),
    )


class RepositorioSupabase:
    """Implementación de ``RepositorioRemoto`` sobre Supabase."""

    def __init__(self, cliente: Any, access_token: Optional[str] = None) -> None:
        self._cliente = cliente
        self._access_token = access_token

    @classmethod
    def desde_sesion(cls) -> Optional["RepositorioSupabase"]:
        """Repositorio de la sesión actual, o None si la app no usa Supabase o no hay sesión válida."""
        try:
            from core import database

            if not database.usar_supabase():
                return None
            cliente = database._obtener_cliente_activo()
            token = None
            try:
                import streamlit as st

                sesion = st.session_state.get("supabase_session")
                token = sesion.get("access_token") if isinstance(sesion, dict) else None
            except Exception:
                token = None
            return cls(cliente, token)
        except Exception as exc:
            print(f"[ReferenceLibrary] Repositorio remoto no disponible: {exc}")
            return None

    # ── Utilidades ───────────────────────────────────────────────────────

    def _almacenamiento(self) -> Any:
        almacenamiento = self._cliente.storage
        if self._access_token:
            # El cliente de Storage no siempre hereda el JWT del usuario; se fija de forma explícita.
            almacenamiento.session.headers["Authorization"] = f"Bearer {self._access_token}"
        return almacenamiento.from_(BUCKET)

    def _ruta(self, clave: str) -> str:
        respuesta = self._cliente.table(TABLA).select("ruta_storage").eq("clave", clave).limit(1).execute()
        if not respuesta.data:
            raise FileNotFoundError(f"La referencia '{clave}' no existe en el catálogo.")
        return str(respuesta.data[0]["ruta_storage"])

    @staticmethod
    def _registro(entrada: EntradaRemota, tamano: int, ruta: str) -> Dict[str, Any]:
        return {
            "clave": entrada.clave,
            "nombre": entrada.nombre,
            "familia": entrada.familia,
            "hash_contenido": entrada.hash_contenido,
            "tamano_bytes": tamano,
            "ruta_storage": ruta,
            "fuente": entrada.fuente,
            "confianza": entrada.confianza,
            "version_extractor": entrada.version_extractor,
            "huella_datos": entrada.huella_datos,
        }

    # ── RepositorioRemoto ────────────────────────────────────────────────

    def listar(self) -> List[EntradaRemota]:
        respuesta = self._cliente.table(TABLA).select(COLUMNAS_ENTRADA).order("clave").execute()
        return [_a_entrada(fila) for fila in (respuesta.data or [])]

    def obtener_conocimiento(self, clave: str) -> Optional[Dict[str, Any]]:
        respuesta = self._cliente.table(TABLA).select("conocimiento").eq("clave", clave).limit(1).execute()
        return respuesta.data[0].get("conocimiento") if respuesta.data else None

    def descargar(self, clave: str) -> bytes:
        return bytes(self._almacenamiento().download(self._ruta(clave)))

    def publicar(self, entrada: EntradaRemota, contenido: bytes, conocimiento: Dict[str, Any]) -> None:
        ruta = ruta_de_almacenamiento(entrada.clave)
        tipo = mimetypes.guess_type(ruta)[0] or TIPO_XLSX
        try:
            self._almacenamiento().upload(ruta, contenido, {"content-type": tipo, "upsert": "true"})
            self._cliente.table(TABLA).upsert(
                {**self._registro(entrada, len(contenido), ruta), "conocimiento": conocimiento}, on_conflict="clave"
            ).execute()
        except Exception as exc:
            if _es_error_de_permiso(exc):
                raise PermissionError("Solo un administrador puede publicar referencias en la nube.") from exc
            raise

    def guardar_conocimiento(self, entrada: EntradaRemota, conocimiento: Dict[str, Any]) -> None:
        self._cliente.table(TABLA).update(
            {
                "conocimiento": conocimiento,
                "hash_contenido": entrada.hash_contenido,
                "version_extractor": entrada.version_extractor,
                "huella_datos": entrada.huella_datos,
            }
        ).eq("clave", entrada.clave).execute()

    def eliminar(self, clave: str) -> None:
        try:
            ruta = self._ruta(clave)
            self._almacenamiento().remove([ruta])
            self._cliente.table(TABLA).delete().eq("clave", clave).execute()
        except Exception as exc:
            if _es_error_de_permiso(exc):
                raise PermissionError("Solo un administrador puede eliminar referencias de la nube.") from exc
            raise


def _es_error_de_permiso(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(marca in texto for marca in ("row-level security", "42501", "unauthorized", "403", "not authorized"))

