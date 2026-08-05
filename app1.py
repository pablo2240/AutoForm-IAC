import json
import os
import traceback
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import sys
import importlib

# Recargar módulos de core para asegurar que los cambios se reflejen en Streamlit sin reiniciar
for modulo in ["core.llm_client", "core.excel_parser", "core.excel_writer", "core.mapper", "core.pdf_processor"]:
    if modulo in sys.modules:
        importlib.reload(sys.modules[modulo])

from core import excel_parser, excel_writer, mapper
from core.llm_client import consultar_llm


def _manual_load_dotenv(dotenv_path: str = ".env"):
    path = Path(dotenv_path)
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            if "=" not in content:
                continue
            key, value = content.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

if load_dotenv is not None:
    load_dotenv()
else:
    _manual_load_dotenv()


def _safe_rerun():
    if hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()
        except Exception:
            pass

# 1. Configuración de pantalla
st.set_page_config(
    page_title="AutoForm AI — Carga de Documentos",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilo personalizado simple
st.markdown("""
    <style>
    .main-title { font-size: 2.2rem; color: #38bdf8; font-weight: 700; margin-bottom: 0.5rem; }
    .sub-title { font-size: 1.1rem; color: #94a3b8; margin-bottom: 2rem; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">📄 AutoForm AI</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Carga un formulario en Excel o PDF para rellenar automáticamente los datos corporativos.</div>', unsafe_allow_html=True)

# 2. Sidebar con información
with st.sidebar:
    st.header("⚙️ Estado del Sistema")
    st.success("Fase 3: Rellenado de Excel")
    st.info("Soporta: `.xlsx`, `.xls`. PDF en construcción.")

    st.markdown("---")
    with st.expander("💬 Probador de Agente", expanded=True):
        if "chat_messages" not in st.session_state:
            st.session_state["chat_messages"] = []

        if st.session_state["chat_messages"]:
            if st.button("🧹 Limpiar Chat", key="btn_clear_chat", use_container_width=True):
                st.session_state["chat_messages"] = []
                _safe_rerun()

        for message in st.session_state["chat_messages"]:
            role = message.get("role", "assistant")
            content = message.get("content", "")
            st.chat_message(role).write(content)

        user_prompt = st.chat_input("Escribe para probar el modelo...")
        if user_prompt:
            st.session_state["chat_messages"].append({"role": "user", "content": user_prompt})
            with st.spinner("Pensando..."):
                respuesta_llm = consultar_llm(user_prompt)
            # Limitar la respuesta del agente a 150 caracteres (truncado en el último espacio)
            MAX_CHARS = 150
            if len(respuesta_llm) > MAX_CHARS:
                corte = respuesta_llm[:MAX_CHARS].rfind(" ")
                respuesta_llm = respuesta_llm[: corte if corte > 0 else MAX_CHARS] + "…"
            st.session_state["chat_messages"].append({"role": "assistant", "content": respuesta_llm})
            _safe_rerun()

# 3. Cargar datos empresariales
datos_empresa = {}
ruta_config = os.path.join("config", "datos_empresa.json")
if os.path.exists(ruta_config):
    with open(ruta_config, "r", encoding="utf-8") as f:
        datos_empresa = json.load(f)


def _sanitizar_resultados(resultados):
    sanitizados = []
    for item in resultados:
        sanitizados.append(
            {
                "hoja": str(item.get("hoja", "")),
                "fila": int(item.get("fila", 0) or 0),
                "columna": int(item.get("columna", 0) or 0),
                "valor": str(item.get("valor", "")),
                "ubicacion": str(item.get("ubicacion", "")),
                "campo": str(item.get("campo", "")),
                "requiereMerge": bool(item.get("requiereMerge", False)),
                "celdasAMergear": int(item.get("celdasAMergear", 1) or 1),
            }
        )
    return sanitizados


# 4. Componente de Carga
uploaded_file = st.file_uploader(
    "Arrastra o selecciona el formulario de un tercero aquí",
    type=["xlsx", "xls", "pdf"],
    help="Sube un archivo Excel o PDF para iniciar la detección de campos.",
)

if uploaded_file is not None:
    file_name = uploaded_file.name
    file_type = file_name.split(".")[-1].lower()

    st.success(f"✅ Archivo cargado correctamente: **{file_name}**")

    col_preview, col_actions = st.columns([2, 1])

    with col_preview:
        st.subheader("👀 Previsualización del Documento")

        if file_type in ["xlsx", "xls"]:
            try:
                uploaded_file.seek(0)
                excel_file = pd.ExcelFile(uploaded_file)
                sheet_names = excel_file.sheet_names

                selected_sheet = st.selectbox("Selecciona la hoja a visualizar:", sheet_names)
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file, sheet_name=selected_sheet, header=None)

                st.dataframe(df, width="stretch", height=400)
            except Exception as e:
                st.error(f"Error al leer el archivo Excel: {e}")

        elif file_type == "pdf":
            st.warning("📄 Documento PDF detectado. Se procesará la estructura de capas de texto/vectores en la Fase 2.")
            st.json({
                "Nombre": file_name,
                "Tamaño (KB)": round(uploaded_file.size / 1024, 2),
                "Tipo": "PDF Document",
            })

    with col_actions:
        st.subheader("⚡ Procesamiento")
        st.write("Haz clic para extraer rótulos, detectar campos vacíos y rellenar con IA.")

        if st.button("🚀 Procesar Formulario"):
            if file_type in ["xlsx", "xls"]:
                if not os.getenv("GEMINI_API_KEY") and not os.getenv("OPENROUTER_API_KEY"):
                    st.error("Configura GEMINI_API_KEY u OPENROUTER_API_KEY en tu archivo .env")
                else:
                    progress_text = "Iniciando procesamiento..."
                    progress_bar = st.progress(0, text=progress_text)
                    try:
                        uploaded_file.seek(0)
                        archivo_bytes = uploaded_file.read()

                        # Paso 1: Carga
                        progress_bar.progress(20, text="📖 Leyendo y cargando el archivo Excel...")
                        libro = excel_parser.cargar_libro(BytesIO(archivo_bytes))
                        
                        # Paso 2: Estructura
                        progress_bar.progress(45, text="🔍 Analizando celdas vacías y estructura del formulario...")
                        mapa_formularios = excel_parser.escanear_mapa_formularios(libro)

                        # Paso 3: IA
                        progress_bar.progress(75, text="🤖 Consultando con la IA en OpenRouter para el mapeo...")
                        resultados = mapper.mapeo_formularios(mapa_formularios, datos_empresa)

                        # Paso 4: Escritura
                        progress_bar.progress(90, text="✍️ Escribiendo datos de la empresa y combinando celdas...")
                        if resultados:
                            resultados = _sanitizar_resultados(resultados)
                            df_resultado = pd.DataFrame.from_records(resultados)
                            df_resultado = df_resultado.astype(
                                {
                                    "hoja": "string",
                                    "fila": "Int64",
                                    "columna": "Int64",
                                    "valor": "string",
                                    "ubicacion": "string",
                                    "campo": "string",
                                    "requiereMerge": "boolean",
                                    "celdasAMergear": "Int64",
                                },
                                errors="ignore",
                            )
                            st.subheader("📍 Coordenadas de escritura para Fase 3")
                            st.dataframe(df_resultado, width="stretch")

                            bytes_relleno = excel_writer.rellenar_formulario_excel(archivo_bytes, resultados, datos_empresa)
                            progress_bar.progress(100, text="✅ ¡Proceso completado con éxito!")
                            st.success("Formulario completado correctamente")
                            st.download_button(
                                "📥 Descargar Formulario Rellenado (.xlsx)",
                                data=bytes_relleno,
                                file_name=f"{os.path.splitext(file_name)[0]}_diligenciado.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        else:
                            progress_bar.progress(100, text="⚠️ Proceso finalizado.")
                            st.info("No se encontraron campos compatibles para rellenar en este formulario.")
                    except Exception as e:
                        progress_bar.empty()
                        st.error(f"⚠️ Se produjo un error durante el procesamiento: {str(e)}")
                        with st.expander("Ver detalles técnicos del error"):
                            st.text(traceback.format_exc())
            else:
                st.warning("Soporte PDF en construcción. Solo Excel está disponible en esta fase.")
else:
    st.info("👆 Por favor, carga un archivo para continuar.")
