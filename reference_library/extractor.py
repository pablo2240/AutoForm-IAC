"""Extracción de conocimiento reutilizable desde un formulario Excel de referencia.

Reutiliza el análisis existente (escaneo de celdas, clasificador de la etapa 2, IR espacial e
inspector de libro) y no llama a ningún LLM. El resultado describe, por cada rótulo: su posición,
sección, contexto, ejemplo de valor y, cuando se puede inferir de forma determinista, el campo
del modelo maestro al que corresponde y de dónde salió esa correspondencia.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.utils import range_boundaries

from core.domain_constants import resolver_campo_por_alias_determinista
from core.profile_manager import aplanar_perfil
from pipeline.handlers import ExcelHandler
from pipeline.stages.stage_2_classifier import clasificar_elementos_formulario


# Tipos del clasificador que representan un rótulo de campo candidato.
TIPOS_CAMPO = {"CAMPO_ENTRADA", "OPCION_SELECCION", "PREGUNTA_CERRADA"}
TIPOS_INSTRUCCION = {"INSTRUCCION_TEXTO"}
TIPOS_TABLA = {"TABLA_CABECERA"}

FUENTE_VALOR = "valor_ejemplo"
FUENTE_ALIAS = "alias"
FUENTE_PLANTILLA = "plantilla_verificada"

MAX_LONGITUD_ETIQUETA = 70
MAX_PALABRAS_ETIQUETA = 9
LONGITUD_MINIMA_VALOR = 4


@dataclass
class CampoReferencia:
    """Conocimiento sobre un rótulo de un formulario de referencia."""

    hoja: str
    fila: int
    columna: int
    coordenada: str
    etiqueta: str
    etiqueta_norm: str
    seccion: str = ""
    contexto_fila: str = ""
    tipo_elemento: str = "CAMPO_ENTRADA"
    ubicacion: str = "derecha"
    ejemplo_valor: str = ""
    campo_maestro: Optional[str] = None
    fuente_campo: str = ""
    confianza: float = 0.0
    vecinos: List[str] = field(default_factory=list)


@dataclass
class ExtraccionDocumento:
    """Resultado completo de analizar un formulario de referencia."""

    campos: List[CampoReferencia] = field(default_factory=list)
    estructura: Dict[str, Any] = field(default_factory=dict)
    plantilla_id: Optional[str] = None


def normalizar_etiqueta(texto: Any) -> str:
    """Minúsculas, sin tildes ni puntuación; base para comparar rótulos y valores."""
    if texto is None:
        return ""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", str(texto).lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9ñ]+", " ", sin_tildes).strip()


def _indice_valores_perfil(datos_empresa: Dict[str, Any]) -> Dict[str, List[str]]:
    """Mapea valor normalizado -> claves canónicas del perfil que lo contienen."""
    indice: Dict[str, List[str]] = defaultdict(list)
    for clave, valor in aplanar_perfil(datos_empresa).items():
        if "." in clave or valor is None or isinstance(valor, (dict, list, bool)):
            continue
        norm = normalizar_etiqueta(valor)
        if len(norm) >= LONGITUD_MINIMA_VALOR:
            indice[norm].append(clave)
    return indice


def huella_datos_empresa(datos_empresa: Optional[Dict[str, Any]]) -> str:
    """Identifica los valores del perfil usados para inferir campos; cambia si el perfil cambia."""
    indice = _indice_valores_perfil(datos_empresa or {})
    contenido = "|".join(f"{valor}={','.join(sorted(claves))}" for valor, claves in sorted(indice.items()))
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()[:16]


def _es_numero_o_fecha(texto: str) -> bool:
    return bool(re.fullmatch(r"[\d\s.,:/\-]+", texto.strip()))


def _parece_etiqueta(texto: str) -> bool:
    """Descarta valores largos, números y fechas que no sirven como rótulo."""
    texto = texto.strip()
    if not texto or _es_numero_o_fecha(texto):
        return False
    if len(texto) > MAX_LONGITUD_ETIQUETA or len(texto.split()) > MAX_PALABRAS_ETIQUETA:
        return False
    return any(c.isalpha() for c in texto)


def _texto(elemento: Dict[str, Any]) -> str:
    valor = elemento.get("valor")
    if valor is None:
        valor = elemento.get("rotulo")
    return str(valor or "").strip()


def _coordenada(fila: int, columna: int) -> str:
    letras = ""
    n = columna
    while n > 0:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return f"{letras}{fila}"


def _elegir_campo_por_valor(
    candidatos: List[str],
    campo_por_alias: Optional[str],
) -> Tuple[Optional[str], float]:
    """Campo que respalda un valor de ejemplo; prioriza precisión sobre cobertura.

    Solo se acepta cuando el alias del rótulo lo confirma o cuando el valor identifica una única
    clave del perfil. Un valor ambiguo (misma cadena en varias claves) o que contradice al alias
    no asigna campo: el rótulo queda sin correspondencia en vez de con una equivocada.
    """
    if campo_por_alias:
        return (campo_por_alias, 0.95) if campo_por_alias in candidatos else (None, 0.0)
    if len(candidatos) == 1:
        return candidatos[0], 0.8
    return None, 0.0


def _agrupar_por_fila(elementos: List[Dict[str, Any]]) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
    filas: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for elem in elementos:
        filas[(str(elem.get("hoja", "")), int(elem.get("fila", 0) or 0))].append(elem)
    for celdas in filas.values():
        celdas.sort(key=lambda e: int(e.get("columna", 0) or 0))
    return filas


def _nuevo_campo(
    elemento: Dict[str, Any],
    hoja: str,
    fila: int,
    textos_fila: List[str],
    ejemplo: str,
    campo: Optional[str],
    fuente: str,
    confianza: float,
) -> CampoReferencia:
    etiqueta = _texto(elemento)
    columna = int(elemento.get("columna", 0) or 0)
    return CampoReferencia(
        hoja=hoja,
        fila=fila,
        columna=columna,
        coordenada=_coordenada(fila, columna),
        etiqueta=etiqueta,
        etiqueta_norm=normalizar_etiqueta(etiqueta),
        seccion=str(elemento.get("seccion_padre", "")),
        contexto_fila=" | ".join(textos_fila),
        tipo_elemento=str(elemento.get("tipo_clasificacion", "CAMPO_ENTRADA")),
        ubicacion=str(elemento.get("tipoEspacioEscritura", "derecha")),
        ejemplo_valor=ejemplo,
        campo_maestro=campo,
        fuente_campo=fuente if campo else "",
        confianza=confianza if campo else 0.0,
        vecinos=[t for t in textos_fila if t != etiqueta][:8],
    )


def _valor_vecino(libro: Any, elemento: Dict[str, Any]) -> str:
    """Contenido de la celda de captura contigua (derecha, o debajo) de un rótulo.

    El escáner descarta como ruido números, correos y teléfonos; leerlos directamente del libro
    permite reconocer esos valores de ejemplo (NIT, correo, teléfono) en formularios diligenciados.
    """
    try:
        hoja = libro[str(elemento.get("hoja", ""))]
        fila, columna = int(elemento.get("fila", 0) or 0), int(elemento.get("columna", 0) or 0)
        max_fila, max_columna = fila, columna
        if elemento.get("coordMerge"):
            _, _, max_columna, max_fila = range_boundaries(str(elemento["coordMerge"]))
        for f, c in ((fila, max_columna + 1), (max_fila + 1, columna)):
            valor = hoja.cell(row=f, column=c).value
            if valor is not None and str(valor).strip():
                return " ".join(str(valor).split())
    except (KeyError, ValueError, AttributeError):
        pass
    return ""


def _extraer_campos(
    elementos: List[Dict[str, Any]],
    indice_valores: Dict[str, List[str]],
    libro: Any,
) -> List[CampoReferencia]:
    """Asocia cada rótulo con un campo maestro (por valor de ejemplo o alias) y su contexto de fila."""
    campos: List[CampoReferencia] = []

    for (hoja, fila), celdas in _agrupar_por_fila(elementos).items():
        candidatas = [c for c in celdas if str(c.get("tipo_clasificacion", "")) in TIPOS_CAMPO and _texto(c)]
        textos_fila = [_texto(c) for c in candidatas]

        for celda in candidatas:
            etiqueta = _texto(celda)
            etiqueta_norm = normalizar_etiqueta(etiqueta)
            # Un texto que coincide con un dato del perfil es un valor ya diligenciado, no un rótulo.
            if not _parece_etiqueta(etiqueta) or etiqueta_norm in indice_valores:
                continue
            seccion = str(celda.get("seccion_padre", ""))
            alias = resolver_campo_por_alias_determinista(etiqueta, seccion=seccion)
            valor = _valor_vecino(libro, celda)
            claves = indice_valores.get(normalizar_etiqueta(valor)) if valor else None

            campo_valor, confianza = _elegir_campo_por_valor(claves, alias) if claves else (None, 0.0)
            if campo_valor:
                campos.append(_nuevo_campo(
                    celda, hoja, fila, textos_fila, ejemplo=valor, campo=campo_valor,
                    fuente=FUENTE_VALOR, confianza=confianza,
                ))
            else:
                campos.append(_nuevo_campo(
                    celda, hoja, fila, textos_fila, ejemplo="", campo=alias, fuente=FUENTE_ALIAS, confianza=0.85,
                ))

    return campos


def _aplicar_plantilla_verificada(campos: List[CampoReferencia], plantilla: Dict[str, Any]) -> int:
    """Una plantilla ya verificada por usuarios es la fuente más confiable de correspondencias."""
    por_celda = {
        (str(p.get("hoja", "")).lower(), int(p.get("fila", 0) or 0), int(p.get("columna", 0) or 0)): p
        for p in plantilla.get("plan_mapeo", [])
        if p.get("campo")
    }
    aplicados = 0
    for campo in campos:
        item = por_celda.get((campo.hoja.lower(), campo.fila, campo.columna))
        if item:
            campo.campo_maestro = str(item["campo"])
            campo.fuente_campo = FUENTE_PLANTILLA
            campo.confianza = 0.95
            aplicados += 1
    return aplicados


def _describir_estructura(
    archivo_bytes: bytes,
    nombre_archivo: str,
    clasificados: List[Dict[str, Any]],
    campos: List[CampoReferencia],
) -> Dict[str, Any]:
    """Resumen estructural: hojas, secciones, tablas, listas de validación e instrucciones."""
    estructura: Dict[str, Any] = {
        "total_elementos": len(clasificados),
        "total_campos": len(campos),
        "campos_con_campo_maestro": sum(1 for c in campos if c.campo_maestro),
        "tipos": dict(Counter(str(e.get("tipo_clasificacion", "")) for e in clasificados)),
        "hojas": sorted({str(e.get("hoja", "")) for e in clasificados}),
        "secciones": [],
        "tablas": [],
        "listas_validacion": [],
        "instrucciones": [],
    }

    vistos = set()
    for e in clasificados:
        tipo = str(e.get("tipo_clasificacion", ""))
        texto = _texto(e)
        if not texto:
            continue
        if tipo == "TITULO_SECCION" and texto not in vistos:
            vistos.add(texto)
            estructura["secciones"].append(texto)
        elif tipo in TIPOS_INSTRUCCION and len(estructura["instrucciones"]) < 25:
            estructura["instrucciones"].append(texto[:300])
        elif tipo in TIPOS_TABLA:
            estructura["tablas"].append(
                {"hoja": str(e.get("hoja", "")), "fila": int(e.get("fila", 0) or 0), "encabezado": texto}
            )

    try:
        from core.excel_inspector import inspeccionar_libro_excel

        inspeccion = inspeccionar_libro_excel(archivo_bytes)
        estructura["hojas"] = list(inspeccion.hojas) or estructura["hojas"]
        estructura["tablas_formales"] = [
            {"nombre": t.nombre, "hoja": t.hoja, "rango": t.rango_ref, "columnas": [c.nombre for c in t.columnas]}
            for t in inspeccion.tablas
        ]
        listas = {
            tuple(regla.opciones_permitidas)
            for regla in inspeccion.validaciones_por_celda.values()
            if regla.tipo == "list" and regla.opciones_permitidas
        }
        estructura["listas_validacion"] = [list(opciones)[:20] for opciones in sorted(listas)][:15]
        estructura["tiene_controles_vml"] = bool(inspeccion.tiene_controles_vml)
    except Exception as exc:  # El inspector es informativo; no debe impedir indexar la referencia.
        estructura["advertencia_inspector"] = f"{type(exc).__name__}: {exc}"

    try:
        from core.spatial_ir import construir_ir

        ir = construir_ir(clasificados, nombre_archivo=nombre_archivo, tipo_documento="excel")
        estructura["total_secciones_ir"] = ir.total_secciones
    except Exception as exc:
        estructura["advertencia_ir"] = f"{type(exc).__name__}: {exc}"

    return estructura


def extraer_conocimiento(
    archivo_bytes: bytes,
    nombre_archivo: str,
    datos_empresa: Optional[Dict[str, Any]] = None,
) -> ExtraccionDocumento:
    """Analiza un Excel de referencia (solo lectura, sin LLM) y devuelve su conocimiento.

    A diferencia de la etapa 1 del pipeline no rechaza libros con controles VML: una referencia
    solo se lee, nunca se modifica.
    """
    libro = openpyxl.load_workbook(filename=BytesIO(archivo_bytes), data_only=False, keep_vba=True)
    elementos = ExcelHandler.escanear(libro)
    clasificados, _ = clasificar_elementos_formulario(elementos, datos_empresa={})

    campos = _extraer_campos(clasificados, _indice_valores_perfil(datos_empresa or {}), libro)

    plantilla_id: Optional[str] = None
    try:
        from template_store.store import calcular_hash_formulario, cargar_plantilla

        plantilla_id = calcular_hash_formulario(elementos)
        plantilla = cargar_plantilla(plantilla_id)
        if plantilla:
            _aplicar_plantilla_verificada(campos, plantilla)
    except Exception as exc:
        print(f"[ReferenceLibrary] Plantilla verificada no disponible para '{nombre_archivo}': {exc}")

    return ExtraccionDocumento(
        campos=campos,
        estructura=_describir_estructura(archivo_bytes, nombre_archivo, clasificados, campos),
        plantilla_id=plantilla_id,
    )


def extraccion_a_dict(extraccion: ExtraccionDocumento) -> Dict[str, Any]:
    """Instantánea serializable del conocimiento extraído (para guardarlo fuera del disco local)."""
    return {
        "estructura": extraccion.estructura,
        "plantilla_id": extraccion.plantilla_id,
        "campos": [asdict(c) for c in extraccion.campos],
    }


def extraccion_desde_dict(datos: Dict[str, Any]) -> ExtraccionDocumento:
    """Reconstruye una extracción desde su instantánea; ignora claves desconocidas de versiones futuras."""
    nombres = {f for f in CampoReferencia.__dataclass_fields__}
    return ExtraccionDocumento(
        campos=[CampoReferencia(**{k: v for k, v in c.items() if k in nombres}) for c in datos.get("campos", [])],
        estructura=dict(datos.get("estructura", {})),
        plantilla_id=datos.get("plantilla_id"),
    )
