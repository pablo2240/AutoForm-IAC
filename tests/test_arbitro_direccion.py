"""Árbitro de dirección (B): encabezados de tabla cuya captura está debajo, no en la celda vacía de la derecha."""

from __future__ import annotations

from io import BytesIO
from typing import Dict, List

from openpyxl import Workbook
from openpyxl.styles import Border, PatternFill, Side

from core.arbitro_direccion import arbitrar_direcciones
from pipeline.handlers import ExcelHandler
from pipeline.stages.stage_2_classifier import clasificar_elementos_formulario

_LADO = Side(style="thin")
_CAJA = Border(left=_LADO, right=_LADO, top=_LADO, bottom=_LADO)
_RELLENO = PatternFill("solid", fgColor="FFF2CC")


def _caja(ws, rango: str, relleno: bool = False) -> None:
    for fila in ws[rango]:
        for celda in fila:
            celda.border = _CAJA
            if relleno:
                celda.fill = _RELLENO


def _tabla_de_encabezados() -> bytes:
    """Fila 2: encabezados Banco | Tipo de Cuenta | Número de Cuenta (el último combinado, borde de la tabla en F).
    Fila 3: celdas de captura bajo cada encabezado. La columna G (a la derecha de la tabla) queda libre y sin bordes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Formato"
    ws["A1"] = "INFORMACIÓN BANCARIA"
    ws["A2"], ws["C2"], ws["D2"] = "Banco", "Tipo de Cuenta", "Número de Cuenta"
    ws.merge_cells("A2:B2")
    ws.merge_cells("D2:F2")
    ws.merge_cells("A3:B3")
    ws.merge_cells("D3:F3")
    _caja(ws, "A2:B2", True)
    _caja(ws, "C2:C2", True)
    _caja(ws, "D2:F2", True)
    _caja(ws, "A3:B3", True)
    _caja(ws, "C3:C3", True)
    _caja(ws, "D3:F3", True)
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _formulario_en_linea() -> bytes:
    """Rótulos con su caja de captura a la derecha y nada especial debajo: no debe cambiar nada."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Formato"
    ws["A1"], ws["A3"] = "Razón social:", "Dirección:"
    ws.merge_cells("B1:E1")
    ws.merge_cells("B3:E3")
    _caja(ws, "B1:E1")
    _caja(ws, "B3:E3")
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


def _direcciones(archivo: bytes) -> Dict[str, str]:
    elementos = ExcelHandler.escanear(archivo)
    arbitrar_direcciones(elementos, archivo)
    clasificados, _ = clasificar_elementos_formulario(elementos, datos_empresa={})
    return {str(e["valor"]): e["tipoEspacioEscritura"] for e in clasificados if e.get("es_campo_viable")}


def test_el_ultimo_encabezado_de_la_fila_escribe_hacia_abajo_como_sus_hermanos() -> None:
    archivo = _tabla_de_encabezados()
    elementos = ExcelHandler.escanear(archivo)

    cambios = arbitrar_direcciones(elementos, archivo)

    assert [c.rotulo for c in cambios] == ["Número de Cuenta"]
    assert cambios[0].puntaje_abajo - cambios[0].puntaje_derecha >= 3
    assert any("fuera de la tabla" in m for m in cambios[0].motivos)
    assert _direcciones(archivo)["Número de Cuenta"] == "abajo"


def test_el_plan_apunta_a_la_celda_de_captura_de_abajo() -> None:
    archivo = _tabla_de_encabezados()
    elementos = ExcelHandler.escanear(archivo)
    arbitrar_direcciones(elementos, archivo)

    cuenta = next(e for e in elementos if e["valor"] == "Número de Cuenta")

    assert cuenta["direccionArbitrada"] == "abajo"
    assert cuenta["destinosPropuestos"]["abajo"] == {"fila_destino": 3, "columna_destino": 4}


def test_no_cambia_los_formularios_con_la_captura_a_la_derecha() -> None:
    archivo = _formulario_en_linea()
    elementos = ExcelHandler.escanear(archivo)

    assert arbitrar_direcciones(elementos, archivo) == []
    assert set(_direcciones(archivo).values()) == {"derecha"}


def test_no_cambia_si_no_hay_evidencia_suficiente_debajo() -> None:
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Teléfono"  # sin bordes, sin celdas combinadas y sin hermanos: caso ambiguo sin pruebas
    salida = BytesIO()
    wb.save(salida)
    elementos = ExcelHandler.escanear(salida.getvalue())

    assert arbitrar_direcciones(elementos, salida.getvalue()) == []


def test_es_idempotente_y_nunca_cambia_en_el_sentido_contrario() -> None:
    archivo = _tabla_de_encabezados()
    elementos = ExcelHandler.escanear(archivo)
    primero = arbitrar_direcciones(elementos, archivo)
    segundo = arbitrar_direcciones(elementos, archivo)

    assert len(primero) == 1 and segundo == []
    assert all(e.get("direccionArbitrada") in (None, "abajo") for e in elementos)


def test_un_relleno_sin_caja_debajo_nunca_basta_para_cambiar_la_direccion() -> None:
    """Un título con relleno debajo y nada a la derecha no es un encabezado de tabla."""
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "NUMERO DE EMPLEADOS:"
    ws["A2"].fill = _RELLENO  # relleno sin bordes: no es una caja de captura
    ws["C1"] = "N°"
    salida = BytesIO()
    wb.save(salida)
    elementos = ExcelHandler.escanear(salida.getvalue())

    assert arbitrar_direcciones(elementos, salida.getvalue()) == []


def test_exige_el_mismo_ancho_que_el_encabezado() -> None:
    """Una caja debajo más angosta que el rótulo combinado no se toma como su celda de captura."""
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Observaciones"
    ws.merge_cells("A1:D1")
    ws.merge_cells("A2:B2")
    _caja(ws, "A1:D1", True)
    _caja(ws, "A2:B2", True)
    salida = BytesIO()
    wb.save(salida)
    elementos = ExcelHandler.escanear(salida.getvalue())

    assert arbitrar_direcciones(elementos, salida.getvalue()) == []


def test_la_direccion_arbitrada_llega_a_la_ir_y_a_la_celda_destino_del_plan() -> None:
    from core.spatial_ir import construir_ir
    from pipeline.context import PipelineContext
    from pipeline.stages.stage_1_parser import ejecutar_stage_1_parser

    ctx = ejecutar_stage_1_parser(PipelineContext(archivo_bytes=_tabla_de_encabezados(), nombre_archivo="f.xlsx"))
    clasificados, _ = clasificar_elementos_formulario(ctx.elementos_raw, datos_empresa={})
    ir = construir_ir(clasificados, "f.xlsx", "excel")

    direcciones_ir = {e.texto: e.direccion_escritura for s in ir.secciones for f in s.filas for e in f.elementos}
    assert ctx.metadatos["arbitro_direccion"][0]["rotulo"] == "Número de Cuenta"
    assert direcciones_ir["Número de Cuenta"] == "abajo"
    assert direcciones_ir["Banco"] == "abajo" and direcciones_ir["Tipo de Cuenta"] == "abajo"
