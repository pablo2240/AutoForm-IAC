"""Punto de entrada único del pipeline hacia la biblioteca de referencias.

El pipeline nunca construye buscadores ni clasificadores: pide el servicio. Si la biblioteca está
desactivada (``AUTOFORM_REFERENCES_ENABLED=0``), vacía o falla algo, todas las funciones devuelven
resultados vacíos y el pipeline sigue exactamente como antes.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from reference_library.families import ClasificacionFormulario, ClasificadorFamilias
from reference_library.fewshot import GeneradorFewShot
from reference_library.library import ReferenceLibrary
from reference_library.remote import RepositorioRemoto, SincronizadorNube
from reference_library.search import BuscadorSemantico
from reference_library.store import ReferenceStore


@dataclass
class ServicioReferencias:
    """Agrupa los componentes de la biblioteca que comparte el pipeline."""

    store: ReferenceStore
    biblioteca: ReferenceLibrary
    buscador: BuscadorSemantico
    clasificador: ClasificadorFamilias
    fewshot: GeneradorFewShot

    def sincronizador_nube(self, repositorio: RepositorioRemoto, es_admin: bool = False) -> SincronizadorNube:
        """Sincronizador con el repositorio remoto de la sesión actual (el servicio es compartido)."""
        return SincronizadorNube(self.biblioteca, repositorio, puede_escribir=es_admin)

    @property
    def listo(self) -> bool:
        """True si hay al menos un documento indexado correctamente."""
        estadisticas = self.store.estadisticas()
        return estadisticas["documentos"] - estadisticas["documentos_con_error"] > 0


_BLOQUEO = threading.Lock()
_BLOQUEO_REGISTRO = threading.Lock()
_servicio: Optional[ServicioReferencias] = None
_hilo_sincronizacion: Optional[threading.Thread] = None
_ultima_sincronizacion: float = 0.0


def referencias_habilitadas() -> bool:
    return os.getenv("AUTOFORM_REFERENCES_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def construir_servicio(
    biblioteca: Optional[ReferenceLibrary] = None,
    buscador: Optional[BuscadorSemantico] = None,
) -> ServicioReferencias:
    biblioteca = biblioteca or ReferenceLibrary()
    buscador = buscador or BuscadorSemantico(biblioteca.store)
    return ServicioReferencias(
        store=biblioteca.store,
        biblioteca=biblioteca,
        buscador=buscador,
        clasificador=ClasificadorFamilias(biblioteca.store, buscador),
        fewshot=GeneradorFewShot(buscador),
    )


def obtener_servicio() -> Optional[ServicioReferencias]:
    """Servicio compartido (se crea una vez por proceso); None si está desactivado o no puede crearse."""
    global _servicio
    if not referencias_habilitadas():
        return None
    with _BLOQUEO:
        if _servicio is None:
            try:
                _servicio = construir_servicio()
            except Exception as exc:
                print(f"[ReferenceLibrary] No se pudo iniciar el servicio de referencias: {exc}")
                return None
        return _servicio


def reiniciar_servicio(servicio: Optional[ServicioReferencias] = None) -> None:
    """Reemplaza (o limpia) el servicio compartido; útil en pruebas y tras cambios de configuración."""
    global _servicio, _hilo_sincronizacion, _ultima_sincronizacion
    with _BLOQUEO:
        _servicio = servicio
        _hilo_sincronizacion = None
        _ultima_sincronizacion = 0.0


def _intervalo_sincronizacion() -> float:
    """Segundos mínimos entre sincronizaciones automáticas (``AUTOFORM_REFERENCES_SYNC_TTL_S``, 600)."""
    try:
        return max(float(os.getenv("AUTOFORM_REFERENCES_SYNC_TTL_S", "600")), 0.0)
    except ValueError:
        return 600.0


def sincronizar_en_segundo_plano(
    datos_empresa: Optional[Dict[str, Any]] = None,
    repositorio: Optional[RepositorioRemoto] = None,
    es_admin: bool = False,
) -> Optional[threading.Thread]:
    """Alinea la base con la carpeta local y, si hay, con el repositorio remoto, sin bloquear la app.

    ``datos_empresa`` y ``repositorio`` deben crearse en el hilo de la sesión (un hilo aparte no tiene
    sesión de Supabase). Mientras no termine, el pipeline usa lo ya indexado (o nada) y sigue igual.
    Es idempotente: no lanza hilos duplicados y no repite la sincronización antes del intervalo
    configurado, de modo que una sesión nueva recoge lo que un administrador publicó entre tanto.
    """
    global _hilo_sincronizacion, _ultima_sincronizacion
    if not referencias_habilitadas():
        return None
    with _BLOQUEO:
        if _hilo_sincronizacion is not None and _hilo_sincronizacion.is_alive():
            return _hilo_sincronizacion
        if _hilo_sincronizacion is not None and time.time() - _ultima_sincronizacion < _intervalo_sincronizacion():
            return _hilo_sincronizacion
        _ultima_sincronizacion = time.time()

        def _trabajo() -> None:
            try:
                servicio = obtener_servicio()
                if servicio is None:
                    return
                reporte = servicio.biblioteca.sincronizar(datos_empresa=datos_empresa)
                print(f"[ReferenceLibrary] Sincronización local: {reporte.resumen()}.")
                if repositorio is not None:
                    reporte_nube = servicio.sincronizador_nube(repositorio, es_admin).sincronizar(datos_empresa)
                    print(f"[ReferenceLibrary] Sincronización con la nube: {reporte_nube.resumen()}.")
                servicio.buscador.reindexar()
            except Exception as exc:
                print(f"[ReferenceLibrary] La sincronización en segundo plano falló: {exc}")

        _hilo_sincronizacion = threading.Thread(target=_trabajo, name="referencias-sync", daemon=True)
        _hilo_sincronizacion.start()
        return _hilo_sincronizacion


# ── Integración con el pipeline ─────────────────────────────────────────────

def clasificar_formulario_ctx(ctx: Any) -> Optional[ClasificacionFormulario]:
    """Etapa 2c: clasifica el formulario y deja el resultado en el contexto del pipeline."""
    servicio = obtener_servicio()
    if servicio is None or not servicio.listo:
        ctx.log("[Stage 2c - Familia] Biblioteca de referencias no disponible: se continúa sin clasificación.")
        return None
    resultado = servicio.clasificador.clasificar(ctx.elementos_clasificados)
    ctx.familia_formulario = resultado.familia
    ctx.metadatos["clasificacion_formulario"] = resultado.a_dict()
    ctx.log(f"[Stage 2c - Familia] {resultado.resumen()}.")
    return resultado


def ejemplos_fewshot_para_lote(
    ctx: Any,
    campos_lote: List[Dict[str, Any]],
    titulo_lote: str,
    campos_validos: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Ejemplos (formato compacto de prompt) para un lote; ``[]`` si no hay biblioteca o ejemplos."""
    servicio = obtener_servicio()
    if servicio is None or servicio.fewshot.top_k == 0 or not servicio.listo:
        return []
    try:
        ejemplos = servicio.fewshot.ejemplos_para_lote(
            campos_lote, familia=getattr(ctx, "familia_formulario", None), campos_validos=campos_validos,
        )
    except Exception as exc:
        ctx.log(f"[Stage 3 - Few-shot] Sin ejemplos para '{titulo_lote}': {exc}")
        return []
    if ejemplos:
        with _BLOQUEO_REGISTRO:  # los lotes del stage 3 se procesan en hilos concurrentes
            ctx.metadatos.setdefault("fewshot", []).append(
                {"lote": titulo_lote, "ejemplos": [e.para_registro() for e in ejemplos]}
            )
        ctx.log(f"[Stage 3 - Few-shot] Lote '{titulo_lote}': {len(ejemplos)} ejemplos recuperados de referencias.")
    return [e.para_prompt() for e in ejemplos]
