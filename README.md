# 🃏 Multi-TCG Deck Studio & AI Judge

Plataforma web local para construcción competitiva de mazos, análisis estadístico y asistencia de arbitraje con Inteligencia Artificial en tiempo real para **6 juegos de cartas coleccionables (TCG)**.

## 🎮 Juegos Soportados
- **Yu-Gi-Oh! TCG** (YGOPRODeck API + Importación/Exportación nativa `.ydk` + Banlist)
- **Digimon Card Game** (DigimonCard.io API + Memory Gauge interactivo)
- **Magic: The Gathering** (Scryfall API)
- **Cardfight!! Vanguard** (Vanguard API)
- **Final Fantasy TCG** (FFDecks API)
- **Flesh and Blood** (The Fab Cube Dataset)

## 🚀 Características Principales
- **Armador Inteligente:** Agrupación automática por copias (`x1` a `x4`), soporte completo para **Main Deck, Extra/Secondary Deck y Side Deck**, y caché local de imágenes.
- **Métricas y Probabilidad Hipergeométrica:** Cálculo de presupuesto en USD en tiempo real, curva de costos, simulador de mano inicial y calculadora hipergeométrica exacta (Anti-Brick).
- **⚖️ Juez Oficial IA (Groq / Gemini):** Resolución de cadenas, timings y rulings complejos basados en el reglamento oficial de cada juego y el texto exacto en inglés de tu mazo activo.
- **🧠 Coach Competitivo IA:** Diagnóstico automático de sinergias, condición de victoria, puntos débiles y sugerencias de optimización.
- **⚔️ Mesa de Duelo en Vivo:** Calculadora de LP para 2 jugadores, Memory Gauge para Digimon, dados D6/D20, moneda y reloj de ronda oficial.

## 🛠️ Instalación y Uso
1. Crear y activar el entorno virtual:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt