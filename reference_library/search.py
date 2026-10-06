"""Búsqueda semántica sobre el conocimiento de las referencias.

La similitud combina el coseno entre embeddings con una similitud léxica de los rótulos
normalizados: los embeddings aportan el significado ("identificación fiscal" ~ "NIT") y el
componente léxico evita que un rótulo casi idéntico quede por debajo de uno solo parecido
en significado. El resultado es una señal para decidir, nunca la única fuente de verdad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from reference_library.embeddings import ProveedorEmbeddings, obtener_proveedor
from reference_library.extractor import FUENTE_PLANTILLA, FUENTE_VALOR, normalizar_etiqueta
from reference_library.store import ReferenceStore
from reference_library.vector_index import IndiceNumpy

try:
    from rapidfuzz import fuzz as _fuzz
except ImportError:  # pragma: no cover - rapidfuzz forma parte de requirements.txt
    _fuzz = None  # type: ignore

# Orígenes de correspondencia con evidencia real (un valor diligenciado o un plan verificado).
FUENTES_VALIDADAS = (FUENTE_VALOR, FUENTE_PLANTILLA)

PESO_EMBEDDING_POR_DEFECTO = 0.5
LOTE_EMBEDDINGS = 128


@dataclass(frozen=True)
class ResultadoBusqueda:
    """Un conocimiento encontrado, con su documento de origen, ubicación y señales de similitud."""

    campo_id: int
    doc_id: str
    documento: str
    familia: str
    etiqueta: str
    campo_maestro: Optional[str]
    fuente_campo: str
    confianza_campo: float
    similitud: float
    sim_embedding: float
    sim_lexica: float
    hoja: str
    coordenada: str
    seccion: str
    contexto_fila: str
    ejemplo_valor: str
    ubicacion: str
    vecinos: List[str] = field(default_factory=list)
    documentos: List[str] = field(default_factory=list)

    @property
    def validado(self) -> bool:
        """True si la correspondencia con el campo maestro tiene evidencia real."""
        return bool(self.campo_maestro) and self.fuente_campo in FUENTES_VALIDADAS


def texto_para_embedding(etiqueta: str, seccion: str = "") -> str:
    """Texto que se vectoriza para un rótulo (consulta y conocimiento usan la misma función)."""
    return str(etiqueta).strip()


def _sim_lexica(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return float(_fuzz.token_set_ratio(a, b)) / 100.0 if _fuzz is not None else 0.0


class BuscadorSemantico:
    """Indexa (de forma incremental) los rótulos de la base y los consulta por similitud."""

    def __init__(
        self,
        store: ReferenceStore,
        proveedor: Optional[ProveedorEmbeddings] = None,
        peso_embedding: float = PESO_EMBEDDING_POR_DEFECTO,
    ) -> None:
        self.store = store
        self.proveedor = proveedor or obtener_proveedor()
        self.peso_embedding = peso_embedding
        self._indice: IndiceNumpy = IndiceNumpy.vacio()
        self._meta: Dict[int, Dict[str, Any]] = {}
        self._huella_cargada: Optional[str] = None
        self._cache_consultas: Dict[str, np.ndarray] = {}

    # ── Indexación ───────────────────────────────────────────────────────

    def reindexar(self, forzar: bool = False) -> int:
        """Genera los embeddings que faltan y recarga el índice. Devuelve cuántos vectores creó."""
        pendientes = self.store.campos_sin_vector(self.proveedor.nombre)
        creados = 0
        if pendientes:
            textos = [texto_para_embedding(p["etiqueta"], p["seccion"]) for p in pendientes]
            unicos = sorted(set(textos))
            vectores: Dict[str, np.ndarray] = {}
            for inicio in range(0, len(unicos), LOTE_EMBEDDINGS):
                lote = unicos[inicio:inicio + LOTE_EMBEDDINGS]
                for texto, vector in zip(lote, self.proveedor.embed(lote)):
                    vectores[texto] = vector
            self.store.guardar_vectores(
                self.proveedor.nombre, [(p["id"], vectores[t]) for p, t in zip(pendientes, textos)]
            )
            creados = len(pendientes)

        huella = self.store.huella_conocimiento()
        if forzar or creados or huella != self._huella_cargada:
            ids, matriz = self.store.cargar_vectores(self.proveedor.nombre)
            self._indice = IndiceNumpy(ids, matriz) if len(ids) else IndiceNumpy.vacio()
            self._meta = {int(c["id"]): c for c in self.store.listar_campos()}
            self._huella_cargada = huella
        return creados

    def _asegurar_indice(self) -> None:
        if self._huella_cargada != self.store.huella_conocimiento():
            self.reindexar()

    # ── Consulta ─────────────────────────────────────────────────────────

    def _vectores_consulta(self, consultas: Sequence[str]) -> List[np.ndarray]:
        textos = [texto_para_embedding(c) for c in consultas]
        faltantes = sorted({t for t in textos if t not in self._cache_consultas})
        if faltantes:
            for texto, vector in zip(faltantes, self.proveedor.embed(faltantes)):
                self._cache_consultas[texto] = vector
        return [self._cache_consultas[t] for t in textos]

    def buscar(
        self,
        consulta: str,
        top_k: int = 5,
        solo_con_campo_maestro: bool = False,
        solo_validados: bool = False,
        familia: Optional[str] = None,
        excluir_doc_ids: Iterable[str] = (),
        umbral: float = 0.0,
    ) -> List[ResultadoBusqueda]:
        """Los ``top_k`` conocimientos más parecidos a ``consulta``, sin repetir rótulos iguales."""
        return self.buscar_lote(
            [consulta], top_k, solo_con_campo_maestro, solo_validados, familia, excluir_doc_ids, umbral
        )[0]

    def buscar_lote(
        self,
        consultas: Sequence[str],
        top_k: int = 5,
        solo_con_campo_maestro: bool = False,
        solo_validados: bool = False,
        familia: Optional[str] = None,
        excluir_doc_ids: Iterable[str] = (),
        umbral: float = 0.0,
    ) -> List[List[ResultadoBusqueda]]:
        """Igual que ``buscar`` pero vectoriza todas las consultas juntas (mucho más rápido)."""
        self._asegurar_indice()
        if not consultas or len(self._indice) == 0:
            return [[] for _ in consultas]

        excluidos = set(excluir_doc_ids)
        permitidos = np.array(
            [
                self._cumple(self._meta[int(i)], solo_con_campo_maestro, solo_validados, familia, excluidos)
                for i in self._indice.ids
            ],
            dtype=bool,
        )
        if not permitidos.any():
            return [[] for _ in consultas]

        resultados: List[List[ResultadoBusqueda]] = []
        pool = max(top_k * 12, 60)
        for texto, vector in zip(consultas, self._vectores_consulta(consultas)):
            consulta_norm = normalizar_etiqueta(texto)
            candidatos = self._indice.buscar(vector, pool, permitidos)
            puntuados: List[Tuple[float, float, float, int]] = []
            for campo_id, sim_emb in candidatos:
                sim_lex = _sim_lexica(consulta_norm, self._meta[campo_id]["etiqueta_norm"])
                similitud = self.peso_embedding * max(sim_emb, 0.0) + (1.0 - self.peso_embedding) * sim_lex
                if sim_lex == 1.0:
                    similitud = max(similitud, 1.0)
                puntuados.append((similitud, sim_emb, sim_lex, campo_id))
            puntuados.sort(key=lambda t: t[0], reverse=True)
            resultados.append(self._agrupar(puntuados, top_k, umbral))
        return resultados

    @staticmethod
    def _cumple(
        meta: Dict[str, Any],
        solo_con_campo_maestro: bool,
        solo_validados: bool,
        familia: Optional[str],
        excluidos: set,
    ) -> bool:
        if meta["doc_id"] in excluidos:
            return False
        if familia is not None and meta["familia"] != familia:
            return False
        if solo_validados:
            return bool(meta["campo_maestro"]) and meta["fuente_campo"] in FUENTES_VALIDADAS
        return bool(meta["campo_maestro"]) if solo_con_campo_maestro else True

    def _agrupar(
        self,
        puntuados: List[Tuple[float, float, float, int]],
        top_k: int,
        umbral: float,
    ) -> List[ResultadoBusqueda]:
        """Une los rótulos idénticos (mismo texto y campo) de distintos documentos en un resultado."""
        grupos: Dict[Tuple[str, Optional[str]], List[Tuple[float, float, float, int]]] = {}
        orden: List[Tuple[str, Optional[str]]] = []
        for item in puntuados:
            meta = self._meta[item[3]]
            clave = (meta["etiqueta_norm"], meta["campo_maestro"])
            if clave not in grupos:
                if len(grupos) >= top_k:
                    continue
                grupos[clave] = []
                orden.append(clave)
            grupos[clave].append(item)

        detalles = self.store.obtener_campos([grupos[c][0][3] for c in orden])
        resultado: List[ResultadoBusqueda] = []
        for clave in orden:
            similitud, sim_emb, sim_lex, campo_id = grupos[clave][0]
            if similitud < umbral:
                continue
            registro = detalles[campo_id]
            documentos = sorted({self._meta[i[3]]["documento"] for i in grupos[clave]})
            resultado.append(
                ResultadoBusqueda(
                    campo_id=campo_id,
                    doc_id=registro["doc_id"],
                    documento=registro["documento"],
                    familia=registro["familia"],
                    etiqueta=registro["etiqueta"],
                    campo_maestro=registro["campo_maestro"],
                    fuente_campo=registro["fuente_campo"],
                    confianza_campo=float(registro["confianza"]),
                    similitud=round(float(similitud), 4),
                    sim_embedding=round(float(sim_emb), 4),
                    sim_lexica=round(float(sim_lex), 4),
                    hoja=registro["hoja"],
                    coordenada=registro["coordenada"],
                    seccion=registro["seccion"],
                    contexto_fila=registro["contexto_fila"],
                    ejemplo_valor=registro["ejemplo_valor"],
                    ubicacion=registro["ubicacion"],
                    vecinos=registro["vecinos"],
                    documentos=documentos,
                )
            )
        return resultado
