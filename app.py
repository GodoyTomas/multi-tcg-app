import os
import json
import uuid
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CACHE_DIR = os.path.join("static", "cache")
DECKS_FILE = "decks.json"
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {"User-Agent": "MultiTCGApp/2.0"}

MEMORIA_FFTCG = []
MEMORIA_FAB = []

# --- GESTIÓN DE MAZOS EN DISCO ---
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

# --- CACHÉ DE IMÁGENES ---
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

@app.route("/")
def inicio():
    return render_template("index.html")

# --- ENDPOINTS DE MAZOS ---
@app.route("/api/decks", methods=["GET"])
def obtener_decks():
    return jsonify(cargar_mazos())

@app.route("/api/decks", methods=["POST"])
def guardar_deck():
    datos = request.json
    mazos = cargar_mazos()
    deck_id = datos.get("id")

    if deck_id:
        for i, m in enumerate(mazos):
            if m["id"] == deck_id:
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
    mazos = [m for m in cargar_mazos() if m["id"] != deck_id]
    guardar_mazos_disco(mazos)
    return jsonify({"ok": True})

# --- ENDPOINT DE BÚSQUEDA MULTI-TCG (CARTAS EN INGLÉS ORIGINAL) ---
@app.route("/api/buscar")
def buscar():
    juego = request.args.get("juego", "yugioh")
    nombre = request.args.get("q", "").strip()

    if not nombre:
        return jsonify([])

    cartas = []

    try:
        # 1. YU-GI-OH! (Idioma original Inglés)
        if juego == "yugioh":
            url = f"https://db.ygoprodeck.com/api/v7/cardinfo.php?fname={nombre}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for c in r.json().get("data", [])[:30]:
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
                    id_unico = f"YGO_{c['id']}"
                    img = c["card_images"][0]["image_url_small"]

                    cartas.append({
                        "id": id_unico,
                        "name": c["name"],
                        "game": "yugioh",
                        "zone": "secondary" if es_extra else "main",
                        "category": cat,
                        "cost": nivel,
                        "power": c.get("atk", 0),
                        "type_line": f"{tipo} / {c.get('race', '')}",
                        "desc": c.get("desc", ""),
                        "image": guardar_imagen_cache(id_unico, img)
                    })

        # 2. DIGIMON TCG
        elif juego == "digimon":
            url = f"https://digimoncard.io/api-public/search.php?n={nombre}&series=Digimon Card Game"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and isinstance(r.json(), list):
                for idx, c in enumerate(r.json()[:30]):
                    codigo = c.get("cardnumber") or c.get("id") or f"unk_{idx}"
                    id_unico = f"DGM_{codigo}"
                    img = c.get("image_url") or f"https://images.digimoncard.io/images/cards/{codigo}.jpg"
                    tipo = c.get("type", "Digimon")
                    es_egg = (tipo == "Digi-Egg")

                    cartas.append({
                        "id": id_unico,
                        "name": c.get("name", "Digimon"),
                        "game": "digimon",
                        "zone": "secondary" if es_egg else "main",
                        "category": tipo,
                        "cost": c.get("level") or c.get("play_cost") or 0,
                        "power": c.get("dp") or 0,
                        "type_line": f"{tipo} / {c.get('color', '')} (Lv.{c.get('level', '-')})",
                        "desc": c.get("maineffect") or c.get("soureeffect") or "No effect",
                        "image": guardar_imagen_cache(id_unico, img)
                    })

        # 3. MAGIC: THE GATHERING
        elif juego == "magic":
            url = f"https://api.scryfall.com/cards/search?q={nombre}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for c in r.json().get("data", [])[:30]:
                    img = c.get("image_uris", {}).get("normal", "")
                    if not img and "card_faces" in c:
                        img = c["card_faces"][0].get("image_uris", {}).get("normal", "")
                    if not img:
                        continue

                    t_line = c.get("type_line", "")
                    if "Creature" in t_line: cat = "Criatura"
                    elif "Land" in t_line: cat = "Tierra"
                    elif "Instant" in t_line or "Sorcery" in t_line: cat = "Hechizo"
                    else: cat = "Otro"

                    id_unico = f"MTG_{c['id']}"
                    cartas.append({
                        "id": id_unico,
                        "name": c["name"],
                        "game": "magic",
                        "zone": "main",
                        "category": cat,
                        "cost": int(c.get("cmc", 0)),
                        "power": c.get("power", 0),
                        "type_line": t_line,
                        "desc": c.get("oracle_text", ""),
                        "image": guardar_imagen_cache(id_unico, img)
                    })

        # 4. CARDFIGHT!! VANGUARD
        elif juego == "vanguard":
            url = f"https://card-fight-vanguard-api.ue.r.appspot.com/api/v1/cards?name={nombre}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for c in r.json().get("data", [])[:30]:
                    id_unico = f"CFV_{c.get('id')}"
                    grado = c.get("grade", 0)
                    es_gzone = int(grado) >= 4 if str(grado).isdigit() else False
                    cartas.append({
                        "id": id_unico,
                        "name": c.get("name", ""),
                        "game": "vanguard",
                        "zone": "secondary" if es_gzone else "main",
                        "category": f"Grado {grado}",
                        "cost": int(grado) if str(grado).isdigit() else 0,
                        "power": c.get("power", 0),
                        "type_line": f"Grade {grado} / {c.get('clan', '')}",
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
            coincidencias = [c for c in MEMORIA_FFTCG if termino_low in c.get("name", "").lower()][:30]
            for c in coincidencias:
                codigo = c.get("serial_number", "FF")
                id_unico = f"FF_{codigo}"
                cartas.append({
                    "id": id_unico,
                    "name": f"{c.get('name')} ({codigo})",
                    "game": "fftcg",
                    "zone": "main",
                    "category": c.get("type", "Forward"),
                    "cost": c.get("cost", 0) or 0,
                    "power": c.get("power", 0) or 0,
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
                    costo = c.get("cost", 0)
                    cartas.append({
                        "id": id_unico,
                        "name": f"{c.get('name')}" + (f" (Pitch {pitch})" if pitch else ""),
                        "game": "fab",
                        "zone": "secondary" if es_sec else "main",
                        "category": tipos[0] if tipos else "Action",
                        "cost": int(costo) if str(costo).isdigit() else 0,
                        "power": c.get("power", 0),
                        "type_line": ", ".join(tipos),
                        "desc": c.get("functional_text_plain", ""),
                        "image": guardar_imagen_cache(id_unico, img)
                    })
                    if len(cartas) >= 30:
                        break

    except Exception as e:
        print(f"Error en búsqueda de {juego}: {e}")

    return jsonify(cartas)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)