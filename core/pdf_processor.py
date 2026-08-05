"""Módulo de extracción y superposición en PDF."""

from pypdf import PdfReader
from reportlab.pdfgen import canvas


def extraer_texto_con_posiciones(ruta: str) -> list:
    """Devuelve la lista de palabras con sus coordenadas (x, y)."""
    lector = PdfReader(ruta)
    palabras = []
    for pagina in lector.pages:
        datos = pagina.extract_text(extraction_mode="layout")
        if datos:
            # En un caso real se extraerían (x, y, ancho, alto) por palabra.
            palabras.append(datos)
    return palabras


def superponer_texto(ruta_pdf: str, ruta_salida: str, campos: dict) -> None:
    """Genera un PDF nuevo escribiendo los campos sobre las posiciones dadas."""
    # Placeholder de implementación de superposición.
    c = canvas.Canvas(ruta_salida)
    for texto, (x, y) in campos.items():
        c.drawString(x, y, str(texto))
    c.showPage()
    c.save()
