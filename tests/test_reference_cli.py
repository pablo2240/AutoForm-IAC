"""Administración por línea de comandos de la biblioteca de referencias."""

from __future__ import annotations

from pathlib import Path

import pytest

from reference_library.__main__ import main
from referencias_helpers import _diligenciado


@pytest.fixture(autouse=True)
def _entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOFORM_REFERENCES_DIR", str(tmp_path / "referencias"))
    monkeypatch.setenv("AUTOFORM_REFERENCES_DB", str(tmp_path / "referencias.db"))
    monkeypatch.setenv("AUTOFORM_EMBEDDING_PROVIDER", "hash")
    (tmp_path / "referencias").mkdir()


def test_ciclo_completo_agregar_buscar_listar_y_eliminar(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    origen = tmp_path / "Formulario_Completo.xlsx"
    origen.write_bytes(_diligenciado())

    assert main(["add", str(origen), "--familia", "proveedor"]) == 0
    assert (tmp_path / "referencias" / "proveedor" / "Formulario_Completo.xlsx").exists()

    capsys.readouterr()
    assert main(["list"]) == 0
    listado = capsys.readouterr().out
    assert "Formulario_Completo.xlsx" in listado and "proveedor" in listado

    assert main(["search", "NIT", "--top-k", "3"]) == 0
    assert "nit" in capsys.readouterr().out

    assert main(["remove", "Formulario_Completo"]) == 0
    assert not (tmp_path / "referencias" / "proveedor" / "Formulario_Completo.xlsx").exists()


def test_sync_reporta_y_remove_de_un_documento_inexistente_falla(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    (tmp_path / "referencias" / "uno.xlsx").write_bytes(_diligenciado())

    assert main(["sync"]) == 0
    assert "1 agregados" in capsys.readouterr().out
    assert main(["remove", "no-existe"]) == 1
