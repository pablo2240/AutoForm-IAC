"""Handler especializado para lectura e inyección tipográfica en documentos PDF (.pdf)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from core.pdf_processor import escanear_mapa_pdf, rellenar_pdf


class PdfHandler:
    """Maneja el escaneo espacial y la inyección tipográfica en archivos PDF."""

    @staticmethod
    def escanear(archivo_bytes: bytes) -> List[Dict[str, Any]]:
        """Extrae palabras, líneas, AcroForms y cajas de inyección del PDF."""
        return escanear_mapa_pdf(archivo_bytes)

    @staticmethod
    def inyectar(
        archivo_bytes: bytes,
        plan_mapeo: List[Dict[str, Any]],
        datos_empresa: Dict[str, Any],
    ) -> Tuple[bytes, List[Dict[str, Any]]]:
        """Inyecta los datos en el PDF con tipografía nativa detectada y genera reporte."""
        pdf_modificado = rellenar_pdf(
            bytes_pdf=archivo_bytes,
            plan_mapeo=plan_mapeo,
            datos_empresa=datos_empresa,
        )

        # Generar reporte estructurado de inyección PDF
        reporte: List[Dict[str, Any]] = []
        for item in plan_mapeo:
            campo = str(item.get("campo", ""))
            valor = datos_empresa.get(campo)
            estado = "OK" if (campo and valor is not None) else "NULL"
            reporte.append({
                "estado": estado,
                "campo": campo,
                "valor_intentado": str(valor)[:80] if valor is not None else None,
                "hoja": str(item.get("hoja", "Pagina_1")),
                "fila_destino": int(item.get("fila", 0) or 0),
                "columna_destino": int(item.get("columna", 0) or 0),
                "motivo": "" if estado == "OK" else "Campo no encontrado en DatosEmpresa",
            })

        return pdf_modificado, reporte
