# Especificación de Diseño Visual UI/UX — Sistema de Diseño IAC Latam (Opción A)

**Fecha**: 2026-08-10  
**Proyecto**: AutoForm AI  
**Objetivo**: Elevar la calidad visual, respuesta adaptativa y consistencia de la interfaz de usuario (`app1.py`) sin alterar la funcionalidad ni la lógica de negocio.

---

## 🎨 1. Sistema de Tokens CSS (`:root`)

Se establece la centralización de tokens de diseño bajo la regla cromática **60-30-10**:

- **60% Dominante (Fondo y Superficies)**:
  - `--bg-app`: `#F8FAFC` (Slate 50, descanso visual positivo).
  - `--bg-surface`: `#FFFFFF` (Superficie limpia de tarjetas e inputs).
- **30% Secundario (Marca y Estructura)**:
  - `--brand-black`: `#121212` (Header institucional y tipografía principal).
  - `--brand-yellow`: `#F8B126` (Amarillo IAC Latam, bordes de acento y estructura).
  - `--border-color`: `#E2E8F0` (Bordes sutiles para tarjetas y separadores).
- **10% Acento / CTA (Acciones)**:
  - `--accent-orange`: `#FF6B00` (Naranja Corporativo IAC para botones primarios y barra de progreso).
  - `--accent-orange-hover`: `#E65100` (Estado hover de botones).
  - `--accent-green`: `#10B981` (Confirmaciones y estado exitoso).

---

## 🧱 2. Componentes Visuales Rediseñados

### A. Header Hero Responsive
- Layout flexible con `@media (max-width: 768px)` para evitar colisiones del badge `"MOTOR GEMINI 2.0 FLASH ACTIVE"` en móviles o pantallas reducidas.
- Tipografía Montserrat en `h1` con span destacado en Amarillo IAC.

### B. Tarjetas (`.iac-card`) y Expansores (`st.expander`)
- Radio de borde unificado: `10px`.
- Sombras sutiles: `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03)`.
- Micro-interacción hover: `transform: translateY(-2px); box-shadow: 0 6px 16px rgba(248, 177, 38, 0.15);`.
- Personalización de los expansores de Streamlit (`[data-testid="stExpander"]`) para alinearlos con el tema visual de IAC Latam.

### C. Inputs y Form Controls
- Bordes interactivos en `st.text_input` y `st.selectbox` que se iluminan al recibir el foco.

### D. Alertas y Notificaciones (`.iac-alert-*`)
- `.iac-alert-success`: Borde verde `#10B981`, fondo `#ECFDF5`.
- `.iac-alert-cache`: Borde azul `#3B82F6`, fondo `#EFF6FF` (para el HIT del Caché Semántico).
- `.iac-alert-warning`: Borde amarillo `#F8B126`, fondo `#FEF3C7`.

### E. Estado Vacío (*Empty State*)
- Presentación limpia y atractiva cuando aún no se ha cargado un archivo Excel/PDF, guiando al usuario con íconos e instrucciones claras.

---

## 🔒 3. Garantías de Preservación
- Cero modificaciones a la lógica de negocio (`mapper.py`, `excel_parser.py`, `excel_writer.py`, `llm_client.py`).
- Mantenimiento estricto del estado de la sesión (`st.session_state`) y del flujo de diligenciamiento de formularios.
