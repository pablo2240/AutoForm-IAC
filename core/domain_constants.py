"""Constantes y Enums de Dominio para AutoForm AI (ADR-0004).

Centraliza la definición de categorías de sección, campos protegidos,
listas negras de términos genéricos y patrones de contacto comercial
para eliminar la duplicación de código en el pipeline.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Set


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

CAMPOS_REP_LEGAL: Set[str] = {
    "representante_legal", "representante_nombres", "representante_apellidos", "cedula", "lugar_expedicion"
}

CAMPOS_EMPRESA: Set[str] = {
    "razon_social", "nit", "direccion", "ciudad", "departamento", "pais", "telefono", "correo", "pagina_web", "tipo_sociedad"
}

# ── Tokens de sección para clasificación de dominio ────────────────────────────
TOKENS_FINANCIEROS_SECCION: Set[str] = {
    "banco", "bancaria", "bancario", "financiera", "financiero", "cuenta", "pagos", "pago", "transferencia", "contab", "giro", "tesoreria"
}

TOKENS_REP_LEGAL_SECCION: Set[str] = {
    "representante", "apoderado", "persona natural", "rep legal", "firmante", "conyuge", "gerente", "titular", "declaracion", "legal"
}

TOKENS_CONTACTO_SECCION: Set[str] = {
    "contacto", "asesor", "consultor", "ejecutivo", "comercial", "operativo"
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
