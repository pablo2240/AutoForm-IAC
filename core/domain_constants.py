"""Constantes y Enums de Dominio para AutoForm AI (ADR-0004).

Centraliza la definición de categorías de sección, campos protegidos,
listas negras de términos genéricos y patrones de contacto comercial
para eliminar la duplicación de código en el pipeline.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Set, Dict


class DomainCategory(str, Enum):
    """Categorías canónicas de sección y aislamiento de dominio (ADR-0004 / ADR-0005)."""
    EMPRESA = "empresa"
    REPRESENTANTE_LEGAL = "representante_legal"
    FINANCIERO = "financiero"
    CONTACTO_COMERCIAL = "contacto_comercial"
    PEP_BENEFICIARIO = "pep_beneficiario"
    GENERAL = "general"
    NO_APLICA = "no_aplica"


# ── Triggers de PEP y Beneficiarios Finales para Safe Passivity (ADR-0005) ─────
TOKENS_PEP_BENEFICIARIOS_SECCION: Set[str] = {
    "pep", "peps", "persona expuesta", "politicamente expuesta", "politicamente expuesto",
    "beneficiario final", "beneficiarios finales", "beneficiario real", "beneficiarios reales"
}

PATRON_PEP_BENEFICIARIOS = re.compile(
    r"\b(?:pep|peps|persona\s+expuesta|pol[ií]ticamente\s+expuest[ao]s?|beneficiario\s+final|beneficiarios\s+finales|beneficiario\s+real|beneficiarios\s+reales)\b",
    re.IGNORECASE
)


# ── Rótulos genéricos u opciones que NUNCA deben recibir mapeo automático ──────
ROTULOS_GENERICOS_BLOQUEADOS: Set[str] = {
    "cliente", "vinculacion", "tipo de vinculacion", "otro", "otros", "otra", "otras",
    "pep", "si", "no", "s", "n", "na", "n/a", "opcion", "opciones", "seleccione",
    "declaracion", "firma", "huella", "fecha", "dia", "mes", "ano", "año",
}

# ── Patrón de limpieza de caracteres terminales y espacios ─────────────────────
PATRON_LIMPIEZA_ROTULO = re.compile(r"[:：_\.\s]+$")

# ── Patrón de contacto comercial / asesor para Safe Passivity ──────────────────
PATRON_CONTACTO_COMERCIAL = re.compile(
    r"\b(?:contacto|asesor(?:\s+comercial)?|consultor(?:\s+plm|\s+comercial)?|ejecutivo\s+comercial)\b",
    re.IGNORECASE
)

# ── Conjuntos de campos protegidos por categoría ──────────────────────────────
CAMPOS_BANCARIOS: Set[str] = {
    "banco", "numero_cuenta", "tipo_cuenta", "sucursal"
}

# ADR-0006: Cifras de Balance y Estados Financieros Empresariales
CAMPOS_FINANCIEROS_BALANCE: Set[str] = {
    "total_activos", "total_pasivos", "total_patrimonio",
    "total_ingresos_mensuales", "total_egresos_mensuales",
    "total_ingresos_anuales", "total_egresos_anuales",
    # Aliases cortos
    "activos", "pasivos", "patrimonio",
    "ingresos_mensuales", "egresos_mensuales",
    "ingresos_anuales", "egresos_anuales",
}

CAMPOS_REP_LEGAL: Set[str] = {
    "representante_legal", "representante_nombres", "representante_apellidos", "cedula", "lugar_expedicion"
}

# ADR-0007: Campos del Responsable del Diligenciamiento / Operador Comercial
CAMPOS_RESPONSABLE_COMERCIAL: Set[str] = {
    "responsable_nombre", "responsable_cargo", "responsable_cedula",
    "responsable_telefono", "responsable_celular", "responsable_correo",
    # Aliases
    "contacto_nombre", "contacto_cargo", "contacto_telefono", "contacto_correo"
}

CAMPOS_EMPRESA: Set[str] = {
    "razon_social", "nit", "direccion", "ciudad", "departamento", "pais", "telefono", "correo", "pagina_web", "tipo_sociedad"
}

# ── Tokens de sección para clasificación de dominio ────────────────────────────
TOKENS_FINANCIEROS_SECCION: Set[str] = {
    "banco", "bancaria", "bancario", "financiera", "financiero", "cuenta", "pagos", "pago", "transferencia", "contab", "giro", "tesoreria"
}

# ADR-0006: Tokens de sección estrictos para Cifras de Balance
TOKENS_BALANCE_SECCION: Set[str] = {
    "financier", "balance", "contab", "cifras", "econom", "económic", "estado de resultado", "situacion financiera"
}

TOKENS_REP_LEGAL_SECCION: Set[str] = {
    "representante", "apoderado", "persona natural", "rep legal", "firmante", "conyuge", "gerente", "titular", "declaracion", "legal",
    "junta", "directiv", "administra", "organo"
}

# ADR-0009: Catálogo canónico de tokens para detección de bloques comerciales y de contacto
TOKENS_CONTACTO_COMERCIAL: Set[str] = {
    "contacto",
    "personal de contacto",
    "informacion de contacto",
    "información de contacto",
    "datos de contacto",
    "contacto comercial",
    "asesor comercial",
    "asesor",
    "responsable del diligenciamiento",
    "diligenciado por",
    "funcionario que diligencia",
    "ejecutivo de cuenta",
    "atencion comercial",
    "atención comercial",
    "contacto de verificación",
    "contacto de verificacion",
    "personal que realiza directamente la operacion",
    "personal que realiza directamente la operación",
    "personal que realiza la operacion",
    "personal que realiza la operación",
    "informacion operativa",
    "información operativa",
    "contacto operativo",
}

TOKENS_REFERENCIAS_EXCLUIDAS: Set[str] = {
    "referencias comerciales",
    "referencia comercial",
    "referencias de clientes",
    "referencias de proveedores",
}

TOKENS_CONTACTO_SECCION: Set[str] = TOKENS_CONTACTO_COMERCIAL.union({
    "consultor", "operativo", "responsable", "diligenciamiento", "cuenta"
})

# ADR-0009: Rótulos bare dentro de secciones de contacto comercial
BARE_LABELS_CONTACTO_COMERCIAL: Dict[str, str] = {
    "nombre": "responsable_nombre",
    "nombre completo": "responsable_nombre",
    "nombres y apellidos": "responsable_nombre",
    "contacto": "responsable_nombre",
    "persona de contacto": "responsable_nombre",
    "asesor": "responsable_nombre",
    "asesor comercial": "responsable_nombre",
    "cargo": "responsable_cargo",
    "posicion": "responsable_cargo",
    "posición": "responsable_cargo",
    "posicion o rol": "responsable_cargo",
    "posición o rol": "responsable_cargo",
    "rol": "responsable_cargo",
    "telefono": "responsable_telefono",
    "teléfono": "responsable_telefono",
    "celular": "responsable_telefono",
    "movil": "responsable_telefono",
    "móvil": "responsable_telefono",
    "tel": "responsable_telefono",
    "cel": "responsable_telefono",
    "correo": "responsable_correo",
    "correo electronico": "responsable_correo",
    "correo electrónico": "responsable_correo",
    "email": "responsable_correo",
    "e-mail": "responsable_correo",
    "cedula": "responsable_cedula",
    "cédula": "responsable_cedula",
    "identificacion": "responsable_cedula",
    "identificación": "responsable_cedula",
    "documento": "responsable_cedula",
    "no. documento": "responsable_cedula",
    "numero de documento": "responsable_cedula",
    "número de documento": "responsable_cedula",
}

# ADR-0009: Remapeo determinista en HSP para campos legales/corporativos que caigan en bloque comercial
CONTACTO_COMERCIAL_REMAP: Dict[str, str] = {
    "representante_legal": "responsable_nombre",
    "representante_nombres": "responsable_nombre",
    "representante_apellidos": "responsable_nombre",
    "cargo": "responsable_cargo",
    "cedula": "responsable_cedula",
    "lugar_expedicion": "",
    "expedicion": "",
    "correo": "responsable_correo",
    "correo_representante": "responsable_correo",
    "celular": "responsable_telefono",
    "celular_representante": "responsable_telefono",
    "telefono": "responsable_telefono",
    "telefono_representante": "responsable_telefono",
}



def limpiar_rotulo(rotulo: str) -> str:
    """Elimina signos de puntuación terminales, subrayados y espacios superfluos."""
    if not rotulo:
        return ""
    return PATRON_LIMPIEZA_ROTULO.sub("", rotulo.lower().strip()).strip()


def es_seccion_o_campo_pep(seccion: str = "", rotulo: str = "", contexto: str = "") -> bool:
    """Determina si una sección, rótulo o contexto circundante pertenece al ámbito de PEP o Beneficiario Final (ADR-0005)."""
    sec_norm = (seccion or "").lower()
    rot_norm = (rotulo or "").lower()
    ctx_norm = (contexto or "").lower()
    if any(t in sec_norm for t in TOKENS_PEP_BENEFICIARIOS_SECCION) or bool(PATRON_PEP_BENEFICIARIOS.search(sec_norm)):
        return True
    if any(t in rot_norm for t in ("pep", "peps", "beneficiario final", "beneficiarios finales", "beneficiario real")) or bool(PATRON_PEP_BENEFICIARIOS.search(rot_norm)):
        return True
    if ctx_norm and (any(t in ctx_norm for t in ("pep", "peps", "beneficiario final", "beneficiarios finales", "beneficiario real")) or bool(PATRON_PEP_BENEFICIARIOS.search(ctx_norm))):
        return True
    return False
