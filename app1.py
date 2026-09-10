import json
import os
import traceback
import warnings
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

import sys
import importlib

for modulo in [
    "core.database", "core.auth_manager", "core.llm_client", "core.excel_parser", "core.excel_writer", "core.mapper",
    "core.profile_manager", "core.spatial_ir", "core.semantic_validator", "core.fastembed_matcher",
    "core.coverage_engine", "core.embedding_engine", "core.field_detection_engine", "core.schema_models",
    "core.domain_constants", "pipeline.context", "pipeline.orchestrator",
    "pipeline.handlers.document_detector", "pipeline.handlers.excel_handler",
    "pipeline.stages.stage_1_parser", "pipeline.stages.stage_2_classifier",
    "pipeline.stages.stage_3_llm_mapper", "pipeline.stages.stage_5_writer",
    "ui.page_verify", "ui.page_download", "ui.page_upload", "template_store.store",
]:
    if modulo in sys.modules:
        importlib.reload(sys.modules[modulo])

from core import excel_parser, excel_writer, mapper, profile_manager, llm_client, auth_manager
from core.mapper import get_debug_info as _get_debug_info

from pipeline.context import PipelineContext
from pipeline.orchestrator import PipelineOrchestrator
from ui.page_verify import render_pantalla_verificacion
from ui.page_download import render_pantalla_descarga

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

# Soporte automático para Streamlit Community Cloud Secrets (st.secrets)
try:
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if isinstance(v, str) and k not in os.environ:
                os.environ[k] = v
except Exception:
    pass


def _safe_rerun():
    if hasattr(st, "rerun"):
        try:
            st.rerun()
        except Exception:
            pass
    elif hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()
        except Exception:
            pass


# 1. Configuración de pantalla con el Sistema de Diseño IAC
logo_favicon_path = Path("assets") / "favicon_iac.png"
st.set_page_config(
    page_title="AutoForm EXCEL | IAC Latam",
    page_icon=str(logo_favicon_path) if logo_favicon_path.exists() else "⚡",
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

# ── ADR-0008: GATEKEEPER SHIELD (AUTENTICACIÓN OBLIGATORIA) ────────────────
if not st.session_state.get("usuario_activo"):
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { display: none !important; }
            [data-testid="stSidebarNav"] { display: none !important; }
            [data-testid="collapsedControl"] { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

    col_izq, col_gate, col_der = st.columns([1, 2, 1])
    with col_gate:
        logo_gate = Path("assets") / "logo_iac_cropped.png"
        if logo_gate.exists():
            st.image(str(logo_gate), width=200)
        else:
            st.markdown("## 🏢 **IAC Latam**")

        st.markdown("""
            <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-top: 5px solid #1E3A8A; border-radius: 12px; padding: 1.4rem 1.8rem; box-shadow: 0 4px 16px rgba(0,0,0,0.06); margin-top: 1rem; margin-bottom: 1.25rem;">
                <h3 style="color: #0F172A; margin-bottom: 0.25rem; font-family: 'Montserrat', sans-serif;">⚡ AutoForm <span style="color: #FF6B00;">EXCEL</span></h3>
                <p style="color: #64748B; font-size: 0.88rem; margin: 0;">Plataforma de Diligenciamiento Inteligente de Formularios Oficiales.</p>
                <div style="margin-top: 0.75rem; font-size: 0.78rem; background: #F8FAFC; border: 1px solid #E2E8F0; padding: 0.45rem 0.75rem; border-radius: 6px; color: #475569;">
                    🔒 Acceso restringido exclusivamente al personal corporativo de IAC Latam.
                </div>
            </div>
        """, unsafe_allow_html=True)

        tab_login, tab_reg = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])

        with tab_login:
            st.markdown("##### Ingreso con Credenciales Corporativas")
            login_correo = st.text_input("Correo Corporativo", placeholder="usuario@iaclatam.com", key="gate_login_correo")
            login_pwd = st.text_input("Contraseña", type="password", key="gate_login_pwd")

            if st.button("Ingresar a la Plataforma", type="primary", use_container_width=True, key="btn_gate_login"):
                if login_correo.strip() and login_pwd:
                    user_auth = profile_manager.autenticar_usuario(login_correo.strip(), login_pwd)
                    if user_auth:
                        st.session_state["usuario_activo"] = user_auth
                        st.success(f"✅ ¡Bienvenido, {user_auth['nombre']}!")
                        _safe_rerun()
                    else:
                        st.error("Credenciales incorrectas o usuario no autorizado.")
                else:
                    st.warning("Ingresa tu correo y contraseña.")

        with tab_reg:
            st.markdown("##### Alta de Nuevo Usuario Corporativo")
            reg_nom = st.text_input("Nombre Completo", placeholder="Ej: Diana Gómez", key="gate_reg_nom")
            reg_car = st.text_input("Cargo / Rol", placeholder="Ej: Consultora de Aplicaciones", key="gate_reg_car")
            reg_ced = st.text_input("Cédula / Documento", placeholder="Ej: 1020304050", key="gate_reg_ced")
            reg_tel = st.text_input("Teléfono / Celular", placeholder="Ej: 3101234567", key="gate_reg_tel")
            reg_dir = st.text_input("Dirección Corporativa", value="Carrera 63 B # 32 E -25 OFC 206", key="gate_reg_dir")
            reg_ciu = st.text_input("Ciudad", value="Bogotá", key="gate_reg_ciu")
            reg_cor = st.text_input("Correo Corporativo (@iac.com.co o @iaclatam.com)", placeholder="nombre@iaclatam.com", key="gate_reg_cor")
            reg_pwd1 = st.text_input("Contraseña (mínimo 6 caracteres)", type="password", key="gate_reg_pwd1")
            reg_pwd2 = st.text_input("Confirmar Contraseña", type="password", key="gate_reg_pwd2")

            if st.button("Crear Cuenta", type="primary", use_container_width=True, key="btn_gate_reg"):
                if not reg_nom.strip():
                    st.error("El nombre completo es obligatorio.")
                elif not reg_cor.strip():
                    st.error("El correo electrónico es obligatorio.")
                elif reg_pwd1 != reg_pwd2:
                    st.error("Las contraseñas no coinciden.")
                elif len(reg_pwd1) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    exito_reg, msg_reg = profile_manager.registrar_usuario(
                        nombre=reg_nom.strip(),
                        correo=reg_cor.strip(),
                        password=reg_pwd1,
                        cargo=reg_car.strip(),
                        cedula=reg_ced.strip(),
                        telefono=reg_tel.strip(),
                        direccion=reg_dir.strip(),
                        ciudad=reg_ciu.strip(),
                        es_admin=0,
                    )
                    if exito_reg:
                        user_auth = profile_manager.autenticar_usuario(reg_cor.strip(), reg_pwd1)
                        if user_auth:
                            st.session_state["usuario_activo"] = user_auth
                            st.success("✅ ¡Cuenta creada exitosamente! Ingresando...")
                            _safe_rerun()
                        else:
                            st.success("✅ Cuenta creada. Inicia sesión en la pestaña anterior.")
                    else:
                        st.error(msg_reg)

    st.stop()

# 3. Header Hero Institucional y Barra de Sesión
usuario_actual = st.session_state["usuario_activo"]
# Sincronización automática de datos frescos desde SQLite (garantiza columnas nuevas como direccion y ciudad)
try:
    _u_fresco = profile_manager.database.obtener_usuario_por_correo_db(usuario_actual.get("correo", ""))
    if _u_fresco:
        st.session_state["usuario_activo"].update(_u_fresco)
        usuario_actual = st.session_state["usuario_activo"]
except Exception:
    pass

es_admin_usuario = bool(usuario_actual.get("es_admin", False))
rol_badge_label = "🛡️ Administrador" if es_admin_usuario else "💼 Asesor Comercial"

nombre_despliegue = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
motor_label = f"AZURE OPENAI ({nombre_despliegue.upper()}) ACTIVE" if (os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY")) else f"OPENAI {nombre_despliegue.upper()} ACTIVE"

st.markdown(f"""
    <div class="iac-header">
        <div>
            <h1 class="iac-title">⚡ AutoForm <span>EXCEL</span></h1>
            <div class="iac-subtitle">Plataforma Inteligente de Diligenciamiento de Formularios Oficiales — IAC Latam</div>
        </div>
        <div class="iac-badge">
            <span>●</span> MOTOR {motor_label}
        </div>
    </div>
""", unsafe_allow_html=True)

# Barra de Sesión Activa
col_ses_info, col_ses_cache, col_ses_btn = st.columns([4, 1.2, 1])
with col_ses_info:
    color_rol = "#1E3A8A" if es_admin_usuario else "#059669"
    st.markdown(f"""
        <div style="font-size: 0.84rem; color: #475569; padding: 0.35rem 0.75rem; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; display: inline-flex; align-items: center; gap: 0.6rem; margin-bottom: 0.75rem;">
            <span>👤 Sesión: <strong>{usuario_actual['nombre']}</strong></span>
            <span style="color: #CBD5E1;">|</span>
            <span style="color: {color_rol}; font-weight: 700;">{rol_badge_label}</span>
            <span style="color: #CBD5E1;">|</span>
            <span><code>{usuario_actual['correo']}</code></span>
        </div>
    """, unsafe_allow_html=True)
with col_ses_cache:
    if st.button("🧹 Limpiar Caché", key="btn_limpiar_cache_top", use_container_width=True, help="Elimina el contexto del formulario en memoria, resetea plantillas y recarga los perfiles"):
        for k in list(st.session_state.keys()):
            if k != "usuario_activo":
                del st.session_state[k]
        try:
            p_emb = Path("config") / "embedding_cache.json"
            if p_emb.exists():
                p_emb.write_text("{}", encoding="utf-8")
            p_tpl = Path("config") / "plantillas_cache.json"
            if p_tpl.exists():
                p_tpl.write_text("{}", encoding="utf-8")
        except Exception:
            pass
        st.success("✅ Caché reiniciado.")
        _safe_rerun()
with col_ses_btn:
    if st.button("🚪 Cerrar Sesión", key="btn_logout_top", use_container_width=True):
        st.session_state.clear()
        _safe_rerun()

# 4. Sidebar Corporativa
with st.sidebar:
    logo_sidebar = Path("assets") / "logo_iac_cropped.png"
    if logo_sidebar.exists():
        st.image(str(logo_sidebar), width=170)
    else:
        st.markdown("### 🏢 **IAC Latam**")
    st.caption("Ingeniería Asistida en Computadora")
    st.markdown("---")

    # 🏢 Fase 2: Gestión de Perfiles Empresariales (Multi-Perfil)
    st.markdown("### 🪪 **Perfil Empresarial Activo**")
    dict_perfiles = profile_manager.listar_perfiles()
    nombres_perfiles = list(dict_perfiles.keys())

    perfil_guardado = profile_manager.obtener_perfil_activo_guardado()
    if "perfil_activo_nombre" not in st.session_state or st.session_state["perfil_activo_nombre"] not in dict_perfiles:
        st.session_state["perfil_activo_nombre"] = (
            perfil_guardado if perfil_guardado in dict_perfiles
            else (nombres_perfiles[0] if nombres_perfiles else "🏢 Principal (IAC Latam)")
        )

    idx_activo = (
        nombres_perfiles.index(st.session_state["perfil_activo_nombre"])
        if st.session_state["perfil_activo_nombre"] in nombres_perfiles
        else 0
    )

    perfil_seleccionado_etiqueta = st.selectbox(
        "Seleccionar Perfil:",
        options=nombres_perfiles,
        index=idx_activo,
        key="sb_selector_perfil_activo",
        help="Los datos de este perfil se usarán para diligenciar los formularios automáticamente."
    )
    if perfil_seleccionado_etiqueta != st.session_state.get("perfil_activo_nombre"):
        st.session_state["perfil_activo_nombre"] = perfil_seleccionado_etiqueta
        profile_manager.guardar_perfil_activo_seleccionado(perfil_seleccionado_etiqueta)

    ruta_perfil_activo = dict_perfiles[perfil_seleccionado_etiqueta]
    datos_empresa = profile_manager.cargar_perfil(ruta_perfil_activo)

    # 👤 Fase 3: Gestión de Operadores / Diligenciado Por (ADR-0007)
    st.markdown("### 👤 **Diligenciado Por (Operador)**")
    if not es_admin_usuario:
        operador_activo = {
            "id": usuario_actual["id"],
            "nombre": usuario_actual["nombre"],
            "cargo": usuario_actual.get("cargo", ""),
            "cedula": usuario_actual.get("cedula", ""),
            "telefono": usuario_actual.get("telefono", ""),
            "correo": usuario_actual["correo"],
            "direccion": usuario_actual.get("direccion", "Carrera 63 B # 32 E -25 OFC 206"),
            "ciudad": usuario_actual.get("ciudad", "Bogotá"),
        }
        st.markdown(f"""
            <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-left: 3px solid #059669; border-radius: 6px; padding: 0.5rem 0.75rem; margin-bottom: 0.5rem;">
                <div style="font-size: 0.7rem; color: #64748B; font-weight: 700; text-transform: uppercase;">Asesor Comercial Activo</div>
                <div style="font-size: 0.88rem; color: #0F172A; font-weight: 700;">👤 {usuario_actual['nombre']}</div>
                <div style="font-size: 0.75rem; color: #475569;">{usuario_actual.get('cargo') or 'Asesor Comercial'}</div>
                <div style="font-size: 0.72rem; color: #94A3B8; font-family: monospace;">{usuario_actual['correo']}</div>
            </div>
        """, unsafe_allow_html=True)
    else:
        operadores_db = profile_manager.listar_operadores()
        nombres_operadores = [f"👤 {op['nombre']}" + (f" ({op['cargo']})" if op.get("cargo") else "") for op in operadores_db]
        mapa_operadores = {
            (f"👤 {op['nombre']}" + (f" ({op['cargo']})" if op.get("cargo") else "")): op
            for op in operadores_db
        }

        opcion_sin_operador = "⚪ Ninguno (Safe Passivity / Manual)"
        opciones_op = [opcion_sin_operador] + nombres_operadores

        op_activo_db = profile_manager.obtener_operador_activo()
        idx_op_def = 0
        if op_activo_db:
            for idx_i, op_item in enumerate(operadores_db):
                if op_item["id"] == op_activo_db["id"]:
                    idx_op_def = idx_i + 1
                    break

        op_seleccionado_etiqueta = st.selectbox(
            "Seleccionar Asesor / Operador:",
            options=opciones_op,
            index=idx_op_def,
            key="sb_selector_operador_activo",
            help="El asesor seleccionado será asignado a los campos comerciales y de contacto sin tocar la información jurídica de la empresa.",
        )

        operador_activo = None
        if op_seleccionado_etiqueta != opcion_sin_operador:
            operador_activo = mapa_operadores.get(op_seleccionado_etiqueta)
            if operador_activo and (not op_activo_db or op_activo_db["id"] != operador_activo["id"]):
                profile_manager.activar_operador(operador_activo["id"])

    # ✏️ Editor Visual de Datos del Perfil Activo (Taxonomía Semántica)
    slug_perfil = profile_manager._slugify(perfil_seleccionado_etiqueta)

    def _al_cambiar_campo(key_w: str, campo_nombre: str):
        if not es_admin_usuario:
            return
        val = st.session_state.get(key_w)
        if val is not None:
            profile_manager.auto_guardar_campo(
                ruta_perfil_activo,
                campo_nombre,
                val,
                nombre_visible=perfil_seleccionado_etiqueta,
            )

    with st.expander("✏️ Editar Datos de Empresa", expanded=False):
        if not es_admin_usuario:
            st.info("🔒 **Modo Solo Lectura**: Como asesor comercial, puedes consultar la información corporativa pero la modificación de datos fiscales, bancarios o de balance está reservada a los administradores.")
        else:
            st.caption("Cada campo se guarda automáticamente en tiempo real al editar.")
        tab_emp, tab_rep, tab_fin = st.tabs(["🏢 Empresa", "👤 Representante", "🏦 Financiero"])
        
        with tab_emp:
            st.markdown("##### 📌 Identificación Corporativa")
            razon_social = st.text_input(
                "Razón Social",
                value=str(datos_empresa.get("razon_social") or ""),
                key=f"pe_{slug_perfil}_rs",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_rs", "razon_social"),
                disabled=not es_admin_usuario,
            )
            nit = st.text_input(
                "NIT / Identificación Tributaria",
                value=str(datos_empresa.get("nit") or ""),
                key=f"pe_{slug_perfil}_nit",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_nit", "nit"),
                disabled=not es_admin_usuario,
            )
            tipo_sociedad = st.text_input(
                "Tipo de Sociedad",
                value=str(datos_empresa.get("tipo_sociedad") or ""),
                key=f"pe_{slug_perfil}_tsoc",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_tsoc", "tipo_sociedad"),
                disabled=not es_admin_usuario,
            )

            st.markdown("##### 📍 Ubicación Principal")
            direccion = st.text_input(
                "Dirección Principal",
                value=str(datos_empresa.get("direccion") or ""),
                key=f"pe_{slug_perfil}_dir",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_dir", "direccion"),
                disabled=not es_admin_usuario,
            )
            ciudad = st.text_input(
                "Ciudad / Municipio",
                value=str(datos_empresa.get("ciudad") or ""),
                key=f"pe_{slug_perfil}_ciu",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_ciu", "ciudad"),
                disabled=not es_admin_usuario,
            )
            departamento = st.text_input(
                "Departamento",
                value=str(datos_empresa.get("departamento") or ""),
                key=f"pe_{slug_perfil}_dep",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_dep", "departamento"),
                disabled=not es_admin_usuario,
            )
            pais = st.text_input(
                "País",
                value=str(datos_empresa.get("pais") or "Colombia"),
                key=f"pe_{slug_perfil}_pais",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_pais", "pais"),
                disabled=not es_admin_usuario,
            )

            st.markdown("##### 📞 Contacto Institucional")
            telefono = st.text_input(
                "Teléfono PBX",
                value=str(datos_empresa.get("telefono") or ""),
                key=f"pe_{slug_perfil}_tel",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_tel", "telefono"),
                disabled=not es_admin_usuario,
            )
            pagina_web = st.text_input(
                "Página Web",
                value=str(datos_empresa.get("pagina_web") or ""),
                key=f"pe_{slug_perfil}_web",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_web", "pagina_web"),
                disabled=not es_admin_usuario,
            )

        with tab_rep:
            st.markdown("##### 🪪 Identidad del Representante")
            representante_legal = st.text_input(
                "Nombre Completo",
                value=str(datos_empresa.get("representante_legal") or ""),
                key=f"pe_{slug_perfil}_rep_nom",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_rep_nom", "representante_legal"),
                disabled=not es_admin_usuario,
            )

            col_nom1, col_nom2 = st.columns(2)
            with col_nom1:
                primer_nombre = st.text_input(
                    "Primer Nombre",
                    value=str(datos_empresa.get("primer_nombre") or ""),
                    key=f"pe_{slug_perfil}_p_nom",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_p_nom", "primer_nombre"),
                    disabled=not es_admin_usuario,
                )
            with col_nom2:
                segundo_nombre = st.text_input(
                    "Segundo Nombre",
                    value=str(datos_empresa.get("segundo_nombre") or ""),
                    key=f"pe_{slug_perfil}_s_nom",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_s_nom", "segundo_nombre"),
                    disabled=not es_admin_usuario,
                )

            col_ape1, col_ape2 = st.columns(2)
            with col_ape1:
                primer_apellido = st.text_input(
                    "Primer Apellido",
                    value=str(datos_empresa.get("primer_apellido") or ""),
                    key=f"pe_{slug_perfil}_p_ape",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_p_ape", "primer_apellido"),
                    disabled=not es_admin_usuario,
                )
            with col_ape2:
                segundo_apellido = st.text_input(
                    "Segundo Apellido",
                    value=str(datos_empresa.get("segundo_apellido") or ""),
                    key=f"pe_{slug_perfil}_s_ape",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_s_ape", "segundo_apellido"),
                    disabled=not es_admin_usuario,
                )

            col_nombres_juntos, col_apellidos_juntos = st.columns(2)
            with col_nombres_juntos:
                rep_nombres = st.text_input(
                    "Nombres (Juntos)",
                    value=str(datos_empresa.get("representante_nombres") or ""),
                    key=f"pe_{slug_perfil}_r_nom",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_r_nom", "representante_nombres"),
                    disabled=not es_admin_usuario,
                )
            with col_apellidos_juntos:
                rep_apellidos = st.text_input(
                    "Apellidos (Juntos)",
                    value=str(datos_empresa.get("representante_apellidos") or ""),
                    key=f"pe_{slug_perfil}_r_ape",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_r_ape", "representante_apellidos"),
                    disabled=not es_admin_usuario,
                )
            
            col_doc1, col_doc2 = st.columns(2)
            with col_doc1:
                tipo_documento = st.text_input(
                    "Tipo de Documento / Tipo ID",
                    value=str(datos_empresa.get("tipo_documento") or "C.C."),
                    key=f"pe_{slug_perfil}_tdoc",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_tdoc", "tipo_documento"),
                    disabled=not es_admin_usuario,
                )
            with col_doc2:
                cedula = st.text_input(
                    "Número de Documento (Cédula)",
                    value=str(datos_empresa.get("cedula") or ""),
                    key=f"pe_{slug_perfil}_ced",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_ced", "cedula"),
                    disabled=not es_admin_usuario,
                )

            col_exp, col_nac = st.columns(2)
            with col_exp:
                lugar_expedicion = st.text_input(
                    "Lugar de Expedición (Ciudad)",
                    value=str(datos_empresa.get("lugar_expedicion") or datos_empresa.get("expedicion") or ""),
                    help="Ciudad o Municipio donde fue expedido el documento del representante. Ej: Envigado",
                    key=f"pe_{slug_perfil}_exp",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_exp", "lugar_expedicion"),
                    disabled=not es_admin_usuario,
                )
            with col_nac:
                lugar_nacimiento = st.text_input(
                    "Lugar de Nacimiento (Ciudad)",
                    value=str(datos_empresa.get("lugar_nacimiento") or "Popayán"),
                    help="Ciudad o Municipio de nacimiento del representante legal. Ej: Popayán",
                    key=f"pe_{slug_perfil}_nac",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_nac", "lugar_nacimiento"),
                    disabled=not es_admin_usuario,
                )

            st.markdown("##### 📍 Residencia / Domicilio Personal")
            col_res_c, col_res_d = st.columns(2)
            with col_res_c:
                ciudad_residencia = st.text_input(
                    "Ciudad de Residencia",
                    value=str(datos_empresa.get("ciudad_residencia") or "Medellín"),
                    help="Ciudad o Municipio de residencia personal del representante. Ej: Medellín",
                    key=f"pe_{slug_perfil}_cres",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_cres", "ciudad_residencia"),
                    disabled=not es_admin_usuario,
                )
            with col_res_d:
                departamento_residencia = st.text_input(
                    "Departamento de Residencia",
                    value=str(datos_empresa.get("departamento_residencia") or "Antioquia"),
                    help="Departamento de residencia personal del representante. Ej: Antioquia",
                    key=f"pe_{slug_perfil}_dres",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_dres", "departamento_residencia"),
                    disabled=not es_admin_usuario,
                )

            st.markdown("##### 📱 Contacto Directo")
            col_cont1, col_cont2 = st.columns(2)
            with col_cont1:
                celular = st.text_input(
                    "Celular / Móvil",
                    value=str(datos_empresa.get("celular") or ""),
                    key=f"pe_{slug_perfil}_cel",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_cel", "celular"),
                    disabled=not es_admin_usuario,
                )
            with col_cont2:
                correo = st.text_input(
                    "Correo Electrónico",
                    value=str(datos_empresa.get("correo") or ""),
                    key=f"pe_{slug_perfil}_cor",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_cor", "correo"),
                    disabled=not es_admin_usuario,
                )

        with tab_fin:
            st.markdown("##### 🏦 Entidad Bancaria")
            banco = st.text_input(
                "Banco",
                value=str(datos_empresa.get("banco") or ""),
                key=f"pe_{slug_perfil}_banco",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_banco", "banco"),
                disabled=not es_admin_usuario,
            )
            sucursal = st.text_input(
                "Sucursal Bancaria",
                value=str(datos_empresa.get("sucursal") or ""),
                key=f"pe_{slug_perfil}_suc",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_suc", "sucursal"),
                disabled=not es_admin_usuario,
            )

            st.markdown("##### 💳 Cuenta para Pagos")
            numero_cuenta = st.text_input(
                "Número de Cuenta",
                value=str(datos_empresa.get("numero_cuenta") or ""),
                key=f"pe_{slug_perfil}_num_cta",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_num_cta", "numero_cuenta"),
                disabled=not es_admin_usuario,
            )
            tipo_cuenta = st.text_input(
                "Tipo de Cuenta",
                value=str(datos_empresa.get("tipo_cuenta") or "AHORROS"),
                key=f"pe_{slug_perfil}_tip_cta",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_tip_cta", "tipo_cuenta"),
                disabled=not es_admin_usuario,
            )
            moneda = st.text_input(
                "Moneda / Divisa",
                value=str(datos_empresa.get("moneda") or "Pesos"),
                help="Moneda predeterminada para operaciones financieras (ej: Pesos, COP, USD)",
                key=f"pe_{slug_perfil}_moneda",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_moneda", "moneda"),
                disabled=not es_admin_usuario,
            )

            st.markdown("##### 📊 Balance y Cifras Financieras")
            total_activos = st.text_input(
                "Total Activos",
                value=str(datos_empresa.get("total_activos") or ""),
                key=f"pe_{slug_perfil}_tot_act",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_tot_act", "total_activos"),
                disabled=not es_admin_usuario,
            )
            total_pasivos = st.text_input(
                "Total Pasivos",
                value=str(datos_empresa.get("total_pasivos") or ""),
                key=f"pe_{slug_perfil}_tot_pas",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_tot_pas", "total_pasivos"),
                disabled=not es_admin_usuario,
            )
            total_patrimonio = st.text_input(
                "Total Patrimonio",
                value=str(datos_empresa.get("total_patrimonio") or ""),
                key=f"pe_{slug_perfil}_tot_pat",
                on_change=_al_cambiar_campo,
                args=(f"pe_{slug_perfil}_tot_pat", "total_patrimonio"),
                disabled=not es_admin_usuario,
            )
            c_ing_men, c_egr_men = st.columns(2)
            with c_ing_men:
                total_ingresos_mensuales = st.text_input(
                    "Total Ingresos Mensuales",
                    value=str(datos_empresa.get("total_ingresos_mensuales") or ""),
                    key=f"pe_{slug_perfil}_ing_men",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_ing_men", "total_ingresos_mensuales"),
                    disabled=not es_admin_usuario,
                )
            with c_egr_men:
                total_egresos_mensuales = st.text_input(
                    "Total Egresos Mensuales",
                    value=str(datos_empresa.get("total_egresos_mensuales") or ""),
                    key=f"pe_{slug_perfil}_egr_men",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_egr_men", "total_egresos_mensuales"),
                    disabled=not es_admin_usuario,
                )
            c_ing_anu, c_egr_anu = st.columns(2)
            with c_ing_anu:
                total_ingresos_anuales = st.text_input(
                    "Total Ingresos Anuales (Opcional)",
                    value=str(datos_empresa.get("total_ingresos_anuales") or ""),
                    key=f"pe_{slug_perfil}_ing_anu",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_ing_anu", "total_ingresos_anuales"),
                    disabled=not es_admin_usuario,
                )
            with c_egr_anu:
                total_egresos_anuales = st.text_input(
                    "Total Egresos Anuales (Opcional)",
                    value=str(datos_empresa.get("total_egresos_anuales") or ""),
                    key=f"pe_{slug_perfil}_egr_anu",
                    on_change=_al_cambiar_campo,
                    args=(f"pe_{slug_perfil}_egr_anu", "total_egresos_anuales"),
                    disabled=not es_admin_usuario,
                )

        if es_admin_usuario:
            if st.button("💾 Guardar y Confirmar Cambios", key="btn_guardar_perfil", width="stretch"):
                datos_guardar = dict(datos_empresa)
                datos_actualizados = {
                    "razon_social": razon_social,
                    "nit": nit,
                    "tipo_sociedad": tipo_sociedad,
                    "direccion": direccion,
                    "ciudad": ciudad,
                    "departamento": departamento,
                    "pais": pais,
                    "telefono": telefono,
                    "pagina_web": pagina_web,
                    "representante_legal": representante_legal,
                    "representante_nombres": rep_nombres,
                    "representante_apellidos": rep_apellidos,
                    "primer_nombre": primer_nombre,
                    "segundo_nombre": segundo_nombre,
                    "primer_apellido": primer_apellido,
                    "segundo_apellido": segundo_apellido,
                    "tipo_documento": tipo_documento,
                    "cedula": cedula,
                    "lugar_expedicion": lugar_expedicion,
                    "expedicion": lugar_expedicion,
                    "lugar_nacimiento": lugar_nacimiento,
                    "ciudad_residencia": ciudad_residencia,
                    "departamento_residencia": departamento_residencia,
                    "celular": celular,
                    "correo": correo,
                    "banco": banco,
                    "sucursal": sucursal,
                    "numero_cuenta": numero_cuenta,
                    "tipo_cuenta": tipo_cuenta,
                    "moneda": moneda,
                    "total_activos": total_activos,
                    "total_pasivos": total_pasivos,
                    "total_patrimonio": total_patrimonio,
                    "total_ingresos_mensuales": total_ingresos_mensuales,
                    "total_egresos_mensuales": total_egresos_mensuales,
                    "total_ingresos_anuales": total_ingresos_anuales,
                    "total_egresos_anuales": total_egresos_anuales,
                }
                datos_guardar.update(datos_actualizados)
                if profile_manager.guardar_perfil(ruta_perfil_activo, datos_guardar, nombre_visible=perfil_seleccionado_etiqueta):
                    profile_manager.guardar_perfil_activo_seleccionado(perfil_seleccionado_etiqueta)
                    st.success("✅ ¡Datos guardados permanentemente en SQLite canónico y archivo JSON!")
                    datos_empresa = datos_guardar
                    _safe_rerun()

    # 👤 Gestión de Operadores / Diligenciado Por (Posicionado directamente debajo de Editar Empresa)
    if es_admin_usuario:
        with st.expander("👤 Gestionar Operadores / Asesores", expanded=False):
            st.caption("Administra los asesores que diligencian los formularios comerciales:")

            # Si hay un operador seleccionado, permitir editar sus datos
            if operador_activo:
                st.markdown(f"##### ✏️ Editar: **{operador_activo['nombre']}**")
                op_nombre = st.text_input("Nombre Completo", value=operador_activo.get("nombre", ""), key=f"edit_op_nom_{operador_activo['id']}")
                op_cargo = st.text_input("Cargo / Rol", value=operador_activo.get("cargo", ""), key=f"edit_op_car_{operador_activo['id']}")
                op_cedula = st.text_input("Cédula / Documento", value=operador_activo.get("cedula", ""), key=f"edit_op_ced_{operador_activo['id']}")
                op_tel = st.text_input("Teléfono / Celular", value=operador_activo.get("telefono", ""), key=f"edit_op_tel_{operador_activo['id']}")
                op_correo = st.text_input("Correo Electrónico", value=operador_activo.get("correo", ""), key=f"edit_op_cor_{operador_activo['id']}")
                op_dir = st.text_input("Dirección", value=operador_activo.get("direccion") or "Carrera 63 B # 32 E -25 OFC 206", key=f"edit_op_dir_{operador_activo['id']}")
                op_ciu = st.text_input("Ciudad", value=operador_activo.get("ciudad") or "Bogotá", key=f"edit_op_ciu_{operador_activo['id']}")

                if st.button("💾 Guardar Datos del Operador", key="btn_guardar_op_actual", use_container_width=True):
                    profile_manager.guardar_operador(
                        operador_id=operador_activo["id"],
                        nombre=op_nombre,
                        cargo=op_cargo,
                        cedula=op_cedula,
                        telefono=op_tel,
                        correo=op_correo,
                        direccion=op_dir,
                        ciudad=op_ciu,
                        es_activo=True,
                    )
                    # Sincronizar en la sesión activa si corresponde al usuario conectado
                    if usuario_actual.get("id") == operador_activo["id"] or usuario_actual.get("correo", "").lower() == op_correo.strip().lower():
                        st.session_state["usuario_activo"]["nombre"] = op_nombre
                        st.session_state["usuario_activo"]["cargo"] = op_cargo
                        st.session_state["usuario_activo"]["cedula"] = op_cedula
                        st.session_state["usuario_activo"]["telefono"] = op_tel
                        st.session_state["usuario_activo"]["correo"] = op_correo
                        st.session_state["usuario_activo"]["direccion"] = op_dir
                        st.session_state["usuario_activo"]["ciudad"] = op_ciu

                    st.success("✅ Datos del operador actualizados exitosamente en SQLite y sesión.")
                    _safe_rerun()
                st.markdown("---")

            st.markdown("##### ➕ Registrar Nuevo Asesor")
            nuevo_op_nombre = st.text_input("Nombre Completo", placeholder="Ej: Diana Gómez", key="nuevo_op_nom")
            nuevo_op_cargo = st.text_input("Cargo", placeholder="Ej: Consultora Comercial", key="nuevo_op_car")
            nuevo_op_ced = st.text_input("Cédula", placeholder="Ej: 1020304050", key="nuevo_op_ced")
            nuevo_op_tel = st.text_input("Teléfono / Celular", placeholder="Ej: 3101234567", key="nuevo_op_tel")
            nuevo_op_cor = st.text_input("Correo", placeholder="Ej: diana.gomez@iaclatam.com", key="nuevo_op_cor")
            nuevo_op_dir = st.text_input("Dirección", value="Carrera 63 B # 32 E -25 OFC 206", key="nuevo_op_dir")
            nuevo_op_ciu = st.text_input("Ciudad", value="Bogotá", key="nuevo_op_ciu")

            if st.button("Crear Asesor", key="btn_crear_nuevo_op", use_container_width=True):
                if nuevo_op_nombre.strip():
                    slug_op = profile_manager._slugify(nuevo_op_nombre)
                    profile_manager.guardar_operador(
                        operador_id=slug_op,
                        nombre=nuevo_op_nombre.strip(),
                        cargo=nuevo_op_cargo.strip(),
                        cedula=nuevo_op_ced.strip(),
                        telefono=nuevo_op_tel.strip(),
                        correo=nuevo_op_cor.strip(),
                        direccion=nuevo_op_dir.strip(),
                        ciudad=nuevo_op_ciu.strip(),
                        es_activo=True,
                    )
                    st.success(f"✅ Operador '{nuevo_op_nombre}' registrado y activado.")
                    _safe_rerun()
                else:
                    st.warning("Ingresa al menos el nombre del asesor.")
    else:
        with st.expander("👤 Mis Datos de Asesor Comercial", expanded=False):
            st.caption("Actualiza tus datos para el diligenciamiento automático de formularios:")
            mi_nom = st.text_input("Nombre Completo", value=usuario_actual.get("nombre", ""), key="mi_op_nom")
            mi_car = st.text_input("Cargo / Rol", value=usuario_actual.get("cargo", ""), key="mi_op_car")
            mi_ced = st.text_input("Cédula / Documento", value=usuario_actual.get("cedula", ""), key="mi_op_ced")
            mi_tel = st.text_input("Teléfono / Celular", value=usuario_actual.get("telefono", ""), key="mi_op_tel")
            mi_dir = st.text_input("Dirección", value=usuario_actual.get("direccion") or "Carrera 63 B # 32 E -25 OFC 206", key="mi_op_dir")
            mi_ciu = st.text_input("Ciudad", value=usuario_actual.get("ciudad") or "Bogotá", key="mi_op_ciu")
            st.text_input("Correo Corporativo", value=usuario_actual.get("correo", ""), disabled=True, key="mi_op_cor")

            if st.button("💾 Guardar Mis Datos", key="btn_guardar_mis_datos", use_container_width=True):
                profile_manager.guardar_operador(
                    operador_id=usuario_actual["id"],
                    nombre=mi_nom,
                    cargo=mi_car,
                    cedula=mi_ced,
                    telefono=mi_tel,
                    correo=usuario_actual["correo"],
                    direccion=mi_dir,
                    ciudad=mi_ciu,
                    es_activo=True,
                )
                st.session_state["usuario_activo"]["nombre"] = mi_nom
                st.session_state["usuario_activo"]["cargo"] = mi_car
                st.session_state["usuario_activo"]["cedula"] = mi_ced
                st.session_state["usuario_activo"]["telefono"] = mi_tel
                st.session_state["usuario_activo"]["direccion"] = mi_dir
                st.session_state["usuario_activo"]["ciudad"] = mi_ciu
                st.success("✅ Tus datos se han actualizado permanentemente en SQLite y sesión.")
                _safe_rerun()

    if es_admin_usuario:
        with st.expander("➕ Crear Nuevo Perfil", expanded=False):
            nuevo_nombre = st.text_input("Nombre del Nuevo Perfil", placeholder="Ej: IAC Sucursal Bogotá")
            if st.button("Crear Perfil", key="btn_crear_perfil", width="stretch"):
                if nuevo_nombre.strip():
                    exito, nueva_ruta, nueva_etiqueta = profile_manager.crear_nuevo_perfil(nuevo_nombre, datos_empresa)
                    if exito:
                        st.session_state["perfil_activo_nombre"] = nueva_etiqueta
                        profile_manager.guardar_perfil_activo_seleccionado(nueva_etiqueta)
                        st.success(f"✅ Perfil creado: {nueva_etiqueta}")
                        _safe_rerun()

        with st.expander("💾 Respaldar / Cargar Perfil (JSON)", expanded=False):
            st.caption("Exporta tus datos para guardarlos en tu equipo o impórtalos en la nube (Streamlit Cloud):")
            json_descarga = profile_manager.obtener_perfil_para_descarga(ruta_perfil_activo)
            st.download_button(
                label="📥 Descargar Perfil Activo (JSON)",
                data=json_descarga,
                file_name=f"{slug_perfil}_datos_empresa.json",
                mime="application/json",
                use_container_width=True,
                help="Descarga este perfil en tu equipo para conservarlo o importarlo en la versión web."
            )
            st.markdown("---")
            archivo_perfil_subido = st.file_uploader(
                "📤 Importar Perfil desde JSON:",
                type=["json"],
                key="uploader_perfil_json",
                help="Sube un archivo JSON previamente exportado para restaurar o cargar una nueva empresa."
            )
            if archivo_perfil_subido is not None:
                if st.button("Restaurar y Activar Perfil", key="btn_importar_perfil_json", use_container_width=True):
                    contenido = archivo_perfil_subido.getvalue().decode("utf-8")
                    nombre_base = archivo_perfil_subido.name.replace(".json", "").replace("datos_empresa_", "").replace("_", " ").title()
                    exito, ruta_imp, etiq_imp = profile_manager.importar_perfil_json(contenido, nombre_sugerido=nombre_base)
                    if exito:
                        st.session_state["perfil_activo_nombre"] = etiq_imp
                        profile_manager.guardar_perfil_activo_seleccionado(etiq_imp)
                        st.success(f"✅ Perfil '{etiq_imp}' importado y activado exitosamente.")
                        _safe_rerun()
                    else:
                        st.error("❌ El archivo JSON no tiene un formato válido.")


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


# 5. Barra de Contexto Activo (Empresa y Operador)
col_ctx1, col_ctx2 = st.columns([1, 1])
with col_ctx1:
    st.markdown(f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-left: 4px solid #1E3A8A; border-radius: 8px; padding: 0.65rem 0.9rem; margin-bottom: 1rem; box-shadow: 0 1px 4px rgba(0,0,0,0.03);">
            <div style="font-size: 0.72rem; color: #64748B; font-weight: 700; text-transform: uppercase;">🏢 Perfil Empresarial</div>
            <div style="font-size: 0.95rem; color: #0F172A; font-weight: 700;">{perfil_seleccionado_etiqueta}</div>
        </div>
    """, unsafe_allow_html=True)
with col_ctx2:
    op_label = f"👤 {operador_activo['nombre']}" + (f" ({operador_activo['cargo']})" if operador_activo.get("cargo") else "") if operador_activo else "⚪ Sin operador (Safe Passivity / Manual)"
    op_color = "#10B981" if operador_activo else "#94A3B8"
    st.markdown(f"""
        <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-left: 4px solid {op_color}; border-radius: 8px; padding: 0.65rem 0.9rem; margin-bottom: 1rem; box-shadow: 0 1px 4px rgba(0,0,0,0.03);">
            <div style="font-size: 0.72rem; color: #64748B; font-weight: 700; text-transform: uppercase;">👤 Diligenciado Por</div>
            <div style="font-size: 0.95rem; color: #0F172A; font-weight: 700;">{op_label}</div>
        </div>
    """, unsafe_allow_html=True)

# 6. Zona de Carga Principal
st.markdown("### 📥 Cargar Formulario de Terceros")

uploaded_file = st.file_uploader(
    "Arrastra y suelta tu archivo Excel (.xlsx, .xlsm, .xls) aquí",
    type=["xlsx", "xls", "xlsm"],
    help="Sube la plantilla de licitación o formulario del proveedor para iniciar el diligenciamiento automático.",
)

if uploaded_file is not None:
    file_name = uploaded_file.name
    file_type = file_name.split(".")[-1].lower()

    es_archivo_autoform = "_autoform" in file_name.lower()
    if es_archivo_autoform:
        st.warning(
            f"⚠️ **Atención:** Has subido un archivo que parece haber sido generado previamente por AutoForm AI (`{file_name}`). "
            "Para un diligenciamiento limpio desde cero y evitar solapamientos de valores ya inyectados, sube la **plantilla original en blanco** (ej: `FMCA07J.- 6.2.xlsx`)."
        )
    st.markdown(f"""
        <div style="background: #ECFDF5; border: 1px solid #10B981; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.25rem; color: #065F46; font-weight: 600; font-size: 0.92rem;">
            ✅ Archivo listo para procesar: <strong>{file_name}</strong> ({(uploaded_file.size/1024):.1f} KB)
        </div>
    """, unsafe_allow_html=True)

    col_preview, col_actions = st.columns([2, 1], gap="medium")

    with col_preview:
        st.markdown("### 👀 Previsualización de Hojas")

        if file_type in ["xlsx", "xls", "xlsm"]:
            try:
                uploaded_file.seek(0)
                excel_file = pd.ExcelFile(uploaded_file)
                sheet_names = excel_file.sheet_names

                selected_sheet = st.selectbox("Seleccionar Hoja:", sheet_names)
                uploaded_file.seek(0)
                df = pd.read_excel(uploaded_file, sheet_name=selected_sheet, header=None)

                # Conversión Arrow-safe en preview: nombres de columna str y celdas limpias
                df_display = df.copy()
                df_display.columns = [f"Col {c+1}" for c in range(len(df_display.columns))]
                df_display = df_display.fillna("").astype(str)
                st.dataframe(df_display, width="stretch", height=380)
            except Exception as e:
                st.error(f"Error al leer el archivo Excel: {e}")

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
            if file_type in ["xlsx", "xls", "xlsm"]:
                tiene_azure = bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY"))
                tiene_openai = bool(os.getenv("OPENAI_API_KEY"))

                if not tiene_azure and not tiene_openai:
                    st.error("Configura tus credenciales de Azure OpenAI u OPENAI_API_KEY en tu archivo .env para ejecutar la IA.")
                    st.stop()

                progress_placeholder = st.empty()
                try:
                    uploaded_file.seek(0)
                    archivo_bytes = uploaded_file.read()

                    # Fusión no invasiva de operador activo en datos_empresa (ADR-0007)
                    datos_empresa_efectivos = profile_manager.fusionar_operador_en_datos_empresa(
                        datos_empresa,
                        operador=operador_activo,
                    )

                    ctx = PipelineContext(
                        archivo_bytes=archivo_bytes,
                        nombre_archivo=file_name,
                        datos_empresa=datos_empresa_efectivos,
                    )

                    def callback_progreso(msg: str, pct: float):
                        paso = min(3, int(pct * 3) + 1)
                        progress_placeholder.markdown(render_stepper_progress(paso, int(pct * 100), msg), unsafe_allow_html=True)

                    # 1. Análisis Semántico y Validador Determinista (HSP)
                    ctx = PipelineOrchestrator.analizar_formulario(ctx, on_progress=callback_progreso)

                    # 2. Inyección Directa 1-Click (Ponytail: Zero friction, 100% deterministic safety)
                    callback_progreso("⚡ Inyectando datos en el documento y preservando formato...", 0.9)
                    ctx = PipelineOrchestrator.rellenar_formulario(ctx)

                    progress_placeholder.empty()

                    # Limpiar estados de tablas de verificación previas
                    for k in list(st.session_state.keys()):
                        if "master_df" in k or "data_editor" in k or "search_input" in k or "vista_filter" in k:
                            del st.session_state[k]

                    st.session_state["pipeline_ctx"] = ctx
                    st.session_state["processed_file_id"] = current_file_id
                    _safe_rerun()

                except Exception as e:
                    progress_placeholder.empty()
                    st.error(f"⚠️ Se produjo un error durante el procesamiento: {str(e)}")
                    with st.expander("Ver detalles técnicos del error"):
                        st.text(traceback.format_exc())

    # ── Renderizado del Pipeline Modular (Descarga Directa + Auditoría Opcional) ──
    if st.session_state.get("pipeline_ctx") is not None and st.session_state.get("processed_file_id") == current_file_id:
        pipeline_context: PipelineContext = st.session_state["pipeline_ctx"]

        if pipeline_context.archivo_resultado:
            st.markdown("---")
            render_pantalla_descarga(pipeline_context, key_prefix="app1_main_flow")

            # Acordeón opcional colapsado si el usuario desea inspeccionar o ajustar celdas
            with st.expander("🔍 Auditoría Detallada y Ajuste Manual de Campos (Opcional)", expanded=False):
                confirmado, plan_verificado = render_pantalla_verificacion(pipeline_context, key_prefix="app1_audit_flow")
                if confirmado:
                    with st.spinner("⚡ Re-inyectando datos actualizados en el documento..."):
                        pipeline_context = PipelineOrchestrator.rellenar_formulario(pipeline_context)
                        st.session_state["pipeline_ctx"] = pipeline_context
                        _safe_rerun()

            if st.button("🔄 Diligenciar Otro Formulario", key="app1_btn_restart_doc"):
                del st.session_state["pipeline_ctx"]
                _safe_rerun()

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

