"""Administración de la biblioteca de referencias desde la línea de comandos.

    python -m reference_library sync                      # alinea la base con docs/referencias
    python -m reference_library list                      # documentos indexados y su estado
    python -m reference_library stats
    python -m reference_library add archivo.xlsx --familia proveedor
    python -m reference_library remove "nombre o doc_id"
    python -m reference_library reprocess ["nombre o doc_id"]
    python -m reference_library search "identificación fiscal" --top-k 5
    python -m reference_library classify formulario.xlsx

Los datos de la empresa (para reconocer valores ya diligenciados) se leen de
``config/datos_empresa.json`` o del archivo indicado con ``--empresa``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from reference_library.library import ReferenceLibrary
from reference_library.service import construir_servicio


def _cargar_empresa(ruta: Optional[str]) -> Dict[str, Any]:
    from core.profile_manager import PROFILE_DEFAULT_PATH, aplanar_perfil

    archivo = Path(ruta) if ruta else PROFILE_DEFAULT_PATH
    if not archivo.exists():
        return {}
    return aplanar_perfil(json.loads(archivo.read_text(encoding="utf-8-sig")))


def _buscar_documento(biblioteca: ReferenceLibrary, referencia: str) -> Optional[str]:
    """Resuelve un doc_id a partir de su id o de (parte de) su nombre."""
    documentos = biblioteca.listar()
    for doc in documentos:
        if referencia in (doc.doc_id, doc.nombre, doc.ruta):
            return doc.doc_id
    coincidencias = [d for d in documentos if referencia.lower() in d.nombre.lower()]
    return coincidencias[0].doc_id if len(coincidencias) == 1 else None


def _imprimir_reporte(reporte: Any) -> None:
    print(reporte.resumen())
    for nombre, error in reporte.errores.items():
        print(f"  ERROR {nombre}: {error}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reference_library", description=__doc__.split("\n")[0])
    parser.add_argument("--empresa", help="JSON con los datos de la empresa para inferir campos por valor")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("sync")
    sub.add_parser("list")
    sub.add_parser("stats")
    p_add = sub.add_parser("add")
    p_add.add_argument("archivo")
    p_add.add_argument("--familia", default="")
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("documento")
    p_re = sub.add_parser("reprocess")
    p_re.add_argument("documento", nargs="?")
    p_se = sub.add_parser("search")
    p_se.add_argument("consulta")
    p_se.add_argument("--top-k", type=int, default=5)
    p_cl = sub.add_parser("classify")
    p_cl.add_argument("archivo")
    args = parser.parse_args(argv)

    empresa = _cargar_empresa(args.empresa)
    biblioteca = ReferenceLibrary(datos_empresa=empresa)

    if args.comando == "sync":
        _imprimir_reporte(biblioteca.sincronizar())
    elif args.comando == "list":
        for doc in biblioteca.listar():
            estado = doc.estado if doc.estado == "ok" else f"ERROR: {doc.error}"
            print(f"{doc.doc_id}  {doc.familia or '-':12} {doc.fuente:24} {doc.total_campos:5} campos  {doc.nombre}  [{estado}]")
    elif args.comando == "stats":
        print(json.dumps(biblioteca.estadisticas(), ensure_ascii=False, indent=2))
    elif args.comando == "add":
        doc_id = biblioteca.agregar(Path(args.archivo), familia=args.familia)
        print(f"Agregado: {doc_id}")
    elif args.comando == "remove":
        doc_id = _buscar_documento(biblioteca, args.documento)
        if doc_id is None:
            print(f"No se encontró un único documento para '{args.documento}'.", file=sys.stderr)
            return 1
        print("Eliminado." if biblioteca.eliminar(doc_id) else "No se pudo eliminar.")
    elif args.comando == "reprocess":
        doc_id = _buscar_documento(biblioteca, args.documento) if args.documento else None
        if args.documento and doc_id is None:
            print(f"No se encontró un único documento para '{args.documento}'.", file=sys.stderr)
            return 1
        _imprimir_reporte(biblioteca.reprocesar(doc_id))
    elif args.comando == "search":
        servicio = construir_servicio(biblioteca)
        for r in servicio.buscador.buscar(args.consulta, top_k=args.top_k, solo_con_campo_maestro=True):
            print(
                f"{r.similitud:.2f}  {r.etiqueta[:40]:42} -> {r.campo_maestro or '-':22} "
                f"{r.documento} {r.hoja}!{r.coordenada} [{r.fuente_campo}]"
            )
    elif args.comando == "classify":
        from pipeline.handlers import ExcelHandler
        from pipeline.stages.stage_2_classifier import clasificar_elementos_formulario

        elementos = ExcelHandler.escanear(Path(args.archivo).read_bytes())
        clasificados, _ = clasificar_elementos_formulario(elementos, datos_empresa={})
        resultado = construir_servicio(biblioteca).clasificador.clasificar(clasificados)
        print(resultado.resumen())
        print(json.dumps(resultado.a_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
