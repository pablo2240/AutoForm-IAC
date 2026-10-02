"""
Pruebas de Regresión – ADR-0011: Tres Documentos de Example
==============================================================
Verifica las correcciones de Q1/Q2/Q4 aprobadas:

  Q1  Aislamiento de Identidades por Rol (representante legal ≠ contacto comercial)
  Q2  Zona PEP Negativa – sub-campos completamente vacíos cuando PEP = NO
  Q4  Encabezados con contexto de sección padre (Sucursal, Área, Identificación)
  Q5  Composición Accionaria / Beneficiarios Finales desde perfil societario

Formularios cubiertos:
  - FMCA07J.- 6.2.xlsx
  - 01 SC-COM-02-25.xlsx
  - GE.F.021_5.5.xlsx

Ejecutar:
    pytest tests/test_three_examples_regression.py -v
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import openpyxl
import pytest

# ── Configuración del entorno ──────────────────────────────────────────────────
os.environ.setdefault("APP_ENVIRONMENT", "development")
os.environ.setdefault("USE_SQLITE", "true")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.excel_inspector import inspeccionar_libro_excel
from core import profile_manager
from pipeline.context import PipelineContext
from pipeline.orchestrator import PipelineOrchestrator

# ── Helpers ────────────────────────────────────────────────────────────────────

EXAMPLE_DIR = ROOT / "example"
OUTPUT_DIR  = ROOT / "scratch" / "excel_output_test"
CONFIG_PATH = ROOT / "config" / "datos_empresa.json"


def _cargar_datos_empresa() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        datos = json.load(f)
    try:
        op = profile_manager.obtener_operador_activo()
        datos = profile_manager.fusionar_operador_en_datos_empresa(datos, operador=op)
    except Exception:
        pass
    return datos


def _ejecutar_pipeline(nombre_archivo: str) -> bytes:
    """Ejecuta el pipeline completo y devuelve los bytes del archivo resultado."""
    path = EXAMPLE_DIR / nombre_archivo
    assert path.exists(), f"Archivo de ejemplo no encontrado: {path}"

    with open(path, "rb") as f:
        raw = f.read()

    datos = _cargar_datos_empresa()
    insp = inspeccionar_libro_excel(raw)
    ctx = PipelineContext(
        archivo_bytes=raw,
        nombre_archivo=nombre_archivo,
        datos_empresa=datos,
    )
    ctx.inspeccion_excel = insp
    ctx = PipelineOrchestrator.analizar_formulario(ctx)
    ctx = PipelineOrchestrator.rellenar_formulario(ctx)
    return ctx.archivo_resultado


def _cargar_ws(nombre_archivo: str) -> "openpyxl.worksheet.worksheet.Worksheet":
    out_path = OUTPUT_DIR / f"resultado_{nombre_archivo}"
    if not out_path.exists():
        datos = _ejecutar_pipeline(nombre_archivo)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(datos)
    wb = openpyxl.load_workbook(out_path, data_only=True)
    return wb.active


def _cell(ws, row: int, col: int) -> Optional[str]:
    v = ws.cell(row=row, column=col).value
    return str(v).strip() if v is not None else None


def _col_with(ws, row: int, text: str) -> Optional[int]:
    """Devuelve la primera columna de la fila cuyo valor contiene el texto."""
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=row, column=c).value
        if v and text.lower() in str(v).lower():
            return c
    return None


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ws_fmca():
    return _cargar_ws("FMCA07J.- 6.2.xlsx")


@pytest.fixture(scope="module")
def ws_sccom():
    return _cargar_ws("01 SC-COM-02-25.xlsx")


@pytest.fixture(scope="module")
def ws_ge():
    return _cargar_ws("GE.F.021_5.5.xlsx")


# ══════════════════════════════════════════════════════════════════════════════
# FMCA07J.- 6.2.xlsx
# ══════════════════════════════════════════════════════════════════════════════

class TestFMCA07J:
    """Q1 · Q4 – Representante Legal e Identificación, Sucursal bancaria."""

    # R30 → Representante Legal / Identificación
    def test_r30_cedula_representante_legal(self, ws_fmca):
        """ADR-0011 Q4: Encabezado IDENTIFICACION (R29) debe llenarse con la cédula del
        representante legal (98555384) en la fila inmediatamente inferior (R30)."""
        assert _cell(ws_fmca, 30, 2) == "98555384", (
            "R30 C2 debe contener la cédula del representante legal"
        )

    def test_r30_nombre_representante_legal(self, ws_fmca):
        """ADR-0011 Q1: El nombre en R30 debe ser el del representante legal
        (Guillermo Humberto Cañón Sarria), no el del contacto comercial."""
        nombre = _cell(ws_fmca, 30, 13)
        assert nombre is not None, "R30 C13 no debe estar vacío"
        assert "guillermo" in nombre.lower(), (
            f"R30 C13 debe ser el representante legal (Guillermo), got: {nombre!r}"
        )
        assert "antonio" not in nombre.lower(), (
            "El contacto comercial (Antonio) no debe aparecer en la sección de representante legal"
        )

    def test_r30_direccion_representante_legal(self, ws_fmca):
        """R30 dirección del representante legal debe estar presente."""
        direccion = _cell(ws_fmca, 30, 27)
        assert direccion is not None, "R30 C27 (dirección) no debe estar vacío"

    # R66 → Referencia Bancaria / Sucursal
    def test_r66_sucursal_bancaria(self, ws_fmca):
        """ADR-0011 Q4: El encabezado SUCURSAL (R65 C16) debe llenarse con 'Medellin'
        en la fila de datos (R66 C16)."""
        sucursal = _cell(ws_fmca, 66, 16)
        assert sucursal is not None, "R66 C16 (sucursal bancaria) no debe estar vacío"
        assert "medellin" in sucursal.lower(), (
            f"Sucursal bancaria debe ser Medellin, got: {sucursal!r}"
        )

    def test_r66_banco(self, ws_fmca):
        """El banco BANCOLOMBIA debe estar en R66 C2."""
        banco = _cell(ws_fmca, 66, 2)
        assert banco is not None
        assert "bancolombia" in banco.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 01 SC-COM-02-25.xlsx
# ══════════════════════════════════════════════════════════════════════════════

class TestSCCOM:
    """Q1 · Q2 · Q4 – Zona PEP negativa vacía, Área en contacto comercial."""

    # R28-R32 → PEP Condicional Positivo (debe estar VACÍO cuando PEP = NO)
    def test_pep_conditional_positive_empty_r28_c6(self, ws_sccom):
        """ADR-0011 Q2: Si PEP = NO, el campo 'Nombre Completo' del PEP debe estar vacío."""
        val = _cell(ws_sccom, 28, 6)
        assert val is None or val.strip() in ("", "Nombre Completo"), (
            f"R28 C6 (nombre PEP condicional) debe estar vacío, got: {val!r}"
        )

    def test_pep_conditional_nombre_completo_empty(self, ws_sccom):
        """ADR-0011 Q2: Ningún valor de persona debe escribirse en las filas R29-R31 de la
        sub-sección PEP condicional."""
        # Verificar que no aparezca ningún nombre de persona en las filas del sub-bloque PEP
        for row in range(29, 32):
            for col in range(4, 8):
                val = _cell(ws_sccom, row, col)
                if val is None:
                    continue
                low = val.lower()
                assert "guillermo" not in low, (
                    f"R{row} C{col}: el representante legal no debe aparecer en la zona PEP condicional"
                )
                assert "antonio" not in low, (
                    f"R{row} C{col}: el contacto comercial no debe aparecer en la zona PEP condicional"
                )

    # R58 → Contacto Comercial / Área
    def test_r58_area_comercial(self, ws_sccom):
        """ADR-0011 Q4: El encabezado 'Área' (R57 C2) debe llenarse con 'Comercial'
        en la fila de datos (R58 C2)."""
        area = _cell(ws_sccom, 58, 2)
        assert area is not None, "R58 C2 (Área del contacto comercial) no debe estar vacío"
        assert "comercial" in area.lower(), (
            f"R58 C2 debe ser 'Comercial', got: {area!r}"
        )

    def test_r58_nombre_contacto_comercial(self, ws_sccom):
        """ADR-0011 Q1: El nombre en R58 debe ser el del contacto comercial (Antonio),
        no el del representante legal (Guillermo)."""
        nombre = _cell(ws_sccom, 58, 3)
        assert nombre is not None, "R58 C3 (nombre contacto) no debe estar vacío"
        assert "guillermo" not in nombre.lower(), (
            "El representante legal no debe aparecer en la fila de contacto comercial"
        )

    def test_r58_cargo_contacto_comercial(self, ws_sccom):
        """R58 debe contener el cargo del contacto comercial."""
        cargo = _cell(ws_sccom, 58, 5)
        assert cargo is not None, "R58 C5 (cargo contacto) no debe estar vacío"


# ══════════════════════════════════════════════════════════════════════════════
# GE.F.021_5.5.xlsx
# ══════════════════════════════════════════════════════════════════════════════

class TestGEF021:
    """Q1 · Q5 – Representante Legal sin Antonio, Accionistas/Beneficiarios desde perfil societario."""

    # R19-R20 → Representante Legal
    def test_r19_nombre_representante_legal(self, ws_ge):
        """ADR-0011 Q1: R19 debe contener el nombre del representante legal (Guillermo),
        jamás el del contacto comercial (Antonio)."""
        nombre = _cell(ws_ge, 19, 4)
        assert nombre is not None, "R19 C4 (nombre representante legal) no debe estar vacío"
        assert "guillermo" in nombre.lower(), (
            f"R19 C4 debe ser Guillermo Humberto Cañón Sarria, got: {nombre!r}"
        )
        assert "antonio" not in nombre.lower(), (
            "Antonio Prieto no debe aparecer en la sección de representante legal"
        )

    def test_r20_cedula_representante_legal(self, ws_ge):
        """R20 debe contener la cédula del representante legal (98555384)."""
        cedula = _cell(ws_ge, 20, 3)
        assert cedula == "98555384", (
            f"R20 C3 (cédula representante legal) debe ser 98555384, got: {cedula!r}"
        )

    def test_r20_correo_representante_legal(self, ws_ge):
        """R20 correo debe ser el del representante legal, no el del contacto comercial."""
        correo = _cell(ws_ge, 20, 10)
        assert correo is not None, "R20 C10 (correo) no debe estar vacío"
        assert "antonio" not in correo.lower(), (
            "El correo del contacto comercial no debe aparecer en la sección del representante legal"
        )
        assert "guillermo" in correo.lower() or "iaclatam" in correo.lower(), (
            f"R20 C10 debe ser el correo de Guillermo, got: {correo!r}"
        )

    # R32 → Composición Accionaria (primer accionista)
    def test_r32_nombre_accionista(self, ws_ge):
        """ADR-0011 Q5: R32 debe contener el nombre del accionista desde el perfil societario."""
        nombre = _cell(ws_ge, 32, 2)
        assert nombre is not None, "R32 C2 (nombre accionista) no debe estar vacío"
        assert "guillermo" in nombre.lower(), (
            f"R32 C2 debe ser Guillermo Humberto Cañón Sarria, got: {nombre!r}"
        )

    def test_r32_tipo_id_accionista(self, ws_ge):
        """R32 debe contener el tipo de identificación (C.C) del accionista."""
        tipo = _cell(ws_ge, 32, 7)
        assert tipo is not None, "R32 C7 (tipo ID accionista) no debe estar vacío"
        assert "c.c" in tipo.lower() or "cc" in tipo.lower(), (
            f"R32 C7 debe ser C.C, got: {tipo!r}"
        )

    # R40 → Beneficiarios Finales
    def test_r40_nombre_beneficiario_final(self, ws_ge):
        """ADR-0011 Q5: R40 debe contener el nombre del beneficiario final desde el perfil societario."""
        nombre = _cell(ws_ge, 40, 2)
        assert nombre is not None, "R40 C2 (nombre beneficiario final) no debe estar vacío"
        assert "guillermo" in nombre.lower(), (
            f"R40 C2 debe ser Guillermo Humberto Cañón Sarria, got: {nombre!r}"
        )

    def test_r40_tipo_id_beneficiario(self, ws_ge):
        """R40 debe contener el tipo de identificación del beneficiario final."""
        tipo = _cell(ws_ge, 40, 7)
        assert tipo is not None, "R40 C7 (tipo ID beneficiario) no debe estar vacío"
        assert "c.c" in tipo.lower() or "cc" in tipo.lower()

    # R10 → País y Departamento
    def test_r10_pais_y_departamento(self, ws_ge):
        """R10 debe contener el País (Colombia en C6) y Departamento (Antioquia en C9)."""
        pais = _cell(ws_ge, 10, 6)
        depto = _cell(ws_ge, 10, 9)
        assert pais == "Colombia", f"R10 C6 (país) debe ser Colombia, got: {pais!r}"
        assert depto == "Antioquia", f"R10 C9 (departamento) debe ser Antioquia, got: {depto!r}"

    # R24 → Junta Directiva
    def test_r24_junta_directiva(self, ws_ge):
        """R24 debe contener la identificación y datos de la junta directiva."""
        tipo_id = _cell(ws_ge, 24, 3)
        numero = _cell(ws_ge, 24, 4)
        nombre = _cell(ws_ge, 24, 5)
        apellidos = _cell(ws_ge, 24, 10)
        assert tipo_id == "C.C", f"R24 C3 (tipo id) debe ser C.C, got: {tipo_id!r}"
        assert numero == "98555384", f"R24 C4 (número id) debe ser 98555384, got: {numero!r}"
        assert nombre is not None and "guillermo" in nombre.lower(), f"R24 C5 (nombre) debe ser Guillermo, got: {nombre!r}"
        assert apellidos is not None and "cañón" in apellidos.lower() or "canon" in apellidos.lower(), f"R24 C10 (apellidos) debe ser Cañón Sarria, got: {apellidos!r}"

    # R32 / R40 → ID Completo y Porcentaje
    def test_r32_composicion_accionaria_completa(self, ws_ge):
        """R32 debe contener ID completo (C.C 98555384) y porcentaje de participación."""
        id_comp = _cell(ws_ge, 32, 7)
        pct = _cell(ws_ge, 32, 11)
        assert id_comp is not None and "98555384" in id_comp and "c.c" in id_comp.lower(), (
            f"R32 C7 debe contener C.C 98555384, got: {id_comp!r}"
        )
        assert pct in ("1", "1.0", "100", "100%", "100.00%"), (
            f"R32 C11 (porcentaje participación) debe ser 1 o 100%, got: {pct!r}"
        )

    def test_r40_beneficiarios_finales_completo(self, ws_ge):
        """R40 debe contener ID completo (C.C 98555384) y porcentaje de participación."""
        id_comp = _cell(ws_ge, 40, 7)
        pct = _cell(ws_ge, 40, 11)
        assert id_comp is not None and "98555384" in id_comp and "c.c" in id_comp.lower(), (
            f"R40 C7 debe contener C.C 98555384, got: {id_comp!r}"
        )
        assert pct in ("1", "1.0", "100", "100%", "100.00%"), (
            f"R40 C11 (porcentaje participación) debe ser 1 o 100%, got: {pct!r}"
        )

    # Aislamiento de roles: ninguna sección legal debe tener datos del contacto comercial
    def test_no_antonio_in_legal_sections(self, ws_ge):
        """ADR-0011 Q1: En ninguna fila de secciones legales debe aparecer 'Antonio'
        escrito por el pipeline.
        Nota: R11 (EMAIL / CONTACTO DE VERIFICACIÓN) es un campo pre-existente en el
        template original y se excluye porque no fue inyectado por AutoForm AI."""
        # Secciones legales están entre R1-R21 y R37+ (societario)
        # Excluimos R11 que es un contacto de verificación pre-cargado en el template GE.F.021
        PRE_EXISTING_ROWS = {11}
        for row in list(range(1, 22)) + list(range(37, 45)):
            if row in PRE_EXISTING_ROWS:
                continue
            for col in range(1, ws_ge.max_column + 1):
                val = _cell(ws_ge, row, col)
                if val and "antonio" in val.lower():
                    pytest.fail(
                        f"R{row} C{col}: 'Antonio' (contacto comercial) encontrado en sección legal: {val!r}"
                    )

