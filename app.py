import os
import json
import uuid
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUTA_ENV = os.path.join(BASE_DIR, ".env")
load_dotenv(RUTA_ENV, encoding="utf-8-sig", override=True)

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

CACHE_DIR = os.path.join(BASE_DIR, "static", "cache")
DECKS_FILE = os.path.join(BASE_DIR, "decks.json")
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {"User-Agent": "MultiTCGApp/2.5"}

MEMORIA_FFTCG = []
MEMORIA_FAB = []
MODELOS_GROQ_CACHE = []

REGLAS_JUEZ_POR_JUEGO = {
    "yugioh": (
        "Sos un Juez Oficial Nivel 3 de Konami para Yu-Gi-Oh! TCG. "
        "Analizá estrictamente el PSCT (Problem-Solving Card Text) en inglés de las cartas involucradas: "
        "distinguí Costo (antes de ';') vs Efecto, condiciones de activación (':'), "
        "efectos 'When... you can' (pueden perder el timing si no son el último evento en ocurrir) vs 'If... you can', "
        "Spell Speed (1, 2, 3), resolución de cadenas (CL1, CL2, SEGOC), restricciones del Damage Step y si selecciona (targets) o no."
    ),
    "digimon": (
        "Sos un Juez Oficial de Bandai para Digimon Card Game. "
        "Aplicá las reglas actuales: el jugador en turno tiene prioridad para resolver sus efectos disparados simultáneos primero, "
        "los efectos [On Play] / [When Digivolving] recién generados toman prioridad (LIFO), verificá el Memory Gauge (el turno pasa solo cuando todos los efectos pendientes terminan de resolver y la memoria está del lado rival) y reglas de Deletion/Battle."
    ),
    "magic": (
        "Sos un Juez Nivel 3 de Magic: The Gathering. "
        "Aplicá las Comprehensive Rules actuales: funcionamiento de la Pila (The Stack - LIFO), pase de Prioridad, "
        "State-Based Actions (SBAs), diferencia entre habilidades activadas, disparadas y de reemplazo, y fases de combate."
    ),
    "vanguard": (
        "Sos un Juez Oficial de Bushiroad para Cardfight!! Vanguard (Standard / OverDress / Divinez). "
        "Aplicá las reglas de resolución de habilidades AUTO en espera, costos (Counter Blast, Soul Blast, Energy Blast), "
        "pasos de batalla (Guard Step, Drive Check, Overtrigger) y Persona Ride."
    ),
    "fftcg": (
        "Sos un Juez Oficial de Final Fantasy TCG (Square Enix). "
        "Aplicá las reglas de la Stack, pago de CP (Crystal Points) descartando cartas o haciendo Dull a Backups, "
        "Field Abilities vs Auto-Abilities vs Action Abilities, EX Bursts y resolución de daño/combate."
    ),
    "fab": (
        "Sos un Juez Oficial de Legend Story Studios para Flesh and Blood TCG. "
        "Aplicá las Comprehensive Rules actuales: Combat Chain (Layer, Attack, Defend, Reaction, Damage, Resolution, Close Step), "
        "Go Again, prioridad en el Reaction Step, Arcane Barrier y equipamiento."
    )
}


def a_entero(valor):
    try:
        return int(valor)
    except (ValueError, TypeError):
        return 0


def a_flotante(valor):
    try:
        return float(valor)
    except (ValueError, TypeError):
        return 0.0


def cargar_mazos():
    if not os.path.exists(DECKS_FILE):
        return []
    try:
        with open(DECKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def guardar_mazos_disco(mazos):
    with open(DECKS_FILE, "w", encoding="utf-8") as f:
        json.dump(mazos, f, ensure_ascii=False, indent=2)


def guardar_imagen_cache(card_id, url_remota):
    if not url_remota:
        return ""
    id_limpio = "".join(c for c in str(card_id) if c.isalnum() or c in ("_", "-"))
    nombre_archivo = f"{id_limpio}.jpg"
    ruta_completa = os.path.join(CACHE_DIR, nombre_archivo)

    if not os.path.exists(ruta_completa):
        try:
            r = requests.get(url_remota, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                with open(ruta_completa, "wb") as f:
                    f.write(r.content)
            else:
                return url_remota
        except Exception:
            return url_remota

    return f"/static/cache/{nombre_archivo}"


def formatear_carta_yugioh(c):
    raw_id = str(c["id"])
    tipo = c.get("type", "")
    es_extra = any(x in tipo for x in ["Fusion", "Synchro", "XYZ", "Link"])
    if "Monster" in tipo:
        cat = "Monstruo"
    elif "Spell" in tipo:
        cat = "Magia"
    elif "Trap" in tipo:
        cat = "Trampa"
    else:
        cat = "Otro"

    nivel = c.get("level") or c.get("rank") or c.get("linkval") or 0
    precios = c.get("card_prices", [{}])[0]
    precio_usd = a_flotante(precios.get("tcgplayer_price") or precios.get("cardmarket_price") or 0.0)
    ban_info = c.get("banlist_info", {}).get("ban_tcg", "Unlimited")

    id_unico = f"YGO_{raw_id}"
    imagenes = c.get("card_images", [{}])
    img = imagenes[0].get("image_url_small") or imagenes[0].get("image_url", "")

    return {
        "id": id_unico,
        "raw_id": raw_id,
        "name": c.get("name", ""),
        "game": "yugioh",
        "zone": "secondary" if es_extra else "main",
        "category": cat,
        "cost": a_entero(nivel),
        "power": a_entero(c.get("atk")),
        "price": precio_usd,
        "ban_status": ban_info,
        "type_line": f"{tipo} / {c.get('race', '')} ({c.get('attribute', 'SPELL/TRAP')})",
        "desc": c.get("desc", ""),
        "image": guardar_imagen_cache(id_unico, img)
    }


@app.route("/")
def inicio():
    return render_template("index.html")


@app.route("/api/decks", methods=["GET"])
def obtener_decks():
    return jsonify(cargar_mazos())


@app.route("/api/decks", methods=["POST"])
def guardar_deck():
    datos = request.json or {}
    mazos = cargar_mazos()
    deck_id = datos.get("id")

    if deck_id:
        for i, m in enumerate(mazos):
            if m.get("id") == deck_id:
                mazos[i] = datos
                break
        else:
            mazos.append(datos)
    else:
        datos["id"] = str(uuid.uuid4())[:8]
        mazos.append(datos)

    guardar_mazos_disco(mazos)
    return jsonify(datos)


@app.route("/api/decks/<deck_id>", methods=["DELETE"])
def eliminar_deck(deck_id):
    mazos = [m for m in cargar_mazos() if m.get("id") != deck_id]
    guardar_mazos_disco(mazos)
    return jsonify({"ok": True})


# --- ENDPOINT DEL JUEZ DE DUELOS IA (GROQ + FALLBACK GEMINI) ---
@app.route("/api/juez", methods=["POST"])
def consultar_juez():
    global MODELOS_GROQ_CACHE
    load_dotenv(RUTA_ENV, encoding="utf-8-sig", override=True)

    datos = request.json or {}
    juego = datos.get("juego", "yugioh")
    pregunta = datos.get("pregunta", "").strip()
    contexto_cartas = datos.get("contexto_cartas", "")

    if not pregunta:
        return jsonify({"respuesta": "Escribí tu duda de ruling o interacción para que pueda ayudarte."}), 400

    regla_base = REGLAS_JUEZ_POR_JUEGO.get(juego, REGLAS_JUEZ_POR_JUEGO["yugioh"])
    system_prompt = (
        f"{regla_base}\n\n"
        "INSTRUCCIONES DE FORMATO:\n"
        "1. Respondé SIEMPRE en español claro, pero mantené los nombres de cartas y términos técnicos clave en inglés.\n"
        "2. Empezá siempre con un '**Veredicto Rápido:**' (Sí se puede / No se puede / Cómo resuelve en 1 o 2 oraciones) para no demorar el duelo.\n"
        "3. Luego agregá '**Explicación de Reglas (Ruling):**' explicando paso a paso por qué ocurre así según el texto de las cartas y las mecánicas del juego.\n"
    )
    if contexto_cartas:
        system_prompt += f"\nTEXTO OFICIAL DE CARTAS EN EL MAZO/BÚSQUEDA ACTUAL DEL JUGADOR:\n{contexto_cartas}\n"

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    error_detalle = ""

    # 1. INTENTO PRINCIPAL CON GROQ
    if groq_key:
        try:
            headers_groq = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }

            if not MODELOS_GROQ_CACHE:
                try:
                    r_mod = requests.get("https://api.groq.com/openai/v1/models", headers=headers_groq, timeout=8)
                    if r_mod.status_code == 200:
                        disponibles = [
                            m["id"] for m in r_mod.json().get("data", [])
                            if not any(x in m["id"].lower() for x in ["whisper", "guard", "tts", "vision", "audio"])
                        ]
                        preferidos = [m for m in disponibles if any(k in m.lower() for k in ["70b", "llama", "deepseek", "qwen"])]
                        MODELOS_GROQ_CACHE = preferidos + [m for m in disponibles if m not in preferidos]
                except Exception as e_mod:
                    print(f"Aviso al listar modelos de Groq: {e_mod}")

            modelos_candidatos = MODELOS_GROQ_CACHE or [
                "llama-3.1-8b-instant",
                "llama3-70b-8192",
                "llama3-8b-8192",
                "gemma2-9b-it"
            ]

            for modelo_actual in modelos_candidatos[:4]:
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers_groq,
                    json={
                        "model": modelo_actual,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": pregunta}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 900
                    },
                    timeout=15
                )
                if r.status_code == 200:
                    texto = r.json()["choices"][0]["message"]["content"]
                    return jsonify({"respuesta": texto, "motor": f"Groq ({modelo_actual})"})
                else:
                    error_detalle = f"Modelo {modelo_actual} devolvió {r.status_code}: {r.text}"
        except Exception as e:
            error_detalle = str(e)
            print(f"Excepción en Groq: {e}")

    # 2. RESPALDO AUTOMÁTICO CON GEMINI
    if gemini_key:
        try:
            url_gem = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            r = requests.post(
                url_gem,
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": pregunta}]}],
                    "generationConfig": {"temperature": 0.2}
                },
                timeout=15
            )
            if r.status_code == 200:
                texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return jsonify({"respuesta": texto, "motor": "Gemini 2.5 Flash"})
        except Exception as e:
            print(f"Error en Gemini: {e}")

    return jsonify({
        "respuesta": (
            f"⚠️ **No se pudo conectar al Juez IA.**\n\n"
            f"- ¿Leyó GROQ_API_KEY del .env?: **{'SÍ (' + groq_key[:8] + '...)' if groq_key else 'NO (está vacía)'}**\n"
            f"- Detalle técnico: `{error_detalle or 'Clave no encontrada'}`"
        ),
        "motor": "Diagnóstico"
    })


# --- ENDPOINT PARA IMPORTAR ARCHIVOS .YDK DE YU-GI-OH! ---
@app.route("/api/importar_ydk", methods=["POST"])
def importar_ydk():
    datos = request.json or {}
    contenido = datos.get("contenido", "")
    if not contenido:
        return jsonify({"error": "Archivo vacío"}), 400

    main_ids = []
    extra_ids = []
    seccion = None

    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if linea.startswith("#main"):
            seccion = "main"
        elif linea.startswith("#extra"):
            seccion = "extra"
        elif linea.startswith("!side"):
            seccion = "side"
        elif not linea.startswith("#"):
            # Algunos .ydk traen ceros a la izquierda; los normalizamos
            limpio = linea.lstrip("0")
            if limpio.isdigit():
                if seccion == "main":
                    main_ids.append(limpio)
                elif seccion == "extra":
                    extra_ids.append(limpio)

    todos_unicos = list(set(main_ids + extra_ids))
    if not todos_unicos:
        return jsonify({"main": [], "secondary": []})

    ids_param = ",".join(todos_unicos)
    url = f"https://db.ygoprodeck.com/api/v7/cardinfo.php?id={ids_param}"
    mapa_cartas = {}

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            for c in r.json().get("data", []):
                carta_obj = formatear_carta_yugioh(c)
                mapa_cartas[str(c["id"])] = carta_obj
                # Mapear también IDs de artes alternativos (card_images)
                for img_item in c.get("card_images", []):
                    if "id" in img_item:
                        mapa_cartas[str(img_item["id"])] = carta_obj
    except Exception as e:
        print(f"Error importando YDK: {e}")

    main_armado = [mapa_cartas[i] for i in main_ids if i in mapa_cartas]
    extra_armado = [mapa_cartas[i] for i in extra_ids if i in mapa_cartas]

    return jsonify({"main": main_armado, "secondary": extra_armado})


# --- ENDPOINT DE BÚSQUEDA MULTI-TCG ---
@app.route("/api/buscar")
def buscar():
    juego = request.args.get("juego", "yugioh")
    nombre = request.args.get("q", "").strip()

    if not nombre:
        return jsonify([])

    cartas = []

    try:
        # 1. YU-GI-OH!
        if juego == "yugioh":
            url = f"https://db.ygoprodeck.com/api/v7/cardinfo.php?fname={nombre}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for c in r.json().get("data", [])[:40]:
                    cartas.append(formatear_carta_yugioh(c))

        # 2. DIGIMON TCG
        elif juego == "digimon":
            url = f"https://digimoncard.io/api-public/search.php?n={nombre}&series=Digimon Card Game"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and isinstance(r.json(), list):
                for idx, c in enumerate(r.json()[:40]):
                    codigo = c.get("cardnumber") or c.get("id") or f"unk_{idx}"
                    id_unico = f"DGM_{codigo}"
                    img = c.get("image_url") or f"https://images.digimoncard.io/images/cards/{codigo}.jpg"
                    tipo = c.get("type", "Digimon")
                    es_egg = (tipo == "Digi-Egg")

                    cartas.append({
                        "id": id_unico,
                        "raw_id": str(codigo),
                        "name": c.get("name", "Digimon"),
                        "game": "digimon",
                        "zone": "secondary" if es_egg else "main",
                        "category": tipo,
                        "cost": a_entero(c.get("level") or c.get("play_cost")),
                        "power": a_entero(c.get("dp")),
                        "price": 0.0,
                        "ban_status": "Unlimited",
                        "type_line": f"{tipo} / {c.get('color', '')} (Lv.{c.get('level', '-')})",
                        "desc": c.get("maineffect") or c.get("soureeffect") or "No effect",
                        "image": guardar_imagen_cache(id_unico, img)
                    })

        # 3. MAGIC: THE GATHERING
        elif juego == "magic":
            url = f"https://api.scryfall.com/cards/search?q={nombre}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for c in r.json().get("data", [])[:40]:
                    img = c.get("image_uris", {}).get("normal", "")
                    if not img and "card_faces" in c:
                        img = c["card_faces"][0].get("image_uris", {}).get("normal", "")
                    if not img:
                        continue

                    t_line = c.get("type_line", "")
                    if "Creature" in t_line:
                        cat = "Criatura"
                    elif "Land" in t_line:
                        cat = "Tierra"
                    elif "Instant" in t_line or "Sorcery" in t_line:
                        cat = "Hechizo"
                    else:
                        cat = "Otro"

                    precio_raw = c.get("prices", {}).get("usd") or c.get("prices", {}).get("usd_foil") or 0.0
                    id_unico = f"MTG_{c['id']}"

                    cartas.append({
                        "id": id_unico,
                        "raw_id": str(c.get("collector_number", "")),
                        "name": c.get("name", ""),
                        "game": "magic",
                        "zone": "main",
                        "category": cat,
                        "cost": a_entero(c.get("cmc")),
                        "power": a_entero(c.get("power")),
                        "price": a_flotante(precio_raw),
                        "ban_status": "Unlimited",
                        "type_line": t_line,
                        "desc": c.get("oracle_text", ""),
                        "image": guardar_imagen_cache(id_unico, img)
                    })

        # 4. CARDFIGHT!! VANGUARD
        elif juego == "vanguard":
            url = f"https://card-fight-vanguard-api.ue.r.appspot.com/api/v1/cards?name={nombre}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for c in r.json().get("data", [])[:40]:
                    id_unico = f"CFV_{c.get('id')}"
                    grado_num = a_entero(c.get("grade"))
                    poder_num = a_entero(c.get("power"))
                    cartas.append({
                        "id": id_unico,
                        "raw_id": str(c.get("id", "")),
                        "name": c.get("name", ""),
                        "game": "vanguard",
                        "zone": "secondary" if grado_num >= 4 else "main",
                        "category": f"Grado {grado_num}",
                        "cost": grado_num,
                        "power": poder_num,
                        "price": 0.0,
                        "ban_status": "Unlimited",
                        "type_line": f"Grade {grado_num} / {c.get('clan', '')}",
                        "desc": c.get("effect", ""),
                        "image": guardar_imagen_cache(id_unico, c.get("imageurl", ""))
                    })

        # 5. FINAL FANTASY TCG
        elif juego == "fftcg":
            global MEMORIA_FFTCG
            if not MEMORIA_FFTCG:
                r = requests.get("https://ffdecks.com/api/cards/basic", headers=HEADERS, timeout=15)
                if r.status_code == 200:
                    MEMORIA_FFTCG = r.json().get("cards", [])

            termino_low = nombre.lower()
            coincidencias = [c for c in MEMORIA_FFTCG if termino_low in c.get("name", "").lower()][:40]
            for c in coincidencias:
                codigo = c.get("serial_number", "FF")
                id_unico = f"FF_{codigo}"
                cartas.append({
                    "id": id_unico,
                    "raw_id": str(codigo),
                    "name": f"{c.get('name')} ({codigo})",
                    "game": "fftcg",
                    "zone": "main",
                    "category": c.get("type", "Forward"),
                    "cost": a_entero(c.get("cost")),
                    "power": a_entero(c.get("power")),
                    "price": 0.0,
                    "ban_status": "Unlimited",
                    "type_line": f"{c.get('type', '')} / {', '.join(c.get('elements', []))}",
                    "desc": c.get("abilities", ""),
                    "image": guardar_imagen_cache(id_unico, c.get("image", ""))
                })

        # 6. FLESH AND BLOOD
        elif juego == "fab":
            global MEMORIA_FAB
            if not MEMORIA_FAB:
                url_fab = "https://raw.githubusercontent.com/the-fab-cube/flesh-and-blood-cards/develop/json/english/card.json"
                r = requests.get(url_fab, headers=HEADERS, timeout=20)
                if r.status_code == 200:
                    MEMORIA_FAB = r.json()

            termino_low = nombre.lower()
            for c in MEMORIA_FAB:
                if termino_low in c.get("name", "").lower():
                    printings = c.get("printings", [])
                    img = next((p.get("image_url") for p in printings if p.get("image_url")), "")
                    if not img:
                        continue
                    codigo = c.get("unique_id", "FAB")
                    id_unico = f"FAB_{codigo}"
                    tipos = c.get("types", [])
                    es_sec = any(t in tipos for t in ["Hero", "Weapon", "Equipment"])
                    pitch = c.get("pitch", "")
                    cartas.append({
                        "id": id_unico,
                        "raw_id": str(codigo),
                        "name": f"{c.get('name')}" + (f" (Pitch {pitch})" if pitch else ""),
                        "game": "fab",
                        "zone": "secondary" if es_sec else "main",
                        "category": tipos[0] if tipos else "Action",
                        "cost": a_entero(c.get("cost")),
                        "power": a_entero(c.get("power")),
                        "price": 0.0,
                        "ban_status": "Unlimited",
                        "type_line": ", ".join(tipos),
                        "desc": c.get("functional_text_plain", ""),
                        "image": guardar_imagen_cache(id_unico, img)
                    })
                    if len(cartas) >= 40:
                        break

    except Exception as e:
        print(f"Error en búsqueda de {juego}: {e}")

    return jsonify(cartas)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)