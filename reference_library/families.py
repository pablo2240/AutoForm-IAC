"""Clasificación de un formulario en una familia de referencias (proveedor, cliente, ...).

Las familias no están en el código: son las subcarpetas de la biblioteca (o el campo ``familia``
del manifiesto), así que agregar una familia nueva solo requiere agregar documentos. La decisión
no depende del nombre del archivo; combina tres señales del contenido:

  * rótulos: qué tan bien cubre cada familia los rótulos del formulario (embeddings + coincidencias),
  * secciones: parecido entre los títulos de sección,
  * estructura: tamaño y forma del formulario (campos, secciones, tablas, hojas).

Se asigna una familia solo si supera umbrales absolutos y relativos; en otro caso el formulario se
trata como desconocido y el resto del sistema usa la búsqueda semántica general.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

from reference_library.extractor import TIPOS_CAMPO, _parece_etiqueta, normalizar_etiqueta
from reference_library.search import BuscadorSemantico
from reference_library.store import ReferenceStore


PESOS = {"etiquetas": 0.6, "secciones": 0.25, "estructura": 0.15}
UMBRAL_COBERTURA = 0.75
TEMPERATURA = 0.06
UMBRAL_PUNTAJE = 0.6
UMBRAL_PROBABILIDAD = 0.6
MARGEN_MINIMO = 0.05
MAX_ETIQUETAS = 400


@dataclass
class ClasificacionFormulario:
    """Resultado de clasificar un formulario; ``familia`` es None cuando se trata como desconocido."""

    familia: Optional[str]
    probabilidades: Dict[str, float] = field(default_factory=dict)
    puntajes: Dict[str, float] = field(default_factory=dict)
    evidencia: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    motivo: str = ""

    @property
    def es_desconocido(self) -> bool:
        return self.familia is None

    @property
    def puntaje_principal(self) -> float:
        return max(self.puntajes.values(), default=0.0)

    def resumen(self) -> str:
        if not self.probabilidades:
            return f"desconocido ({self.motivo})"
        orden = sorted(self.probabilidades.items(), key=lambda kv: kv[1], reverse=True)
        texto = ", ".join(f"{f} {p * 100:.0f}%" for f, p in orden[:3])
        return f"{self.familia or 'desconocido'} [{texto}]"

    def a_dict(self) -> Dict[str, Any]:
        return {
            "familia": self.familia,
            "probabilidades": {k: round(v, 4) for k, v in self.probabilidades.items()},
            "puntajes": {k: round(v, 4) for k, v in self.puntajes.items()},
            "evidencia": self.evidencia,
            "motivo": self.motivo,
        }


def _texto(elemento: Dict[str, Any]) -> str:
    valor = elemento.get("valor")
    if valor is None:
        valor = elemento.get("rotulo")
    return str(valor or "").strip()


def caracteristicas_estructurales(
    total_campos: int, secciones: int, tablas: int, hojas: int
) -> np.ndarray:
    """Forma del formulario en una escala comparable (logarítmica para los conteos grandes)."""
    return np.array(
        [math.log1p(total_campos), math.log1p(secciones), math.log1p(tablas), float(max(hojas, 1))],
        dtype=np.float32,
    )


def _cercania(a: np.ndarray, b: np.ndarray) -> float:
    """1.0 si las características coinciden, tendiendo a 0 cuanto más difieren."""
    denominador = np.maximum(np.maximum(np.abs(a), np.abs(b)), 1e-6)
    return float(np.clip(1.0 - np.mean(np.abs(a - b) / denominador), 0.0, 1.0))


class ClasificadorFamilias:
    """Clasifica formularios nuevos usando el conocimiento ya indexado de cada familia."""

    def __init__(
        self,
        store: ReferenceStore,
        buscador: BuscadorSemantico,
        umbral_puntaje: float = UMBRAL_PUNTAJE,
        umbral_probabilidad: float = UMBRAL_PROBABILIDAD,
    ) -> None:
        self.store = store
        self.buscador = buscador
        self.umbral_puntaje = umbral_puntaje
        self.umbral_probabilidad = umbral_probabilidad
        self._huella: Optional[str] = None
        self._secciones: Dict[str, np.ndarray] = {}
        self._estructura: Dict[str, np.ndarray] = {}

    # ── Conocimiento por familia ─────────────────────────────────────────

    def _cargar_familias(self) -> None:
        """Vectoriza los títulos de sección y promedia la estructura de cada familia (en memoria)."""
        huella = self.store.huella_conocimiento()
        if huella == self._huella:
            return
        titulos: Dict[str, List[str]] = {}
        formas: Dict[str, List[np.ndarray]] = {}
        for doc in self.store.listar_documentos():
            if doc.estado != "ok" or not doc.familia:
                continue
            est = doc.estructura
            titulos.setdefault(doc.familia, []).extend(est.get("secciones", []))
            formas.setdefault(doc.familia, []).append(
                caracteristicas_estructurales(
                    est.get("total_campos", 0), len(est.get("secciones", [])),
                    len(est.get("tablas", [])) + len(est.get("tablas_formales", [])), len(est.get("hojas", [])),
                )
            )
        self._estructura = {f: np.mean(v, axis=0) for f, v in formas.items()}
        self._secciones = {}
        for familia, lista in titulos.items():
            unicos = sorted({t for t in lista if t.strip()})
            if unicos:
                self._secciones[familia] = np.asarray(self.buscador.proveedor.embed(unicos), dtype=np.float32)
        self._huella = huella

    # ── Clasificación ────────────────────────────────────────────────────

    def clasificar(
        self,
        elementos_clasificados: List[Dict[str, Any]],
        excluir_doc_ids: Iterable[str] = (),
    ) -> ClasificacionFormulario:
        """Estima a qué familia pertenece un formulario a partir de su contenido, no de su nombre."""
        self.buscador.asegurar_indice()
        self._cargar_familias()
        if not self._estructura:
            return ClasificacionFormulario(None, motivo="la biblioteca no tiene familias definidas")

        etiquetas = list(dict.fromkeys(
            _texto(e) for e in elementos_clasificados
            if str(e.get("tipo_clasificacion", "")) in TIPOS_CAMPO and _parece_etiqueta(_texto(e))
        ))[:MAX_ETIQUETAS]
        secciones = list(dict.fromkeys(
            _texto(e) for e in elementos_clasificados
            if str(e.get("tipo_clasificacion", "")) == "TITULO_SECCION" and _texto(e)
        ))
        if not etiquetas:
            return ClasificacionFormulario(None, motivo="el formulario no tiene rótulos analizables")

        por_familia = self.buscador.mejor_similitud_por_familia(etiquetas, excluir_doc_ids)
        vectores_secciones = (
            np.asarray(self.buscador.proveedor.embed(secciones), dtype=np.float32) if secciones else None
        )
        forma = caracteristicas_estructurales(
            len(etiquetas), len(secciones),
            sum(1 for e in elementos_clasificados if str(e.get("tipo_clasificacion", "")) == "TABLA_CABECERA"),
            len({str(e.get("hoja", "")) for e in elementos_clasificados}),
        )

        puntajes: Dict[str, float] = {}
        evidencia: Dict[str, Dict[str, Optional[float]]] = {}
        for familia, similitudes in por_familia.items():
            cobertura = float(np.mean(similitudes >= UMBRAL_COBERTURA))
            componentes: Dict[str, Optional[float]] = {
                "etiquetas": 0.5 * float(np.mean(similitudes)) + 0.5 * cobertura,
                "secciones": None,
                "estructura": _cercania(forma, self._estructura[familia]),
            }
            if vectores_secciones is not None and familia in self._secciones:
                componentes["secciones"] = float(np.mean((vectores_secciones @ self._secciones[familia].T).max(axis=1)))
            disponibles = {k: v for k, v in componentes.items() if v is not None}
            peso_total = sum(PESOS[k] for k in disponibles)
            puntajes[familia] = sum(PESOS[k] * v for k, v in disponibles.items()) / peso_total
            evidencia[familia] = {k: (round(v, 4) if v is not None else None) for k, v in componentes.items()}
            evidencia[familia]["cobertura_etiquetas"] = round(cobertura, 4)

        if not puntajes:
            return ClasificacionFormulario(None, motivo="sin conocimiento comparable")

        valores = np.array(list(puntajes.values()), dtype=np.float64)
        exponentes = np.exp((valores - valores.max()) / TEMPERATURA)
        probabilidades = dict(zip(puntajes, (exponentes / exponentes.sum()).tolist()))

        ordenadas = sorted(puntajes, key=puntajes.get, reverse=True)
        mejor = ordenadas[0]
        margen = puntajes[mejor] - (puntajes[ordenadas[1]] if len(ordenadas) > 1 else 0.0)
        if puntajes[mejor] < self.umbral_puntaje:
            motivo = f"similitud insuficiente ({puntajes[mejor]:.2f} < {self.umbral_puntaje:.2f})"
            familia = None
        elif probabilidades[mejor] < self.umbral_probabilidad or margen < MARGEN_MINIMO:
            motivo = "ninguna familia destaca sobre las demás"
            familia = None
        else:
            motivo, familia = "coincidencia suficiente", mejor

        return ClasificacionFormulario(familia, probabilidades, puntajes, evidencia, motivo)
