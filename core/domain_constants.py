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


# ── Triggers de PEP para Safe Passivity (ADR-0005 / ADR-0011) ─────────────────
TOKENS_PEP_SECCION: Set[str] = {
    "pep", "peps", "persona expuesta", "politicamente expuesta", "politicamente expuesto",
    "personas expuestas", "politica expuesta", "expuesta politicamente",
}

PATRON_PEP = re.compile(
    r"\b(?:pep|peps|persona\s+expuesta|pol[ií]ticamente\s+expuest[ao]s?)\b",
    re.IGNORECASE
)
PATRON_PEP_BENEFICIARIOS = PATRON_PEP

PATRON_PEP_CONDICIONAL_POSITIVO = re.compile(
    r"(?:en\s+caso\s+de\s+que\s+(?:su\s+respuesta\s+)?(?:haya\s+sido|sea)\s+positiva|"
    r"en\s+caso\s+afirmativo|si\s+(?:su\s+)?respuesta\s+es\s+(?:positiva|si\b)|"
    r"indique\s+(?:el\s+)?nombre\s+completo\s+e\s+identificaci[oó]n\s+del\s+pep)",
    re.IGNORECASE
)

# ── Triggers de Composición Accionaria y Beneficiarios Finales (ADR-0011) ──────
TOKENS_SOCIETARIO_SECCION: Set[str] = {
    "composicion accionaria", "composición accionaria", "accionistas", "accionista",
    "socios", "socio", "participacion accionaria", "participación accionaria",
    "beneficiarios finales", "beneficiario final", "beneficiarios reales", "beneficiario real",
}

PATRON_SOCIETARIO = re.compile(
    r"\b(?:composici[oó]n\s+accionaria|accionistas?|socios?|participaci[oó]n\s+accionaria|beneficiari[ao]s?\s+final(?:es)?|beneficiari[ao]s?\s+real(?:es)?)\b",
    re.IGNORECASE
)


ROTULOS_GENERICOS_BLOQUEADOS: Set[str] = {
    "cliente", "vinculacion", "tipo de vinculacion", "otro", "otros", "otra", "otras",
    "pep", "si", "no", "s", "n", "na", "n/a", "opcion", "opciones", "seleccione",
    "declaracion", "firma", "huella", "fecha", "dia", "mes", "ano", "año",
    "tipo 1", "tipo 2", "tipo 3", "tipo 4", "tipo 5",
    "comercial", "cartera", "contabilidad", "calidad",
    "seleccionado por", "aprobado por", "evaluado por", "calificado por",
    "concepto comercial", "concepto", "concepto final",
}

# ── Patrón de limpieza de caracteres terminales y espacios ─────────────────────
PATRON_LIMPIEZA_ROTULO = re.compile(r"[:：_\.\s\$]+$")

# ── Patrón de contacto comercial / asesor para Safe Passivity ──────────────────
PATRON_CONTACTO_COMERCIAL = re.compile(
    r"\b(?:contacto|asesor(?:\s+comercial)?|consultor(?:\s+plm|\s+comercial)?|ejecutivo\s+comercial|encargado\s+de\s+ventas|ventas)\b",
    re.IGNORECASE
)

# ── Conjuntos de campos protegidos por categoría ──────────────────────────────
CAMPOS_BANCARIOS: Set[str] = {
    "banco", "numero_cuenta", "tipo_cuenta", "sucursal", "moneda",
    "nit_cert_bancaria", "nit_bancario", "nit_certificacion",
}

# ADR-0006: Cifras de Balance y Estados Financieros Empresariales
CAMPOS_FINANCIEROS_BALANCE: Set[str] = {
    "total_activos", "total_pasivos", "total_patrimonio",
    "total_ingresos_mensuales", "total_egresos_mensuales",
    "total_ingresos_anuales", "total_egresos_anuales",
    "moneda",
    # Aliases cortos
    "activos", "pasivos", "patrimonio",
    "ingresos_mensuales", "egresos_mensuales",
    "ingresos_anuales", "egresos_anuales",
    "otros_ingresos",
}

CAMPOS_REP_LEGAL: Set[str] = {
    "representante_legal", "representante_nombres", "representante_apellidos",
    "primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido",
    "cedula", "lugar_expedicion", "lugar_nacimiento",
    "ciudad_residencia", "departamento_residencia", "nacionalidad",
}

# ADR-0007: Campos del Responsable del Diligenciamiento / Operador Comercial
CAMPOS_RESPONSABLE_COMERCIAL: Set[str] = {
    "responsable_nombre", "responsable_cargo", "responsable_cedula",
    "responsable_telefono", "responsable_celular", "responsable_correo",
    "responsable_direccion", "responsable_ciudad", "responsable_departamento",
    "responsable_area",
    # Aliases
    "contacto_nombre", "contacto_cargo", "contacto_telefono", "contacto_correo",
    "contacto_direccion", "contacto_ciudad", "contacto_departamento",
    "contacto_area",
}

CAMPOS_EMPRESA: Set[str] = {
    "razon_social", "nit", "nit_cert_bancaria", "nit_bancario", "nit_titular",
    "direccion", "ciudad", "departamento", "pais", "telefono", "correo", "pagina_web", "tipo_sociedad"
}

# Campos de Composición Accionaria y Beneficiarios Finales (ADR-0011)
CAMPOS_SOCIETARIO: Set[str] = {
    "accionista_nombre", "accionista_tipo_id", "accionista_identificacion", "accionista_porcentaje",
    "socio_nombre", "socio_tipo_id", "socio_identificacion", "socio_porcentaje",
    "beneficiario_nombre", "beneficiario_tipo_id", "beneficiario_identificacion", "beneficiario_porcentaje",
}

# ── Tokens de sección para clasificación de dominio ────────────────────────────
TOKENS_FINANCIEROS_SECCION: Set[str] = {
    "banco", "bancaria", "bancario", "financiera", "financiero", "cuenta", "pagos", "pago", "transferencia", "contab", "giro", "tesoreria", "entidad", "moneda", "divisa"
}

# ADR-0006: Tokens de sección estrictos para Cifras de Balance
TOKENS_BALANCE_SECCION: Set[str] = {
    "financier", "balance", "contab", "cifras", "econom", "económic", "estado de resultado", "situacion financiera"
}

TOKENS_REP_LEGAL_SECCION: Set[str] = {
    "representante", "apoderado", "persona natural", "rep legal", "firmante", "firma", "conyuge", "gerente", "titular", "declaracion", "legal",
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
    "encargado de ventas",
    "ventas",
}

TOKENS_REFERENCIAS_EXCLUIDAS: Set[str] = {
    "referencias comerciales",
    "referencia comercial",
    "referencias de clientes",
    "referencias de proveedores",
}

# ADR-0010: Tokens de secciones de uso exclusivo o diligenciamiento interno del cliente
TOKENS_USO_INTERNO_EXCLUSIVO: Set[str] = {
    "espacio diligenciado por",
    "espacio diligenciado",
    "para ser diligenciado por",
    "diligenciado por la empresa",
    "diligenciado por el cliente",
    "uso exclusivo",
    "uso interno",
    "espacio exclusivo",
    "campo exclusivo",
    "exclusivo para",
    "exclusivo de",
    "para uso exclusivo",
    "espacio reservado",
    "reservado para la empresa",
    "reservado para",
    "para uso de la entidad",
    "espacio para diligenciamiento",
    "seleccion del proveedor",
    "selección del proveedor",
    "evaluacion del proveedor",
    "evaluación del proveedor",
    "evaluacion de proveedores",
    "evaluación de proveedores",
    "calificacion del proveedor",
    "calificación del proveedor",
    "criterios de seleccion",
    "criterios de selección",
    "escala de calificacion",
    "escala de calificación",
    "concepto comercial",
    "concepto de la entidad",
    "seleccionado por",
    "aprobado por",
    "evaluado por",
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
    "nombre encargado de ventas": "responsable_nombre",
    "encargado de ventas": "responsable_nombre",
    "nombre del encargado de ventas": "responsable_nombre",
    "asesor de ventas": "responsable_nombre",
    "cargo": "responsable_cargo",
    "posicion": "responsable_cargo",
    "posición": "responsable_cargo",
    "posicion o rol": "responsable_cargo",
    "posición o rol": "responsable_cargo",
    "rol": "responsable_cargo",
    "telefono": "responsable_telefono",
    "teléfono": "responsable_telefono",
    "telefono * ext o celular": "responsable_telefono",
    "telefono * ext. o celular": "responsable_telefono",
    "telefono o celular": "responsable_telefono",
    "telefono / celular": "responsable_telefono",
    "telefono fijo o celular": "responsable_telefono",
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
    "e mail": "responsable_correo",
    "mail": "responsable_correo",
    "cedula": "responsable_cedula",
    "cédula": "responsable_cedula",
    "identificacion": "responsable_cedula",
    "identificación": "responsable_cedula",
    "documento": "responsable_cedula",
    "no. documento": "responsable_cedula",
    "numero de documento": "responsable_cedula",
    "número de documento": "responsable_cedula",
    "direccion": "responsable_direccion",
    "dirección": "responsable_direccion",
    "domicilio": "responsable_direccion",
    "ciudad": "responsable_ciudad",
    "municipio": "responsable_ciudad",
    "departamento": "responsable_departamento",
    "depto": "responsable_departamento",
    "area": "responsable_area",
    "área": "responsable_area",
}

# ADR-0009 / ADR-0011: Remapeo determinista en HSP para campos genéricos que caigan en bloque comercial
# NUNCA remapear representante_legal, representante_nombres o representante_apellidos a contacto comercial
CONTACTO_COMERCIAL_REMAP: Dict[str, str] = {
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
    "direccion": "responsable_direccion",
    "ciudad": "responsable_ciudad",
    "departamento": "responsable_departamento",
    "area": "responsable_area",
    "área": "responsable_area",
}



def limpiar_rotulo(rotulo: str) -> str:
    """Elimina signos de puntuación terminales, subrayados y espacios superfluos."""
    if not rotulo:
        return ""
    return PATRON_LIMPIEZA_ROTULO.sub("", rotulo.lower().strip()).strip()


def es_seccion_o_campo_pep(seccion: str = "", rotulo: str = "", contexto: str = "") -> bool:
    """Determina si una sección, rótulo o contexto circundante pertenece al ámbito de PEP (ADR-0005 / ADR-0011)."""
    sec_norm = (seccion or "").lower()
    rot_norm = (rotulo or "").lower()
    ctx_norm = (contexto or "").lower()
    if any(t in sec_norm for t in TOKENS_PEP_SECCION) or bool(PATRON_PEP.search(sec_norm)):
        return True
    if any(t in rot_norm for t in ("pep", "peps", "persona expuesta")) or bool(PATRON_PEP.search(rot_norm)):
        return True
    if ctx_norm and (any(t in ctx_norm for t in ("pep", "peps")) or bool(PATRON_PEP.search(ctx_norm))):
        return True
    return False


def es_seccion_o_campo_societario(seccion: str = "", rotulo: str = "", contexto: str = "") -> bool:
    """Determina si una sección o rótulo pertenece al ámbito societario o de beneficiarios finales (ADR-0011)."""
    sec_norm = (seccion or "").lower()
    rot_norm = (rotulo or "").lower()
    ctx_norm = (contexto or "").lower()
    if any(t in sec_norm for t in TOKENS_SOCIETARIO_SECCION) or bool(PATRON_SOCIETARIO.search(sec_norm)):
        return True
    if any(t in rot_norm for t in ("accionista", "accionistas", "socio", "socios", "beneficiario final", "beneficiarios finales", "beneficiario real", "beneficiarios reales", "participacion accionaria")):
        return True
    if ctx_norm and (any(t in ctx_norm for t in ("accionista", "socios", "beneficiario final")) or bool(PATRON_SOCIETARIO.search(ctx_norm))):
        return True
    return False


# ── Reglas de Inyección Geográfica (Q1) ────────────────────────────────────────
NIVELES_TERRITORIALES: Set[str] = {"ciudad", "municipio"}
NIVEL_DEPARTAMENTAL: Set[str] = {"departamento", "depto"}

CIUDAD_A_DEPARTAMENTO: Dict[str, str] = {
    "bogota": "Cundinamarca",
    "bogotá": "Cundinamarca",
    "bogota d.c.": "Cundinamarca",
    "bogotá d.c.": "Cundinamarca",
    "medellin": "Antioquia",
    "medellín": "Antioquia",
    "envigado": "Antioquia",
    "cali": "Valle del Cauca",
    "barranquilla": "Atlántico",
    "popayan": "Cauca",
    "popayán": "Cauca",
    "cartagena": "Bolívar",
    "bucaramanga": "Santander",
}


def resolver_rotulo_geografico(rotulo_norm: str, valor_ciudad: str = "Medellín", valor_depto: str = "Antioquia") -> str:
    """Resuelve el valor geográfico estricto según la distinción territorial del rótulo (Q1).

    - Si el rótulo combina dos niveles territoriales distintos (municipal + departamental): "Medellín / Antioquia".
    - Si el rótulo es puramente municipal ("ciudad", "municipio", "ciudad/municipio"): "Medellín".
    - Si el rótulo es puramente departamental ("departamento", "depto"): "Antioquia".
    - Asocia de forma canónica Bogotá con el departamento Cundinamarca.
    """
    rot_limpio = rotulo_norm.lower().strip()
    partes = [p.strip() for p in rot_limpio.split("/") if p.strip()]

    tiene_municipal = any(p in NIVELES_TERRITORIALES for p in partes) or any(t in rot_limpio for t in NIVELES_TERRITORIALES)
    tiene_departamental = any(p in NIVEL_DEPARTAMENTAL for p in partes) or any(d in rot_limpio for d in NIVEL_DEPARTAMENTAL)

    c = (valor_ciudad or "Medellín").strip()
    c_norm = c.lower()
    depto_sugerido = CIUDAD_A_DEPARTAMENTO.get(c_norm, valor_depto or "Antioquia")
    d = (valor_depto if (valor_depto and valor_depto.lower() not in ("antioquia", "cundinamarca") or c_norm in ("medellin", "medellín")) else depto_sugerido).strip()
    if any(b in c_norm for b in ("bogota", "bogotá")):
        d = "Cundinamarca"

    if tiene_municipal and tiene_departamental:
        return f"{c} / {d}" if (c and d) else (c or d)
    elif tiene_municipal:
        return c
    elif tiene_departamental:
        return d
    return c


# ── Prioridad de Títulos de Sección (Q4) ───────────────────────────────────────
TOKENS_TITULO_SECCION_PRIORITARIO: Set[str] = {
    "información financiera", "informacion financiera",
    "información fiscal", "informacion fiscal",
    "datos financieros", "datos fiscales",
    "condiciones de pago y descuentos", "condiciones de pago y descuento",
    "pago y descuentos", "pagos y descuentos",
    "datos bancarios", "información bancaria", "informacion bancaria",
    "referencias bancarias", "referencia bancaria",
}


# ── Representante Legal: Geografía y Sinónimos de Residencia (Q3) ─────────────
REPRESENTANTE_GEOGRAFIA: Dict[str, str] = {
    "lugar_nacimiento": "Popayán",
    "ciudad_residencia": "Medellín",
    "departamento_residencia": "Antioquia",
}

SINONIMOS_CIUDAD_RESIDENCIA: Set[str] = {
    "municipio de residencia", "ciudad domicilio",
    "lugar de residencia", "domicilio del representante",
    "ciudad de residencia", "ciudad residencia", "municipio residencia",
}


# ── Desglose de Nombres del Representante Legal (Q2) ──────────────────────────
def desglosar_nombre_completo(nombre_completo: str) -> Dict[str, str]:
    """Desglosa un nombre completo en sus 4 componentes canónicos (Q2).

    Guillermo Humberto Cañón Sarria -> 4 partes: 2 nombres + 2 apellidos.
    """
    partes = str(nombre_completo or "").strip().split()
    if len(partes) == 4:
        return {
            "primer_nombre": partes[0],
            "segundo_nombre": partes[1],
            "primer_apellido": partes[2],
            "segundo_apellido": partes[3],
        }
    elif len(partes) == 3:
        return {
            "primer_nombre": partes[0],
            "segundo_nombre": "",
            "primer_apellido": partes[1],
            "segundo_apellido": partes[2],
        }
    elif len(partes) == 2:
        return {
            "primer_nombre": partes[0],
            "segundo_nombre": "",
            "primer_apellido": partes[1],
            "segundo_apellido": "",
        }
    elif len(partes) > 4:
        return {
            "primer_nombre": partes[0],
            "segundo_nombre": " ".join(partes[1:-2]),
            "primer_apellido": partes[-2],
            "segundo_apellido": partes[-1],
        }
    elif len(partes) == 1:
        return {
            "primer_nombre": partes[0],
            "segundo_nombre": "",
            "primer_apellido": "",
            "segundo_apellido": "",
        }
    return {
        "primer_nombre": "",
        "segundo_nombre": "",
        "primer_apellido": "",
        "segundo_apellido": "",
    }


# ── Aliases Determinísticos Configurables para Mapeo Rápido y Exacto ─────────
ALIASES_DETERMINISTICOS_CAMPOS: Dict[str, List[str]] = {
    "nit": [
        "nit", "número de identificación tributaria", "numero de identificacion tributaria",
        "identificación tributaria", "identificacion tributaria", "tax id", "rut",
        "número de identificación", "numero de identificacion", "documento",
        "id tributario", "nit/rut", "nit / rut", "identificación fiscal", "identificacion fiscal",
        "numero id tributario", "no de identificacion", "nro identificacion",
    ],
    "razon_social": [
        "razon social", "razón social", "nombre de la empresa", "nombre o razon social",
        "nombre o razón social", "empresa", "denominación social", "denominacion social",
        "nombre comercial", "razon social / nombre comercial", "razon social o nombre comercial",
        "nombre de la compañia", "nombre de la compania", "proponente", "proveedor",
    ],
    "direccion": [
        "direccion", "dirección", "domicilio", "dirección principal", "direccion principal",
        "domicilio principal", "dirección de correspondencia", "direccion de correspondencia",
        "direccion fisica", "dirección física", "direccion empresa",
    ],
    "telefono": [
        "telefono", "teléfono", "telefono fijo", "teléfono fijo", "telefono empresa",
        "teléfono empresa", "conmutador", "telefono de contacto", "tel", "tel.",
    ],
    "celular": [
        "celular", "móvil", "movil", "telefono celular", "teléfono celular",
        "número celular", "numero celular", "cel", "cel.",
    ],
    "correo": [
        "correo", "email", "e-mail", "correo electronico", "correo electrónico",
        "correo corporativo", "correo principal", "email corporativo", "e-mail corporativo",
    ],
    "ciudad": [
        "ciudad", "municipio", "ciudad domicilio", "ciudad principal", "ciudad sede",
        "municipio / ciudad", "ciudad / municipio",
    ],
    "departamento": [
        "departamento", "departamento domicilio", "estado o departamento", "provincia",
        "dpto", "depto",
    ],
    "pais": [
        "pais", "país", "nacion", "nación", "pais de origen", "país de origen",
    ],
    "pagina_web": [
        "pagina web", "página web", "sitio web", "web", "url", "portal web",
    ],
    "representante_legal": [
        "representante legal", "nombre representante legal", "nombre del representante legal",
        "apoderado legal", "nombre representante", "gerente general",
        "nombres y apellidos del representante legal", "representante",
    ],
    "primer_nombre": [
        "primer nombre", "1er nombre", "primer nombre representante",
    ],
    "segundo_nombre": [
        "segundo nombre", "2do nombre", "segundo nombre representante",
    ],
    "primer_apellido": [
        "primer apellido", "1er apellido", "primer apellido representante",
    ],
    "segundo_apellido": [
        "segundo apellido", "2do apellido", "segundo apellido representante",
    ],
    "cedula": [
        "cedula", "cédula", "cedula de ciudadania", "cédula de ciudadanía",
        "cc", "c.c.", "documento representante", "documento de identidad",
        "número de documento", "numero de documento", "identificacion representante",
        "cedula rep legal", "cédula rep legal", "no. documento", "nro. documento",
    ],
    "tipo_documento": [
        "tipo de documento", "tipo documento", "tipo id", "tipo de id",
        "tipo identificacion", "tipo de identificacion", "clase de documento",
    ],
    "lugar_expedicion": [
        "lugar de expedicion", "lugar de expedición", "lugar expedición", "lugar expedicion",
        "ciudad expedicion", "ciudad expedición", "de expedicion", "de expedición",
    ],
    "fecha_expedicion": [
        "fecha de expedicion", "fecha de expedición", "fecha expedición", "fecha expedicion",
    ],
    "cargo": [
        "cargo", "rol", "cargo representante", "puesto", "cargo que desempeña",
    ],
    "banco": [
        "banco", "entidad bancaria", "nombre del banco", "institucion financiera",
        "entidad financiera",
    ],
    "numero_cuenta": [
        "numero de cuenta", "número de cuenta", "no de cuenta", "no. cuenta",
        "num cuenta", "cuenta bancaria", "no cuenta", "nro de cuenta", "nro cuenta",
    ],
    "tipo_cuenta": [
        "tipo de cuenta", "tipo cuenta", "corriente o ahorros", "ahorros o corriente",
        "clase de cuenta", "tipo de producto",
    ],
    "sucursal": [
        "sucursal", "sucursal bancaria", "oficina bancaria",
    ],
    "moneda": [
        "moneda", "tipo de moneda", "divisa",
    ],
    "total_activos": [
        "total activos", "activos", "valor activos", "total de activos", "activos totales",
    ],
    "total_pasivos": [
        "total pasivos", "pasivos", "valor pasivos", "total de pasivos", "pasivos totales",
    ],
    "total_patrimonio": [
        "total patrimonio", "patrimonio", "patrimonio neto", "total de patrimonio",
    ],
    "total_ingresos_mensuales": [
        "ingresos mensuales", "total ingresos mensuales", "ingresos operacionales mensuales",
    ],
    "total_egresos_mensuales": [
        "egresos mensuales", "total egresos mensuales", "gastos mensuales",
    ],
    "responsable_area": [
        "area", "área", "area comercial", "área comercial", "departamento comercial",
    ],
    "accionista_nombre": [
        "nombre accionista", "nombre socio", "nombre/razon social", "nombre / razon social",
        "accionista nombre", "nombre del accionista", "nombre o razon social",
    ],
    "accionista_identificacion": [
        "identificacion accionista", "identificacion/tipo id", "identificación/tipo id",
        "identificacion socio", "numero identificacion accionista",
    ],
    "accionista_porcentaje": [
        "porcentaje participacion", "porcentaje participación", "porcentaje participacion accionaria",
        "% participacion", "% de participacion", "% participacion accionaria",
    ],
    "beneficiario_nombre": [
        "nombre beneficiario final", "beneficiario final nombre", "nombre del beneficiario final",
    ],
    "beneficiario_identificacion": [
        "identificacion beneficiario final", "identificacion beneficiario real",
    ],
}


def resolver_campo_por_alias_determinista(texto_rotulo: str) -> Optional[str]:
    """Resuelve determinísticamente el campo maestro a partir de un texto de rótulo o encabezado.
    
    Aplica normalización de tildes, puntuación y mayúsculas/minúsculas.
    Retorna la clave del campo (ej. 'nit') si hay coincidencia exacta o de alta prioridad.
    """
    if not texto_rotulo:
        return None
    
    rotulo_limpio = limpiar_rotulo(texto_rotulo).strip().lower()
    if not rotulo_limpio:
        return None
    
    # 1. Búsqueda exacta en el catálogo de aliases
    for campo_key, aliases in ALIASES_DETERMINISTICOS_CAMPOS.items():
        for alias in aliases:
            if rotulo_limpio == alias.lower():
                return campo_key
                
    # 2. Búsqueda por subcadena delimitada o prefijo exacto (ej. "NIT:" o "Razón Social *")
    for campo_key, aliases in ALIASES_DETERMINISTICOS_CAMPOS.items():
        for alias in aliases:
            # Si el alias es suficientemente largo (>= 3 chars) y está contenido como palabra completa
            if len(alias) >= 3:
                patron = rf"\b{re.escape(alias.lower())}\b"
                if re.search(patron, rotulo_limpio):
                    return campo_key
                    
    return None


