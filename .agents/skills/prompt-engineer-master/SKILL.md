---
name: prompt-engineer-master
description: "Guía Maestra para el Diseño, Optimización e Ingeniería de Prompts para todo tipo de modelos de IA (LLMs, Generación de Código, JSON Estructurado, Vision, Razonamiento CoT e Imágenes). Utilízalo para crear, auditar o refinar prompts altamente efectivos."
---

# 🧠 Prompt Engineer Master — Guía Universal de Ingeniería de Prompts

Esta habilidad proporciona patrones, arquitecturas, plantillas y mejores prácticas para diseñar prompts profesionales para cualquier tipo de modelo de Inteligencia Artificial (OpenAI GPT, Google Gemini, Anthropic Claude, DeepSeek, LLaMA, Midjourney, DALL-E).

---

## 📌 1. Anatomía de un Prompt Perfecto (El Marco R-C-T-O)

Todo prompt robusto y de alto rendimiento debe estructurarse utilizando el marco **R-C-T-O**:

1. **R - Rol / Persona:** Quién es el modelo (experiencia, tono, dominio técnico).
2. **C - Contexto & Antecedentes:** Información de fondo, datos de entrada o estado actual del proyecto.
3. **T - Tarea / Instrucción:** La acción exacta que debe realizar el modelo (verbos en imperativo).
4. **O - Output / Formato de Salida:** Esquema esperado (JSON, Tabla Markdown, Código puro, XML).
5. **C - Restricciones (Constraints):** Lo que NUNCA debe hacer el modelo (Reglas negativas, límites de tokens, idioma).

---

## 🛠️ 2. Patrones por Tipo de Caso de Uso

### A. Prompts para Salida JSON Estructurada (JSON Mode / Pydantic)
Ideal para extracción de datos, clasificadores y pipelines backend.

```text
## ROL
Eres un motor de extracción de datos de precisión. Tu única función es transformar el texto de entrada en un objeto JSON válido.

## REGLAS STRICTAS DE FORMATO
1. Responde ÚNICAMENTE con JSON válido.
2. NO incluyas explicaciones, razonamientos ni bloques ```json ``` a menos que se solicite.
3. Si un campo no está presente en el texto, asigna `null` o cadena vacía `""`.
4. Respeta los tipos de datos: enteros como int, booleanos como true/false.

## ESQUEMA ESPERADO
{
  "campo_1": "string",
  "campo_2": 0,
  "es_valido": true
}
```

---

### B. Prompts de Sistema para Agentes de Código y Asistentes (System Prompt)
Para configurar asistentes conversacionales, agentes de coding y bots especializados.

```text
## IDENTIDAD Y OBJETIVO
Eres [Nombre], un Ingeniero Senior especializado en [Tecnología]. Tu objetivo es ayudar a los desarrolladores a construir software limpio, mantenible y seguro.

## PRINCIPIOS DE CÓDIGO
- Escribe código autocontenido, fuertemente tipado y sin placeholders (evita '// ... resto del código').
- Preserva las firmas de funciones y APIs existentes.
- Prioriza legibilidad y eficiencia.

## FLUJO DE TRABAJO
1. Analiza el problema y comprende los requisitos.
2. Explica brevemente la estrategia propuesta.
3. Proporciona el código completo en bloques Markdown con el lenguaje correspondiente.
```

---

### C. Prompts con Razonamiento Guiado (Chain-of-Thought / CoT)
Para tareas complejas de lógica, matemáticas, análisis legal o refactorización profunda.

```text
Por favor resuelve el siguiente problema utilizando el método paso a paso (Chain of Thought):

## PASOS A SEGUIR
1. Paso 1 - Análisis: Identifica las variables e hipótesis iniciales.
2. Paso 2 - Descomposición: Divide el problema en sub-problemas más pequeños.
3. Paso 3 - Evaluación: Considera 2 alternativas de solución y compara pros/contras.
4. Paso 4 - Conclusión: Presenta la solución final dentro de las etiquetas <respuesta_final>...</respuesta_final>.
```

---

### D. Prompts para Generación de Imágenes (Midjourney / DALL-E 3 / Imagen)
Para crear imágenes con alto impacto visual y realismo.

**Estructura:** `[Sujeto principal] + [Entorno/Escena] + [Estilo artístico/Fotográfico] + [Iluminación] + [Camara/Lente/Paleta de colores] + [Parámetros]`

**Ejemplo:**
> "A ultra-realistic cinematic portrait of a cybernetic software engineer working in a dimly lit neon lab, dark violet and amber gradient ambient lighting, 85mm lens, f/1.4, photorealistic, 8k resolution, highly detailed texture --ar 16:9 --v 6.0"

---

## ⛔ 3. Anti-Patrones a Evitar

| Anti-Patrón | ¿Por qué falla? | Alternativa Correcta |
| :--- | :--- | :--- |
| **Instrucciones Vagas** (*"Haz un buen resumen"*) | Alta variabilidad | *"Resume el texto en 3 puntos clave de máximo 15 palabras cada uno"* |
| **Negación Simple** (*"No seas largo"*) | El LLM atiende las palabras clave | *"Mantiene la respuesta acotada a menos de 100 palabras"* |
| **Falta de Ejemplos (Few-Shot)** | El modelo adivina el estilo | Incluir 1 o 2 ejemplos del par `Entrada -> Salida Esperada` |

---

## 🎯 4. Lista de Chequeo de Calidad (Audit Check)

Antes de desplegar cualquier prompt en producción, valida:
- [ ] ¿Está definido el rol o persona claramente?
- [ ] ¿El formato de salida está delimitado y sin ambigüedades?
- [ ] ¿Se especificó el idioma deseado?
- [ ] ¿Tiene restricciones negativas para evitar alucinaciones?
- [ ] Si es un modelo de razonamiento, ¿se especificó dónde colocar el JSON o resultado final?
