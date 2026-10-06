"""Biblioteca de formularios de referencia: agregar, actualizar, eliminar y reprocesar.

La carpeta de referencias es la fuente de verdad (va en el repositorio); la base SQLite se deriva
de ella. ``sincronizar`` compara el hash de cada archivo y solo reprocesa lo que cambió, por lo
que pasar de 5 a miles de formularios no requiere cambios de código.

Convenciones (todas opcionales):
  * La primera subcarpeta es la familia del formulario: ``proveedor/archivo.xlsx``.
  * ``referencias.json`` en la raíz puede fijar familia, fuente y confianza por archivo.
  * Sin manifiesto, un nombre con "completo" se toma como diligenciado y verificado, y uno con
    "autoform" como generado por la propia app (menos confiable).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from reference_library.extractor import ExtraccionDocumento, extraer_conocimiento, huella_datos_empresa
from reference_library.settings import (
    EXTENSIONES_SOPORTADAS,
    EXTRACTOR_VERSION,
    NOMBRE_MANIFIESTO,
    directorio_referencias,
)
from reference_library.store import DocumentoReferencia, ReferenceStore


FUENTE_VERIFICADA = ("diligenciado_verificado", 0.9)
FUENTE_GENERADA = ("generado_autoform", 0.6)
FUENTE_REFERENCIA = ("referencia", 0.75)


@dataclass
class ReporteSincronizacion:
    """Resultado de sincronizar la carpeta de referencias con la base de conocimiento."""

    agregados: List[str] = field(default_factory=list)
    actualizados: List[str] = field(default_factory=list)
    eliminados: List[str] = field(default_factory=list)
    sin_cambios: List[str] = field(default_factory=list)
    errores: Dict[str, str] = field(default_factory=dict)

    @property
    def hubo_cambios(self) -> bool:
        return bool(self.agregados or self.actualizados or self.eliminados)

    def resumen(self) -> str:
        return (
            f"{len(self.agregados)} agregados, {len(self.actualizados)} actualizados, "
            f"{len(self.eliminados)} eliminados, {len(self.sin_cambios)} sin cambios, "
            f"{len(self.errores)} con error"
        )


def _hash_contenido(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()[:16]


def _doc_id(clave: str) -> str:
    return hashlib.sha256(clave.lower().encode("utf-8")).hexdigest()[:16]


def _datos_empresa_por_defecto() -> Dict[str, Any]:
    """Datos fijos de la empresa; permiten inferir campos desde formularios ya diligenciados."""
    try:
        from core import profile_manager

        return dict(profile_manager.obtener_empresa_fija().datos)
    except Exception as exc:
        print(f"[ReferenceLibrary] Sin datos de empresa para inferir campos por valor: {exc}")
        return {}


class ReferenceLibrary:
    """Administra la carpeta de referencias y la base de conocimiento derivada."""

    def __init__(
        self,
        directorio: Optional[Path] = None,
        store: Optional[ReferenceStore] = None,
        datos_empresa: Optional[Union[Dict[str, Any], Callable[[], Dict[str, Any]]]] = None,
        extractor: Callable[[bytes, str, Optional[Dict[str, Any]]], ExtraccionDocumento] = extraer_conocimiento,
    ) -> None:
        self.directorio = Path(directorio) if directorio else directorio_referencias()
        self.store = store or ReferenceStore()
        self._datos_empresa = datos_empresa if datos_empresa is not None else _datos_empresa_por_defecto
        self._extractor = extractor

    # ── Utilidades ───────────────────────────────────────────────────────

    def _datos(self) -> Dict[str, Any]:
        return self._datos_empresa() if callable(self._datos_empresa) else dict(self._datos_empresa)

    def _clave(self, archivo: Path) -> str:
        return archivo.relative_to(self.directorio).as_posix()

    def _leer_manifiesto(self) -> Dict[str, Dict[str, Any]]:
        ruta = self.directorio / NOMBRE_MANIFIESTO
        if not ruta.exists():
            return {}
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8-sig"))
            return {str(k).lower(): v for k, v in contenido.items() if isinstance(v, dict)}
        except (OSError, ValueError) as exc:
            print(f"[ReferenceLibrary] Manifiesto ilegible, se ignora ({exc}).")
            return {}

    def _metadatos(self, clave: str, nombre: str) -> Tuple[str, str, float]:
        """Familia, fuente y confianza de un archivo (manifiesto > carpeta/nombre)."""
        partes = clave.split("/")
        familia = partes[0] if len(partes) > 1 else ""
        nombre_min = nombre.lower()
        if "completo" in nombre_min:
            fuente, confianza = FUENTE_VERIFICADA
        elif "autoform" in nombre_min:
            fuente, confianza = FUENTE_GENERADA
        else:
            fuente, confianza = FUENTE_REFERENCIA
        manual = self._leer_manifiesto().get(clave.lower()) or self._leer_manifiesto().get(nombre_min) or {}
        return (
            str(manual.get("familia", familia)),
            str(manual.get("fuente", fuente)),
            float(manual.get("confianza", confianza)),
        )

    def _archivos(self) -> List[Path]:
        if not self.directorio.exists():
            return []
        return sorted(
            p for p in self.directorio.rglob("*")
            if p.is_file() and p.suffix.lower() in EXTENSIONES_SOPORTADAS and not p.name.startswith("~$")
        )

    # ── Procesamiento ────────────────────────────────────────────────────

    def _procesar(self, archivo: Path, forzar: bool = False) -> str:
        """Devuelve 'agregado', 'actualizado', 'sin_cambios' o 'error'."""
        clave = self._clave(archivo)
        doc_id = _doc_id(clave)
        contenido = archivo.read_bytes()
        hash_actual = _hash_contenido(contenido)
        datos = self._datos()
        huella = huella_datos_empresa(datos)
        previo = self.store.obtener_documento(doc_id)

        if previo and not forzar and previo.hash_contenido == hash_actual and previo.version_extractor == EXTRACTOR_VERSION:
            if previo.estado == "error" or previo.huella_datos == huella:
                return "error" if previo.estado == "error" else "sin_cambios"

        familia, fuente, confianza = self._metadatos(clave, archivo.name)
        try:
            extraccion = self._extractor(contenido, archivo.name, datos)
        except Exception as exc:
            self.store.registrar_error(
                doc_id, clave, archivo.name, familia, hash_actual, huella, EXTRACTOR_VERSION,
                f"{type(exc).__name__}: {exc}",
            )
            return "error"

        self.store.reemplazar_documento(
            doc_id=doc_id, ruta=clave, nombre=archivo.name, familia=familia, hash_contenido=hash_actual,
            huella_datos=huella, fuente=fuente, confianza=confianza, version_extractor=EXTRACTOR_VERSION,
            plantilla_id=extraccion.plantilla_id, estructura=extraccion.estructura, campos=extraccion.campos,
        )
        return "actualizado" if previo else "agregado"

    # ── API pública ──────────────────────────────────────────────────────

    def sincronizar(self, eliminar_faltantes: bool = True) -> ReporteSincronizacion:
        """Alinea la base con la carpeta: agrega nuevos, actualiza cambiados y retira los borrados."""
        reporte = ReporteSincronizacion()
        presentes = set()
        for archivo in self._archivos():
            presentes.add(_doc_id(self._clave(archivo)))
            resultado = self._procesar(archivo)
            if resultado == "agregado":
                reporte.agregados.append(archivo.name)
            elif resultado == "actualizado":
                reporte.actualizados.append(archivo.name)
            elif resultado == "error":
                doc = self.store.obtener_documento(_doc_id(self._clave(archivo)))
                reporte.errores[archivo.name] = doc.error if doc else "error desconocido"
            else:
                reporte.sin_cambios.append(archivo.name)

        if eliminar_faltantes:
            for doc in self.store.listar_documentos():
                if doc.doc_id not in presentes:
                    self.store.eliminar_documento(doc.doc_id)
                    reporte.eliminados.append(doc.nombre)
        return reporte

    def agregar(
        self,
        origen: Union[Path, str, bytes],
        nombre: Optional[str] = None,
        familia: str = "",
    ) -> str:
        """Copia un formulario a la carpeta de referencias, lo procesa y devuelve su ``doc_id``."""
        if isinstance(origen, bytes):
            if not nombre:
                raise ValueError("Se requiere el nombre del archivo para agregar una referencia desde bytes.")
            contenido, nombre_final = origen, Path(nombre).name
        else:
            ruta_origen = Path(origen)
            contenido, nombre_final = ruta_origen.read_bytes(), Path(nombre or ruta_origen.name).name

        if Path(nombre_final).suffix.lower() not in EXTENSIONES_SOPORTADAS:
            raise ValueError(f"Formato no soportado: solo {', '.join(EXTENSIONES_SOPORTADAS)}.")
        familia_limpia = Path(familia).name if familia else ""

        destino = self.directorio / familia_limpia / nombre_final if familia_limpia else self.directorio / nombre_final
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        resultado = self._procesar(destino, forzar=True)
        doc_id = _doc_id(self._clave(destino))
        if resultado == "error":
            doc = self.store.obtener_documento(doc_id)
            raise ValueError(f"No se pudo procesar '{nombre_final}': {doc.error if doc else 'error desconocido'}")
        return doc_id

    def eliminar(self, doc_id: str, borrar_archivo: bool = True) -> bool:
        """Quita una referencia y todo el conocimiento que aportó (y su archivo, salvo que se indique)."""
        doc = self.store.obtener_documento(doc_id)
        if doc is None:
            return False
        if borrar_archivo:
            archivo = self.directorio / doc.ruta
            if archivo.exists():
                archivo.unlink()
        return self.store.eliminar_documento(doc_id)

    def reprocesar(self, doc_id: Optional[str] = None) -> ReporteSincronizacion:
        """Vuelve a extraer el conocimiento de un documento, o de todos, ignorando el hash."""
        reporte = ReporteSincronizacion()
        for archivo in self._archivos():
            if doc_id and _doc_id(self._clave(archivo)) != doc_id:
                continue
            resultado = self._procesar(archivo, forzar=True)
            if resultado == "error":
                doc = self.store.obtener_documento(_doc_id(self._clave(archivo)))
                reporte.errores[archivo.name] = doc.error if doc else "error desconocido"
            else:
                reporte.actualizados.append(archivo.name)
        return reporte

    def listar(self) -> List[DocumentoReferencia]:
        return self.store.listar_documentos()

    def estadisticas(self) -> Dict[str, Any]:
        return self.store.estadisticas()
