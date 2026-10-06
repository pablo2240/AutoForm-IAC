"""Base de conocimiento de referencias (SQLite).

Cada conocimiento guarda el documento del que procede (``doc_id``), de modo que borrar o
actualizar un documento elimina o reemplaza exactamente lo que aportó. La base es derivada de
la carpeta de referencias: puede borrarse y reconstruirse sin perder información.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from reference_library.extractor import CampoReferencia
from reference_library.settings import ruta_base_conocimiento


_ESQUEMA = (
    """
    CREATE TABLE IF NOT EXISTS ref_documentos (
        doc_id TEXT PRIMARY KEY,
        ruta TEXT NOT NULL,
        nombre TEXT NOT NULL,
        familia TEXT NOT NULL DEFAULT '',
        tipo_documento TEXT NOT NULL DEFAULT 'excel',
        hash_contenido TEXT NOT NULL,
        huella_datos TEXT NOT NULL DEFAULT '',
        fuente TEXT NOT NULL DEFAULT 'referencia',
        confianza REAL NOT NULL DEFAULT 0.75,
        estado TEXT NOT NULL DEFAULT 'ok',
        error TEXT NOT NULL DEFAULT '',
        origen TEXT NOT NULL DEFAULT 'local',
        version_extractor TEXT NOT NULL DEFAULT '',
        plantilla_id TEXT,
        estructura_json TEXT NOT NULL DEFAULT '{}',
        total_campos INTEGER NOT NULL DEFAULT 0,
        creado_en TEXT NOT NULL,
        actualizado_en TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ref_campos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT NOT NULL REFERENCES ref_documentos(doc_id) ON DELETE CASCADE,
        hoja TEXT NOT NULL DEFAULT '',
        fila INTEGER NOT NULL DEFAULT 0,
        columna INTEGER NOT NULL DEFAULT 0,
        coordenada TEXT NOT NULL DEFAULT '',
        etiqueta TEXT NOT NULL,
        etiqueta_norm TEXT NOT NULL,
        seccion TEXT NOT NULL DEFAULT '',
        contexto_fila TEXT NOT NULL DEFAULT '',
        tipo_elemento TEXT NOT NULL DEFAULT '',
        ubicacion TEXT NOT NULL DEFAULT '',
        ejemplo_valor TEXT NOT NULL DEFAULT '',
        campo_maestro TEXT,
        fuente_campo TEXT NOT NULL DEFAULT '',
        confianza REAL NOT NULL DEFAULT 0,
        vecinos_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ref_campos_doc ON ref_campos (doc_id)",
    "CREATE INDEX IF NOT EXISTS idx_ref_campos_maestro ON ref_campos (campo_maestro)",
    "CREATE INDEX IF NOT EXISTS idx_ref_campos_etiqueta ON ref_campos (etiqueta_norm)",
    """
    CREATE TABLE IF NOT EXISTS ref_vectores (
        campo_id INTEGER NOT NULL REFERENCES ref_campos(id) ON DELETE CASCADE,
        modelo TEXT NOT NULL,
        dim INTEGER NOT NULL,
        vector BLOB NOT NULL,
        PRIMARY KEY (campo_id, modelo)
    )
    """,
)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DocumentoReferencia:
    """Metadatos de un documento indexado."""

    doc_id: str
    ruta: str
    nombre: str
    familia: str
    tipo_documento: str
    hash_contenido: str
    huella_datos: str
    fuente: str
    confianza: float
    estado: str
    error: str
    origen: str
    version_extractor: str
    plantilla_id: Optional[str]
    estructura: Dict[str, Any]
    total_campos: int
    creado_en: str
    actualizado_en: str


def _a_documento(fila: sqlite3.Row) -> DocumentoReferencia:
    return DocumentoReferencia(
        doc_id=fila["doc_id"],
        ruta=fila["ruta"],
        nombre=fila["nombre"],
        familia=fila["familia"],
        tipo_documento=fila["tipo_documento"],
        hash_contenido=fila["hash_contenido"],
        huella_datos=fila["huella_datos"],
        fuente=fila["fuente"],
        confianza=float(fila["confianza"]),
        estado=fila["estado"],
        error=fila["error"],
        origen=fila["origen"],
        version_extractor=fila["version_extractor"],
        plantilla_id=fila["plantilla_id"],
        estructura=json.loads(fila["estructura_json"] or "{}"),
        total_campos=int(fila["total_campos"]),
        creado_en=fila["creado_en"],
        actualizado_en=fila["actualizado_en"],
    )


class ReferenceStore:
    """Acceso a la base de conocimiento de referencias."""

    def __init__(self, ruta_db: Optional[Path] = None) -> None:
        self.ruta_db = Path(ruta_db) if ruta_db else ruta_base_conocimiento()
        self.ruta_db.parent.mkdir(parents=True, exist_ok=True)
        with self._conexion() as conn:
            for sentencia in _ESQUEMA:
                conn.execute(sentencia)
            columnas = {f["name"] for f in conn.execute("PRAGMA table_info(ref_documentos)").fetchall()}
            if "origen" not in columnas:  # bases creadas antes de la persistencia en la nube
                conn.execute("ALTER TABLE ref_documentos ADD COLUMN origen TEXT NOT NULL DEFAULT 'local'")

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.ruta_db), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ── Escritura ────────────────────────────────────────────────────────

    def reemplazar_documento(
        self,
        doc_id: str,
        ruta: str,
        nombre: str,
        familia: str,
        hash_contenido: str,
        huella_datos: str,
        fuente: str,
        confianza: float,
        version_extractor: str,
        plantilla_id: Optional[str],
        estructura: Dict[str, Any],
        campos: List[CampoReferencia],
        origen: str = "local",
    ) -> None:
        """Inserta o reemplaza, en una sola transacción, un documento y todo su conocimiento."""
        ahora = _ahora()
        with self._conexion() as conn:
            previo = conn.execute("SELECT creado_en FROM ref_documentos WHERE doc_id = ?", (doc_id,)).fetchone()
            conn.execute("DELETE FROM ref_documentos WHERE doc_id = ?", (doc_id,))
            conn.execute(
                """
                INSERT INTO ref_documentos (doc_id, ruta, nombre, familia, tipo_documento, hash_contenido,
                    huella_datos, fuente, confianza, estado, error, origen, version_extractor, plantilla_id,
                    estructura_json, total_campos, creado_en, actualizado_en)
                VALUES (?, ?, ?, ?, 'excel', ?, ?, ?, ?, 'ok', '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id, ruta, nombre, familia, hash_contenido, huella_datos, fuente, confianza,
                    origen, version_extractor, plantilla_id, json.dumps(estructura, ensure_ascii=False),
                    len(campos), previo["creado_en"] if previo else ahora, ahora,
                ),
            )
            conn.executemany(
                """
                INSERT INTO ref_campos (doc_id, hoja, fila, columna, coordenada, etiqueta, etiqueta_norm,
                    seccion, contexto_fila, tipo_elemento, ubicacion, ejemplo_valor, campo_maestro,
                    fuente_campo, confianza, vecinos_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        doc_id, c.hoja, c.fila, c.columna, c.coordenada, c.etiqueta, c.etiqueta_norm, c.seccion,
                        c.contexto_fila, c.tipo_elemento, c.ubicacion, c.ejemplo_valor, c.campo_maestro,
                        c.fuente_campo, c.confianza, json.dumps(c.vecinos, ensure_ascii=False),
                    )
                    for c in campos
                ],
            )

    def registrar_error(
        self,
        doc_id: str,
        ruta: str,
        nombre: str,
        familia: str,
        hash_contenido: str,
        huella_datos: str,
        version_extractor: str,
        error: str,
        origen: str = "local",
    ) -> None:
        """Deja constancia de un documento que no pudo procesarse, sin conocimiento asociado."""
        ahora = _ahora()
        with self._conexion() as conn:
            previo = conn.execute("SELECT creado_en FROM ref_documentos WHERE doc_id = ?", (doc_id,)).fetchone()
            conn.execute("DELETE FROM ref_documentos WHERE doc_id = ?", (doc_id,))
            conn.execute(
                """
                INSERT INTO ref_documentos (doc_id, ruta, nombre, familia, hash_contenido, huella_datos,
                    estado, error, origen, version_extractor, creado_en, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?, 'error', ?, ?, ?, ?, ?)
                """,
                (doc_id, ruta, nombre, familia, hash_contenido, huella_datos, error[:500], origen, version_extractor,
                 previo["creado_en"] if previo else ahora, ahora),
            )

    def eliminar_documento(self, doc_id: str) -> bool:
        """Elimina un documento y, en cascada, todo el conocimiento que aportó."""
        with self._conexion() as conn:
            return conn.execute("DELETE FROM ref_documentos WHERE doc_id = ?", (doc_id,)).rowcount > 0

    # ── Lectura ──────────────────────────────────────────────────────────

    def obtener_documento(self, doc_id: str) -> Optional[DocumentoReferencia]:
        with self._conexion() as conn:
            fila = conn.execute("SELECT * FROM ref_documentos WHERE doc_id = ?", (doc_id,)).fetchone()
        return _a_documento(fila) if fila else None

    def listar_documentos(self, origen: Optional[str] = None) -> List[DocumentoReferencia]:
        with self._conexion() as conn:
            if origen:
                filas = conn.execute(
                    "SELECT * FROM ref_documentos WHERE origen = ? ORDER BY familia, nombre", (origen,)
                ).fetchall()
            else:
                filas = conn.execute("SELECT * FROM ref_documentos ORDER BY familia, nombre").fetchall()
        return [_a_documento(f) for f in filas]

    def listar_campos(
        self,
        doc_id: Optional[str] = None,
        solo_con_campo_maestro: bool = False,
    ) -> List[Dict[str, Any]]:
        """Conocimiento a nivel de rótulo, siempre con el documento del que procede."""
        consulta = """
            SELECT c.*, d.nombre AS documento, d.familia AS familia, d.fuente AS fuente_documento,
                   d.confianza AS confianza_documento
            FROM ref_campos c JOIN ref_documentos d ON d.doc_id = c.doc_id
            WHERE 1 = 1
        """
        parametros: List[Any] = []
        if doc_id:
            consulta += " AND c.doc_id = ?"
            parametros.append(doc_id)
        if solo_con_campo_maestro:
            consulta += " AND c.campo_maestro IS NOT NULL"
        consulta += " ORDER BY c.doc_id, c.hoja, c.fila, c.columna"
        with self._conexion() as conn:
            filas = conn.execute(consulta, parametros).fetchall()
        resultado = []
        for fila in filas:
            registro = dict(fila)
            registro["vecinos"] = json.loads(registro.pop("vecinos_json") or "[]")
            resultado.append(registro)
        return resultado

    def estadisticas(self) -> Dict[str, Any]:
        with self._conexion() as conn:
            documentos = conn.execute("SELECT COUNT(*) AS n FROM ref_documentos").fetchone()["n"]
            con_error = conn.execute("SELECT COUNT(*) AS n FROM ref_documentos WHERE estado = 'error'").fetchone()["n"]
            campos = conn.execute("SELECT COUNT(*) AS n FROM ref_campos").fetchone()["n"]
            mapeados = conn.execute("SELECT COUNT(*) AS n FROM ref_campos WHERE campo_maestro IS NOT NULL").fetchone()["n"]
            familias = [
                f["familia"] for f in conn.execute(
                    "SELECT DISTINCT familia FROM ref_documentos WHERE familia != '' ORDER BY familia"
                ).fetchall()
            ]
        return {
            "documentos": documentos,
            "documentos_con_error": con_error,
            "campos": campos,
            "campos_con_campo_maestro": mapeados,
            "familias": familias,
        }

    # ── Vectores (embeddings) ────────────────────────────────────────────

    def campos_sin_vector(self, modelo: str) -> List[Dict[str, Any]]:
        """Rótulos que todavía no tienen embedding generado con ``modelo``."""
        with self._conexion() as conn:
            filas = conn.execute(
                """
                SELECT c.id, c.etiqueta, c.seccion, c.campo_maestro
                FROM ref_campos c
                LEFT JOIN ref_vectores v ON v.campo_id = c.id AND v.modelo = ?
                WHERE v.campo_id IS NULL
                """,
                (modelo,),
            ).fetchall()
        return [dict(f) for f in filas]

    def guardar_vectores(self, modelo: str, vectores: Sequence[Tuple[int, np.ndarray]]) -> None:
        with self._conexion() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO ref_vectores (campo_id, modelo, dim, vector) VALUES (?, ?, ?, ?)",
                [
                    (int(campo_id), modelo, int(vector.shape[0]), np.asarray(vector, dtype=np.float32).tobytes())
                    for campo_id, vector in vectores
                ],
            )

    def cargar_vectores(self, modelo: str) -> Tuple[np.ndarray, np.ndarray]:
        """Todos los vectores del modelo como (ids, matriz); matriz vacía si no hay ninguno."""
        with self._conexion() as conn:
            filas = conn.execute(
                "SELECT campo_id, dim, vector FROM ref_vectores WHERE modelo = ? ORDER BY campo_id", (modelo,)
            ).fetchall()
        if not filas:
            return np.zeros(0, dtype=np.int64), np.zeros((0, 1), dtype=np.float32)
        ids = np.array([f["campo_id"] for f in filas], dtype=np.int64)
        matriz = np.vstack([np.frombuffer(f["vector"], dtype=np.float32) for f in filas])
        return ids, matriz

    def obtener_campos(self, ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
        """Conocimiento completo (con su documento de origen) de los ids pedidos."""
        if not ids:
            return {}
        marcadores = ",".join("?" for _ in ids)
        with self._conexion() as conn:
            filas = conn.execute(
                f"""
                SELECT c.*, d.nombre AS documento, d.familia AS familia, d.fuente AS fuente_documento,
                       d.confianza AS confianza_documento
                FROM ref_campos c JOIN ref_documentos d ON d.doc_id = c.doc_id
                WHERE c.id IN ({marcadores})
                """,
                [int(i) for i in ids],
            ).fetchall()
        resultado: Dict[int, Dict[str, Any]] = {}
        for fila in filas:
            registro = dict(fila)
            registro["vecinos"] = json.loads(registro.pop("vecinos_json") or "[]")
            resultado[int(registro["id"])] = registro
        return resultado

    def huella_conocimiento(self) -> str:
        """Cambia cuando se agregan, actualizan o eliminan documentos; invalida el índice en memoria."""
        with self._conexion() as conn:
            fila = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(actualizado_en), '') AS ultimo FROM ref_documentos"
            ).fetchone()
            campos = conn.execute("SELECT COUNT(*) AS n FROM ref_campos").fetchone()["n"]
        return f"{fila['n']}:{campos}:{fila['ultimo']}"
