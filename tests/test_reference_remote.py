"""Persistencia remota de la biblioteca de referencias (ADR-0016)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from reference_library import ReferenceLibrary, ReferenceStore
from reference_library.extractor import extraccion_a_dict, extraccion_desde_dict, extraer_conocimiento
from reference_library.remote import EntradaRemota, SincronizadorNube
from reference_library.repositorio_supabase import RepositorioSupabase, ruta_de_almacenamiento
from reference_library.settings import EXTRACTOR_VERSION
from referencias_helpers import DATOS_EMPRESA, _diligenciado, _en_blanco


class RepositorioMemoria:
    """Repositorio remoto de prueba que imita las reglas RLS: solo un administrador escribe."""

    def __init__(self, es_admin: bool = True) -> None:
        self.es_admin = es_admin
        self.filas: Dict[str, Dict[str, Any]] = {}
        self.archivos: Dict[str, bytes] = {}
        self.descargas = 0

    def _exigir_admin(self) -> None:
        if not self.es_admin:
            raise PermissionError("Solo un administrador puede escribir.")

    def listar(self) -> List[EntradaRemota]:
        return [fila["entrada"] for fila in self.filas.values()]

    def obtener_conocimiento(self, clave: str) -> Optional[Dict[str, Any]]:
        return self.filas[clave]["conocimiento"]

    def descargar(self, clave: str) -> bytes:
        self.descargas += 1
        return self.archivos[clave]

    def publicar(self, entrada: EntradaRemota, contenido: bytes, conocimiento: Dict[str, Any]) -> None:
        self._exigir_admin()
        self.filas[entrada.clave] = {"entrada": entrada, "conocimiento": conocimiento}
        self.archivos[entrada.clave] = contenido

    def guardar_conocimiento(self, entrada: EntradaRemota, conocimiento: Dict[str, Any]) -> None:
        self._exigir_admin()
        self.filas[entrada.clave] = {"entrada": entrada, "conocimiento": conocimiento}

    def eliminar(self, clave: str) -> None:
        self._exigir_admin()
        self.filas.pop(clave, None)
        self.archivos.pop(clave, None)


def _biblioteca(tmp_path: Path, nombre: str = "equipo", extractor=extraer_conocimiento) -> ReferenceLibrary:
    directorio = tmp_path / nombre / "referencias"
    directorio.mkdir(parents=True, exist_ok=True)
    return ReferenceLibrary(
        directorio, ReferenceStore(tmp_path / nombre / "c.db"), datos_empresa=DATOS_EMPRESA, extractor=extractor
    )


def _extractor_prohibido(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("No debía volver a analizarse el Excel: bastaba la instantánea.")


def test_la_instantanea_conserva_todo_el_conocimiento() -> None:
    original = extraer_conocimiento(_diligenciado(), "f.xlsx", DATOS_EMPRESA)

    copia = extraccion_desde_dict(extraccion_a_dict(original))

    assert copia.campos == original.campos
    assert copia.estructura == original.estructura
    assert copia.plantilla_id == original.plantilla_id


def test_un_administrador_publica_y_otra_maquina_reconstruye_sin_descargar_ni_reanalizar(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    administrador = SincronizadorNube(_biblioteca(tmp_path, "admin"), repo, puede_escribir=True)
    doc_id = administrador.subir(_diligenciado(), "uno.xlsx", "proveedor", DATOS_EMPRESA)

    assert repo.archivos["proveedor/uno.xlsx"]
    assert administrador.biblioteca.store.obtener_documento(doc_id).origen == "nube"

    # Reinicio en la nube: disco vacío, usuario sin permisos de escritura.
    nueva = _biblioteca(tmp_path, "reinicio", extractor=_extractor_prohibido)
    reporte = SincronizadorNube(nueva, repo, puede_escribir=False).sincronizar(DATOS_EMPRESA)

    assert reporte.agregados == ["uno.xlsx"] and not reporte.errores
    assert repo.descargas == 0
    documento = nueva.listar()[0]
    assert documento.familia == "proveedor" and documento.origen == "nube"
    assert any(c["campo_maestro"] == "nit" for c in nueva.store.listar_campos())


def test_un_usuario_sin_permisos_no_puede_publicar_ni_eliminar(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=False)
    asesor = SincronizadorNube(_biblioteca(tmp_path), repo, puede_escribir=False)

    with pytest.raises(PermissionError):
        asesor.subir(_diligenciado(), "uno.xlsx")
    with pytest.raises(PermissionError):
        asesor.eliminar("cualquiera")
    assert repo.filas == {}


def test_el_servidor_rechaza_la_escritura_aunque_el_cliente_crea_poder(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=False)
    enganado = SincronizadorNube(_biblioteca(tmp_path), repo, puede_escribir=True)

    with pytest.raises(PermissionError):
        enganado.subir(_diligenciado(), "uno.xlsx")


def test_una_instantanea_obsoleta_se_reanaliza_y_solo_un_administrador_la_actualiza(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    SincronizadorNube(_biblioteca(tmp_path, "admin"), repo, puede_escribir=True).subir(
        _diligenciado(), "uno.xlsx", "", DATOS_EMPRESA
    )
    clave = "uno.xlsx"
    repo.filas[clave]["entrada"] = replace(repo.filas[clave]["entrada"], version_extractor="0-vieja")

    repo.es_admin = False
    lector = SincronizadorNube(_biblioteca(tmp_path, "lector"), repo, puede_escribir=False)
    reporte = lector.sincronizar(DATOS_EMPRESA)

    assert reporte.agregados == ["uno.xlsx"] and repo.descargas == 1
    assert repo.filas[clave]["entrada"].version_extractor == "0-vieja"  # un lector no reescribe la nube

    repo.es_admin = True
    SincronizadorNube(_biblioteca(tmp_path, "admin2"), repo, puede_escribir=True).sincronizar(DATOS_EMPRESA)
    assert repo.filas[clave]["entrada"].version_extractor == EXTRACTOR_VERSION


def test_cambiar_los_datos_de_la_empresa_reanaliza_las_referencias_de_la_nube(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    SincronizadorNube(_biblioteca(tmp_path, "admin"), repo, puede_escribir=True).subir(
        _diligenciado(), "uno.xlsx", "", {}
    )
    lector = SincronizadorNube(_biblioteca(tmp_path, "lector"), repo, puede_escribir=False)

    lector.sincronizar(DATOS_EMPRESA)

    assert repo.descargas == 1


def test_lo_que_se_borra_de_la_nube_se_retira_de_la_base_local(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    admin = SincronizadorNube(_biblioteca(tmp_path, "admin"), repo, puede_escribir=True)
    admin.subir(_diligenciado(), "uno.xlsx", "", DATOS_EMPRESA)
    lector_biblioteca = _biblioteca(tmp_path, "lector")
    lector = SincronizadorNube(lector_biblioteca, repo)
    lector.sincronizar(DATOS_EMPRESA)
    assert len(lector_biblioteca.listar()) == 1

    repo.eliminar("uno.xlsx")
    reporte = lector.sincronizar(DATOS_EMPRESA)

    assert reporte.eliminados == ["uno.xlsx"]
    assert lector_biblioteca.listar() == []


def test_eliminar_quita_archivo_conocimiento_y_documento(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    admin = SincronizadorNube(_biblioteca(tmp_path), repo, puede_escribir=True)
    doc_id = admin.subir(_diligenciado(), "uno.xlsx", "", DATOS_EMPRESA)

    assert admin.eliminar(doc_id) is True

    assert repo.filas == {} and repo.archivos == {}
    assert admin.biblioteca.store.listar_campos() == []
    assert admin.eliminar(doc_id) is False


def test_la_sincronizacion_local_no_toca_lo_que_vive_en_la_nube(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    biblioteca = _biblioteca(tmp_path)
    SincronizadorNube(biblioteca, repo, puede_escribir=True).subir(_diligenciado(), "uno.xlsx", "", DATOS_EMPRESA)

    reporte = biblioteca.sincronizar(datos_empresa=DATOS_EMPRESA)  # carpeta local vacía

    assert reporte.eliminados == []
    assert [d.nombre for d in biblioteca.listar()] == ["uno.xlsx"]


def test_publicar_locales_sube_solo_lo_que_falta(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    biblioteca = _biblioteca(tmp_path)
    (biblioteca.directorio / "proveedor").mkdir()
    (biblioteca.directorio / "proveedor" / "a.xlsx").write_bytes(_diligenciado())
    (biblioteca.directorio / "b.xlsx").write_bytes(_en_blanco())
    biblioteca.sincronizar(datos_empresa=DATOS_EMPRESA)
    nube = SincronizadorNube(biblioteca, repo, puede_escribir=True)

    primera = nube.publicar_locales(DATOS_EMPRESA)
    segunda = nube.publicar_locales(DATOS_EMPRESA)

    assert sorted(primera.agregados) == ["a.xlsx", "b.xlsx"]
    assert segunda.agregados == [] and sorted(segunda.sin_cambios) == ["a.xlsx", "b.xlsx"]
    assert set(repo.filas) == {"proveedor/a.xlsx", "b.xlsx"}


def test_reprocesar_un_documento_de_la_nube_actualiza_su_instantanea(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    admin = SincronizadorNube(_biblioteca(tmp_path), repo, puede_escribir=True)
    doc_id = admin.subir(_diligenciado(), "uno.xlsx", "", DATOS_EMPRESA)
    repo.filas["uno.xlsx"]["conocimiento"] = {"campos": [], "estructura": {}}

    admin.reprocesar(doc_id, DATOS_EMPRESA)

    assert repo.descargas == 1
    assert repo.filas["uno.xlsx"]["conocimiento"]["campos"]


def test_un_archivo_remoto_ilegible_se_registra_como_error_sin_romper_el_resto(tmp_path: Path) -> None:
    repo = RepositorioMemoria(es_admin=True)
    SincronizadorNube(_biblioteca(tmp_path, "admin"), repo, puede_escribir=True).subir(
        _diligenciado(), "bueno.xlsx", "", DATOS_EMPRESA
    )
    repo.filas["roto.xlsx"] = {
        "entrada": EntradaRemota("roto.xlsx", "roto.xlsx", "", "abc", "referencia", 0.75, "", "", False),
        "conocimiento": None,
    }
    repo.archivos["roto.xlsx"] = b"no es un excel"

    reporte = SincronizadorNube(_biblioteca(tmp_path, "lector"), repo).sincronizar(DATOS_EMPRESA)

    assert reporte.agregados == ["bueno.xlsx"] and "roto.xlsx" in reporte.errores


# ── Repositorio Supabase con un cliente simulado ────────────────────────────

class _Consulta:
    def __init__(self, cliente: "_ClienteFalso", tabla: str) -> None:
        self.cliente, self.tabla = cliente, tabla
        self.operacion, self.payload, self.filtros = "select", None, {}

    def select(self, columnas: str) -> "_Consulta":
        self.operacion = "select"
        return self

    def eq(self, columna: str, valor: Any) -> "_Consulta":
        self.filtros[columna] = valor
        return self

    def order(self, *_a: Any, **_k: Any) -> "_Consulta":
        return self

    def limit(self, *_a: Any, **_k: Any) -> "_Consulta":
        return self

    def upsert(self, payload: Dict[str, Any], on_conflict: str = "") -> "_Consulta":
        self.operacion, self.payload = "upsert", payload
        return self

    def update(self, payload: Dict[str, Any]) -> "_Consulta":
        self.operacion, self.payload = "update", payload
        return self

    def delete(self) -> "_Consulta":
        self.operacion = "delete"
        return self

    def execute(self) -> Any:
        filas = self.cliente.filas
        if self.operacion != "select" and not self.cliente.es_admin:
            raise Exception('new row violates row-level security policy for table "referencias_catalogo" (42501)')
        if self.operacion == "select":
            datos = [f for f in filas.values() if all(f.get(k) == v for k, v in self.filtros.items())]
            return SimpleNamespace(data=datos)
        if self.operacion == "upsert":
            filas[self.payload["clave"]] = {**self.payload, "tiene_conocimiento": self.payload.get("conocimiento") is not None}
        elif self.operacion == "update":
            filas[self.filtros["clave"]].update(self.payload)
        else:
            filas.pop(self.filtros["clave"], None)
        return SimpleNamespace(data=[])


class _Bucket:
    def __init__(self, cliente: "_ClienteFalso") -> None:
        self.cliente = cliente

    def upload(self, ruta: str, contenido: bytes, opciones: Dict[str, str]) -> None:
        if not self.cliente.es_admin:
            raise Exception("new row violates row-level security policy (42501)")
        self.cliente.objetos[ruta] = contenido
        self.cliente.opciones_subida = opciones

    def download(self, ruta: str) -> bytes:
        return self.cliente.objetos[ruta]

    def remove(self, rutas: List[str]) -> None:
        for ruta in rutas:
            self.cliente.objetos.pop(ruta, None)


class _ClienteFalso:
    def __init__(self, es_admin: bool = True) -> None:
        self.es_admin = es_admin
        self.filas: Dict[str, Dict[str, Any]] = {}
        self.objetos: Dict[str, bytes] = {}
        self.opciones_subida: Dict[str, str] = {}
        self.storage = SimpleNamespace(session=SimpleNamespace(headers={}), from_=lambda bucket: _Bucket(self))

    def table(self, nombre: str) -> _Consulta:
        return _Consulta(self, nombre)


def test_el_repositorio_supabase_publica_lista_descarga_y_elimina() -> None:
    cliente = _ClienteFalso(es_admin=True)
    repo = RepositorioSupabase(cliente, access_token="jwt-de-prueba")
    entrada = EntradaRemota("proveedor/Fórmulario (1).xlsx", "Fórmulario (1).xlsx", "proveedor", "h1", "referencia", 0.75, "1", "x", True)

    repo.publicar(entrada, b"contenido", {"campos": []})

    ruta = ruta_de_almacenamiento(entrada.clave)
    assert cliente.objetos[ruta] == b"contenido"
    assert cliente.opciones_subida["upsert"] == "true"
    assert cliente.storage.session.headers["Authorization"] == "Bearer jwt-de-prueba"
    assert repo.listar() == [entrada]
    assert repo.obtener_conocimiento(entrada.clave) == {"campos": []}
    assert repo.descargar(entrada.clave) == b"contenido"

    repo.eliminar(entrada.clave)
    assert cliente.objetos == {} and cliente.filas == {}


def test_los_nombres_de_objeto_no_dependen_de_caracteres_especiales() -> None:
    ruta = ruta_de_almacenamiento("proveedor/Fórmulario ñandú (1).xlsx")

    assert ruta.endswith(".xlsx") and ruta.replace(".xlsx", "").isalnum()
    assert ruta == ruta_de_almacenamiento("proveedor/Fórmulario ñandú (1).xlsx")


def test_el_repositorio_supabase_traduce_el_rechazo_de_rls_a_permission_error() -> None:
    repo = RepositorioSupabase(_ClienteFalso(es_admin=False))
    entrada = EntradaRemota("a.xlsx", "a.xlsx", "", "h", "referencia", 0.75, "1", "x", True)

    with pytest.raises(PermissionError):
        repo.publicar(entrada, b"x", {})
