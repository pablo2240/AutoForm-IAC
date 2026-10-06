"""Few-shot dinámico: selecciona, para cada lote de rótulos, solo los ejemplos más útiles.

Flujo por lote: rótulos del formulario nuevo -> búsqueda semántica -> candidatos con evidencia real
-> selección (primero la familia detectada, luego el resto) -> como máximo ``top_k`` ejemplos para
el LLM. Nunca se envían documentos completos; cada ejemplo ocupa una línea corta.

Solo se usan correspondencias con evidencia real (valor de ejemplo coincidente o plantilla ya
verificada). Los campos del responsable comercial se excluyen: tienen reglas de aislamiento propias
(ADR-0007/0009) y las valida el motor determinista de todas formas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from core.domain_constants import CAMPOS_RESPONSABLE_COMERCIAL
from reference_library.extractor import normalizar_etiqueta
from reference_library.search import BuscadorSemantico, ResultadoBusqueda


TOP_K_POR_DEFECTO = 5
UMBRAL_SIMILITUD = 0.6
CANDIDATOS_POR_ROTULO = 3
MAX_EJEMPLOS_POR_ROTULO = 2


def top_k_configurado() -> int:
    """``AUTOFORM_FEWSHOT_TOP_K``: 0 desactiva el few-shot; sin definir usa 5."""
    valor = os.getenv("AUTOFORM_FEWSHOT_TOP_K", "").strip()
    if not valor:
        return TOP_K_POR_DEFECTO
    try:
        return max(int(valor), 0)
    except ValueError:
        return TOP_K_POR_DEFECTO


def umbral_configurado() -> float:
    """``AUTOFORM_FEWSHOT_UMBRAL``: similitud mínima (0-1) de un ejemplo; sin definir usa 0.6."""
    try:
        return min(max(float(os.getenv("AUTOFORM_FEWSHOT_UMBRAL", "").strip()), 0.0), 1.0)
    except ValueError:
        return UMBRAL_SIMILITUD


@dataclass(frozen=True)
class EjemploFewShot:
    """Un caso resuelto de una referencia que sirve de guía para un rótulo nuevo."""

    rotulo: str
    campo: str
    seccion: str
    similitud: float
    documento: str
    familia: str
    rotulo_nuevo: str

    def para_prompt(self) -> Dict[str, Any]:
        """Representación compacta para el LLM (sin rutas, coordenadas ni valores de otras empresas)."""
        ejemplo = {"rotulo_ref": self.rotulo, "campo": self.campo, "similitud": round(self.similitud, 2)}
        if self.seccion:
            ejemplo["seccion_ref"] = self.seccion
        return ejemplo

    def para_registro(self) -> Dict[str, Any]:
        return {**self.para_prompt(), "documento": self.documento, "familia": self.familia, "para": self.rotulo_nuevo}


def _texto_rotulo(campo: Dict[str, Any]) -> str:
    return str(campo.get("rotulo") or campo.get("valor") or "").strip()


def _contexto_rotulo(campo: Dict[str, Any]) -> str:
    return str(campo.get("_seccion_titulo") or campo.get("seccion") or "").strip()


class GeneradorFewShot:
    """Genera ejemplos few-shot a partir del buscador semántico."""

    def __init__(
        self,
        buscador: BuscadorSemantico,
        top_k: Optional[int] = None,
        umbral: Optional[float] = None,
    ) -> None:
        self.buscador = buscador
        self.top_k = top_k_configurado() if top_k is None else max(top_k, 0)
        self.umbral = umbral_configurado() if umbral is None else umbral

    def ejemplos_para_lote(
        self,
        campos_lote: Sequence[Dict[str, Any]],
        familia: Optional[str] = None,
        campos_validos: Optional[Set[str]] = None,
        excluir_doc_ids: Iterable[str] = (),
        top_k: Optional[int] = None,
    ) -> List[EjemploFewShot]:
        """Como máximo ``top_k`` ejemplos para el lote, priorizando la familia detectada.

        ``campos_validos`` restringe los campos que un ejemplo puede proponer (los del modelo
        maestro de la empresa), de modo que una referencia nunca introduce campos inexistentes.
        """
        limite = self.top_k if top_k is None else max(top_k, 0)
        rotulos = [_texto_rotulo(c) for c in campos_lote]
        if limite == 0 or not any(rotulos):
            return []

        excluir = list(excluir_doc_ids)
        pares = [(r, _contexto_rotulo(c)) for r, c in zip(rotulos, campos_lote) if r]
        consultas = [r for r, _ in pares]
        contextos = [c for _, c in pares]
        candidatos: List[Tuple[float, float, ResultadoBusqueda, str]] = []

        for etapa, filtro_familia in enumerate((familia, None) if familia else (None,)):
            resultados = self.buscador.buscar_lote(
                consultas, top_k=CANDIDATOS_POR_ROTULO, solo_validados=True,
                familia=filtro_familia, excluir_doc_ids=excluir, umbral=self.umbral, contextos=contextos,
            )
            for consulta, lista in zip(consultas, resultados):
                for r in lista:
                    if not self._es_utilizable(r, campos_validos):
                        continue
                    # La familia detectada tiene prioridad: su etapa (0) va antes que la general (1).
                    candidatos.append((float(etapa), -r.similitud, r, consulta))

        candidatos.sort(key=lambda t: (t[0], t[1]))
        seleccion: List[EjemploFewShot] = []
        vistos: Set[Tuple[str, str]] = set()
        por_rotulo: Dict[str, int] = {}
        for _, _, r, consulta in candidatos:
            clave = (normalizar_etiqueta(r.etiqueta), str(r.campo_maestro))
            if clave in vistos or por_rotulo.get(consulta, 0) >= MAX_EJEMPLOS_POR_ROTULO:
                continue
            vistos.add(clave)
            por_rotulo[consulta] = por_rotulo.get(consulta, 0) + 1
            seleccion.append(
                EjemploFewShot(
                    rotulo=r.etiqueta, campo=str(r.campo_maestro), seccion=r.seccion,
                    similitud=r.similitud, documento=r.documento, familia=r.familia, rotulo_nuevo=consulta,
                )
            )
            if len(seleccion) >= limite:
                break
        return seleccion

    @staticmethod
    def _es_utilizable(r: ResultadoBusqueda, campos_validos: Optional[Set[str]]) -> bool:
        if not r.campo_maestro or r.campo_maestro in CAMPOS_RESPONSABLE_COMERCIAL:
            return False
        return campos_validos is None or r.campo_maestro in campos_validos
