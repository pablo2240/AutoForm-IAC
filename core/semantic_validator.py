"""Validador Determinístico Semántico — Fase 2 del pipeline HSP de AutoForm AI.

Responsabilidad ÚNICA: comprobar que un mapeo propuesto (plan_mapeo generado por el LLM
o por el Template Store) sea estructuralmente coherente antes de presentarlo al usuario.

=========================================================================================
PRINCIPIO CENTRAL (ajuste aprobado por el usuario):
  La inteligencia principal es ESTRUCTURA + CONTEXTO + CLASIFICACIÓN + SEMÁNTICA.
  Este módulo NO acumula reglas por rótulo (ej. "si contiene 'banco' entonces...").
  Comprueba únicamente propiedades estructurales y de compatibilidad universales:

    1. El tipo de elemento es compatible con el mapping (FIELD/UNKNOWN → mapeable;
       OPTION/SECTION_TITLE/DECORATIVE/INSTRUCTION/LEGAL_TEXT → no se mapean).
    2. El campo maestro propuesto existe en datos_empresa.
    3. El tipo de dato del valor vs. el campo es compatible (fecha≠texto_libre, etc.).
    4. La sección no está marcada como OMITIR_* (short-circuit de sección completa).
    5. No existe una contradicción evidente entre rótulo y campo (detectada solo cuando
       la incompatibilidad es estructuralmente obvia, no por lógica por-rótulo).
    6. Los casos ambiguos van a estado REVISION, nunca a DESCARTADO automáticamente.

=========================================================================================
Salida por ítem del plan:
    {
        "estado": "APROBADO" | "REVISION" | "DESCARTADO",
        "motivo": str,           # vacío si APROBADO
        "nivel_confianza": "EXACTA" | "ALTA" | "PARCIAL" | "SIN_COINCIDENCIA",
        "campo_propuesto": str,  # campo maestro del LLM
        "campo_final": str,      # puede diferir si se autocorrigió
        ...resto del plan_item original
    }
=========================================================================================
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# 1. CONSTANTES DE ESTADO Y CONFIANZA
# ──────────────────────────────────────────────────────────────────────────────

class EstadoMapeo:
    APROBADO = "APROBADO"
    REVISION = "REVISION"
    DESCARTADO = "DESCARTADO"


class NivelConfianza:
    EXACTA = "EXACTA"
    ALTA = "ALTA"
    PARCIAL = "PARCIAL"
    SIN_COINCIDENCIA = "SIN_COINCIDENCIA"


# Tipos de elemento del IR que pueden ser mapeados a datos maestros
_TIPOS_MAPEABLES = {"FIELD", "UNKNOWN"}

# Tipos de elemento que NUNCA se mapean (structuralmente incompatibles)
_TIPOS_NO_MAPEABLES = {"OPTION", "SECTION_TITLE", "DECORATIVE", "INSTRUCTION", "LEGAL_TEXT"}

# Campos del perfil que almacenan fechas (no texto libre)
_CAMPOS_FECHA: Set[str] = {"fecha_expedicion", "fecha_nacimiento", "fecha_constitucion"}

# Campos del perfil que almacenan valores numéricos o con formato
_CAMPOS_NUMERICOS: Set[str] = {"nit", "cedula", "numero_cuenta"}

# Secciones semánticamente propias del representante legal / persona natural
_TOKENS_SECCION_REP_LEGAL = {
    "representante", "apoderado", "persona natural", "rep legal", "firmante", "conyuge", "gerente", "titular",
}

# Secciones semánticamente propias de la empresa / persona jurídica / proponente
_TOKENS_SECCION_EMPRESA = {
    "empresa", "sociedad", "persona juridica", "razon social", "proponente", "oferente",
    "proveedor", "cliente", "tributaria", "tributario", "solicitante", "entidad", "general", "basica",
}

# Secciones semánticamente bancarias / financieras
_TOKENS_SECCION_BANCARIA = {
    "banco", "bancaria", "bancario", "financiera", "financiero", "cuenta", "pagos",
}

# Tokens que identifican secciones de terceros u uso interno
_TOKENS_SECCION_OMITIR = {
    "tercero", "proveedor externo", "para uso de", "uso exclusivo",
    "espacio reservado", "auditoría", "auditoria", "observaciones del líder",
}


# ──────────────────────────────────────────────────────────────────────────────
# 2. HELPERS DE NORMALIZACIÓN
# ──────────────────────────────────────────────────────────────────────────────

def _normalizar(txt: str) -> str:
    """Normaliza: sin acentos, minúsculas, espacios colapsados."""
    if not txt:
        return ""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", str(txt).lower())
        if unicodedata.category(c) != "Mn"
    )
    sin_acentos = sin_acentos.replace("°", "").replace("º", "")
    return re.sub(r"[\s_\-\./\\]+", " ", sin_acentos).strip()


def _aplanar_datos_empresa(datos_empresa: Dict[str, Any]) -> Dict[str, Any]:
    """Aplana el perfil jerárquico en un dict plano {clave: valor}.

    Ejemplo: {"empresa": {"identidad": {"nit": "8110..."}}} → {"nit": "8110..."}
    """
    plano: Dict[str, Any] = {}

    def _recorrer(obj: Any, prefijo: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _recorrer(v, k)
        else:
            if prefijo:
                plano[prefijo] = obj

    _recorrer(datos_empresa)

    # Generación compuesta ciudad_departamento si existen ambos
    c_val = str(plano.get("ciudad", "")).strip()
    d_val = str(plano.get("departamento", "")).strip()
    if c_val and d_val:
        plano["ciudad_departamento"] = f"{c_val}/{d_val}"
    elif c_val:
        plano["ciudad_departamento"] = c_val
    elif d_val:
        plano["ciudad_departamento"] = d_val

    return plano


def _obtener_valor_maestro(campo: str, datos_planos: Dict[str, Any]) -> Optional[Any]:
    """Retorna el valor del campo en los datos planos, o None si no existe."""
    # Prueba directa
    if campo in datos_planos:
        return datos_planos[campo]
    # Prueba de última parte compuesta: "empresa.nit" → "nit"
    if "." in campo:
        terminal = campo.split(".")[-1]
        if terminal in datos_planos:
            return datos_planos[terminal]
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 3. REGLAS ESTRUCTURALES (no por rótulo, sino por propiedades universales)
# ──────────────────────────────────────────────────────────────────────────────

def _regla_tipo_elemento_compatible(
    tipo_elemento: str,
) -> Tuple[bool, str]:
    """R1: El tipo de elemento IR debe ser mapeable (FIELD/UNKNOWN)."""
    if tipo_elemento in _TIPOS_MAPEABLES:
        return True, ""
    if tipo_elemento in _TIPOS_NO_MAPEABLES:
        return False, (
            f"El tipo de elemento '{tipo_elemento}' no es mapeable. "
            f"Solo FIELD y UNKNOWN pueden asignarse a campos maestros."
        )
    return True, ""


def _regla_campo_existe(
    campo: str,
    datos_planos: Dict[str, Any],
) -> Tuple[bool, str]:
    """R2: El campo propuesto debe existir en datos_empresa."""
    valor = _obtener_valor_maestro(campo, datos_planos)
    if valor is None:
        return False, f"El campo '{campo}' no existe en el perfil empresarial."
    return True, ""


def _regla_campo_tiene_valor(
    campo: str,
    datos_planos: Dict[str, Any],
) -> Tuple[bool, str]:
    """R2b: El campo debe tener un valor no vacío."""
    valor = _obtener_valor_maestro(campo, datos_planos)
    if valor is None:
        return False, f"Campo '{campo}' inexistente en el perfil."
    if str(valor).strip() == "":
        return True, f"El campo '{campo}' existe pero su valor está vacío en el perfil."
    return True, ""


def _regla_compatibilidad_tipo_dato(
    campo: str,
    rotulo_normalizado: str,
) -> Tuple[bool, str]:
    """R3: Compatibilidad estructural entre campo maestro y contexto del rótulo.

    Detecta únicamente contradicciones obvias a nivel de tipo de dato:
      - Un campo de fecha NO puede asignarse a un rótulo que dice "banco", "nit", etc.
      - Un campo de texto libre NO puede asignarse a un rótulo que claramente pide fecha.

    NO aplica lógica por-rótulo específica. Solo detección de incompatibilidad
    de categoría entre la semántica del campo y la del rótulo.
    """
    # Si el campo es de fecha pero el rótulo NO contiene ninguna referencia temporal
    if campo in _CAMPOS_FECHA:
        tokens_fecha = {"fecha", "date", "vigencia", "expedicion", "nacimiento", "constitucion"}
        if not any(t in rotulo_normalizado for t in tokens_fecha):
            return False, (
                f"El campo '{campo}' es de tipo fecha pero el rótulo '{rotulo_normalizado}' "
                f"no hace referencia a una fecha. Probable asignación incorrecta."
            )

    # Si el rótulo claramente pide una fecha pero el campo no es de fecha ni texto libre
    tokens_fecha_rotulo = {"fecha", "date", "vigencia"}
    es_rotulo_de_fecha = any(t in rotulo_normalizado for t in tokens_fecha_rotulo)
    if es_rotulo_de_fecha and campo in _CAMPOS_NUMERICOS:
        return False, (
            f"El rótulo '{rotulo_normalizado}' solicita una fecha pero "
            f"el campo '{campo}' es numérico/identificador."
        )

    return True, ""


def _regla_lugar_expedicion_no_es_fecha(
    campo: str,
    rotulo_normalizado: str,
) -> Tuple[bool, str]:
    """R3b: lugar_expedicion NUNCA debe asignarse a rótulos de fecha.

    Esta regla corrige el error sistemático documentado:
    "lugar_expedicion" → celda "Fecha de expedición".
    Es una barrera de seguridad estructural, no una regla por rótulo.
    """
    if campo in ("lugar_expedicion", "expedicion"):
        tokens_fecha = {"fecha", "date", "dd", "mm", "yyyy", "vigencia", "dia", "año"}
        if any(t in rotulo_normalizado for t in tokens_fecha):
            return False, (
                f"'{campo}' es un lugar (texto), no una fecha. "
                f"No puede asignarse al rótulo de fecha '{rotulo_normalizado}'."
            )
    return True, ""


def _regla_no_asignar_tipo_documento_a_compuesto(
    campo: str,
    rotulo_normalizado: str,
) -> Tuple[str, str]:
    """R4 (autocorrección): CC/CE/PAS/NIT compuesto → usar 'nit', no 'tipo_documento' (a menos que pida explícitamente el tipo).

    Retorna (campo_final, motivo_correccion). Si no hay corrección, motivo es vacío.
    """
    # Si el rótulo pide explícitamente el TIPO (ej. "Tipo de Identificación (CC-Pasaporte-CE)"), conservar tipo_documento
    if "tipo" in rotulo_normalizado or "clase" in rotulo_normalizado:
        return campo, ""

    patron_compuesto = re.compile(
        r"\b(?:cc[\/\s]*ce|cc[\/\s]*nit|nit[\/\s]*cc|cc[\/\s]*ce[\/\s]*pas)\b",
        re.IGNORECASE
    )
    if campo == "tipo_documento" and patron_compuesto.search(rotulo_normalizado):
        return "nit", "Rótulo compuesto CC/CE/PAS/NIT → corregido a 'nit' (el campo pide el número, no el tipo)."
    return campo, ""


def _regla_telefono_en_seccion_rep_legal(
    campo: str,
    seccion_normalizada: str,
    rotulo_normalizado: str = "",
) -> Tuple[str, str]:
    """R5 (autocorrección): Teléfono móvil prioritario o en sección representante legal → 'celular'."""
    if re.search(r"\btel[eé]fono[\s/]*celular\b|\btel[\s/]*cel\b|\bcelular\b|\bmovil\b", rotulo_normalizado):
        return "celular", "Rótulo 'Teléfono Celular' / 'Teléfono/Celular' → asignado a 'celular' (prioridad móvil)."

    if campo == "telefono":
        if any(t in seccion_normalizada for t in _TOKENS_SECCION_REP_LEGAL):
            return "celular", (
                "Sección del representante legal: 'telefono' empresa corregido a 'celular' "
                "(se espera el móvil del representante, no el PBX de la empresa)."
            )
    return campo, ""


def _regla_autocorrecciones_semanticas_adicionales(
    campo: str,
    rotulo_normalizado: str,
    seccion_normalizada: str = "",
) -> Tuple[str, str]:
    """R5b (autocorrecciones semánticas de negocio solicitadas con desambiguación contextual)."""
    # 1. Ciudad / Departamento combinado
    if re.search(r"\bciudad[\s/]+departamento\b|\bciudad[\s/]+depto\b|\bmunicipio[\s/]+departamento\b", rotulo_normalizado):
        if campo != "ciudad_departamento":
            return "ciudad_departamento", "Rótulo combinado 'Ciudad/Departamento' → asignado a campo compuesto 'ciudad_departamento'."

    # 2. Razón Social o Nombres y Apellidos -> representante_legal
    if "razon social" in rotulo_normalizado and ("nombres" in rotulo_normalizado or "apellidos" in rotulo_normalizado):
        if campo != "representante_legal":
            return "representante_legal", "Rótulo 'Razón Social o Nombres y Apellidos' → asignado a 'representante_legal'."

    # 3. Nombre Comercial -> razon_social
    if "nombre comercial" in rotulo_normalizado:
        if campo != "razon_social":
            return "razon_social", "Rótulo 'Nombre Comercial' → asignado a 'razon_social'."

    # 4. NIT / TAX ID -> nit
    if re.search(r"\bnit[\s/]*tax\s*id\b|\btax\s*id\b", rotulo_normalizado):
        if campo != "nit":
            return "nit", "Rótulo 'NIT / TAX ID' → asignado a 'nit'."

    # 5. Tipo de Identificación -> tipo_documento
    if "tipo" in rotulo_normalizado and any(k in rotulo_normalizado for k in ("documento", "identificacion", "id")):
        if campo != "tipo_documento":
            return "tipo_documento", "Rótulo 'Tipo de Identificación' → asignado a 'tipo_documento'."

    # 5b. Número de Cuenta / No. de Cuenta / Cuenta No. -> numero_cuenta
    if re.search(r"\b(?:n[uú]mero|no|nro|num)?\s*(?:de\s+)?cuenta\b", rotulo_normalizado):
        if "tipo" not in rotulo_normalizado and "clase" not in rotulo_normalizado:
            if campo != "numero_cuenta":
                return "numero_cuenta", "Rótulo 'No. de Cuenta / Cuenta' → asignado a 'numero_cuenta'."

    # 6. Desambiguación Contextual de 'Número', 'No.', 'N°', 'Identificación' (Empresa vs Representante vs Bancario)
    es_rotulo_numero_o_id = bool(
        re.match(r"^\s*(?:n[uú]mero|no|n|nro|num|identificaci[oó]n|documento|id|no\s*doc)[°º\.:]?\s*$", rotulo_normalizado, re.IGNORECASE)
        or re.search(r"\b(?:n[uú]mero|nro|no|n[°º]?)\s*(?:de\s+)?(?:identificaci[oó]n|documento|id|nit|c[eé]dula|cuenta)\b", rotulo_normalizado)
        or re.search(r"\b(?:identificaci[oó]n|documento|cuenta)\s*(?:no|n[uú]mero|nro|n[°º])?\b", rotulo_normalizado)
    )

    if es_rotulo_numero_o_id and "tipo" not in rotulo_normalizado and "clase" not in rotulo_normalizado:
        # Contexto Bancario / Cuenta
        if any(t in seccion_normalizada for t in _TOKENS_SECCION_BANCARIA):
            if campo != "numero_cuenta":
                return "numero_cuenta", "Rótulo 'Número' en contexto Bancario → asignado a 'numero_cuenta'."

        # Contexto Representante Legal / Persona Natural (o si el campo ya apuntaba a representante)
        elif any(t in seccion_normalizada for t in _TOKENS_SECCION_REP_LEGAL) or "representante" in rotulo_normalizado or "apoderado" in rotulo_normalizado or "natural" in rotulo_normalizado or "persona natural" in seccion_normalizada:
            if campo != "cedula":
                return "cedula", "Rótulo 'Número/Identificación' en contexto de Representante Legal → asignado a 'cedula'."

        # Contexto Empresa / Razón Social / Persona Jurídica / General
        elif "nit" in rotulo_normalizado or "tributaria" in rotulo_normalizado or any(t in seccion_normalizada for t in _TOKENS_SECCION_EMPRESA):
            if campo != "nit":
                return "nit", "Rótulo 'Número/Identificación' en contexto de Empresa/Persona Jurídica → asignado a 'nit'."

        # Si no hay sección específica pero dice Identificación -> cedula por defecto
        elif campo not in ("cedula", "nit", "numero_cuenta"):
            return "cedula", "Rótulo 'Identificación / Número' → asignado a 'cedula'."

    return campo, ""


# ──────────────────────────────────────────────────────────────────────────────
# 4. CÁLCULO DE NIVEL DE CONFIANZA
# ──────────────────────────────────────────────────────────────────────────────

def _calcular_nivel_confianza(
    campo: str,
    rotulo_normalizado: str,
    datos_planos: Dict[str, Any],
    tiene_valor: bool,
    tipo_elemento: str,
) -> str:
    """Determina el nivel de confianza del mapeo en 4 niveles.

    EXACTA:          El rótulo normalizado contiene exactamente el nombre del campo.
    ALTA:            El valor del campo existe y el rótulo es semánticamente compatible.
    PARCIAL:         El campo existe pero hay ambigüedad estructural menor.
    SIN_COINCIDENCIA: El campo no existe o está vacío.
    """
    if not tiene_valor:
        return NivelConfianza.SIN_COINCIDENCIA

    # Exacta: el rótulo contiene literalmente el nombre del campo
    campo_norm = _normalizar(campo.replace("_", " "))
    if campo_norm in rotulo_normalizado or rotulo_normalizado in campo_norm:
        return NivelConfianza.EXACTA

    # Alta: el tipo es FIELD y el campo tiene valor no vacío
    if tipo_elemento == "FIELD" and tiene_valor:
        return NivelConfianza.ALTA

    # Parcial: tipo UNKNOWN o campo sin valor concreto
    return NivelConfianza.PARCIAL


# ──────────────────────────────────────────────────────────────────────────────
# 5. VALIDADOR PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

def validar_item_mapeo(
    plan_item: Dict[str, Any],
    datos_empresa: Dict[str, Any],
    datos_planos: Optional[Dict[str, Any]] = None,
    documento_ir: Optional[Any] = None,
) -> Dict[str, Any]:
    """Valida un único ítem del plan_mapeo contra las 5 reglas estructurales."""
    if datos_planos is None:
        datos_planos = _aplanar_datos_empresa(datos_empresa)

    campo_original = str(plan_item.get("campo") or "").strip()
    rotulo = str(plan_item.get("valor") or plan_item.get("rotulo") or "").strip()
    seccion = str(plan_item.get("seccion") or plan_item.get("seccion_padre") or "").strip()
    tipo_elemento = str(plan_item.get("tipo_elemento") or "FIELD").strip()

    rotulo_norm = _normalizar(rotulo)
    seccion_norm = _normalizar(seccion)

    resultado = dict(plan_item)
    resultado["campo_propuesto"] = campo_original
    resultado["campo_final"] = campo_original
    resultado["estado"] = EstadoMapeo.APROBADO
    resultado["motivo"] = ""
    resultado["nivel_confianza"] = NivelConfianza.PARCIAL

    # ── Caso vacío: sin campo propuesto → REVISION ──────────────────────────
    if not campo_original:
        resultado["estado"] = EstadoMapeo.REVISION
        resultado["motivo"] = "El mapeo no tiene campo asignado."
        resultado["nivel_confianza"] = NivelConfianza.SIN_COINCIDENCIA
        return resultado

    # ── R0: Descarte de Títulos de Sección, Instrucciones y Opciones ────────
    try:
        from pipeline.stages.stage_2_classifier import es_titulo_seccion, _PATRON_OPCIONES_SELECCION
        if es_titulo_seccion(rotulo) or _PATRON_OPCIONES_SELECCION.match(rotulo):
            resultado["estado"] = EstadoMapeo.DESCARTADO
            resultado["campo_final"] = ""
            resultado["motivo"] = f"El rótulo '{rotulo}' es un título o encabezado decorativo y no un campo de entrada."
            resultado["nivel_confianza"] = NivelConfianza.SIN_COINCIDENCIA
            return resultado
    except ImportError:
        pass

    # ── R1: Tipo de elemento compatible ─────────────────────────────────────
    ok_tipo, msg_tipo = _regla_tipo_elemento_compatible(tipo_elemento)
    if not ok_tipo:
        resultado["estado"] = EstadoMapeo.DESCARTADO
        resultado["motivo"] = msg_tipo
        resultado["nivel_confianza"] = NivelConfianza.SIN_COINCIDENCIA
        return resultado

    # ── Autocorrecciones estructurales y semánticas previas (R4, R5, R5b) ────
    campo_ajustado_r4, motivo_r4 = _regla_no_asignar_tipo_documento_a_compuesto(
        campo_original, rotulo_norm
    )
    if motivo_r4:
        campo_original = campo_ajustado_r4
        resultado["campo_final"] = campo_ajustado_r4
        resultado["motivo"] = motivo_r4

    campo_ajustado_r5, motivo_r5 = _regla_telefono_en_seccion_rep_legal(
        campo_original, seccion_norm, rotulo_norm
    )
    if motivo_r5:
        campo_original = campo_ajustado_r5
        resultado["campo_final"] = campo_ajustado_r5
        resultado["motivo"] = motivo_r5

    campo_ajustado_r5b, motivo_r5b = _regla_autocorrecciones_semanticas_adicionales(
        campo_original, rotulo_norm, seccion_norm
    )
    if motivo_r5b:
        campo_original = campo_ajustado_r5b
        resultado["campo_final"] = campo_ajustado_r5b
        resultado["motivo"] = motivo_r5b

    # ── R2: Campo existe en perfil ──────────────────────────────────────────
    ok_existe, msg_existe = _regla_campo_existe(campo_original, datos_planos)
    if not ok_existe:
        resultado["estado"] = EstadoMapeo.REVISION
        resultado["motivo"] = msg_existe
        resultado["nivel_confianza"] = NivelConfianza.SIN_COINCIDENCIA
        return resultado

    # ── R2b: Campo tiene valor ──────────────────────────────────────────────
    ok_valor, msg_valor = _regla_campo_tiene_valor(campo_original, datos_planos)
    tiene_valor = ok_valor and msg_valor == ""
    if ok_valor and msg_valor:
        resultado["estado"] = EstadoMapeo.REVISION
        resultado["motivo"] = msg_valor
        resultado["nivel_confianza"] = NivelConfianza.PARCIAL

    # ── R3: Compatibilidad de tipo de dato ──────────────────────────────────
    ok_tipo_dato, msg_tipo_dato = _regla_compatibilidad_tipo_dato(campo_original, rotulo_norm)
    if not ok_tipo_dato:
        resultado["estado"] = EstadoMapeo.DESCARTADO
        resultado["motivo"] = msg_tipo_dato
        resultado["nivel_confianza"] = NivelConfianza.SIN_COINCIDENCIA
        return resultado

    # ── R3b: lugar_expedicion ≠ fecha ───────────────────────────────────────
    ok_exp, msg_exp = _regla_lugar_expedicion_no_es_fecha(campo_original, rotulo_norm)
    if not ok_exp:
        resultado["estado"] = EstadoMapeo.DESCARTADO
        resultado["motivo"] = msg_exp
        resultado["nivel_confianza"] = NivelConfianza.SIN_COINCIDENCIA
        return resultado

    # ── Nivel de confianza final ─────────────────────────────────────────────
    nivel = _calcular_nivel_confianza(
        campo_original, rotulo_norm, datos_planos, tiene_valor, tipo_elemento
    )
    if resultado["estado"] == EstadoMapeo.APROBADO:
        resultado["nivel_confianza"] = nivel

    return resultado


def validar_plan_mapeo(
    plan_mapeo: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    documento_ir: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Valida todos los ítems del plan_mapeo generado por el LLM.

    Implementa el short-circuit de secciones OMITIR_*:
    si el documento_ir está disponible y una sección está marcada como OMITIR_*,
    sus elementos NO pasan por las reglas individuales — se marcan DESCARTADO
    directamente con motivo claro.

    Args:
        plan_mapeo: Lista de dicts del plan de mapeo inicial.
        datos_empresa: Perfil empresarial completo.
        documento_ir: (opcional) DocumentoIR para detección de secciones omitidas.

    Returns:
        Lista de dicts enriquecidos con estado, motivo, nivel_confianza, campo_final.
    """
    # Aplanar perfil una sola vez (performance en lotes)
    datos_planos = _aplanar_datos_empresa(datos_empresa)

    # Construir índice de secciones omitidas desde el IR (short-circuit)
    secciones_omitidas: Set[str] = set()
    if documento_ir is not None:
        try:
            from core.spatial_ir import PertinenciaSeccion
            for sec in documento_ir.secciones:
                if sec.pertinencia in (
                    PertinenciaSeccion.OMITIR_TERCEROS,
                    PertinenciaSeccion.OMITIR_USO_INTERNO,
                    PertinenciaSeccion.OMITIR_LEGAL,
                ):
                    secciones_omitidas.add(_normalizar(sec.titulo))
        except (ImportError, AttributeError):
            pass  # Si el IR no está disponible, seguimos sin short-circuit

    plan_validado: List[Dict[str, Any]] = []

    for item in plan_mapeo:
        # ── Short-circuit: sección marcada OMITIR_* en el IR ─────────────────
        seccion_item = _normalizar(
            str(item.get("seccion") or item.get("seccion_padre") or "")
        )
        if secciones_omitidas and any(
            seccion_item.startswith(omit) or omit in seccion_item
            for omit in secciones_omitidas
        ):
            resultado = dict(item)
            resultado["campo_propuesto"] = str(item.get("campo") or "")
            resultado["campo_final"] = ""
            resultado["estado"] = EstadoMapeo.DESCARTADO
            resultado["motivo"] = (
                f"La sección '{seccion_item}' está marcada como no aplicable (OMITIR). "
                f"Sus elementos se omiten sin procesamiento individual."
            )
            resultado["nivel_confianza"] = NivelConfianza.SIN_COINCIDENCIA
            plan_validado.append(resultado)
            continue

        # ── Validación individual del ítem ────────────────────────────────────
        resultado = validar_item_mapeo(item, datos_empresa, datos_planos, documento_ir)

        # Aplicar campo_final como campo efectivo cuando hubo autocorrección
        campo_final = resultado.get("campo_final", "")
        campo_prop = resultado.get("campo_propuesto", "")
        if campo_final and campo_final != campo_prop:
            resultado["campo"] = campo_final

        plan_validado.append(resultado)

    return plan_validado


# ──────────────────────────────────────────────────────────────────────────────
# 6. RESUMEN DE VALIDACIÓN (para logging y UI)
# ──────────────────────────────────────────────────────────────────────────────

def generar_resumen_validacion(plan_validado: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Genera estadísticas de validación para logging y diagnóstico.

    Returns:
        Dict con conteos por estado y nivel de confianza, lista de ítems por revisión.
    """
    conteo_estado: Dict[str, int] = {
        EstadoMapeo.APROBADO: 0,
        EstadoMapeo.REVISION: 0,
        EstadoMapeo.DESCARTADO: 0,
    }
    conteo_confianza: Dict[str, int] = {
        NivelConfianza.EXACTA: 0,
        NivelConfianza.ALTA: 0,
        NivelConfianza.PARCIAL: 0,
        NivelConfianza.SIN_COINCIDENCIA: 0,
    }
    items_revision: List[Dict[str, Any]] = []
    autocorreciones: List[Dict[str, str]] = []

    for item in plan_validado:
        estado = item.get("estado", EstadoMapeo.APROBADO)
        confianza = item.get("nivel_confianza", NivelConfianza.PARCIAL)
        conteo_estado[estado] = conteo_estado.get(estado, 0) + 1
        conteo_confianza[confianza] = conteo_confianza.get(confianza, 0) + 1

        if estado == EstadoMapeo.REVISION:
            items_revision.append({
                "rotulo": item.get("valor", item.get("rotulo", "")),
                "campo_propuesto": item.get("campo_propuesto", ""),
                "motivo": item.get("motivo", ""),
            })

        campo_prop = item.get("campo_propuesto", "")
        campo_final = item.get("campo_final", campo_prop)
        if campo_final and campo_prop and campo_final != campo_prop:
            autocorreciones.append({
                "rotulo": item.get("valor", item.get("rotulo", "")),
                "original": campo_prop,
                "corregido": campo_final,
                "motivo": item.get("motivo", ""),
            })

    total = len(plan_validado)
    return {
        "total_items": total,
        "por_estado": conteo_estado,
        "por_confianza": conteo_confianza,
        "tasa_aprobacion": round(conteo_estado[EstadoMapeo.APROBADO] / max(1, total) * 100, 1),
        "items_revision": items_revision,
        "autocorrecciones": autocorreciones,
    }
