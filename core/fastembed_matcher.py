"""Módulo de Rescate Semántico Local con FastEmbed (Capa 3).

Permite vectorizar rótulos no resueltos y compararlos mediante similitud coseno
contra el perfil taxonómico de la empresa en CPU (<5ms, costo $0 de API).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

_MODELO_FASTEMBED = None

# Descripciones semánticas enriquecidas para cada clave canónica
DESCRIPCIONES_TAXONOMIA: Dict[str, str] = {
    "razon_social": "Nombre de la empresa, razón social, denominación jurídica, proponente o contratista",
    "nit": "NIT, número de identificación tributaria, registro único tributario RUT, Tax ID, identificación de la empresa",
    "tipo_sociedad": "Tipo de sociedad, tipo de persona jurídica, S.A.S., S.A., Ltda, forma societaria",
    "representante_legal": "Nombre y apellidos completos del representante legal, apoderado, gerente o firmante autorizado",
    "representante_nombres": "Primer y segundo nombre de la persona natural o representante legal",
    "representante_apellidos": "Primer y segundo apellido de la persona natural o representante legal",
    "tipo_documento": "Tipo de documento de identidad, cédula de ciudadanía C.C., cédula de extranjería C.E., pasaporte",
    "cedula": "Número de cédula de ciudadanía, número de documento de identidad de la persona natural o representante legal",
    "lugar_expedicion": "Lugar de expedición, ciudad o municipio donde se expidió la cédula o documento de identidad",
    "direccion": "Dirección física, domicilio principal, sede de la empresa, calle, carrera, número, oficina",
    "ciudad": "Ciudad, municipio, localidad, domicilio fiscal de la empresa",
    "departamento": "Departamento, provincia, estado, región",
    "pais": "País de constitución o domicilio, Colombia",
    "ciudad_departamento": "Ciudad y departamento combinados, municipio y departamento, lugar de domicilio",
    "telefono": "Teléfono fijo, número de teléfono principal, PBX, línea de atención institucional de la empresa",
    "celular": "Teléfono celular, móvil, número de teléfono de contacto personal del representante legal",
    "correo": "Correo electrónico, email, dirección de correo de contacto o facturación",
    "pagina_web": "Página web, sitio web, portal web, URL corporativa",
    "banco": "Nombre de la entidad bancaria, banco, institución financiera",
    "numero_cuenta": "Número de cuenta bancaria, número de cuenta de ahorros o corriente",
    "tipo_cuenta": "Tipo de cuenta bancaria, ahorros, corriente",
    "sucursal": "Sucursal bancaria, oficina bancaria",
}


def _obtener_modelo():
    """Carga perezosa (lazy singleton) del modelo FastEmbed en CPU."""
    global _MODELO_FASTEMBED
    if _MODELO_FASTEMBED is not None:
        return _MODELO_FASTEMBED

    try:
        from fastembed import TextEmbedding
        _MODELO_FASTEMBED = TextEmbedding("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        return _MODELO_FASTEMBED
    except Exception as exc:
        print(f"[AutoForm AI FastEmbed] No se pudo cargar el modelo FastEmbed: {exc}")
        return None


def buscar_rescate_vectorial(
    rotulo: str,
    campos_candidatos: List[str],
    umbral: float = 0.70,
) -> Optional[Tuple[str, float]]:
    """Compara semánticamente el rótulo contra las descripciones de campos candidatos.

    Args:
        rotulo: Texto del rótulo del formulario (ej. 'Entidad Bancaria').
        campos_candidatos: Lista de claves de la empresa disponibles para asignar.
        umbral: Similitud coseno mínima requerida (0.0 a 1.0, default 0.70).

    Returns:
        Tupla (mejor_campo, score) si supera el umbral, o None si ningún candidato supera el umbral.
    """
    if not rotulo or not campos_candidatos:
        return None

    model = _obtener_modelo()
    if model is None:
        return None

    # Filtrar solo candidatos válidos
    candidatos_validos = [c for c in campos_candidatos if c in DESCRIPCIONES_TAXONOMIA]
    if not candidatos_validos:
        candidatos_validos = list(campos_candidatos)

    textos_candidatos = [
        f"{c}: {DESCRIPCIONES_TAXONOMIA.get(c, c)}"
        for c in candidatos_validos
    ]

    try:
        # Generar embeddings de una pasada
        todos_textos = [rotulo] + textos_candidatos
        vectores = np.array(list(model.embed(todos_textos)))
        
        # Normalizar para similitud coseno
        normas = np.linalg.norm(vectores, axis=1, keepdims=True)
        normas[normas == 0] = 1e-12
        vectores = vectores / normas

        vec_rotulo = vectores[0]
        vec_candidatos = vectores[1:]

        similitudes = np.dot(vec_candidatos, vec_rotulo)
        mejor_idx = int(np.argmax(similitudes))
        mejor_score = float(similitudes[mejor_idx])

        if mejor_score >= umbral:
            return candidatos_validos[mejor_idx], mejor_score

    except Exception as exc:
        print(f"[AutoForm AI FastEmbed] Error al calcular similitud vectorial: {exc}")

    return None
