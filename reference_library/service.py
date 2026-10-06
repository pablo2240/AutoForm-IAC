"""Punto de entrada único del pipeline hacia la biblioteca de referencias.

El pipeline nunca construye buscadores ni clasificadores: pide el servicio. Si la biblioteca está
desactivada (``AUTOFORM_REFERENCES_ENABLED=0``), vacía o falla algo, todas las funciones devuelven
resultados vacíos y el pipeline sigue exactamente como antes.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from reference_library.families import ClasificacionFormulario, ClasificadorFamilias
from reference_library.fewshot import GeneradorFewShot
from reference_library.library import ReferenceLibrary
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

    @property
    def listo(self) -> bool:
        """True si hay al menos un documento indexado correctamente."""
        estadisticas = self.store.estadisticas()
        return estadisticas["documentos"] - estadisticas["documentos_con_error"] > 0


_BLOQUEO = threading.Lock()
_BLOQUEO_REGISTRO = threading.Lock()
_servicio: Optional[ServicioReferencias] = None
_hilo_sincronizacion: Optional[threading.Thread] = None


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
    global _servicio, _hilo_sincronizacion
    with _BLOQUEO:
        _servicio = servicio
        _hilo_sincronizacion = None


def sincronizar_en_segundo_plano(datos_empresa: Optional[Dict[str, Any]] = None) -> Optional[threading.Thread]:
    """Alinea la base con la carpeta de referencias sin bloquear el arranque de la aplicación.

    ``datos_empresa`` debe leerse en el hilo de la sesión (un hilo aparte no tiene sesión de
    Supabase) y se usa para reconocer los valores ya diligenciados en las referencias.

    Mientras no termine, el pipeline usa lo ya indexado (o nada) y sigue funcionando igual.
    Es idempotente: llamarla varias veces no lanza hilos duplicados.
    """
    global _hilo_sincronizacion
    if not referencias_habilitadas():
        return None
    with _BLOQUEO:
        if _hilo_sincronizacion is not None and _hilo_sincronizacion.is_alive():
            return _hilo_sincronizacion

        def _trabajo() -> None:
            try:
                servicio = obtener_servicio()
                if servicio is None:
                    return
                reporte = servicio.biblioteca.sincronizar(datos_empresa=datos_empresa)
                servicio.buscador.reindexar()
                print(f"[ReferenceLibrary] Sincronización completada: {reporte.resumen()}.")
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
