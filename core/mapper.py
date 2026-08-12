"""Orquestador de la Fase 2 y Fase 3 de AutoForm AI.

Recibe el mapa visual del formulario, genera el plan de mapeo y extiende el plan
para permitir la escritura física nativa en Excel.

Cambios v2:
  - Fix: import Tuple desde typing (corrige NameError en _calcular_celda_destino).
  - Fix: _filtrar_datos_empresa ahora usa modo PERMISIVO como fallback para evitar
    descartar campos legítimos por sinónimos no previstos.
  - Nuevo: _generar_reporte_cobertura() emite un log estructurado de qué campo
    se mapeó, cuál fue excluido en el filtro, y cuál el LLM no asignó.
  - Nuevo: _enriquecer_con_ancholinea() copia anchoLinea desde el mapa original
    hacia cada ítem del plan de mapeo, necesario para que el writer combine
    líneas de captura correctamente.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple   # ← FIX: Tuple estaba ausente

from core import semantic_cache
from core.llm_client import invocar_llm, STRICT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Claves del parser que necesita la IA para decidir semánticamente la
# ubicación. Los demás campos son internos y sólo aumentan tokens.
# ---------------------------------------------------------------------------
_CLAVES_LLM = {
    "hoja", "fila", "columna", "valor",
    "tipoEspacioEscritura", "anchoLinea", "anchoMergeVecino",
    "derechaVacia", "abajoVacia", "derechaEsMerge", "esMergePrincipal",
    "esCasillaVerificacion",
}

_CAMPOS_VIRTUALES = {"nit_sin_dv", "nit_dv"}


# ---------------------------------------------------------------------------
# LLM-04: Caché en memoria por hash del mapa de formularios
# ---------------------------------------------------------------------------
_cache_mapeos: Dict[str, List[Dict[str, Any]]] = {}
_cache_debug: Dict[str, Dict[str, Any]] = {}


def _hash_mapa(mapa_purgado: List[Dict[str, Any]]) -> str:
    """Genera un hash SHA-256 determinísta del mapa purgado."""
    contenido = json.dumps(mapa_purgado, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


def get_debug_info(hash_form: str) -> Optional[Dict[str, Any]]:
    """Retorna la información de debug almacenada para el hash dado."""
    return _cache_debug.get(hash_form)


def _purgar_mapa(mapa: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Genera una representación limpia y estructurada para el LLM con ID incremental explícito (1..N)."""
    purgado = []
    for idx, entrada in enumerate(mapa):
        purgado.append({
            "id": idx + 1,
            "rotulo": str(entrada.get("valor", "")).strip(),
            "hoja": str(entrada.get("hoja", "")),
            "fila": entrada.get("fila"),
            "columna": entrada.get("columna"),
            "tipoEspacioEscritura": str(entrada.get("tipoEspacioEscritura", "derecha")).lower(),
            "anchoLinea": entrada.get("anchoLinea", 1),
        })
    return purgado


# ---------------------------------------------------------------------------
# FIX PRINCIPAL: _filtrar_datos_empresa con modo PERMISIVO como fallback
# ---------------------------------------------------------------------------

#: Sinónimos de cada campo canónico tal como pueden aparecer en formularios.
_INDICIOS: Dict[str, List[str]] = {
    "razon_social":              ["nombre", "razon", "empresa", "proveedor", "social", "denominacion", "entidad"],
    "nit":                       ["nit", "rut", "identificacion", "cc/ce/pas", "fiscal", "tributaria", "registro"],
    "cedula":                    ["cedula", "c.c", "documento", "identidad", "id", "dni", "pasaporte"],
    "direccion":                 ["direccion", "domicilio", "domicilo", "residencia", "ubicacion", "sede", "principal"],
    "ciudad":                    ["ciudad", "municipio", "localidad", "poblacion"],
    "departamento":              ["departamento", "dpto", "estado", "provincia", "region"],
    "telefono":                  ["telefono", "tel", "celular", "contacto", "fono", "movil", "fax"],
    "correo":                    ["correo", "email", "e-mail", "mail", "electronico"],
    "pagina_web":                ["web", "pagina", "url", "sitio", "portal", "http"],
    "representante_legal":       ["representante", "legal", "gerente", "director", "administrador", "apoderado"],
    "representante_nombres":     ["nombres", "primer nombre", "segundo nombre"],
    "representante_apellidos":   ["apellidos", "primer apellido", "segundo apellido"],
    "pais":                      ["pais", "nacionalidad", "origen", "country"],
    "banco":                     ["banco", "bancaria", "financiera", "entidad bancaria", "institucion"],
    "numero_cuenta":             ["cuenta", "nro cuenta", "no. cuenta", "numero cuenta", "n° cuenta"],
    "tipo_cuenta":               ["tipo cuenta", "tipo de cuenta", "modalidad", "clase cuenta"],
    "sucursal":                  ["sucursal", "agencia", "oficina bancaria"],
}


def _filtrar_datos_empresa(
    mapa_purgo: List[Dict[str, Any]],
    datos: Dict[str, Any],
    modo_permisivo: bool = False,
) -> Dict[str, Any]:
    """Devuelve los campos de DatosEmpresa relevantes para el formulario actual.

    Estrategia:
    1. Primer pase ESTRICTO: retener sólo campos cuyos sinónimos aparecen en el
       vocabulario de rótulos del formulario.
    2. Si el resultado estricto cubre < 50 % de las claves disponibles, activar
       modo PERMISIVO: devolver todos los campos (safe-fallback que garantiza
       que el LLM recibe la información completa y decide él qué usar).

    Args:
        mapa_purgo:    Lista de entradas purgadas del parser.
        datos:         Diccionario completo de datos de la empresa.
        modo_permisivo: Si True, fuerza devolución de todos los campos sin filtro.
    """
    if modo_permisivo:
        return dict(datos)

    vocabulario = " ".join(
        str(e.get("valor", "")).lower() for e in mapa_purgo
    )

    resultado: Dict[str, Any] = {}
    for campo, valor in datos.items():
        indicios = _INDICIOS.get(campo)
        if indicios is None:
            # Clave desconocida → incluir por seguridad
            resultado[campo] = valor
        elif any(indicio in vocabulario for indicio in indicios):
            resultado[campo] = valor

    # ── FIX: Fallback permisivo si el filtro estricto dejó menos de la mitad ──
    total_campos = len(datos)
    campos_retenidos = len(resultado)
    if total_campos > 0 and campos_retenidos < max(1, total_campos // 2):
        print(
            f"[AutoForm AI] [WARNING] Filtro estricto retuvo solo {campos_retenidos}/{total_campos} campos. "
            f"Activando modo PERMISIVO para garantizar cobertura completa."
        )
        return dict(datos)

    return resultado


# ---------------------------------------------------------------------------
# Construcción del prompt
# ---------------------------------------------------------------------------

def construir_prompt(mapa_formularios: List[Dict[str, Any]], datos_empresa: Dict[str, Any]) -> str:
    """Construye el payload JSON compacto para el LLM."""
    mapa_purgado = _purgar_mapa(mapa_formularios)
    datos_filtrados = _filtrar_datos_empresa(mapa_purgado, datos_empresa)

    payload = {
        "F": mapa_purgado,
        "D": datos_filtrados,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Enriquecimiento: propagar anchoLinea desde el mapa original al plan de mapeo
# ---------------------------------------------------------------------------

def _enriquecer_con_ancholinea(
    plan_mapeo: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Copia anchoLinea y anchoMergeVecino desde el mapa original hacia cada
    ítem del plan de mapeo usando la clave (hoja, fila, columna) como índice.

    El writer usa anchoLinea para saber cuántas celdas contiguas combinar
    cuando rellena una línea de captura dividida (WRITER-03). Sin este paso,
    celdasAMergear siempre queda en 1 y el valor se escribe en una sola celda.
    """
    # Índice O(1): (hoja, fila, columna) → entrada del parser
    indice_mapa: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
    for entrada in mapa_formularios:
        clave = (
            str(entrada.get("hoja", "")),
            int(entrada.get("fila", 0) or 0),
            int(entrada.get("columna", 0) or 0),
        )
        indice_mapa[clave] = entrada

    enriquecidos: List[Dict[str, Any]] = []
    for item in plan_mapeo:
        clave = (
            str(item.get("hoja", "")),
            int(item.get("fila", 0) or 0),
            int(item.get("columna", 0) or 0),
        )
        entrada_original = indice_mapa.get(clave)
        item_enriquecido = dict(item)

        if entrada_original is not None:
            ancho_linea = int(entrada_original.get("anchoLinea", 1) or 1)
            ancho_merge = int(entrada_original.get("anchoMergeVecino", 1) or 1)

            # Propagar anchoLinea al plan de mapeo para que el writer lo use
            item_enriquecido["anchoLinea"] = ancho_linea

            # Si el LLM no calculó celdasAMergear correctamente, usar el valor
            # del parser que es más preciso (basado en escaneo visual real).
            celdas_llm = int(item.get("celdasAMergear", 1) or 1)
            if celdas_llm <= 1 and (ancho_linea > 1 or ancho_merge > 1):
                item_enriquecido["celdasAMergear"] = max(ancho_linea, ancho_merge)
                item_enriquecido["requiereMerge"] = True

        enriquecidos.append(item_enriquecido)

    return enriquecidos


# ---------------------------------------------------------------------------
# Reporte de cobertura estructurado
# ---------------------------------------------------------------------------

def _generar_reporte_cobertura(
    datos_empresa: Dict[str, Any],
    datos_filtrados: Dict[str, Any],
    plan_final: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Genera un reporte detallado con el estado de cada campo del perfil.

    Returns:
        Dict con listas: mapeados, excluidos_por_filtro, no_asignados_por_llm.
    """
    todos_campos = set(datos_empresa.keys()) | _CAMPOS_VIRTUALES
    en_filtrado = set(datos_filtrados.keys())
    asignados = {item["campo"] for item in plan_final if item.get("campo")}

    excluidos_por_filtro = sorted(todos_campos - en_filtrado - _CAMPOS_VIRTUALES)
    no_asignados_llm = sorted(en_filtrado - asignados)
    mapeados = sorted(asignados)

    reporte = {
        "total_campos_perfil": len(todos_campos),
        "campos_mapeados": mapeados,
        "excluidos_por_filtro": excluidos_por_filtro,
        "no_asignados_por_llm": no_asignados_llm,
        "cobertura_pct": round(len(mapeados) / max(len(en_filtrado), 1) * 100, 1),
    }

    # Log estructurado para diagnóstico
    print("\n" + "=" * 60)
    print("REPORTE DE COBERTURA AutoForm AI")
    print("=" * 60)
    print(f"  [OK] Mapeados ({len(mapeados)}):           {mapeados}")
    print(f"  [EXCLUDED] Excluidos por filtro ({len(excluidos_por_filtro)}): {excluidos_por_filtro}")
    print(f"  [UNASSIGNED] No asignados LLM ({len(no_asignados_llm)}):    {no_asignados_llm}")
    print(f"  [STATS] Cobertura: {reporte['cobertura_pct']}%")
    print("=" * 60 + "\n")

    return reporte


# ---------------------------------------------------------------------------
# Helpers de validación e inferencia
# ---------------------------------------------------------------------------

_CAMPOS_REQUIEREN_MERGE = {
    "razon_social", "direccion", "representante_legal",
    "representante_nombres", "representante_apellidos",
    "correo", "pagina_web", "objeto_social", "actividad_economica",
}

_PATRON_ETIQUETA_MERGE = re.compile(
    r"firma|\bdirecci[oó]n\b|\bdomicilio\b|\brazon\b|social|nombre\s+completo"
    r"|tel[eé]fono|correo|email|p[aá]gina\s*web|objeto|actividad",
    flags=re.IGNORECASE,
)


def _necesita_merge(etiqueta: str, campo: str) -> bool:
    if campo in _CAMPOS_REQUIEREN_MERGE:
        return True
    if _PATRON_ETIQUETA_MERGE.search(str(etiqueta or "")):
        return True
    if "_" in str(etiqueta or ""):
        return True
    return False


def _validar_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Cada elemento del resultado debe ser un objeto JSON.")

    campo = str(item.get("campo", "")).strip()
    if not campo:
        return {
            "hoja": str(item.get("hoja", "")),
            "fila": int(item.get("fila", 0) or 0),
            "columna": int(item.get("columna", 0) or 0),
            "valor": str(item.get("valor", "")),
            "ubicacion": "",
            "campo": "",
            "requiereMerge": False,
            "celdasAMergear": 1,
        }

    ubicacion = str(item.get("ubicacion", "")).lower().strip()
    if ubicacion not in {"derecha", "abajo", "misma"}:
        raise ValueError(
            f"Ubicación inválida: {ubicacion!r}. Solo se admite 'derecha', 'abajo' o 'misma'."
        )

    requiere_merge = bool(item.get("requiereMerge", False))
    celdas_a_mergear = int(item.get("celdasAMergear", 1) or 1)
    if celdas_a_mergear < 1:
        celdas_a_mergear = 1
    if requiere_merge and celdas_a_mergear == 1:
        celdas_a_mergear = 3

    return {
        "hoja": str(item.get("hoja", "")),
        "fila": int(item.get("fila", 0) or 0),
        "columna": int(item.get("columna", 0) or 0),
        "valor": str(item.get("valor", "")),
        "ubicacion": ubicacion,
        "campo": campo,
        "requiereMerge": requiere_merge,
        "celdasAMergear": celdas_a_mergear,
    }


def _extraer_json(texto: str) -> Any:
    """Extrae y parsea JSON de la respuesta del LLM (6 estrategias en cascada)."""
    texto_limpio = texto.strip()

    # 1. Parseo directo
    try:
        return json.loads(texto_limpio)
    except json.JSONDecodeError:
        pass

    # 2. Bloques markdown ```json ... ```
    bloque = re.search(r'```(?:json)?\s*(.*?)\s*```', texto, re.DOTALL | re.IGNORECASE)
    if bloque:
        try:
            return json.loads(bloque.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Primera '[' hasta última ']' o '{' hasta '}'
    for patron in (r'(\[.*\])', r'(\{.*\})'):
        m = re.search(patron, texto, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

    # 4. Búsqueda inversa desde el último '[' (para modelos de razonamiento)
    ultimo_corchete = texto_limpio.rfind('[')
    if ultimo_corchete != -1:
        fragmento = texto_limpio[ultimo_corchete:]
        try:
            return json.loads(fragmento)
        except json.JSONDecodeError:
            pass
        pos = fragmento.rfind('}')
        if pos != -1:
            reparado = fragmento[:pos + 1].rstrip().rstrip(',') + '\n]'
            try:
                return json.loads(reparado)
            except json.JSONDecodeError:
                pass

    # 5. Reparación genérica de array truncado
    try:
        pos_ultimo = texto_limpio.rfind('}')
        if pos_ultimo != -1:
            recortado = texto_limpio[:pos_ultimo + 1].strip()
            if not recortado.endswith(']'):
                recortado += '\n]'
            pos_inicio = recortado.find('[')
            if pos_inicio != -1:
                return json.loads(recortado[pos_inicio:])
    except json.JSONDecodeError:
        pass

    raise ValueError("No se encontró una estructura JSON válida en la respuesta del LLM.")


def _procesar_resultado_llm(respuesta: str) -> List[Dict[str, Any]]:
    """Extrae y parsea la lista de emparejamientos compactos {id, campo, ubicacion} del LLM.

    NO usa Pydantic MapeoItem (que requiere hoja/fila/columna). La conversión a
    coordenadas físicas ocurre en _reconstruir_mapeo_fisico().
    """
    datos_raw: Any = None
    texto = str(respuesta).strip()

    # 1. Parseo directo
    try:
        datos_raw = json.loads(texto)
    except json.JSONDecodeError:
        pass

    # 2. Bloques markdown ```json ... ```
    if datos_raw is None:
        for m in re.finditer(r'```(?:json)?\s*(.*?)\s*```', texto, re.DOTALL | re.IGNORECASE):
            try:
                datos_raw = json.loads(m.group(1).strip())
                break
            except json.JSONDecodeError:
                pass

    # 3. Buscar desde último '[' o '{'
    if datos_raw is None:
        for ch_o, ch_c in [('[', ']'), ('{', '}')]:
            idx = texto.rfind(ch_o)
            if idx != -1:
                try:
                    datos_raw = json.loads(texto[idx:])
                    break
                except json.JSONDecodeError:
                    try:
                        fragmento = texto[idx:]
                        idx_c = fragmento.rfind(ch_c)
                        if idx_c != -1:
                            datos_raw = json.loads(fragmento[:idx_c + 1])
                            break
                    except json.JSONDecodeError:
                        pass

    if datos_raw is None:
        print(f"[AutoForm AI Pydantic] Error: No se pudo parsear JSON de respuesta LLM")
        return []

    # Normalizar a lista
    if isinstance(datos_raw, dict):
        if "mappings" in datos_raw and isinstance(datos_raw["mappings"], list):
            datos_raw = datos_raw["mappings"]
        elif "resultado" in datos_raw and isinstance(datos_raw["resultado"], list):
            datos_raw = datos_raw["resultado"]
        else:
            datos_raw = [datos_raw]

    if not isinstance(datos_raw, list):
        return []

    # Retornar solo items con id/campo o con hoja/fila/columna — sin validación Pydantic
    resultado: List[Dict[str, Any]] = []
    for item in datos_raw:
        if not isinstance(item, dict):
            continue
        tiene_compacto = "id" in item and "campo" in item
        tiene_fisico = "hoja" in item and "fila" in item and "columna" in item and "campo" in item
        if tiene_compacto or tiene_fisico:
            resultado.append(item)
    return resultado


# ---------------------------------------------------------------------------
# Auditoría de cobertura y re-consulta focalizada
# ---------------------------------------------------------------------------

def _evaluar_cobertura_campos(
    datos_empresa_filtrados: Dict[str, Any],
    mapeos_realizados: List[Dict[str, Any]],
) -> List[str]:
    """Devuelve los campos de DatosEmpresa que el LLM no asignó a ninguna celda."""
    esperados = set(datos_empresa_filtrados.keys())
    asignados = {item["campo"] for item in mapeos_realizados if item.get("campo")}
    return sorted(list(esperados - asignados))


def _construir_prompt_focalizado(
    mapa_formularios: List[Dict[str, Any]],
    mapeos_realizados: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    campos_faltantes: List[str],
) -> str:
    """Payload ultra-compacto para la re-consulta de cobertura."""
    celdas_ocupadas = {
        (item["hoja"], item["fila"], item["columna"])
        for item in mapeos_realizados
    }
    mapa_purgado = _purgar_mapa(mapa_formularios)
    rotulos_libres = [
        elem for elem in mapa_purgado
        if (elem.get("hoja"), elem.get("fila"), elem.get("columna")) not in celdas_ocupadas
    ]
    datos_faltantes = {k: datos_empresa[k] for k in campos_faltantes if k in datos_empresa}
    payload = {"F": rotulos_libres, "D": datos_faltantes}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# LLM-03: Deduplicación de coordenadas destino
# ---------------------------------------------------------------------------

def _calcular_celda_destino(item: Dict[str, Any]) -> Tuple[str, int, int]:
    """Calcula la coordenada de destino final (hoja, fila_destino, col_destino)."""
    hoja = str(item.get("hoja", ""))
    fila = int(item.get("fila", 0) or 0)
    col  = int(item.get("columna", 0) or 0)
    ubicacion = str(item.get("ubicacion", "")).lower()

    if ubicacion == "misma":
        return (hoja, fila, col)
    elif ubicacion == "abajo":
        return (hoja, fila + 1, col)
    else:
        return (hoja, fila, col + 1)


def deduplicar_coordenadas_destino(mapeos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Conserva sólo la primera asignación a cada celda de destino."""
    destinos_ocupados: set = set()
    resultado: List[Dict[str, Any]] = []
    for item in mapeos:
        coord = _calcular_celda_destino(item)
        if coord in destinos_ocupados:
            print(
                f"[AutoForm AI LLM-03] Deduplicación: campo '{item.get('campo')}' "
                f"omitido (celda destino {coord} ya ocupada)."
            )
            continue
        destinos_ocupados.add(coord)
        resultado.append(item)
    return resultado


def _validar_hard_gates_mapeo(
    resultado_mapeo: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Hard-Gate Validador: Garantiza que la Razón Social y el NIT no sean omitidos.

    Si el formulario tiene una celda para 'Razón Social' o 'NIT' y existe el dato en
    datos_empresa, se fuerza su asignación si el LLM por error lo dejó fuera.
    """
    campos_mapeados = {m.get("campo") for m in resultado_mapeo if m.get("campo")}
    mapeo_resultado = list(resultado_mapeo)

    # Regla 1: Razón Social
    if "razon_social" not in campos_mapeados and datos_empresa.get("razon_social"):
        for elem in mapa_formularios:
            val_str = str(elem.get("valor", "")).strip().lower()
            if re.search(r"r[aá]z[oó]n\s+social|nombre\s+(?:de\s+la\s+)?empresa|proponente|oferente|sociedad", val_str):
                mapeo_resultado.append({
                    "hoja": elem.get("hoja", ""),
                    "fila": int(elem.get("fila", 1)),
                    "columna": int(elem.get("columna", 1)),
                    "valor": elem.get("valor", ""),
                    "ubicacion": "derecha",
                    "campo": "razon_social",
                    "requiereMerge": True,
                    "celdasAMergear": int(elem.get("anchoLinea", 3) or 3),
                    "anchoLinea": int(elem.get("anchoLinea", 3) or 3),
                })
                print(f"[AutoForm AI Hard-Gate] Razón Social recuperada automáticamente para el rótulo '{elem.get('valor')}'")
                break

    # Regla 2: NIT
    if "nit" not in campos_mapeados and datos_empresa.get("nit"):
        for elem in mapa_formularios:
            val_str = str(elem.get("valor", "")).strip().lower()
            if re.search(r"\bnit\b|n\.i\.t|identificaci[oó]n\s+tributaria|r\.u\.t", val_str):
                mapeo_resultado.append({
                    "hoja": elem.get("hoja", ""),
                    "fila": int(elem.get("fila", 1)),
                    "columna": int(elem.get("columna", 1)),
                    "valor": elem.get("valor", ""),
                    "ubicacion": "derecha",
                    "campo": "nit",
                    "requiereMerge": False,
                    "celdasAMergear": 1,
                    "anchoLinea": 1,
                })
                print(f"[AutoForm AI Hard-Gate] NIT recuperado automáticamente para el rótulo '{elem.get('valor')}'")
                break

    return mapeo_resultado



def _fusionar_mapeos(
    mapeos_iniciales: List[Dict[str, Any]],
    mapeos_complementarios: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Combina mapeos sin colisiones de celdas origen."""
    celdas_existentes = {
        (item["hoja"], item["fila"], item["columna"]) for item in mapeos_iniciales
    }
    resultado = list(mapeos_iniciales)
    for item in mapeos_complementarios:
        clave = (item["hoja"], item["fila"], item["columna"])
        if clave not in celdas_existentes:
            resultado.append(item)
            celdas_existentes.add(clave)
    return resultado


def _reconstruir_mapeo_fisico(
    coincidencias_semanticas: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Transforma respuestas compactas del LLM (id -> campo) en objetos físicos con hoja, fila, columna."""
    dict_mapa = {idx + 1: elem for idx, elem in enumerate(mapa_formularios)}
    resultado = []

    for match in coincidencias_semanticas:
        item_id = match.get("id")
        campo = match.get("campo")
        ubicacion_llm = str(match.get("ubicacion", "")).lower()

        if item_id in dict_mapa and campo and campo in datos_empresa:
            elem = dict_mapa[item_id]
            val_str = str(elem.get("valor", "")).strip()

            tipo_sugerido = str(elem.get("tipoEspacioEscritura", "derecha")).lower()
            if re.search(r"_{2,}|\.{3,}", val_str):
                ubicacion_calc = "misma"
            elif ubicacion_llm in ("derecha", "abajo", "misma"):
                ubicacion_calc = ubicacion_llm
            elif tipo_sugerido in ("derecha", "abajo", "misma"):
                ubicacion_calc = tipo_sugerido
            else:
                ubicacion_calc = "derecha"

            ancho_l = int(elem.get("anchoLinea", 1) or 1)
            resultado.append({
                "hoja": elem.get("hoja", ""),
                "fila": int(elem.get("fila", 1)),
                "columna": int(elem.get("columna", 1)),
                "inicioLineaCol": int(elem.get("inicioLineaCol") or elem.get("columna", 1)),
                "finLineaCol": int(elem.get("finLineaCol") or elem.get("columna", 1)),
                "valor": val_str,
                "ubicacion": ubicacion_calc,
                "campo": campo,
                "requiereMerge": bool(ancho_l > 1 and ubicacion_calc == "derecha"),
                "celdasAMergear": ancho_l,
                "anchoLinea": ancho_l,
            })
    return resultado


# ---------------------------------------------------------------------------
# Orquestador principal
# ---------------------------------------------------------------------------

# Variable global para pausar/activar el caché
CACHE_HABILITADO: bool = False


def deshabilitar_cache() -> None:
    """Pone en pausa completamente el sistema de caché."""
    global CACHE_HABILITADO
    CACHE_HABILITADO = False
    print("[AutoForm AI Cache] Caché pausado / deshabilitado.")


def habilitar_cache() -> None:
    """Activa el sistema de caché."""
    global CACHE_HABILITADO
    CACHE_HABILITADO = True
    print("[AutoForm AI Cache] Caché activado.")


def mapeo_formularios(
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Genera el plan de mapeo completo para un formulario Excel.

    Flujo:
    1. Caché exacto (hash SHA-256) → retorno inmediato (si CACHE_HABILITADO).
    2. Caché semántico fuzzy (rapidfuzz ≥ 90 %) → adaptar coordenadas (si CACHE_HABILITADO).
    3. Llamada principal al LLM.
    4. Auditoría de cobertura + re-consulta focalizada si hay omisiones.
    5. Deduplicación de coordenadas destino.
    6. Enriquecimiento con anchoLinea del parser (WRITER-03).
    7. Persistencia en caché de sesión y en disco (si CACHE_HABILITADO).
    """
    if not isinstance(mapa_formularios, list):
        raise ValueError("El mapa de formularios debe ser una lista de objetos.")

    mapa_purgado_pre = _purgar_mapa(mapa_formularios)
    form_hash = _hash_mapa(mapa_purgado_pre)

    if CACHE_HABILITADO:
        # ── 1. Caché exacto ───────────────────────────────────────────────────
        if form_hash in _cache_mapeos:
            print(f"[AutoForm AI LLM-04] Cache HIT Exacto (hash {form_hash[:12]}...).")
            return _cache_mapeos[form_hash]

        # ── 2. Caché semántico fuzzy ──────────────────────────────────────────
        huella = semantic_cache.generar_huella_formulario(mapa_purgado_pre)
        res_fuzzy = semantic_cache.buscar_plantilla_similar(huella, umbral=90.0)

        if res_fuzzy is not None:
            id_plantilla, plantilla_guardada, score = res_fuzzy
            plan_adaptado = semantic_cache.adaptar_mapeo_plantilla(mapa_formularios, plantilla_guardada)
            plan_adaptado = _enriquecer_con_ancholinea(plan_adaptado, mapa_formularios)

            plan_valido = [
                p for p in plan_adaptado
                if p.get("hoja") and int(p.get("fila", 0) or 0) > 0 and p.get("campo")
            ]

            if plan_valido:
                print(
                    f"[AutoForm AI FASE B] Cache Semantico HIT "
                    f"(Score: {score:.1f}% - Plantilla: {id_plantilla})."
                )
                _cache_mapeos[form_hash] = plan_valido
                _cache_debug[form_hash] = {
                    "hash": form_hash,
                    "tipo_cache": "SEMANTIC_FUZZY_HIT",
                    "score_similaridad": round(score, 1),
                    "plantilla_coincidente": id_plantilla,
                    "rotulos_enviados": len(mapa_purgado_pre),
                    "prompt_payload": f"[Caché Semántico Fuzzy {score:.1f}% — plantilla {id_plantilla}]",
                    "respuesta_llm": json.dumps(plan_valido, ensure_ascii=False),
                    "campos_mapeados": len(plan_valido),
                    "campos_faltantes_detectados": [],
                }
                return plan_valido
            else:
                print(
                    f"[AutoForm AI FASE B] Cache Semantico HIT invalido (plan vacio) "
                    f"para {id_plantilla}. Forzando Cache MISS..."
                )
                try:
                    semantic_cache.eliminar_plantilla(id_plantilla)
                except Exception:
                    pass
    else:
        print("[AutoForm AI Cache] Caché desactivado. Procesando dinámicamente con IA (LLM)...")

    print(f"[AutoForm AI LLM-04] Cache MISS (hash {form_hash[:12]}...). Invocando LLM...")

    # ── 3. Llamada principal al LLM ───────────────────────────────────────
    mapa_purgado = _purgar_mapa(mapa_formularios)
    datos_filtrados = _filtrar_datos_empresa(mapa_purgado, datos_empresa, modo_permisivo=False)

    prompt_principal = json.dumps(
        {"F": mapa_purgado, "D": datos_filtrados},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    respuesta_principal = invocar_llm(prompt_principal)
    coincidencias_raw = _procesar_resultado_llm(respuesta_principal)
    mapeos_iniciales = _reconstruir_mapeo_fisico(coincidencias_raw, mapa_formularios, datos_empresa)

    # ── 4. Auditoría de cobertura ─────────────────────────────────────────
    campos_faltantes = _evaluar_cobertura_campos(datos_filtrados, mapeos_iniciales)
    resultado_final: List[Dict[str, Any]]

    if not campos_faltantes:
        print("[AutoForm AI Coverage] [OK] Cobertura 100 %.")
        resultado_final = mapeos_iniciales
    else:
        print(
            f"[AutoForm AI Coverage] [WARNING] Faltan {len(campos_faltantes)} campos: "
            f"{campos_faltantes}. Ejecutando re-mapeo focalizado..."
        )
        try:
            prompt_focalizado = _construir_prompt_focalizado(
                mapa_formularios, mapeos_iniciales, datos_empresa, campos_faltantes
            )
            respuesta_comp = invocar_llm(prompt_focalizado)
            coincidencias_comp_raw = _procesar_resultado_llm(respuesta_comp)
            mapeos_comp = _reconstruir_mapeo_fisico(coincidencias_comp_raw, mapa_formularios, datos_empresa)
            resultado_final = _fusionar_mapeos(mapeos_iniciales, mapeos_comp)
            print(
                f"[AutoForm AI Coverage] Re-mapeo: +{len(resultado_final) - len(mapeos_iniciales)} "
                f"campos recuperados."
            )
        except Exception as exc:
            print(f"[AutoForm AI Warning] Re-consulta de cobertura falló ({exc}). Usando mapeo inicial.")
            resultado_final = mapeos_iniciales

    # ── 5. Hard Gates Validador (Garantizar campos críticos Razón Social y NIT) ──
    resultado_final = _validar_hard_gates_mapeo(resultado_final, mapa_formularios, datos_empresa)

    # ── 6. Deduplicación ──────────────────────────────────────────────────
    resultado_final = deduplicar_coordenadas_destino(resultado_final)

    # ── 7. Enriquecimiento con anchoLinea del parser (WRITER-03) ──────────
    resultado_final = _enriquecer_con_ancholinea(resultado_final, mapa_formularios)

    # ── 8. Reporte de cobertura en consola ────────────────────────────────
    _generar_reporte_cobertura(datos_empresa, datos_filtrados, resultado_final)


    # ── 8. Persistencia (solo si el caché está activo) ───────────────────────
    if CACHE_HABILITADO:
        _cache_mapeos[form_hash] = resultado_final
        try:
            semantic_cache.guardar_plantilla_en_cache(form_hash[:16], mapa_purgado_pre, resultado_final)
        except Exception as exc:
            print(f"[AutoForm AI Warning] No se pudo guardar en Caché Semántico: {exc}")

    _cache_debug[form_hash] = {
        "hash": form_hash,
        "tipo_cache": "LLM_GENERATED",
        "rotulos_enviados": len(mapa_purgado_pre),
        "prompt_payload": prompt_principal,
        "respuesta_llm": respuesta_principal,
        "campos_mapeados": len(resultado_final),
        "campos_faltantes_detectados": campos_faltantes if campos_faltantes else [],
    }

    return resultado_final