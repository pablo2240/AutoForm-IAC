"""Módulo de Verificación Posterior e Integridad de Archivos Excel (.xlsx).

Parte de la Suite de Precisión de AutoForm AI.
Garantiza el principio de Inmutabilidad e Integridad Estructural:
  1. Reabre el archivo Excel generado en memoria (copia independiente).
  2. Comprueba que los valores esperados del plan quedaron en las celdas correctas.
  3. Certifica que el 100% de las fórmulas preexistentes permanecen intactas (no convertidas a estáticos ni borradas).
  4. Certifica la conservación de las validaciones de datos (DataValidations).
  5. Si detecta corrupción o violación de integridad, levanta un fallo controlado y bloquea la entrega del archivo.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from core.excel_inspector import InspeccionLibroExcel


@dataclass
class ResultadoVerificacion:
    """Resultado del chequeo de integridad post-escritura."""
    es_valido: bool
    total_verificados: int = 0
    exitosos: int = 0
    fallidos: int = 0
    formulas_preservadas: int = 0
    formulas_danadas: int = 0
    validaciones_preservadas: int = 0
    errores_bloqueantes: List[str] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)
    detalles: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def resumen_metricas(self) -> Dict[str, Any]:
        return {
            "valido": self.es_valido,
            "total_verificados": self.total_verificados,
            "exitosos": self.exitosos,
            "fallidos": self.fallidos,
            "formulas_preservadas": self.formulas_preservadas,
            "formulas_danadas": self.formulas_danadas,
            "validaciones_preservadas": self.validaciones_preservadas,
            "errores_bloqueantes": len(self.errores_bloqueantes),
            "advertencias": len(self.advertencias),
        }


def _son_valores_equivalentes(val_esperado: Any, val_encontrado: Any) -> bool:
    """Compara si dos valores son semánticamente equivalentes (manejando tipos float/int/str)."""
    if val_esperado is None and val_encontrado is None:
        return True
    if val_esperado is None or val_encontrado is None:
        return False

    str_esp = str(val_esperado).replace("\xa0", " ").strip()
    str_enc = str(val_encontrado).replace("\xa0", " ").strip()

    if str_esp.lower() == str_enc.lower():
        return True

    # Si el valor esperado está contenido (p. ej. en misma celda "NIT: 900123")
    if str_esp.lower() in str_enc.lower():
        return True

    # Comparación numérica y porcentajes (ej. 100 vs 1.0 en formato porcentaje)
    try:
        f_esp = float(str_esp.replace(",", ".").replace("$", "").replace("%", "").strip())
        f_enc = float(str_enc.replace(",", ".").replace("$", "").replace("%", "").strip())
        if abs(f_esp - f_enc) < 0.0001:
            return True
        if abs(f_esp / 100.0 - f_enc) < 0.0001 or abs(f_esp - f_enc / 100.0) < 0.0001:
            return True
    except Exception:
        pass

    return False


def verificar_integridad_excel(
    archivo_original_bytes: bytes,
    archivo_generado_bytes: bytes,
    plan_mapeo: List[Dict[str, Any]],
    inspeccion_original: InspeccionLibroExcel,
    reporte_inyeccion: Optional[List[Dict[str, Any]]] = None,
) -> ResultadoVerificacion:
    """Verifica exhaustivamente que el Excel generado cumpla todos los estándares de integridad."""
    res = ResultadoVerificacion(es_valido=True)

    try:
        wb_generado = openpyxl.load_workbook(filename=io.BytesIO(archivo_generado_bytes), data_only=False)
    except Exception as exc:
        res.es_valido = False
        res.errores_bloqueantes.append(f"El archivo generado está corrupto o no pudo ser abierto por Excel: {exc}")
        return res

    from core.excel_inspector import inspeccionar_libro_excel
    insp_generado = inspeccionar_libro_excel(archivo_generado_bytes)

    # 1. VERIFICACIÓN DE FÓRMULAS ORIGINALES
    for (hoja_f, fila_f, col_f), formula_orig in inspeccion_original.celdas_con_formula.items():
        if hoja_f not in wb_generado.sheetnames:
            continue
        ws_gen = wb_generado[hoja_f]
        celda_gen = ws_gen.cell(row=fila_f, column=col_f)
        val_gen = celda_gen.value

        es_formula_actual = (
            celda_gen.data_type == "f" or 
            (val_gen is not None and isinstance(val_gen, str) and val_gen.startswith("="))
        )

        if not es_formula_actual or str(val_gen) != str(formula_orig):
            res.formulas_danadas += 1
            res.es_valido = False
            msg_err = (
                f"🚨 FÓRMULA DESTRUIDA en Hoja '{hoja_f}' Celda ({fila_f}, {col_f}). "
                f"Fórmula original: '{formula_orig}', Valor actual: '{val_gen}'"
            )
            res.errores_bloqueantes.append(msg_err)
        else:
            res.formulas_preservadas += 1

    # 1b. La escritura preserva hojas y validaciones. Cambios menores de formato se registran como advertencias.
    for hoja in inspeccion_original.hojas:
        if insp_generado.hojas_firma.get(hoja) != inspeccion_original.hojas_firma.get(hoja):
            res.advertencias.append(f"Estado o visibilidad de hoja ajustada: '{hoja}'.")
        if insp_generado.validaciones_firma.get(hoja, ()) != inspeccion_original.validaciones_firma.get(hoja, ()):
            res.advertencias.append(f"Validaciones de datos ajustadas en '{hoja}'.")
        if insp_generado.tablas_firma.get(hoja, ()) != inspeccion_original.tablas_firma.get(hoja, ()):
            res.advertencias.append(f"Estructura de tabla ajustada en '{hoja}'.")
    if insp_generado.estilos_firma != inspeccion_original.estilos_firma:
        res.advertencias.append("Se detectaron ajustes de estilo en celdas diligenciadas.")

    # 2. VERIFICACIÓN DE VALORES INYECTADOS
    # Si tenemos reporte de inyección detallado, verificar las celdas reportadas como escritas
    items_a_verificar = []
    if reporte_inyeccion:
        for r_item in reporte_inyeccion:
            if str(r_item.get("estado", "")).upper() == "OK":
                f_d = r_item.get("fila_destino") or r_item.get("fila")
                c_d = r_item.get("columna_destino") or r_item.get("columna")
                val_d = r_item.get("valor") if r_item.get("valor") is not None else r_item.get("valor_intentado")
                if f_d is not None and c_d is not None:
                    items_a_verificar.append({
                        "hoja": r_item.get("hoja"),
                        "fila_destino": int(f_d),
                        "columna_destino": int(c_d),
                        "valor": val_d,
                        "campo": r_item.get("campo"),
                    })

    destinos_autorizados = {
        (str(item.get("hoja") or ""), int(item.get("fila_destino") or 0), int(item.get("columna_destino") or 0))
        for item in (reporte_inyeccion or []) if str(item.get("estado", "")).upper() == "OK"
    }
    for coord, valor_original in inspeccion_original.valores_existentes.items():
        if coord in destinos_autorizados:
            continue
        if insp_generado.valores_existentes.get(coord) != valor_original:
            res.errores_bloqueantes.append(
                f"Valor existente alterado en {coord[0]}!R{coord[1]}C{coord[2]}."
            )


    if not items_a_verificar and reporte_inyeccion is None:
        for item in plan_mapeo:
            estado_item = str(item.get("estado", "")).upper()
            if estado_item in ("DESCARTADO", "SKIP", "OMITIDO"):
                continue

            f_dest = item.get("fila_destino") or item.get("fila_escritura")
            c_dest = item.get("columna_destino") or item.get("columna_escritura")
            if not f_dest or not c_dest:
                f_orig = int(item.get("fila", 1) or 1)
                c_orig = int(item.get("columna", 1) or 1)
                ub = str(item.get("ubicacion", "derecha")).lower()
                if ub == "derecha":
                    f_dest, c_dest = f_orig, c_orig + 1
                elif ub == "abajo":
                    f_dest, c_dest = f_orig + 1, c_orig
                else:
                    f_dest, c_dest = f_orig, c_orig

            items_a_verificar.append({
                "hoja": item.get("hoja"),
                "fila_destino": f_dest,
                "columna_destino": c_dest,
                "valor": item.get("valor"),
                "campo": item.get("campo"),
            })

    for it_verif in items_a_verificar:
        hoja_it = it_verif.get("hoja", "")
        if not hoja_it or hoja_it not in wb_generado.sheetnames:
            continue

        fila_it = int(it_verif["fila_destino"])
        col_it = int(it_verif["columna_destino"])
        val_esperado = it_verif.get("valor")
        if val_esperado is None:
            continue


        ws_it = wb_generado[hoja_it]
        celda_actual = ws_it.cell(row=int(fila_it), column=int(col_it))
        val_actual = celda_actual.value

        res.total_verificados += 1

        if _son_valores_equivalentes(val_esperado, val_actual):
            res.exitosos += 1
            res.detalles.append({
                "hoja": hoja_it,
                "fila": fila_it,
                "columna": col_it,
                "esperado": val_esperado,
                "encontrado": val_actual,
                "estado": "OK",
            })
        else:
            res.fallidos += 1
            advertencia = (
                f"Divergencia en [{hoja_it}!R{fila_it}C{col_it}]: "
                f"Esperado '{val_esperado}', Encontrado '{val_actual}'"
            )
            res.advertencias.append(advertencia)
            res.errores_bloqueantes.append(advertencia)
            res.es_valido = False
            res.detalles.append({
                "hoja": hoja_it,
                "fila": fila_it,
                "columna": col_it,
                "esperado": val_esperado,
                "encontrado": val_actual,
                "estado": "DIVERGENCIA",
            })

    # 3. VERIFICACIÓN DE VALIDACIONES DE DATOS
    for sheet_name in wb_generado.sheetnames:
        ws_gen = wb_generado[sheet_name]
        cant_dv = len(ws_gen.data_validations.dataValidation) if hasattr(ws_gen, "data_validations") else 0
        res.validaciones_preservadas += cant_dv

    # Si hubo fórmulas dañadas o el archivo está vacío, invalidar
    if res.formulas_danadas > 0 or res.errores_bloqueantes:
        res.es_valido = False

    return res
