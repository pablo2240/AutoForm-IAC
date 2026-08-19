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

from core import excel_parser, excel_writer, mapper, profile_manager, pdf_processor, llm_client
from core import pdf_vision
from core.mapper import get_debug_info as _get_debug_info

# ── IMPORTS DE LIBRERÍAS DE UI AVANZADA (NIVEL 3) ──────────────────────────
try:
    from streamlit_option_menu import option_menu
except ImportError:
    option_menu = None

try:
    from streamlit_lottie import st_lottie
except ImportError:
    st_lottie = None

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
except ImportError:
    AgGrid = None

try:
    from streamlit_extras.add_vertical_space import add_vertical_space
except ImportError:
    add_vertical_space = None


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

# 2. Inyección del Sistema de Diseño Oficial de IAC (Vanilla CSS - Opción A)
st.markdown("""
    <style>
    /* Google Fonts: Inter & Montserrat */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Montserrat:wght@600;700;800&display=swap');

    :root {
        /* Sistema 60-30-10 */
        --bg-app: #F8FAFC;
        --bg-surface: #FFFFFF;
        --brand-black: #121212;
        --brand-yellow: #F8B126;
        --accent-orange: #FF6B00;
        --accent-orange-hover: #E65100;
        --accent-green: #10B981;
        --accent-blue: #3B82F6;
        
        /* Neutros & Textos */
        --text-main: #1E293B;
        --text-muted: #64748B;
        --border-color: #E2E8F0;
        
        /* Elevación & Radios */
        --radius-card: 10px;
        --radius-btn: 8px;
        --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.04);
        --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.05);
        --shadow-hover: 0 8px 24px rgba(248, 177, 38, 0.18);
        --transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: var(--text-main);
        background-color: var(--bg-app);
    }

    .stApp {
        background-color: var(--bg-app);
    }

    /* Header Institucional IAC */
    .iac-header {
        background: var(--brand-black);
        border-bottom: 4px solid var(--brand-yellow);
        padding: 1.25rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.75rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        transition: var(--transition);
    }

    @media (max-width: 768px) {
        .iac-header {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.85rem;
            padding: 1rem 1.25rem;
        }
    }
    
    .iac-title {
        font-family: 'Montserrat', sans-serif;
        font-size: 1.85rem;
        font-weight: 800;
        color: #FFFFFF;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 0.6rem;
        letter-spacing: -0.5px;
    }

    .iac-title span {
        color: var(--brand-yellow);
    }

    .iac-subtitle {
        font-size: 0.92rem;
        color: #94A3B8;
        margin-top: 0.2rem;
    }

    .iac-badge {
        background: #FEF3C7;
        color: #92400E;
        border: 1px solid var(--brand-yellow);
        padding: 0.38rem 0.9rem;
        border-radius: 20px;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.4px;
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        box-shadow: 0 2px 6px rgba(248, 177, 38, 0.12);
    }

    /* Tarjetas (Cards) estilo IAC */
    .iac-card {
        background: var(--bg-surface);
        border: 1px solid var(--border-color);
        border-left: 4px solid var(--brand-yellow);
        border-radius: var(--radius-card);
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.25rem;
        box-shadow: var(--shadow-sm);
        transition: var(--transition);
    }

    .iac-card:hover {
        border-color: var(--brand-yellow);
        box-shadow: var(--shadow-hover);
        transform: translateY(-2px);
    }

    /* Banners de Estado y Alertas Reutilizables */
    .iac-alert {
        padding: 0.85rem 1.15rem;
        border-radius: 8px;
        margin: 0.85rem 0;
        font-size: 0.9rem;
        font-weight: 600;
        line-height: 1.5;
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .iac-alert-success {
        background: #ECFDF5;
        border: 1px solid #10B981;
        border-left: 4px solid #10B981;
        color: #065F46;
    }

    .iac-alert-cache {
        background: #EFF6FF;
        border: 1px solid #3B82F6;
        border-left: 4px solid #3B82F6;
        color: #1E40AF;
    }

    .iac-alert-warning {
        background: #FEF3C7;
        border: 1px solid var(--brand-yellow);
        border-left: 4px solid var(--brand-yellow);
        color: #92400E;
    }

    /* Encabezados H1, H2, H3 */
    h1, h2, h3 {
        font-family: 'Montserrat', sans-serif !important;
        color: var(--brand-black) !important;
        font-weight: 700 !important;
    }

    .iac-section-title {
        font-family: 'Montserrat', sans-serif;
        font-size: 1.35rem;
        font-weight: 700;
        color: var(--brand-black);
        border-bottom: 2px solid var(--brand-yellow);
        padding-bottom: 0.35rem;
        margin-bottom: 1rem;
        display: inline-block;
    }

    /* Botones Principales CTA (Naranja Corporativo #FF6B00) */
    .stButton > button[kind="primary"], div.stButton > button:first-child {
        background: linear-gradient(135deg, var(--accent-orange) 0%, var(--accent-orange-hover) 100%) !important;
        color: #FFFFFF !important;
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        border: none !important;
        border-radius: var(--radius-btn) !important;
        padding: 0.65rem 1.75rem !important;
        box-shadow: 0 4px 14px rgba(255, 107, 0, 0.3) !important;
        transition: var(--transition) !important;
    }

    .stButton > button[kind="primary"]:hover, div.stButton > button:first-child:hover {
        background: linear-gradient(135deg, var(--accent-orange-hover) 0%, #C74300 100%) !important;
        box-shadow: 0 6px 18px rgba(255, 107, 0, 0.45) !important;
        transform: translateY(-1px);
    }

    /* Botones de Descargar (CTA Naranja) */
    .stDownloadButton > button {
        background: linear-gradient(135deg, var(--accent-orange) 0%, var(--accent-orange-hover) 100%) !important;
        color: #FFFFFF !important;
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: var(--radius-btn) !important;
        padding: 0.75rem 2rem !important;
        box-shadow: 0 4px 14px rgba(255, 107, 0, 0.35) !important;
        width: 100%;
        transition: var(--transition) !important;
    }

    .stDownloadButton > button:hover {
        background: linear-gradient(135deg, var(--accent-orange-hover) 0%, #C74300 100%) !important;
        box-shadow: 0 6px 18px rgba(255, 107, 0, 0.5) !important;
        transform: translateY(-1px);
    }

    /* File Uploader Estilizado con borde Amarillo IAC */
    [data-testid="stFileUploader"] {
        background: var(--bg-surface);
        border: 2px dashed var(--brand-yellow);
        border-radius: var(--radius-card);
        padding: 1.25rem;
        transition: var(--transition);
        box-shadow: var(--shadow-sm);
    }

    [data-testid="stFileUploader"]:hover {
        border-color: var(--accent-orange);
        background-color: #FFFDF5;
        box-shadow: 0 4px 14px rgba(248, 177, 38, 0.15);
    }

    /* Estilizado de Expansores Streamlit */
    [data-testid="stExpander"] {
        background: var(--bg-surface);
        border: 1px solid var(--border-color) !important;
        border-radius: var(--radius-card) !important;
        box-shadow: var(--shadow-sm);
        margin-bottom: 0.85rem;
        overflow: hidden;
    }

    [data-testid="stExpander"]:hover {
        border-color: var(--brand-yellow) !important;
    }

    /* Tarjetas de Métricas */
    [data-testid="stMetric"] {
        background: var(--bg-surface);
        border: 1px solid var(--border-color);
        border-top: 4px solid var(--brand-yellow);
        border-radius: var(--radius-card);
        padding: 0.85rem 1rem;
        box-shadow: var(--shadow-sm);
        transition: var(--transition);
    }

    [data-testid="stMetric"]:hover {
        transform: translateY(-1px);
        box-shadow: var(--shadow-md);
    }

    [data-testid="stMetricLabel"] {
        color: var(--text-muted) !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
    }

    [data-testid="stMetricValue"] {
        color: var(--brand-black) !important;
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
    }

    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: var(--bg-surface);
        border-right: 1px solid var(--border-color);
    }

    section[data-testid="stSidebar"][aria-expanded="true"] {
        min-width: 300px;
        max-width: 380px;
    }

    /* Progress bar */
    .stProgress > div > div > div > div {
        background-color: var(--accent-orange) !important;
    }

    /* Tablas Dataframe */
    .stDataFrame {
        border: 1px solid var(--border-color);
        border-radius: var(--radius-card);
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
            <span>●</span> MOTOR OPENAI GPT-4.1-MINI ACTIVE
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
            expedicion = st.text_input("Ciudad de Expedición (Cédula)", value=datos_empresa.get("expedicion", ""),
                                       help="Ciudad donde fue expedida la cédula del representante legal. Ej: Medellín")
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

        if st.button("💾 Guardar Perfil Empresarial", key="btn_guardar_perfil", width="stretch"):
            datos_actualizados = {
                "razon_social": razon_social,
                "nit": nit,
                "direccion": direccion,
                "telefono": telefono,
                "correo": correo,
                "cedula": cedula,
                "expedicion": expedicion,
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
        if st.button("Crear Perfil", key="btn_crear_perfil", width="stretch"):
            if nuevo_nombre.strip():
                exito, nueva_ruta, nueva_etiqueta = profile_manager.crear_nuevo_perfil(nuevo_nombre, datos_empresa)
                if exito:
                    st.session_state["perfil_activo_nombre"] = nueva_etiqueta
                    st.success(f"✅ Perfil creado: {nueva_etiqueta}")
                    _safe_rerun()


# ── COMPONENTES HTML REUTILIZABLES ──────────────────────────────────────────

def _clean_html(html_str: str) -> str:
    """Elimina la sangría inicial (4+ espacios) de cada línea para evitar que Streamlit renderice el HTML como un bloque de código Markdown."""
    return "\n".join(line.strip() for line in html_str.splitlines() if line.strip())


def render_kpi_card(valor: str, label: str, color_borde: str = "#F8B126", icono: str = "📊") -> str:
    """Retorna el HTML de una tarjeta KPI con borde superior coloreado y elevación hover."""
    html_raw = f"""
        <div style="
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-top: 4px solid {color_borde};
            border-radius: 10px;
            padding: 1rem 1.15rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            margin-bottom: 0.5rem;
        ">
            <div style="font-size: 0.78rem; color: #64748B; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; display: flex; align-items: center; justify-content: space-between;">
                <span>{label}</span>
                <span style="font-size: 1.1rem;">{icono}</span>
            </div>
            <div style="font-size: 1.35rem; color: #121212; font-weight: 800; font-family: 'Montserrat', sans-serif; margin-top: 0.35rem;">
                {valor}
            </div>
        </div>
    """
    return _clean_html(html_raw)


def render_stepper_progress(paso_actual: int, porcentaje: int, texto_estado: str) -> str:
    """Genera la barra de progreso por pasos (Stepper) en HTML/CSS pura."""
    pasos = [
        ("1", "Estructura Espacial"),
        ("2", "Mapeo IA"),
        ("3", "Inyección Nativa"),
    ]
    
    steps_html = ""
    for idx, (num, titulo) in enumerate(pasos, 1):
        if idx < paso_actual:
            circle = '<div style="width: 26px; height: 26px; border-radius: 50%; background: #10B981; color: white; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.8rem;">✓</div>'
            text_style = 'color: #065F46; font-weight: 700;'
        elif idx == paso_actual:
            circle = f'<div style="width: 26px; height: 26px; border-radius: 50%; background: #FF6B00; color: white; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 0.8rem; box-shadow: 0 0 0 3px rgba(255,107,0,0.25);">{num}</div>'
            text_style = 'color: #FF6B00; font-weight: 800;'
        else:
            circle = f'<div style="width: 26px; height: 26px; border-radius: 50%; background: #E2E8F0; color: #64748B; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 0.8rem;">{num}</div>'
            text_style = 'color: #94A3B8; font-weight: 500;'
            
        steps_html += f"""
            <div style="display: flex; align-items: center; gap: 0.45rem;">
                {circle}
                <span style="font-size: 0.84rem; {text_style}">{titulo}</span>
            </div>
        """
        if idx < len(pasos):
            steps_html += f'<div style="flex: 1; height: 3px; background: {"#10B981" if idx < paso_actual else "#E2E8F0"}; margin: 0 0.4rem;"></div>'

    html_raw = f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 1.15rem 1.35rem; margin: 1rem 0; box-shadow: 0 2px 8px rgba(0,0,0,0.03);">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.85rem;">
                {steps_html}
            </div>
            <div style="background: #F1F5F9; border-radius: 6px; height: 8px; overflow: hidden; margin-bottom: 0.4rem;">
                <div style="width: {porcentaje}%; height: 100%; background: linear-gradient(90deg, #FF6B00 0%, #F8B126 100%); transition: width 0.35s ease;"></div>
            </div>
            <div style="font-size: 0.82rem; color: #64748B; font-weight: 600; text-align: right;">
                ⚡ {texto_estado} ({porcentaje}%)
            </div>
        </div>
    """
    return _clean_html(html_raw)


    return _clean_html(html_raw)


def render_aggrid_coincidencias(df_resultado):
    """Renderiza una tabla Enterprise AgGrid con edición, filtros y ordenamiento dinámico."""
    if AgGrid is not None:
        try:
            df_safe = df_resultado.astype(str)
            gb = GridOptionsBuilder.from_dataframe(df_safe)
            gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)
            gb.configure_side_bar()
            gb.configure_default_column(editable=True, groupable=True, filter=True, resizable=True)
            gridOptions = gb.build()
            return AgGrid(df_safe, gridOptions=gridOptions, height=280, theme="streamlit", fit_columns_on_grid_load=True)
        except Exception as e:
            print(f"[AutoForm AI Warning] AgGrid no pudo cargar: {e}")
    return None

def _sanitizar_resultados(resultados):
    sanitizados = []
    for item in resultados:
        val_raw = item.get("valor", "")
        if hasattr(val_raw, "isoformat") or hasattr(val_raw, "strftime"):
            val_str = str(val_raw)
        else:
            val_str = str(val_raw) if val_raw is not None else ""

        sanitizados.append(
            {
                "hoja": str(item.get("hoja", "")),
                "fila": int(item.get("fila", 0) or 0),
                "columna": int(item.get("columna", 0) or 0),
                "valor": val_str,
                "ubicacion": str(item.get("ubicacion", "")),
                "campo": str(item.get("campo", "")),
                "requiereMerge": bool(item.get("requiereMerge", False)),
                "celdasAMergear": int(item.get("celdasAMergear", 1) or 1),
            }
        )
    return sanitizados


def _deduplicar_por_campo(resultados):
    """Deduplica resultados por coordenada destino (hoja, fila, columna)
    para evitar colisiones de escritura, permitiendo que campos requeridos en múltiples
    secciones (ej. Cédula en Representante Legal y Junta Directiva) se inyecten.
    """
    vistos = set()
    resultado = []
    for item in resultados:
        clave = (item.get("hoja", ""), int(item.get("fila", 0)), int(item.get("columna", 0)))
        if clave not in vistos:
            vistos.add(clave)
            resultado.append(item)
    return resultado


# 6. Zona de Carga Principal
st.markdown("### 📥 Cargar Formulario de Terceros")

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

                # Conversión Arrow-safe en preview: datetime y otros tipos complejos -> str
                df_display = df.copy()
                for col in df_display.columns:
                    df_display[col] = df_display[col].apply(
                        lambda x: str(x) if x is not None and not isinstance(x, (str, int, float, bool)) else x
                    )
                st.dataframe(df_display, width="stretch", height=380)
            except Exception as e:
                st.error(f"Error al leer el archivo Excel: {e}")

        elif file_type == "pdf":
            try:
                uploaded_file.seek(0)
                bytes_pdf = uploaded_file.read()
                imagenes_png = pdf_processor.renderizar_paginas_png(bytes_pdf, max_paginas=2)
                
                if imagenes_png:
                    for i, img_bytes in enumerate(imagenes_png):
                        st.image(img_bytes, caption=f"Página {i+1}", width="stretch")
                else:
                    st.info("No se pudieron renderizar las páginas del PDF.")
            except Exception as e:
                st.error(f"Error al leer el archivo PDF: {e}")

    with col_actions:
        st.markdown("### ⚡ Ejecutar IA")
        st.write("Extrae rótulos visuales, analiza campos vacíos e inyecta los datos de la empresa respetando estilos.")

        # HITO 3: Hash MD5 del binario del archivo — clave determinista de sesión (calculado fuera del botón)
        uploaded_file.seek(0)
        _archivo_bytes_md5 = uploaded_file.read()
        import hashlib as _hl
        file_md5 = _hl.md5(_archivo_bytes_md5).hexdigest()
        current_file_id = f"md5:{file_md5}"

        if st.button("🚀 Procesar Formulario", type="primary", width="stretch"):
            if file_type in ["xlsx", "xls", "pdf"]:
                if not os.getenv("OPENAI_API_KEY"):
                    st.error("Configura OPENAI_API_KEY en tu archivo .env para ejecutar la IA.")


                progress_placeholder = st.empty()
                progress_placeholder.markdown(render_stepper_progress(1, 15, "Iniciando motor espacial..."), unsafe_allow_html=True)
                try:
                    uploaded_file.seek(0)
                    archivo_bytes = uploaded_file.read()

                    # Paso 1 & 2: Carga y Estructura
                    if file_type == "pdf":
                        progress_placeholder.markdown(render_stepper_progress(1, 30, "Detectando tipo de PDF (digital/escaneado)..."), unsafe_allow_html=True)
                        tipo_info = pdf_vision.detectar_tipo_pdf(archivo_bytes)
                        tipo_pdf = tipo_info.get("tipo", "digital")

                        if tipo_pdf == "escaneado":
                            progress_placeholder.markdown(render_stepper_progress(2, 55, "PDF escaneado: OCR + IA Visual (Vision)..."), unsafe_allow_html=True)
                            mapa_formularios = pdf_vision.construir_mapa_desde_ocr(archivo_bytes)
                            elementos_vision = pdf_vision.detectar_campos_vision_llm(archivo_bytes, datos_empresa)
                            if elementos_vision:
                                resultados = pdf_processor.construir_mapa_desde_vision(archivo_bytes, elementos_vision)
                            elif mapa_formularios:
                                resultados = mapper.mapeo_formularios(mapa_formularios, datos_empresa)
                            else:
                                resultados = []
                        else:
                            progress_placeholder.markdown(render_stepper_progress(1, 35, "Escaneando coordenadas bidireccionales del PDF..."), unsafe_allow_html=True)
                            mapa_formularios = pdf_processor.escanear_mapa_pdf(archivo_bytes)

                            if len(mapa_formularios) < 8:
                                progress_placeholder.markdown(render_stepper_progress(2, 60, "Analizando imagen del PDF con IA Visual (Vision)..."), unsafe_allow_html=True)
                                elementos_vision = pdf_vision.detectar_campos_vision_llm(archivo_bytes, datos_empresa)
                                if elementos_vision:
                                    resultados = pdf_processor.construir_mapa_desde_vision(archivo_bytes, elementos_vision)
                                else:
                                    resultados = mapper.mapeo_formularios(mapa_formularios, datos_empresa)
                            else:
                                progress_placeholder.markdown(render_stepper_progress(2, 75, "Invocando IA para mapeo semántico bidireccional..."), unsafe_allow_html=True)
                                resultados = mapper.mapeo_formularios(mapa_formularios, datos_empresa)
                    else:
                        progress_placeholder.markdown(render_stepper_progress(1, 25, "Leyendo estructura espacial del libro Excel..."), unsafe_allow_html=True)
                        libro = excel_parser.cargar_libro(BytesIO(archivo_bytes))
                        progress_placeholder.markdown(render_stepper_progress(1, 45, "Analizando celdas vacías y líneas de captura..."), unsafe_allow_html=True)
                        mapa_formularios = excel_parser.escanear_mapa_formularios(libro)
                        progress_placeholder.markdown(render_stepper_progress(2, 75, "Invocando IA para mapeo semántico..."), unsafe_allow_html=True)
                        resultados = mapper.mapeo_formularios(mapa_formularios, datos_empresa)

                    # LLM-04: Detectar caché
                    mapa_purgado_ui = mapper._purgar_mapa(mapa_formularios) if mapa_formularios else []
                    form_hash_ui = mapper._hash_mapa(mapa_purgado_ui) if mapa_purgado_ui else "vision_mode"
                    debug_info = _get_debug_info(form_hash_ui)

                    # Paso 4: Escritura
                    progress_placeholder.markdown(render_stepper_progress(3, 90, "Inyectando datos y preservando plantilla..."), unsafe_allow_html=True)

                    resultados_limpios = [r for r in resultados if r.get("hoja") and r.get("campo")] if resultados else []

                    # FIX: deduplicar por campo (evita escribir el mismo dato en múltiples posiciones)
                    resultados_limpios = _deduplicar_por_campo(resultados_limpios)

                    if resultados_limpios:
                        # FIX: el sanitizado (sin claves _pdf_*) solo alimenta el DataFrame
                        # de pantalla; el relleno y la validación reciben los originales.
                        resultados_sanitizados = _sanitizar_resultados(resultados_limpios)
                        # Construir DataFrame Arrow-safe (forzar todo a str)
                        df_resultado = pd.DataFrame.from_records(resultados_sanitizados)
                        df_resultado = df_resultado.map(lambda x: str(x) if x is not None else "").astype(str)

                        if file_type == "pdf":
                            bytes_relleno = pdf_processor.rellenar_pdf(archivo_bytes, resultados_limpios, datos_empresa)
                            # Motor PDF v2: validación visual + auto-corrección de bounding boxes
                            advertencias_visuales = []
                            if any(r.get("_pdf_page") is not None for r in resultados_limpios):
                                bytes_relleno, advertencias_visuales = pdf_vision.validar_relleno_vision(
                                    archivo_bytes, bytes_relleno, resultados_limpios, datos_empresa
                                )
                            reporte_inyeccion = []
                            st.session_state["resultado_advertencias_pdf"] = advertencias_visuales
                            file_extension = "pdf"
                            mime_type = "application/pdf"
                        else:
                            # HITO 2: Escanear celdas pre-diligenciadas para reprocesamiento incremental
                            from core.excel_parser import escanear_celdas_prellenadas as _escanear_prellenadas
                            from io import BytesIO as _BytesIO
                            _wb_previo = excel_parser.cargar_libro(_BytesIO(archivo_bytes))
                            _celdas_pre = _escanear_prellenadas(_wb_previo)
                            bytes_relleno, reporte_inyeccion = excel_writer.rellenar_formulario_excel(
                                archivo_bytes, resultados_sanitizados, datos_empresa, celdas_prellenadas=_celdas_pre
                            )
                            file_extension = "xlsx"
                            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

                        progress_placeholder.empty()

                        # Guardar en st.session_state para evitar reseteos al hacer click
                        st.session_state["processed_file_id"] = current_file_id
                        st.session_state["resultado_bytes"] = bytes_relleno
                        st.session_state["resultado_reporte_inyeccion"] = reporte_inyeccion
                        st.session_state["resultado_df"] = df_resultado
                        st.session_state["resultado_file_name"] = file_name
                        st.session_state["resultado_extension"] = file_extension
                        st.session_state["resultado_mime"] = mime_type
                        st.session_state["resultado_debug"] = debug_info
                    else:
                        progress_placeholder.markdown(render_stepper_progress(3, 100, "Proceso finalizado."), unsafe_allow_html=True)
                        st.info(
                            "No se encontraron campos compatibles para rellenar en este formulario. "
                            "Verifica que el perfil de empresa tenga datos y que el formulario PDF "
                            "contenga etiquetas reconocibles o casillas de entrada."
                        )
                except Exception as e:
                    progress_placeholder.empty()
                    st.error(f"⚠️ Se produjo un error durante el procesamiento: {str(e)}")
                    with st.expander("Ver detalles técnicos del error"):
                        st.text(traceback.format_exc())

        # Renderizado persistente desde st.session_state (Fuera de st.button, no se resetea al hacer click en descargar)
        if st.session_state.get("processed_file_id") == current_file_id and "resultado_bytes" in st.session_state:
            bytes_relleno = st.session_state["resultado_bytes"]
            df_resultado = st.session_state["resultado_df"]
            file_name_out = st.session_state["resultado_file_name"]
            file_ext_out = st.session_state["resultado_extension"]
            mime_type_out = st.session_state["resultado_mime"]
            debug_info_out = st.session_state.get("resultado_debug")

            if debug_info_out:
                with st.expander("🔍 Panel de Debug — Mapeo Semántico IA", expanded=False):
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.markdown(render_kpi_card(str(debug_info_out["rotulos_enviados"]), "Rótulos Enviados", "#F8B126", "📝"), unsafe_allow_html=True)
                    with c2:
                        st.markdown(render_kpi_card(str(debug_info_out["campos_mapeados"]), "Campos Mapeados", "#10B981", "✅"), unsafe_allow_html=True)
                    faltantes_list = debug_info_out.get("campos_faltantes_detectados", [])
                    with c3:
                        st.markdown(render_kpi_card(str(len(faltantes_list)), "Campos Faltantes", "#FF6B00" if faltantes_list else "#3B82F6", "⚠️"), unsafe_allow_html=True)
                    with c4:
                        st.markdown(render_kpi_card(str(debug_info_out["hash"][:8]), "Hash Formulario", "#64748B", "🔑"), unsafe_allow_html=True)

                    if faltantes_list:
                        st.warning(f"🚫 Campos omitidos o no encontrados: `{'`, `'.join(faltantes_list)}`")

                    tab_payload, tab_response = st.tabs(["📤 Payload Enviado", "📥 Respuesta RAW LLM"])
                    with tab_payload:
                        try:
                            payload_dict = json.loads(debug_info_out["prompt_payload"])
                            st.json(payload_dict)
                        except Exception:
                            st.code(debug_info_out["prompt_payload"], language="json")
                    with tab_response:
                        try:
                            respuesta_dict = json.loads(debug_info_out["respuesta_llm"])
                            st.json(respuesta_dict)
                        except Exception:
                            st.code(debug_info_out["respuesta_llm"], language="json")

            if debug_info_out and debug_info_out.get("tipo_cache") == "SEMANTIC_FUZZY_HIT":
                score_fuzzy = debug_info_out.get("score_similaridad", 95.0)
                st.markdown(f"""
                    <div class="iac-alert iac-alert-cache">
                        <div>⚡ <strong>Caché Semántico HIT ({score_fuzzy:.1f}% Similitud)</strong></div>
                        <div style="font-size: 0.82rem; opacity: 0.9;">Mapeado inteligente adaptado en &lt; 0.05s ($0 consumo de API).</div>
                    </div>
                """, unsafe_allow_html=True)

            st.markdown("""
                <div class="iac-alert iac-alert-warning">
                    <div>🎉 <strong>Formulario Diligenciado Correctamente</strong></div>
                    <div style="font-size: 0.82rem; opacity: 0.9;">Se inyectaron los datos respetando diseño nativo del documento.</div>
                </div>
            """, unsafe_allow_html=True)

            st.download_button(
                f"📥 Descargar Formulario Rellenado (.{file_ext_out})",
                data=bytes_relleno,
                file_name=f"{os.path.splitext(file_name_out)[0]}_diligenciado.{file_ext_out}",
                mime=mime_type_out,
            )

            # Panel de Auditoría y Verificación Completa
            if debug_info_out and "verificacion_auditoria" in debug_info_out:
                audit_rep = debug_info_out["verificacion_auditoria"]
                cobertura_pct = audit_rep.get("porcentaje_cobertura", 100.0)
                total_map = audit_rep.get("total_mapeados", len(df_resultado))
                omitidos = audit_rep.get("campos_omitidos", [])

                st.markdown("### 🔍 Reporte de Auditoría y Verificación de Integridad")
                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    st.metric("Campos Inyectados", f"{total_map} celdas")
                with col_m2:
                    st.metric("Cobertura de DatosEmpresa", f"{cobertura_pct}%")
                with col_m3:
                    st.metric("Estado de Verificación", "✅ VERIFICADO OK" if not omitidos else "⚠️ REVISIÓN FOCALIZADA")

                if omitidos:
                    with st.expander(f"⚠️ Detalle de campos omitidos por la plantilla ({len(omitidos)})"):
                        st.write("Los siguientes campos de tu perfil de empresa no fueron solicitados en esta plantilla:", omitidos)

            reporte_inyeccion = st.session_state.get("resultado_reporte_inyeccion", [])

            st.markdown("### 📍 Coordenadas e Información Inyectada")

            # Panel de reporte de inyección (nuevo)
            if reporte_inyeccion:
                df_reporte = pd.DataFrame(reporte_inyeccion)
                df_reporte = df_reporte.astype(str).fillna("")
                ok   = df_reporte[df_reporte["estado"] == "OK"]
                skip = df_reporte[df_reporte["estado"] == "SKIP"]
                null = df_reporte[df_reporte["estado"] == "NULL"]
                err  = df_reporte[df_reporte["estado"] == "ERROR"]

                preserved = df_reporte[df_reporte["estado"] == "PRESERVED"]
                c1, c2, c3, c4, c5 = st.columns(5)
                with c1:
                    st.markdown(render_kpi_card(str(len(ok)),        "Escritos OK",        "#10B981", "OK"), unsafe_allow_html=True)
                with c2:
                    st.markdown(render_kpi_card(str(len(preserved)), "Preservados",        "#6366F1", "OK"), unsafe_allow_html=True)
                with c3:
                    st.markdown(render_kpi_card(str(len(skip)),      "Saltados (ocupados)", "#F8B126", "!"), unsafe_allow_html=True)
                with c4:
                    st.markdown(render_kpi_card(str(len(null)),      "Sin valor (NULL)",   "#3B82F6", "?"), unsafe_allow_html=True)
                with c5:
                    st.markdown(render_kpi_card(str(len(err)),       "Errores",            "#EF4444", "X"), unsafe_allow_html=True)

                with st.expander("Ver reporte completo de inyeccion por campo", expanded=len(err) > 0 or len(skip) > 2):
                    no_ok = df_reporte[~df_reporte["estado"].isin(["OK", "PRESERVED"])]
                    if not no_ok.empty:
                        st.warning(f"⚠️ {len(no_ok)} campos no se escribieron correctamente:")
                        st.dataframe(
                            no_ok[["estado", "campo", "valor_intentado", "hoja", "fila_destino", "columna_destino", "motivo"]],
                            width="stretch",
                            height=min(300, len(no_ok) * 40 + 40),
                        )
                    else:
                        st.success("✅ Todos los campos fueron escritos sin problemas.")

                    st.markdown("**Todos los campos:**")
                    st.dataframe(
                        df_reporte[["estado", "campo", "valor_intentado", "hoja", "fila_destino", "columna_destino", "motivo"]],
                        width="stretch",
                        height=min(400, len(df_reporte) * 40 + 40),
                    )

            advertencias_pdf = st.session_state.get("resultado_advertencias_pdf", [])
            if advertencias_pdf:
                with st.expander(f"🔍 Validación Visual PDF (auto-corrección) — {len(advertencias_pdf)} advertencia(s)", expanded=len(advertencias_pdf) > 0):
                    df_adv = pd.DataFrame(advertencias_pdf).astype(str).fillna("")
                    st.dataframe(df_adv, width="stretch", height=min(300, len(df_adv) * 40 + 40))
                    st.caption("Las bounding boxes problemáticas se corrigieron automáticamente con visión LLM.")

                if AgGrid is not None:
                    render_aggrid_coincidencias(df_resultado)
                else:
                    st.dataframe(df_resultado, width="stretch")

else:
    st.markdown("""
        <div class="iac-card" style="text-align: center; padding: 2.5rem 1.5rem; margin-top: 1rem;">
            <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">📄⚡</div>
            <h3 style="margin-bottom: 0.5rem;">Carga tu Formulario Oficial para Comenzar</h3>
            <p style="color: #64748B; font-size: 0.95rem; max-width: 550px; margin: 0 auto 1.5rem auto;">
                Selecciona tu perfil empresarial en el panel izquierdo y arrastra una plantilla de Excel (.xlsx, .xls) para el diligenciamiento cognitivo automático.
            </p>
            <div style="display: flex; justify-content: center; gap: 1.5rem; flex-wrap: wrap; font-size: 0.85rem; color: #475569; font-weight: 600;">
                <div>1️⃣ Carga de Plantilla</div>
                <div>➔</div>
                <div>2️⃣ Mapeo Inteligente IA</div>
                <div>➔</div>
                <div>3️⃣ Descarga en Excel Nativo</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

