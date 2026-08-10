---
name: modern-web-design-master
description: Guía maestra de buenas prácticas, diseño web moderno (UI/UX) y arquitectura de interfaces de alta gama. Define estándares de accesibilidad WCAG AA, la regla 60-30-10 de color, tipografía modular, micro-interacciones, diseño responsivo y optimización de Web Vitals.
---

# 🚀 Skill: Modern Web Design Master & UI/UX Standards

Esta skill establece la guía definitiva de buenas prácticas para diseñar e implementar aplicaciones web y sitios digitales modernos, atractivos, accesibles y de altísima calidad visual y técnica.

---

## 🎨 1. Composición Cromática y Regla 60-30-10

Para lograr interfaces limpias, profesionales y sin saturación visual, aplica siempre la **Regla 60-30-10**:

- **60% Color Dominante (Base/Fondo)**: Blanco (`#FFFFFF`), Gris Neutro (`#F8FAFC`) o Dark Slate (`#121212`). Proporciona descanso visual y espacio negativo.
- **30% Color Secundario (Estructura y Marca)**: Tonos de marca (ej. Azul Corporativo, Amarillo IAC `#F8B126`). Define bordes, tarjetas, encabezados, divisores y elementos de contexto.
- **10% Color de Acento / CTA (Acción)**: Color vibrante de alto contraste (ej. Naranja `#FF6B00`, Verde Éxito `#10B981`). Reservado **exclusivamente** para acciones principales (botones de envío, descargas, acciones críticas).

---

## ✒️ 2. Tipografía y Jerarquía Visual

1. **Familias Tipográficas Recomendadas**:
   - UI Moderna / Dashboard: `Inter`, `Segoe UI`, `System-UI`.
   - Marca / Títulos Impactantes: `Montserrat`, `Outfit`, `Poppins`.
   - Código / Datos Técnicos: `Fira Code`, `JetBrains Mono`.

2. **Escala Modular de Tamaños**:
   - `H1 (Hero / Título Principal)`: 2.2rem - 2.8rem (Weight 700 / 800)
   - `H2 (Títulos de Sección)`: 1.5rem - 1.8rem (Weight 700)
   - `H3 (Subsecciones / Tarjetas)`: 1.2rem - 1.35rem (Weight 600)
   - `Body (Texto Principal)`: 1rem (16px) — Line-height 1.6
   - `Small / Captions`: 0.85rem (13.5px) — Line-height 1.4

3. **Regla de Contraste**: El texto debe mantener un ratio mínimo de **4.5:1** sobre su fondo correspondiente (Cumplimiento WCAG 2.1 AA).

---

## 🧩 3. Estilo de Componentes UI Modernos

### Tarjetas Elevadas (Card Containers)
- Fondo blanco (`#FFFFFF`) con bordes sutiles `1px solid #E2E8F0`.
- Radio de borde moderado: `border-radius: 10px`.
- Sombra sutil por defecto: `box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03)`.
- Micro-animación en hover: `transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);`.

### Botones de Acción (CTA Buttons)
- **Botón Primario**: Fondo degradado suave en color de acento, texto blanco en negrita (`font-weight: 700`), `border-radius: 8px`, sombra `0 4px 14px rgba(...)`.
- **Botón Secundario**: Fondo neutro o transparente, borde `1.5px solid`, texto en color secundario o marca.
- **Estado Disabled**: Opacidad `0.5`, cursor `not-allowed`, sin eventos hover.

### Badges e Indicadores de Estado
- Estilo Pill: `border-radius: 20px`, relleno interno `0.35rem 0.85rem`.
- Combinación suave de colores pastel (fondo claro + texto oscuro intenso).

---

## 💻 4. Estructura de Tokens CSS (`:root`)

Todo proyecto moderno debe centralizar sus variables en un bloque `:root`:

```css
:root {
  /* Marca & Acentos */
  --color-primary: #046BD2;
  --color-primary-hover: #045CB4;
  --color-accent-cta: #FF6B00;
  --color-accent-cta-hover: #E65100;
  --color-brand-yellow: #F8B126;

  /* Neutros & Superficies */
  --bg-app: #F8FAFC;
  --bg-surface: #FFFFFF;
  --bg-dark-header: #121212;
  
  /* Textos */
  --text-main: #1E293B;
  --text-muted: #64748B;
  --text-light: #F8FAFC;

  /* Bordes & Sombras */
  --border-light: #E2E8F0;
  --radius-card: 10px;
  --radius-button: 8px;
  --shadow-card: 0 4px 12px rgba(0, 0, 0, 0.03);
  --shadow-cta: 0 4px 14px rgba(255, 107, 0, 0.35);
  
  /* Transiciones */
  --transition-fast: all 0.15s ease;
  --transition-normal: all 0.25s ease;
}
```

---

## 📱 5. Responsive Design & Mobile-First

- Diseña contemplando breakpoints estándar:
  - `Mobile`: `< 640px` (Layout de 1 columna, paddings compactos).
  - `Tablet`: `640px - 1024px` (Grid flexible de 2 columnas).
  - `Desktop`: `> 1024px` (Layout completo multisectorial con sidebar/hero).
- Usa unidades relativas (`rem`, `%`, `vw`, `vh`) en lugar de píxeles fijos para dimensiones contenedoras.

---

## ⚡ 6. Lista de Chequeo de Calidad (UI/UX QA Checklist)

Antes de dar por completado cualquier desarrollo de interfaz, verifica:

- [ ] **WCAG AA**: ¿Los textos y botones cumplen con la tasa de contraste requerida?
- [ ] **Jerarquía Visual**: ¿Destacan claramente los títulos sobre el texto de cuerpo?
- [ ] **Feedback al Usuario**: ¿El sistema muestra loaders (`st.spinner`, progress bar, estados de carga) durante operaciones asíncronas?
- [ ] **Micro-interacciones**: ¿Los botones e interactivos tienen respuesta visual al pasar el cursor (`:hover`, `:active`)?
- [ ] **Sin Marcadores de Posición Raros**: ¿Se utilizan textos reales o datos de demostración limpios en lugar de textos basura?
