"""Persistencia remota de la biblioteca de referencias (ADR-0016).

Los formularios de referencia contienen datos reales y el repositorio es público, así que no se
versionan. En la nube viven en un almacenamiento privado y su *conocimiento ya extraído* se guarda
como instantánea JSON: al reiniciar la app (disco efímero) la base local se reconstruye importando
instantáneas, sin volver a escanear los Excel. El archivo solo se descarga y reprocesa cuando la
instantánea no sirve (cambió el extractor o los datos de la empresa).

``RepositorioRemoto`` es la interfaz; ``repositorio_supabase`` es su implementación de producción.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, List

from reference_library.extractor import (
    ExtraccionDocumento,
    extraccion_a_dict,
    extraccion_desde_dict,
    huella_datos_empresa,
)
from reference_library.library import (
    ReferenceLibrary,
    ReporteSincronizacion,
    calcular_hash,
    doc_id_para,
)
from reference_library.settings import EXTENSIONES_SOPORTADAS, EXTRACTOR_VERSION

PREFIJO_NUBE = "nube/"


@dataclass(frozen=True)
class EntradaRemota:
    """Una referencia del catálogo remoto (sin su conocimiento, que se pide aparte)."""

    clave: str
    nombre: str
    familia: str
    hash_contenido: str
    fuente: str
    confianza: float
    version_extractor: str
    huella_datos: str
    tiene_conocimiento: bool


class RepositorioRemoto(Protocol):
    """Contrato mínimo de un almacenamiento remoto de referencias."""

    def listar(self) -> List[EntradaRemota]: ...

    def obtener_conocimiento(self, clave: str) -> Optional[Dict[str, Any]]: ...

    def descargar(self, clave: str) -> bytes: ...

    def publicar(
        self,
        entrada: EntradaRemota,
        contenido: bytes,
        conocimiento: Dict[str, Any],
    ) -> None:
        """Guarda archivo y conocimiento. Falla con ``PermissionError`` si el usuario no es administrador."""
        ...

    def guardar_conocimiento(self, entrada: EntradaRemota, conocimiento: Dict[str, Any]) -> None: ...

    def eliminar(self, clave: str) -> None: ...


class SincronizadorNube:
    """Mantiene la base local alineada con el repositorio remoto (la fuente persistente en la nube)."""

    def __init__(
        self,
        biblioteca: ReferenceLibrary,
        repositorio: RepositorioRemoto,
        puede_escribir: bool = False,
    ) -> None:
        self.biblioteca = biblioteca
        self.repositorio = repositorio
        self.puede_escribir = puede_escribir

    # ── Utilidades ───────────────────────────────────────────────────────

    @staticmethod
    def clave_de(nombre: str, familia: str = "") -> str:
        return f"{familia}/{nombre}" if familia else nombre

    def _importar(
        self,
        entrada: EntradaRemota,
        extraccion: ExtraccionDocumento,
        huella: str,
        hash_contenido: Optional[str] = None,
    ) -> str:
        doc_id = doc_id_para(PREFIJO_NUBE + entrada.clave)
        self.biblioteca.store.reemplazar_documento(
            doc_id=doc_id, ruta=PREFIJO_NUBE + entrada.clave, nombre=entrada.nombre, familia=entrada.familia,
            hash_contenido=hash_contenido or entrada.hash_contenido, huella_datos=huella, fuente=entrada.fuente,
            confianza=entrada.confianza, version_extractor=EXTRACTOR_VERSION, plantilla_id=extraccion.plantilla_id,
            estructura=extraccion.estructura, campos=extraccion.campos, origen="nube",
        )
        return doc_id

    # ── Sincronización (lectura) ─────────────────────────────────────────

    def sincronizar(self, datos_empresa: Optional[Dict[str, Any]] = None) -> ReporteSincronizacion:
        """Importa a la base local lo nuevo o cambiado del repositorio y retira lo que ya no existe."""
        reporte = ReporteSincronizacion()
        datos = self.biblioteca.datos_empresa_actuales() if datos_empresa is None else dict(datos_empresa)
        huella = huella_datos_empresa(datos)
        store = self.biblioteca.store
        presentes = set()

        for entrada in self.repositorio.listar():
            doc_id = doc_id_para(PREFIJO_NUBE + entrada.clave)
            presentes.add(doc_id)
            previo = store.obtener_documento(doc_id)
            if (
                previo and previo.estado == "ok" and previo.hash_contenido == entrada.hash_contenido
                and previo.version_extractor == EXTRACTOR_VERSION and previo.huella_datos == huella
            ):
                reporte.sin_cambios.append(entrada.nombre)
                continue

            try:
                extraccion = self._extraccion(entrada, datos, huella)
                self._importar(entrada, extraccion[0], huella, extraccion[1])
            except Exception as exc:
                store.registrar_error(
                    doc_id, PREFIJO_NUBE + entrada.clave, entrada.nombre, entrada.familia, entrada.hash_contenido,
                    huella, EXTRACTOR_VERSION, f"{type(exc).__name__}: {exc}", origen="nube",
                )
                reporte.errores[entrada.nombre] = f"{type(exc).__name__}: {exc}"
                continue
            (reporte.actualizados if previo else reporte.agregados).append(entrada.nombre)

        for doc in store.listar_documentos(origen="nube"):
            if doc.doc_id not in presentes:
                store.eliminar_documento(doc.doc_id)
                reporte.eliminados.append(doc.nombre)
        return reporte

    def _extraccion(self, entrada: EntradaRemota, datos: Dict[str, Any], huella: str):
        """Instantánea vigente si existe; si no, descarga el archivo y lo analiza (y la actualiza si puede)."""
        if (
            entrada.tiene_conocimiento and entrada.version_extractor == EXTRACTOR_VERSION
            and entrada.huella_datos == huella
        ):
            instantanea = self.repositorio.obtener_conocimiento(entrada.clave)
            if instantanea:
                return extraccion_desde_dict(instantanea), entrada.hash_contenido

        contenido = self.repositorio.descargar(entrada.clave)
        extraccion = self.biblioteca.extraer(contenido, entrada.nombre, datos)
        hash_real = calcular_hash(contenido)
        if self.puede_escribir:
            try:
                actualizada = EntradaRemota(
                    entrada.clave, entrada.nombre, entrada.familia, hash_real, entrada.fuente, entrada.confianza,
                    EXTRACTOR_VERSION, huella, True,
                )
                self.repositorio.guardar_conocimiento(actualizada, extraccion_a_dict(extraccion))
            except Exception as exc:  # actualizar la instantánea es una optimización, no un requisito
                print(f"[ReferenceLibrary] No se pudo actualizar la instantánea de '{entrada.nombre}': {exc}")
        return extraccion, hash_real

    # ── Escritura (solo administradores; la política RLS lo exige también en el servidor) ──

    def subir(
        self,
        contenido: bytes,
        nombre: str,
        familia: str = "",
        datos_empresa: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Analiza un formulario, lo publica (archivo + conocimiento) y lo deja disponible localmente."""
        if not self.puede_escribir:
            raise PermissionError("Solo un administrador puede publicar referencias en la nube.")
        from pathlib import Path

        nombre_final = Path(nombre).name
        if Path(nombre_final).suffix.lower() not in EXTENSIONES_SOPORTADAS:
            raise ValueError(f"Formato no soportado: solo {', '.join(EXTENSIONES_SOPORTADAS)}.")
        familia_limpia = Path(familia).name if familia else ""
        clave = self.clave_de(nombre_final, familia_limpia)
        datos = self.biblioteca.datos_empresa_actuales() if datos_empresa is None else dict(datos_empresa)
        huella = huella_datos_empresa(datos)

        try:
            extraccion = self.biblioteca.extraer(contenido, nombre_final, datos)
        except Exception as exc:
            raise ValueError(f"No se pudo procesar '{nombre_final}': {type(exc).__name__}: {exc}") from exc

        _, fuente, confianza = self.biblioteca.metadatos_de(clave, nombre_final)
        entrada = EntradaRemota(
            clave, nombre_final, familia_limpia, calcular_hash(contenido), fuente, confianza,
            EXTRACTOR_VERSION, huella, True,
        )
        self.repositorio.publicar(entrada, contenido, extraccion_a_dict(extraccion))
        return self._importar(entrada, extraccion, huella)

    def reprocesar(self, doc_id: str, datos_empresa: Optional[Dict[str, Any]] = None) -> None:
        """Descarga un formulario de la nube, vuelve a analizarlo y actualiza su instantánea."""
        doc = self.biblioteca.store.obtener_documento(doc_id)
        if doc is None or doc.origen != "nube":
            raise ValueError("La referencia no pertenece a la nube.")
        clave = doc.ruta[len(PREFIJO_NUBE):]
        entrada = next((e for e in self.repositorio.listar() if e.clave == clave), None)
        if entrada is None:
            raise ValueError("La referencia ya no existe en la nube.")
        datos = self.biblioteca.datos_empresa_actuales() if datos_empresa is None else dict(datos_empresa)
        huella = huella_datos_empresa(datos)
        contenido = self.repositorio.descargar(clave)
        extraccion = self.biblioteca.extraer(contenido, entrada.nombre, datos)
        hash_real = calcular_hash(contenido)
        if self.puede_escribir:
            actualizada = EntradaRemota(
                clave, entrada.nombre, entrada.familia, hash_real, entrada.fuente, entrada.confianza,
                EXTRACTOR_VERSION, huella, True,
            )
            self.repositorio.guardar_conocimiento(actualizada, extraccion_a_dict(extraccion))
        self._importar(entrada, extraccion, huella, hash_real)

    def eliminar(self, doc_id: str) -> bool:
        """Retira una referencia de la nube (archivo y conocimiento) y de la base local."""
        if not self.puede_escribir:
            raise PermissionError("Solo un administrador puede eliminar referencias de la nube.")
        doc = self.biblioteca.store.obtener_documento(doc_id)
        if doc is None or doc.origen != "nube":
            return False
        self.repositorio.eliminar(doc.ruta[len(PREFIJO_NUBE):])
        return self.biblioteca.store.eliminar_documento(doc_id)

    def publicar_locales(self, datos_empresa: Optional[Dict[str, Any]] = None) -> ReporteSincronizacion:
        """Sube a la nube las referencias de la carpeta local que todavía no están publicadas."""
        reporte = ReporteSincronizacion()
        remotas = {(e.clave, e.hash_contenido) for e in self.repositorio.listar()}
        for archivo in self.biblioteca.archivos_locales():
            familia, _, _ = self.biblioteca.metadatos_de(self.biblioteca.clave_de(archivo), archivo.name)
            contenido = archivo.read_bytes()
            clave = self.clave_de(archivo.name, familia)
            if (clave, calcular_hash(contenido)) in remotas:
                reporte.sin_cambios.append(archivo.name)
                continue
            try:
                self.subir(contenido, archivo.name, familia, datos_empresa)
                reporte.agregados.append(archivo.name)
            except PermissionError:
                raise
            except Exception as exc:
                reporte.errores[archivo.name] = str(exc)
        return reporte
