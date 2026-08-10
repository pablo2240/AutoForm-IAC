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

from core import excel_parser, excel_writer, mapper, profile_manager
from core.llm_client import consultar_llm
from core.mapper import get_debug_info as _get_debug_info


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
    elif hasattr(st, "rerun"):
        try:
            st.rerun()
        except Exception:
            pass


# 1. Configuración de pantalla con el Sistema de Diseño IAC
st.set_page_config(
    page_title="AutoForm AI | IAC Latam",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. Inyección del Sistema de Diseño Oficial de IAC (Vanilla CSS)
st.markdown("""
    <style>
    /* Google Fonts: Inter & Montserrat */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Montserrat:wght@600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #1E293B;
        background-color: #F8FAFC;
    }

    .stApp {
        background-color: #F8FAFC;
    }

    /* Header Institucional IAC */
    .iac-header {
        background: #121212;
        border-bottom: 4px solid #F8B126;
        padding: 1.25rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.75rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.12);
    }
    
    .iac-title {
        font-family: 'Montserrat', sans-serif;
        font-size: 1.8rem;
        font-weight: 800;
        color: #FFFFFF;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 0.6rem;
    }

    .iac-title span {
        color: #F8B126;
    }

    .iac-subtitle {
        font-size: 0.92rem;
        color: #94A3B8;
        margin-top: 0.2rem;
    }

    .iac-badge {
        background: #FEF3C7;
        color: #92400E;
        border: 1px solid #F8B126;
        padding: 0.35rem 0.85rem;
        border-radius: 20px;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.3px;
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
    }

    /* Tarjetas (Cards) estilo IAC */
    .iac-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #F8B126;
        border-radius: 10px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
        transition: all 0.2s ease-in-out;
    }

    .iac-card:hover {
        border-color: #F8B126;
        box-shadow: 0 6px 16px rgba(248, 177, 38, 0.15);
    }

    /* Encabezados H1, H2, H3 */
    h1, h2, h3 {
        font-family: 'Montserrat', sans-serif !important;
        color: #121212 !important;
        font-weight: 700 !important;
    }

    .stMarkdown h2, .stMarkdown h3 {
        border-bottom: 2px solid #F8B126;
        padding-bottom: 0.3rem;
        display: inline-block;
    }

    /* Botones Principales CTA (Naranja Corporativo #FF6B00) */
    .stButton > button[kind="primary"], div.stButton > button:first-child {
        background: linear-gradient(135deg, #FF6B00 0%, #E65100 100%) !important;
        color: #FFFFFF !important;
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.65rem 1.75rem !important;
        box-shadow: 0 4px 14px rgba(255, 107, 0, 0.3) !important;
        transition: all 0.2s ease !important;
    }

    .stButton > button[kind="primary"]:hover, div.stButton > button:first-child:hover {
        background: linear-gradient(135deg, #E65100 0%, #C74300 100%) !important;
        box-shadow: 0 6px 18px rgba(255, 107, 0, 0.45) !important;
        transform: translateY(-1px);
    }

    /* Botones de Descargar (CTA Naranja) */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #FF6B00 0%, #E65100 100%) !important;
        color: #FFFFFF !important;
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.75rem 2rem !important;
        box-shadow: 0 4px 14px rgba(255, 107, 0, 0.35) !important;
        width: 100%;
    }

    .stDownloadButton > button:hover {
        background: linear-gradient(135deg, #E65100 0%, #C74300 100%) !important;
        box-shadow: 0 6px 18px rgba(255, 107, 0, 0.5) !important;
    }

    /* Botón Secundario (Borde Amarillo IAC) */
    .btn-secondary button {
        background: #FFFFFF !important;
        color: #121212 !important;
        border: 1.5px solid #F8B126 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }

    .btn-secondary button:hover {
        background: #FFFBEB !important;
        border-color: #FF6B00 !important;
    }

    /* File Uploader Estilizado con borde Amarillo IAC */
    [data-testid="stFileUploader"] {
        background: #FFFFFF;
        border: 2px dashed #F8B126;
        border-radius: 10px;
        padding: 1rem;
        transition: all 0.2s ease;
    }

    [data-testid="stFileUploader"]:hover {
        border-color: #FF6B00;
        background-color: #FFFDF5;
    }

    /* Tarjetas de Métricas */
    [data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-top: 4px solid #F8B126;
        border-radius: 8px;
        padding: 0.85rem 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }

    [data-testid="stMetricLabel"] {
        color: #64748B !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
    }

    [data-testid="stMetricValue"] {
        color: #121212 !important;
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
    }

    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E2E8F0;
    }

    /* Progress bar */
    .stProgress > div > div > div > div {
        background-color: #FF6B00 !important;
    }

    /* Tablas Dataframe */
    .stDataFrame {
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        overflow: hidden;
    }
    </style>
""", unsafe_allow_html=True)

# 3. Header Hero Institucional
st.markdown("""
    <div class="iac-header">
        <div>
            <h1 class="iac-title">⚡ AutoForm <span>AI</span></h1>
            <div class="iac-subtitle">Plataforma Inteligente de Diligenciamiento de Formularios Oficiales — IAC Latam</div>
        </div>
        <div class="iac-badge">
            <span>●</span> MOTOR GEMINI 2.0 FLASH ACTIVE
        </div>
    </div>
""", unsafe_allow_html=True)

# 4. Sidebar Corporativa
with st.sidebar:
    st.markdown("### 🏢 **IAC Latam**")
    st.caption("Ingeniería Asistida en Computadora")
    st.markdown("---")

    # 🏢 Fase 2: Gestión de Perfiles Empresariales (Multi-Perfil)
    st.markdown("### 🪪 **Perfil Empresarial Activo**")
    dict_perfiles = profile_manager.listar_perfiles()
    nombres_perfiles = list(dict_perfiles.keys())

    if "perfil_activo_nombre" not in st.session_state or st.session_state["perfil_activo_nombre"] not in dict_perfiles:
        st.session_state["perfil_activo_nombre"] = nombres_perfiles[0] if nombres_perfiles else "🏢 Principal (IAC Latam)"

    perfil_seleccionado_etiqueta = st.selectbox(
        "Seleccionar Perfil:",
        options=nombres_perfiles,
        index=nombres_perfiles.index(st.session_state["perfil_activo_nombre"]) if st.session_state["perfil_activo_nombre"] in nombres_perfiles else 0,
        help="Los datos de este perfil se usarán para diligenciar los formularios automáticamente."
    )
    st.session_state["perfil_activo_nombre"] = perfil_seleccionado_etiqueta
    ruta_perfil_activo = dict_perfiles[perfil_seleccionado_etiqueta]
    datos_empresa = profile_manager.cargar_perfil(ruta_perfil_activo)

    # ✏️ Editor Visual de Datos del Perfil Activo
    with st.expander("✏️ Editar Datos de Empresa", expanded=False):
        tab_id, tab_ub, tab_bn = st.tabs(["🪪 ID", "📍 Contacto", "🏦 Banco"])
        
        with tab_id:
            razon_social = st.text_input("Razón Social", value=datos_empresa.get("razon_social", ""))
            nit = st.text_input("NIT", value=datos_empresa.get("nit", ""))
            representante_legal = st.text_input("Representante Legal", value=datos_empresa.get("representante_legal", ""))
            cedula = st.text_input("Cédula Representante", value=datos_empresa.get("cedula", ""))
            rep_nombres = st.text_input("Nombres Rep.", value=datos_empresa.get("representante_nombres", ""))
            rep_apellidos = st.text_input("Apellidos Rep.", value=datos_empresa.get("representante_apellidos", ""))

        with tab_ub:
            direccion = st.text_input("Dirección Principal", value=datos_empresa.get("direccion", ""))
            ciudad = st.text_input("Ciudad", value=datos_empresa.get("ciudad", ""))
            departamento = st.text_input("Departamento", value=datos_empresa.get("departamento", ""))
            pais = st.text_input("País", value=datos_empresa.get("pais", "Colombia"))
            telefono = st.text_input("Teléfono", value=datos_empresa.get("telefono", ""))
            correo = st.text_input("Correo Electrónico", value=datos_empresa.get("correo", ""))
            pagina_web = st.text_input("Página Web", value=datos_empresa.get("pagina_web", ""))

        with tab_bn:
            banco = st.text_input("Banco", value=datos_empresa.get("banco", ""))
            numero_cuenta = st.text_input("Número de Cuenta", value=datos_empresa.get("numero_cuenta", ""))
            
            tipo_cta_actual = str(datos_empresa.get("tipo_cuenta", "AHORROS")).upper()
            idx_tipo = 0 if "AHORRO" in tipo_cta_actual else (1 if "CORRIENTE" in tipo_cta_actual else 2)
            tipo_cuenta = st.selectbox("Tipo de Cuenta", options=["AHORROS", "CORRIENTE", "OTRO"], index=idx_tipo)
            sucursal = st.text_input("Sucursal Bancaria", value=datos_empresa.get("sucursal", ""))

        if st.button("💾 Guardar Perfil Empresarial", key="btn_guardar_perfil", use_container_width=True):
            datos_actualizados = {
                "razon_social": razon_social,
                "nit": nit,
                "direccion": direccion,
                "telefono": telefono,
                "correo": correo,
                "cedula": cedula,
                "ciudad": ciudad,
                "departamento": departamento,
                "pagina_web": pagina_web,
                "representante_legal": representante_legal,
                "representante_nombres": rep_nombres,
                "representante_apellidos": rep_apellidos,
                "pais": pais,
                "banco": banco,
                "numero_cuenta": numero_cuenta,
                "tipo_cuenta": tipo_cuenta,
                "sucursal": sucursal,
            }
            if profile_manager.guardar_perfil(ruta_perfil_activo, datos_actualizados):
                st.success("✅ ¡Datos del perfil guardados!")
                datos_empresa = datos_actualizados
                _safe_rerun()

    with st.expander("➕ Crear Nuevo Perfil", expanded=False):
        nuevo_nombre = st.text_input("Nombre del Nuevo Perfil", placeholder="Ej: IAC Sucursal Bogotá")
        if st.button("Crear Perfil", key="btn_crear_perfil", use_container_width=True):
            if nuevo_nombre.strip():
                exito, nueva_ruta, nueva_etiqueta = profile_manager.crear_nuevo_perfil(nuevo_nombre, datos_empresa)
                if exito:
                    st.session_state["perfil_activo_nombre"] = nueva_etiqueta
                    st.success(f"✅ Perfil creado: {nueva_etiqueta}")
                    _safe_rerun()

    st.markdown("---")
    
    with st.expander("💬 Probador de Agente", expanded=False):
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

        user_prompt = st.chat_input("Probar razonamiento del modelo...")
        if user_prompt:
            st.session_state["chat_messages"].append({"role": "user", "content": user_prompt})
            st.chat_message("user").write(user_prompt)
            
            with st.spinner("Consultando modelo..."):
                respuesta_llm = consultar_llm(user_prompt)
            
            MAX_CHARS = 150
            if len(respuesta_llm) > MAX_CHARS:
                corte = respuesta_llm[:MAX_CHARS].rfind(" ")
                respuesta_llm = respuesta_llm[: corte if corte > 0 else MAX_CHARS] + "…"
                
            st.session_state["chat_messages"].append({"role": "assistant", "content": respuesta_llm})
            st.chat_message("assistant").write(respuesta_llm)
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


# 6. Zona de Carga Principal
st.markdown("### 📥 1. Cargar Formulario de Terceros")

uploaded_file = st.file_uploader(
    "Arrastra y suelta tu archivo Excel (.xlsx, .xls) o PDF aquí",
    type=["xlsx", "xls", "pdf"],
    help="Sube la plantilla de licitación o formulario del proveedor para iniciar el diligenciamiento automático.",
)

if uploaded_file is not None:
    file_name = uploaded_file.name
    file_type = file_name.split(".")[-1].lower()

    st.markdown(f"""
        <div style="background: #ECFDF5; border: 1px solid #10B981; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.25rem; color: #065F46; font-weight: 600; font-size: 0.92rem;">
            ✅ Archivo listo para procesar: <strong>{file_name}</strong> ({(uploaded_file.size/1024):.1f} KB)
        </div>
    """, unsafe_allow_html=True)

    col_preview, col_actions = st.columns([2, 1], gap="medium")

    with col_preview:
        st.markdown("### 👀 Previsualización de Hojas")

        if file_type in ["xlsx", "xls"]:
            try:
                uploaded_file.seek(0)
                excel_file = pd.ExcelFile(uploaded_file)
                sheet_names = excel_file.sheet_names

                selected_sheet = st.selectbox("Seleccionar Hoja:", sheet_names)
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file, sheet_name=selected_sheet, header=None)

                st.dataframe(df, width="stretch", height=380)
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
        st.markdown("### ⚡ Ejecutar IA")
        st.write("Extrae rótulos visuales, analiza campos vacíos e inyecta los datos de la empresa respetando estilos.")

        if st.button("🚀 Procesar Formulario", type="primary", use_container_width=True):
            if file_type in ["xlsx", "xls"]:
                if not os.getenv("GEMINI_API_KEY") and not os.getenv("OPENROUTER_API_KEY"):
                    st.error("Configura GEMINI_API_KEY u OPENROUTER_API_KEY en tu archivo .env")
                else:
                    progress_bar = st.progress(0, text="Iniciando motor de IA...")
                    try:
                        uploaded_file.seek(0)
                        archivo_bytes = uploaded_file.read()

                        # Paso 1: Carga
                        progress_bar.progress(20, text="📖 Leyendo estructura espacial del libro Excel...")
                        libro = excel_parser.cargar_libro(BytesIO(archivo_bytes))
                        
                        # Paso 2: Estructura
                        progress_bar.progress(45, text="🔍 Analizando celdas vacías y líneas de captura...")
                        mapa_formularios = excel_parser.escanear_mapa_formularios(libro)

                        # Paso 3: IA
                        progress_bar.progress(75, text="🤖 Invocando Gemini 2.0 Flash para mapeo semántico...")
                        resultados = mapper.mapeo_formularios(mapa_formularios, datos_empresa)

                        # LLM-04: Detectar caché
                        mapa_purgado_ui = mapper._purgar_mapa(mapa_formularios)
                        form_hash_ui = mapper._hash_mapa(mapa_purgado_ui)
                        debug_info = _get_debug_info(form_hash_ui)

                        # Paso 4: Escritura
                        progress_bar.progress(90, text="✍️ Inyectando datos y preservando fuentes/colores...")
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

                            bytes_relleno = excel_writer.rellenar_formulario_excel(archivo_bytes, resultados, datos_empresa)
                            progress_bar.progress(100, text="✅ ¡Proceso completado exitosamente!")

                            if debug_info and debug_info.get("tipo_cache") == "SEMANTIC_FUZZY_HIT":
                                score_fuzzy = debug_info.get("score_similaridad", 95.0)
                                st.markdown(f"""
                                    <div style="background: #EFF6FF; border-left: 4px solid #3B82F6; padding: 0.75rem 1rem; border-radius: 6px; margin: 0.5rem 0; color: #1E40AF; font-weight: 600; font-size: 0.88rem;">
                                        ⚡ <strong>Caché Semántico HIT ({score_fuzzy:.1f}% Similitud)</strong> — Mapeado inteligente adaptado en &lt; 0.05s ($0 consumo de API).
                                    </div>
                                """, unsafe_allow_html=True)

                            st.markdown("""
                                <div style="background: #FEF3C7; border-left: 4px solid #F8B126; padding: 0.85rem 1rem; border-radius: 6px; margin: 1rem 0;">
                                    <strong style="color: #92400E;">🎉 Formulario Diligenciado Correctamente</strong>
                                    <div style="font-size: 0.85rem; color: #78350F;">Se inyectaron los datos respetando colores, bordes y fuentes originales.</div>
                                </div>
                            """, unsafe_allow_html=True)

                            st.download_button(
                                "📥 Descargar Formulario Rellenado (.xlsx)",
                                data=bytes_relleno,
                                file_name=f"{os.path.splitext(file_name)[0]}_diligenciado.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )

                            st.markdown("### 📍 Coordenadas Inyectadas")
                            st.dataframe(df_resultado, width="stretch", height=250)

                            # ── LLM-05: Panel de Debug ────────────────────────────────────────
                            if debug_info:
                                with st.expander("🔍 Panel de Debug — Mapeo Semántico IA", expanded=False):
                                    c1, c2, c3, c4 = st.columns(4)
                                    c1.metric("📝 Rótulos Enviados", debug_info["rotulos_enviados"])
                                    c2.metric("✅ Campos Mapeados", debug_info["campos_mapeados"])
                                    faltantes_list = debug_info.get("campos_faltantes_detectados", [])
                                    c3.metric("⚠️ Campos Faltantes", len(faltantes_list))
                                    c4.metric("🔑 Hash Formulario", debug_info["hash"][:10] + "...")

                                    if faltantes_list:
                                        st.warning(f"🚫 Campos omitidos o no encontrados: `{'`, `'.join(faltantes_list)}`")

                                    tab_payload, tab_response = st.tabs(["📤 Payload Enviado", "📥 Respuesta RAW LLM"])
                                    
                                    with tab_payload:
                                        try:
                                            payload_dict = json.loads(debug_info["prompt_payload"])
                                            st.json(payload_dict)
                                        except Exception:
                                            st.code(debug_info["prompt_payload"], language="json")

                                    with tab_response:
                                        try:
                                            respuesta_dict = json.loads(debug_info["respuesta_llm"])
                                            st.json(respuesta_dict)
                                        except Exception:
                                            st.code(debug_info["respuesta_llm"], language="json")
                            # ─────────────────────────────────────────────────────────────────────
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
    st.info("👆 Por favor, carga un archivo para comenzar.")

