"""Confianza honesta (A2): el puntaje de una asignación refleja la evidencia que la respalda.

Antes, toda asignación del LLM salía como "Alta" mientras el campo tuviera valor en el perfil, aunque el
rótulo no tuviera relación con el campo ("Activación" -> razon_social). Aquí el puntaje sale de señales:

  Evidencia fuerte (0.90-0.95)
    * el alias determinista del rótulo apunta al mismo campo, o la asignación nació de una regla determinista
    * el rótulo contiene el nombre del campo (nivel EXACTA del validador) o el validador la remapeó por contexto
    * un formulario de referencia con evidencia real tiene el mismo rótulo asignado al mismo campo
  Solo el LLM (sin evidencia fuerte): se mide la similitud semántica entre el rótulo y la descripción del campo
    * >= 0.50  -> 0.80 "Alta"
    * 0.30-0.50 -> 0.60 "Requiere revisión" (se escribe, pero queda marcada)
    * < 0.30   -> 0.30 sin relación: se descarta (no se escribe)

Si no hay modelo de embeddings disponible, una asignación sin evidencia fuerte queda en 0.60 y nunca se
descarta por esta vía (la compuerta A1 sigue actuando). Los umbrales se calibraron con los pares
rótulo-campo de los formularios de referencia: 5 de 6 asignaciones absurdas conocidas quedan por debajo
de 0.30 y la similitud mediana de un par correcto es 0.52 (al azar, 0.25).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

import re
import unicodedata

from core.domain_constants import (
    CAMPOS_BANCARIOS,
    CAMPOS_REP_LEGAL,
    CAMPOS_SOCIETARIO,
    TOKENS_FINANCIEROS_SECCION,
    TOKENS_REP_LEGAL_SECCION,
    TOKENS_SOCIETARIO_SECCION,
    resolver_campo_por_alias_determinista,
)

PUNTAJE_FUERTE = 0.95
PUNTAJE_CONTEXTO = 0.90
PUNTAJE_ALTO = 0.80
PUNTAJE_REVISION = 0.60
PUNTAJE_SIN_RELACION = 0.30
SIMILITUD_ALTA = 0.50
SIMILITUD_MINIMA = 0.30
FUENTES_DETERMINISTAS = ("determinista_alias", "rescate_patron", "cobertura_patron")
MARCAS_DE_VALIDADOR = ("Context-First", "ADR-", "Autocorr")

PUNTAJE_DECLARATIVO = 0.85
PUNTAJE_DOMINIO = 0.65

# Fórmulas de declaración ("Yo, ____ identificado con ____ expedido en ____") cuyo campo lo fija el contexto,
# no el significado de las palabras; el prompt del LLM las trata explícitamente.
_PATRON_DECLARATIVO = re.compile(
    r"^\s*(?:yo|nosotros|certifico|declaro|expedid[oa]|identificad[oa]|domiciliad[oa]|actuando|en\s+calidad)\b",
    re.IGNORECASE,
)
# Dominio de la sección en el que se espera cada grupo de campos (aislamiento de dominios, ADR-0004/0011).
_DOMINIOS = (
    (CAMPOS_REP_LEGAL, TOKENS_REP_LEGAL_SECCION),
    (CAMPOS_BANCARIOS, TOKENS_FINANCIEROS_SECCION),
    (CAMPOS_SOCIETARIO, TOKENS_SOCIETARIO_SECCION),
)

_CACHE_LOCK = threading.Lock()
_vectores_campo: Dict[str, np.ndarray] = {}


@dataclass(frozen=True)
class Evaluacion:
    """Confianza de una asignación rótulo -> campo, con las señales que la sustentan."""

    score: float
    nivel: str
    senales: Dict[str, float] = field(default_factory=dict)
    motivo: str = ""
    descartar: bool = False


def nivel_para(score: float) -> str:
    if score >= 0.95:
        return "EXACTA"
    if score >= 0.75:
        return "ALTA"
    if score >= 0.50:
        return "PARCIAL"
    return "SIN_COINCIDENCIA"


def _campo_terminal(campo: str) -> str:
    return str(campo or "").split(".")[-1].strip()


def _texto_de_campo(campo: str, descripciones: Dict[str, str]) -> Optional[str]:
    descripcion = descripciones.get(campo)
    return f"{campo.replace('_', ' ')}: {descripcion}" if descripcion else None


def similitudes_semanticas(rotulos: Sequence[str], campos: Sequence[str]) -> List[Optional[float]]:
    """Similitud coseno entre cada rótulo y la descripción de su campo; None donde no hay modelo o descripción."""
    resultados: List[Optional[float]] = [None] * len(rotulos)
    try:
        from core.fastembed_matcher import DESCRIPCIONES_TAXONOMIA, _obtener_modelo

        modelo = _obtener_modelo()
        if modelo is None:
            return resultados
        pendientes = [i for i, c in enumerate(campos) if _texto_de_campo(_campo_terminal(c), DESCRIPCIONES_TAXONOMIA)]
        if not pendientes:
            return resultados

        with _CACHE_LOCK:
            faltan = sorted({_campo_terminal(campos[i]) for i in pendientes} - set(_vectores_campo))
            if faltan:
                textos = [_texto_de_campo(c, DESCRIPCIONES_TAXONOMIA) or c for c in faltan]
                vectores = np.array(list(modelo.embed(textos)), dtype=np.float32)
                vectores /= np.maximum(np.linalg.norm(vectores, axis=1, keepdims=True), 1e-12)
                _vectores_campo.update(dict(zip(faltan, vectores)))
            vectores_campo = {c: _vectores_campo[c] for c in {_campo_terminal(campos[i]) for i in pendientes}}

        vectores_rotulo = np.array(list(modelo.embed([str(rotulos[i]) for i in pendientes])), dtype=np.float32)
        vectores_rotulo /= np.maximum(np.linalg.norm(vectores_rotulo, axis=1, keepdims=True), 1e-12)
        for fila, i in enumerate(pendientes):
            resultados[i] = float(vectores_rotulo[fila] @ vectores_campo[_campo_terminal(campos[i])])
    except Exception as exc:  # sin modelo (o con error) no se emite juicio semántico
        print(f"[AutoForm AI Confianza] Similitud semántica no disponible: {exc}")
        return [None] * len(rotulos)
    return resultados


def _normalizar(texto: Any) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_tildes).strip()


def _dominio_compatible(campo: str, seccion: str) -> bool:
    """True si la sección pertenece al dominio donde se espera ese campo (representante, banco, socios)."""
    seccion_norm = _normalizar(seccion)
    terminal = _campo_terminal(campo)
    return any(
        terminal in campos and any(token in seccion_norm for token in tokens) for campos, tokens in _DOMINIOS
    )


def _evidencia_fuerte(item: Dict[str, Any], rotulo: str, campo: str) -> Optional[Evaluacion]:
    if str(item.get("fuente") or item.get("fuente_mapeo") or "") in FUENTES_DETERMINISTAS:
        return Evaluacion(PUNTAJE_FUERTE, "EXACTA", {"determinista": 1.0}, "Regla determinista")
    seccion = str(item.get("seccion") or item.get("seccion_padre") or "")
    if resolver_campo_por_alias_determinista(rotulo, seccion=seccion) == _campo_terminal(campo):
        return Evaluacion(PUNTAJE_FUERTE, "EXACTA", {"alias": 1.0}, "El alias del rótulo apunta a este campo")
    if str(item.get("nivel_confianza") or "").upper() == "EXACTA":
        return Evaluacion(PUNTAJE_FUERTE, "EXACTA", {"exacta": 1.0}, "El rótulo contiene el nombre del campo")
    motivo = str(item.get("motivo") or "")
    if any(marca in motivo for marca in MARCAS_DE_VALIDADOR):
        return Evaluacion(PUNTAJE_CONTEXTO, "ALTA", {"validador": 1.0}, "Asignación respaldada por el validador de contexto")
    if _PATRON_DECLARATIVO.search(rotulo) and _campo_terminal(campo) in CAMPOS_REP_LEGAL:
        return Evaluacion(PUNTAJE_DECLARATIVO, "ALTA", {"declarativo": 1.0}, "Fórmula de declaración del representante")
    return None


def evaluar_confianza(
    items: Sequence[Dict[str, Any]],
    referencia_validada: Optional[Any] = None,
) -> List[Evaluacion]:
    """Evalúa cada asignación del plan. ``referencia_validada(rotulo, campo) -> bool`` consulta la biblioteca."""
    evaluaciones: List[Optional[Evaluacion]] = [None] * len(items)
    pendientes: List[int] = []

    for i, item in enumerate(items):
        rotulo = str(item.get("rotulo_original") or item.get("rotulo") or "").strip()
        campo = str(item.get("campo") or "")
        fuerte = _evidencia_fuerte(item, rotulo, campo)
        if fuerte is None and referencia_validada is not None:
            try:
                if referencia_validada(rotulo, _campo_terminal(campo)):
                    fuerte = Evaluacion(PUNTAJE_CONTEXTO, "ALTA", {"referencia": 1.0}, "Coincide con un formulario de referencia")
            except Exception:
                fuerte = None
        if fuerte is not None:
            evaluaciones[i] = fuerte
        else:
            pendientes.append(i)

    similitudes = similitudes_semanticas(
        [str(items[i].get("rotulo_original") or items[i].get("rotulo") or "") for i in pendientes],
        [str(items[i].get("campo") or "") for i in pendientes],
    )
    for i, similitud in zip(pendientes, similitudes):
        if similitud is None:
            evaluaciones[i] = Evaluacion(PUNTAJE_REVISION, "PARCIAL", {}, "Sin evidencia semántica disponible: revisar")
        elif similitud >= SIMILITUD_ALTA:
            evaluaciones[i] = Evaluacion(PUNTAJE_ALTO, "ALTA", {"semantica": round(similitud, 3)}, "Similitud rótulo-campo alta")
        elif similitud >= SIMILITUD_MINIMA:
            evaluaciones[i] = Evaluacion(
                PUNTAJE_REVISION, "PARCIAL", {"semantica": round(similitud, 3)},
                f"Similitud rótulo-campo moderada ({similitud:.2f}): revisar",
            )
        elif _dominio_compatible(str(items[i].get("campo") or ""), str(items[i].get("seccion") or items[i].get("seccion_padre") or "")):
            # El significado no coincide, pero la sección sí es del dominio del campo: se revisa, no se descarta.
            evaluaciones[i] = Evaluacion(
                PUNTAJE_DOMINIO, "PARCIAL", {"semantica": round(similitud, 3), "dominio": 1.0},
                f"Similitud baja ({similitud:.2f}) pero la sección es del dominio del campo: revisar",
            )
        else:
            evaluaciones[i] = Evaluacion(
                PUNTAJE_SIN_RELACION, "SIN_COINCIDENCIA", {"semantica": round(similitud, 3)},
                f"Sin evidencia: el rótulo no guarda relación con el campo (similitud {similitud:.2f})", descartar=True,
            )
    return [e for e in evaluaciones if e is not None]
