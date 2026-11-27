import os
import re
import json
import uuid
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, Response
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

HEADERS = {
    "User-Agent": "MultiTCGApp/3.3 (compatible; Python requests)",
    "Accept": "application/json"
}

HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01"
}

MEMORIA_FFTCG = []
MEMORIA_FAB = []
MODELOS_GROQ_CACHE = []

TCGCSV_CATEGORIAS = {
    "vanguard": 16,
    "fftcg": 24,
    "fab": 62,
    "digimon": 63
}

PRECIOS_MEMORIA = {}
PRECIOS_SINCRONIZANDO = set()
LOCK_PRECIOS = threading.Lock()

PALABRAS_SELLADO = (
    "booster", "display", "case", "starter deck", "structure deck",
    "box", "pack", "bundle", "sleeve", "playmat", "deck box", "tin", "gift set"
)

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

REGLAS_ARMADO_POR_JUEGO = {
    "yugioh": "Main Deck de 40 a 60 cartas (ideal 40-42), Extra Deck de hasta 15 cartas y Side Deck de hasta 15 cartas. Máximo 3 copias por carta respetando la Banlist TCG vigente.",
    "digimon": "Main Deck exacto de 50 cartas y Digi-Egg Deck de 0 a 5 cartas. Máximo 4 copias por código de carta, respetando la curva de niveles (Lv.3 a Lv.6/7) y sinergia de colores.",
    "magic": "Main Deck mínimo de 60 cartas y Sideboard de hasta 15 cartas (máximo 4 copias salvo tierras básicas), o 100 cartas singleton si el usuario pide Commander. Respetá curva de maná y base de tierras.",
    "vanguard": "Mazo Standard de 50 cartas exactas (4 Ride Deck + 46 Main Deck, incluyendo 16 Triggers con 1 Overtrigger y hasta 4 Sentinelas) y máximo 4 copias por nombre, respetando Nación/Clan.",
    "fftcg": "Main Deck exacto de 50 cartas, máximo 3 copias por código de carta, equilibrando Forwards, Backups, Summons y elementos para generar CP de forma consistente.",
    "fab": "Formato Classic Constructed (60 a 80 cartas incluyendo Héroe, Armas y Equipo; máximo 3 copias por color/pitch) o Blitz (40 cartas, 2 copias) si el usuario lo indica. Respetá clase/talento del Héroe y balance de Pitch Rojo/Amarillo/Azul."
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


def normalizar_rareza(juego, rareza_raw):
    if not rareza_raw:
        return "Común", 2

    txt = str(rareza_raw).strip()
    low = txt.lower()

    if juego == "fab":
        mapa_fab = {
            "t": ("Token", 1), "c": ("Common", 2), "r": ("Rare", 3),
            "s": ("Super Rare", 4), "p": ("Promo", 4), "m": ("Majestic", 5),
            "l": ("Legendary", 6), "f": ("Fabled", 7), "v": ("Marvel", 7)
        }
        if low in mapa_fab:
            return mapa_fab[low]

    if juego == "fftcg":
        mapa_ff = {
            "c": ("Common", 2), "s": ("Starter", 3), "r": ("Rare", 4),
            "pr": ("Promo", 4), "h": ("Hero", 5), "l": ("Legend", 6)
        }
        if low in mapa_ff:
            return mapa_ff[low]

    if juego == "digimon":
        mapa_dgm = {
            "c": ("Common", 2), "u": ("Uncommon", 3), "r": ("Rare", 4),
            "p": ("Promo", 4), "sr": ("Super Rare", 5), "sec": ("Secret Rare", 6)
        }
        if low in mapa_dgm:
            return mapa_dgm[low]

    if juego == "vanguard":
        mapa_vg = {
            "c": ("C", 2), "r": ("R", 3), "pr": ("PR", 4), "rr": ("RR", 4),
            "rrr": ("RRR", 5), "vr": ("VR", 6), "gr": ("GR", 6), "or": ("OR", 6),
            "sp": ("SP", 7), "sec": ("SEC", 7), "ffr": ("FFR", 7), "dsr": ("DSR", 7), "lsr": ("LSR", 7)
        }
        if low in mapa_vg:
            return mapa_vg[low]

    if any(k in low for k in ("quarter century", "starlight", "ghost", "fabled", "marvel")):
        return txt.title(), 7
    if any(k in low for k in ("secret", "collector", "ultimate", "mythic", "legendary", "legend")):
        return txt.title(), 6
    if any(k in low for k in ("ultra", "majestic", "hero", "super", "special", "bonus")):
        return txt.title(), 5
    if "promo" in low:
        return txt.title(), 4
    if "rare" in low and "uncommon" not in low:
        return txt.title(), 4 if juego in ("magic", "digimon", "fftcg") else 3
    if "uncommon" in low or "starter" in low:
        return txt.title(), 3
    if "common" in low or "short print" in low:
        return txt.title(), 2
    if "token" in low:
        return txt.title(), 1

    return txt, 2


def normalizar_nombre_carta(texto):
    if not texto:
        return ""
    limpio = re.sub(r"\([^)]*\)", " ", str(texto))
    limpio = re.sub(r"\[[^\]]*\]", " ", limpio)
    limpio = re.sub(r"\s-\s[A-Za-z0-9\-/]+$", "", limpio)
    limpio = re.sub(r"[^a-zA-Z0-9\s]", " ", limpio.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def extraer_campo_wiki(patron, texto):
    m = re.search(patron, texto, re.IGNORECASE)
    if not m:
        return ""
    val = m.group(1).strip()
    val = re.sub(r"\[\[([^|\]]+\|)?([^\]]+)\]\]", r"\2", val)
    val = re.sub(r"\{\{[^}]+\}\}", "", val)
    val = re.sub(r"<[^>]+>", " ", val)
    return val.strip()


# --- MOTOR DE PRECIOS MULTI-TCG (TCGCSV / TCGPLAYER) ---
def _descargar_grupo_tcgcsv(cat_id, group_id):
    por_codigo = {}
    por_nombre = {}
    try:
        r_pr = requests.get(
            f"https://tcgcsv.com/tcgplayer/{cat_id}/{group_id}/prices",
            headers=HEADERS,
            timeout=12
        )
        if r_pr.status_code != 200:
            return por_codigo, por_nombre

        precios_pid = {}
        for item in r_pr.json().get("results", []):
            pid = item.get("productId")
            precio = a_flotante(item.get("marketPrice") or item.get("midPrice") or item.get("lowPrice"))
            if pid and precio > 0:
                if pid not in precios_pid or precio < precios_pid[pid]:
                    precios_pid[pid] = precio

        if not precios_pid:
            return por_codigo, por_nombre

        r_prod = requests.get(
            f"https://tcgcsv.com/tcgplayer/{cat_id}/{group_id}/products",
            headers=HEADERS,
            timeout=12
        )
        if r_prod.status_code != 200:
            return por_codigo, por_nombre

        for prod in r_prod.json().get("results", []):
            pid = prod.get("productId")
            precio = precios_pid.get(pid)
            if not precio:
                continue

            nombre_raw = prod.get("name", "")
            nombre_low = nombre_raw.lower()
            if any(p in nombre_low for p in PALABRAS_SELLADO):
                continue

            codigo = ""
            for ext in prod.get("extendedData", []):
                if ext.get("name", "").lower() in ("number", "card number", "code"):
                    codigo = str(ext.get("value", "")).strip().upper()
                    break

            if not codigo:
                m_cod = re.search(r"\b([A-Z]{1,4}\d{0,2}-\d{2,3}[A-Z]?|\d{1,2}-\d{3}[A-Z])\b", nombre_raw.upper())
                if m_cod:
                    codigo = m_cod.group(1)

            if codigo:
                if codigo not in por_codigo or precio < por_codigo[codigo]:
                    por_codigo[codigo] = round(precio, 2)

            base = normalizar_nombre_carta(nombre_raw)
            if base:
                if base not in por_nombre or precio < por_nombre[base]:
                    por_nombre[base] = round(precio, 2)

                for color in ("red", "yellow", "blue"):
                    if f"({color})" in nombre_low:
                        clave_color = f"{base}|{color}"
                        if clave_color not in por_nombre or precio < por_nombre[clave_color]:
                            por_nombre[clave_color] = round(precio, 2)
    except Exception:
        pass

    return por_codigo, por_nombre


def _sincronizar_precios_worker(juego):
    cat_id = TCGCSV_CATEGORIAS.get(juego)
    if not cat_id:
        return

    print(f"[Precios] Sincronizando cotizaciones USD de '{juego}' desde TCGCSV...")
    por_codigo = {}
    por_nombre = {}

    try:
        r_grp = requests.get(
            f"https://tcgcsv.com/tcgplayer/{cat_id}/groups",
            headers=HEADERS,
            timeout=15
        )
        if r_grp.status_code != 200:
            print(f"[Precios] No se pudieron listar expansiones de '{juego}' (HTTP {r_grp.status_code}).")
            return

        grupos = [g["groupId"] for g in r_grp.json().get("results", []) if "groupId" in g]

        with ThreadPoolExecutor(max_workers=12) as executor:
            futuros = [executor.submit(_descargar_grupo_tcgcsv, cat_id, gid) for gid in grupos]
            for fut in as_completed(futuros):
                cods, noms = fut.result()
                for k, v in cods.items():
                    if k not in por_codigo or v < por_codigo[k]:
                        por_codigo[k] = v
                for k, v in noms.items():
                    if k not in por_nombre or v < por_nombre[k]:
                        por_nombre[k] = v

        datos_finales = {"por_codigo": por_codigo, "por_nombre": por_nombre}
        ruta = os.path.join(CACHE_DIR, f"precios_{juego}.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos_finales, f)

        with LOCK_PRECIOS:
            PRECIOS_MEMORIA[juego] = datos_finales

        print(f"[Precios] '{juego}' listo: {len(por_nombre)} cartas y {len(por_codigo)} códigos cacheados.")
    except Exception as e:
        print(f"[Precios] Error sincronizando '{juego}': {e}")
    finally:
        with LOCK_PRECIOS:
            PRECIOS_SINCRONIZANDO.discard(juego)


def iniciar_sincronizacion_precios(juego, forzar=False):
    if juego not in TCGCSV_CATEGORIAS:
        return False

    ruta = os.path.join(CACHE_DIR, f"precios_{juego}.json")
    if not forzar and os.path.exists(ruta):
        return False

    with LOCK_PRECIOS:
        if juego in PRECIOS_SINCRONIZANDO:
            return True
        PRECIOS_SINCRONIZANDO.add(juego)

    hilo = threading.Thread(target=_sincronizar_precios_worker, args=(juego,), daemon=True)
    hilo.start()
    return True


def obtener_precio_tcg(juego, nombre, codigo="", pitch=""):
    if juego not in TCGCSV_CATEGORIAS:
        return 0.0

    datos = PRECIOS_MEMORIA.get(juego)
    if datos is None:
        ruta = os.path.join(CACHE_DIR, f"precios_{juego}.json")
        if os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                with LOCK_PRECIOS:
                    PRECIOS_MEMORIA[juego] = datos
            except Exception:
                datos = None

    if not datos:
        iniciar_sincronizacion_precios(juego, forzar=False)
        return 0.0

    por_codigo = datos.get("por_codigo", {})
    por_nombre = datos.get("por_nombre", {})

    if codigo:
        cod_up = str(codigo).strip().upper()
        if cod_up in por_codigo:
            return a_flotante(por_codigo[cod_up])

    base = normalizar_nombre_carta(nombre)
    if juego == "fab" and pitch:
        mapa_pitch = {"1": "red", "2": "yellow", "3": "blue"}
        color = mapa_pitch.get(str(pitch).strip())
        if color and f"{base}|{color}" in por_nombre:
            return a_flotante(por_nombre[f"{base}|{color}"])

    if base in por_nombre:
        return a_flotante(por_nombre[base])

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


def cargar_dataset_local(nombre_archivo, urls_remotas, timeout=40):
    ruta = os.path.join(CACHE_DIR, nombre_archivo)
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
                if datos:
                    return datos
        except Exception:
            pass

    if isinstance(urls_remotas, str):
        urls_remotas = [urls_remotas]

    for url in urls_remotas:
        try:
            r = requests.get(url, headers=HEADERS_BROWSER, timeout=timeout)
            if r.status_code == 200:
                datos = r.json()
                with open(ruta, "w", encoding="utf-8") as f:
                    json.dump(datos, f)
                return datos
        except Exception as e:
            print(f"[TCG] Error descargando {url}: {e}")
    return []


def formatear_carta_yugioh(c, usar_cache_img=True):
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
    precio_usd = a_flotante(
        precios.get("tcgplayer_price")
        or precios.get("cardmarket_price")
        or precios.get("coolstuffinc_price")
        or 0.0
    )
    ban_info = c.get("banlist_info", {}).get("ban_tcg", "Unlimited")

    mejor_rareza = ("Common", 2)
    for st in c.get("card_sets", []):
        r_lbl, r_rk = normalizar_rareza("yugioh", st.get("set_rarity", ""))
        if r_rk > mejor_rareza[1]:
            mejor_rareza = (r_lbl, r_rk)

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
        "rarity": mejor_rareza[0],
        "rarity_rank": mejor_rareza[1],
        "ban_status": ban_info,
        "type_line": f"{tipo} / {c.get('race', '')} ({c.get('attribute', 'SPELL/TRAP')})",
        "desc": c.get("desc", ""),
        "image": guardar_imagen_cache(id_unico, img) if usar_cache_img else img
    }


def _parsear_paginas_vanguard(pages, filtro_grado="", filtro_unidad="", incluir_zero=False, vistos=None):
    resultados = []
    if vistos is None:
        vistos = set()

    for page_id, p in pages.items():
        if page_id in vistos:
            continue
        titulo = p.get("title", "")
        if not incluir_zero and "(ZERO)" in titulo.upper():
            continue

        revs = p.get("revisions", [])
        if not revs:
            continue
        wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "") or revs[0].get("*", "")
        if "CardTable" not in wikitext and "| grade" not in wikitext.lower():
            continue

        img = p.get("thumbnail", {}).get("source") or p.get("original", {}).get("source") or ""
        if not img:
            continue

        grado_num = a_entero(extraer_campo_wiki(r"\|\s*grade\s*=\s*(\d+)", wikitext))
        if filtro_grado != "" and str(grado_num) != str(filtro_grado):
            continue

        unidad_raw = extraer_campo_wiki(r"\|\s*(?:cardtype|unittype|type)\s*=\s*([^\n|]+)", wikitext)
        if filtro_unidad and filtro_unidad.lower() not in (unidad_raw.lower() + " " + wikitext[:600].lower()):
            continue

        poder_num = a_entero(extraer_campo_wiki(r"\|\s*power\s*=\s*(\d+)", wikitext))
        clan = extraer_campo_wiki(r"\|\s*(?:clan|nation)\s*=\s*([^\n|]+)", wikitext)

        rareza_raw = extraer_campo_wiki(r"\|\s*rarity\s*=\s*([^\n|]+)", wikitext)
        if not rareza_raw:
            m_rar = re.search(r"\b(DSR|LSR|FFR|SEC|SP|VR|GR|OR|RRR|RR|PR|R|C)\b", wikitext)
            rareza_raw = m_rar.group(1) if m_rar else "C"
        r_lbl, r_rk = normalizar_rareza("vanguard", rareza_raw.split(",")[0].strip())

        efecto = ""
        m_ef = re.search(r"\|\s*effect\s*=\s*(.*?)(?=\n\|\s*[a-zA-Z_]+\s*=|\n\}\})", wikitext, re.IGNORECASE | re.DOTALL)
        if m_ef:
            efecto = m_ef.group(1).strip()
            efecto = re.sub(r"\[\[([^|\]]+\|)?([^\]]+)\]\]", r"\2", efecto)
            efecto = re.sub(r"\{\{[^}|]+\|([^}]+)\}\}", r"[\1]", efecto)
            efecto = re.sub(r"\{\{([^}]+)\}\}", r"[\1]", efecto)
            efecto = re.sub(r"'''?", "", efecto)
            efecto = re.sub(r"<br\s*/?>", "\n", efecto, flags=re.IGNORECASE)
            efecto = re.sub(r"<[^>]+>", "", efecto).strip()

        vistos.add(page_id)
        resultados.append({
            "id": f"CFV_{page_id}",
            "raw_id": str(page_id),
            "name": titulo,
            "game": "vanguard",
            "zone": "secondary" if (grado_num >= 4 or "g unit" in unidad_raw.lower()) else "main",
            "category": f"Grado {grado_num}",
            "cost": grado_num,
            "power": poder_num,
            "price": obtener_precio_tcg("vanguard", titulo),
            "rarity": r_lbl,
            "rarity_rank": r_rk,
            "ban_status": "Unlimited",
            "type_line": f"Grade {grado_num}" + (f" / {clan}" if clan else "") + (f" ({unidad_raw})" if unidad_raw else ""),
            "desc": efecto or "No effect text.",
            "image": img
        })

    return resultados


def llamar_motor_ia(system_prompt, user_prompt, max_tokens=1000):
    global MODELOS_GROQ_CACHE
    load_dotenv(RUTA_ENV, encoding="utf-8-sig", override=True)

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    error_detalle = ""

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
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.25,
                        "max_tokens": max_tokens
                    },
                    timeout=22
                )
                if r.status_code == 200:
                    texto = r.json()["choices"][0]["message"]["content"]
                    return {"respuesta": texto, "motor": f"Groq ({modelo_actual})"}
                else:
                    error_detalle = f"Modelo {modelo_actual} devolvió {r.status_code}: {r.text}"
        except Exception as e:
            error_detalle = str(e)

    if gemini_key and gemini_key.startswith("AIza"):
        try:
            url_gem = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            r = requests.post(
                url_gem,
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {"temperature": 0.25}
                },
                timeout=22
            )
            if r.status_code == 200:
                texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return {"respuesta": texto, "motor": "Gemini 2.5 Flash"}
        except Exception as e:
            print(f"Error en Gemini: {e}")

    return {
        "respuesta": (
            f"⚠️ **No se pudo conectar al motor IA.**\n\n"
            f"- ¿Leyó GROQ_API_KEY del .env?: **{'SÍ (' + groq_key[:8] + '...)' if groq_key else 'NO'}**\n"
            f"- Detalle técnico: `{error_detalle or 'Clave no encontrada'}`"
        ),
        "motor": "Diagnóstico"
    }


@app.route("/")
def inicio():
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    datos_pwa = {
        "name": "Multi-TCG Deck Studio & Judge",
        "short_name": "Multi-TCG",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f1115",
        "theme_color": "#e63946",
        "icons": [
            {
                "src": "https://cdn-icons-png.flaticon.com/512/3813/3813681.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }
    return Response(json.dumps(datos_pwa), mimetype="application/json")


@app.route("/api/precios/sincronizar/<juego>", methods=["POST", "GET"])
def api_sincronizar_precios(juego):
    if juego not in TCGCSV_CATEGORIAS:
        return jsonify({"ok": True, "mensaje": f"{juego} ya trae precios en vivo desde su API."})
    iniciar_sincronizacion_precios(juego, forzar=True)
    return jsonify({"ok": True, "estado": "sincronizando", "juego": juego})


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


# --- ENDPOINT DEL JUEZ IA + ARQUITECTO DE MAZOS ---
@app.route("/api/juez", methods=["POST"])
def consultar_juez():
    datos = request.json or {}
    juego = datos.get("juego", "yugioh")
    modo = datos.get("modo", "ruling")
    pregunta = datos.get("pregunta", "").strip()
    contexto_cartas = datos.get("contexto_cartas", "")

    if not pregunta:
        return jsonify({"respuesta": "Escribí tu consulta o las cartas base para que pueda ayudarte."}), 400

    if modo == "deckbuilder":
        regla_armado = REGLAS_ARMADO_POR_JUEGO.get(juego, REGLAS_ARMADO_POR_JUEGO["yugioh"])
        system_prompt = (
            f"Sos un Arquitecto Competitivo de Mazos (Deckbuilder Top Tier) especializado en {juego.upper()}.\n"
            f"REGLAS DE CONSTRUCCIÓN DEL JUEGO: {regla_armado}\n\n"
            "INSTRUCCIONES OBLIGATORIAS:\n"
            "1. Respetá OBLIGATORIAMENTE todas las cartas que mencione el jugador en su pedido: nunca las saques ni las reemplaces; armá la estrategia, motores y ratios alrededor de ellas.\n"
            "2. Respondé en español claro, pero escribí TODOS los nombres de cartas exactamente en inglés para que el jugador pueda buscarlas directo en el Armador.\n"
            "3. Usá exactamente esta estructura:\n"
            "   - **🎯 Estrategia Central:** Cómo ganás aprovechando las cartas que pidió el jugador.\n"
            "   - **📋 Lista Competitiva Sugerida:** Separada por zonas (Main Deck, Extra/Secundario y Side Deck) con cantidades exactas (`3x Card Name`) sumando un total legal.\n"
            "   - **⚡ Combos Clave y Sinergias:** Pasos concretos para explotar las cartas elegidas.\n"
            "   - **🔧 Ajustes Budget / Techs:** Alternativas económicas o cartas para adaptar al meta local.\n"
        )
        if contexto_cartas:
            system_prompt += f"\nCARTAS QUE EL JUGADOR YA TIENE CARGADAS EN SU MAZO ACTUAL:\n{contexto_cartas}\n"
        return jsonify(llamar_motor_ia(system_prompt, pregunta, max_tokens=1600))

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

    return jsonify(llamar_motor_ia(system_prompt, pregunta, max_tokens=900))


# --- ENDPOINT DEL COACH IA DE MAZOS ---
@app.route("/api/analizar_mazo", methods=["POST"])
def analizar_mazo():
    datos = request.json or {}
    juego = datos.get("juego", "yugioh")
    nombre_mazo = datos.get("nombre", "Mi Mazo")
    lista_mazo = datos.get("lista_mazo", "")

    if not lista_mazo:
        return jsonify({"respuesta": "Agregá cartas a tu mazo primero para que el Coach IA pueda analizarlo."}), 400

    system_prompt = (
        f"Sos un Coach Competitivo Top Tier de {juego.upper()}. "
        "Analizá la lista de cartas del jugador y respondé en español manteniendo los nombres de cartas en inglés con esta estructura exacta:\n"
        "1. **🎯 Plan de Juego y Condición de Victoria:** Cómo gana este mazo.\n"
        "2. **⚡ Combos y Sinergias Clave:** Qué cartas buscar primero y cómo conectan entre sí.\n"
        "3. **🛡️ Puntos Débiles y Choke Points:** Qué interrupciones del rival frenan a este mazo y cómo jugar alrededor de ellas.\n"
        "4. **🔧 Recomendaciones de Optimización y Side Deck:** Qué ratios ajustar o qué cartas agregar para hacerlo más consistente."
    )
    user_prompt = f"Analizá este mazo llamado '{nombre_mazo}' ({juego}):\n\n{lista_mazo}"

    return jsonify(llamar_motor_ia(system_prompt, user_prompt, max_tokens=1100))


# --- ENDPOINT PARA IMPORTAR ARCHIVOS .YDK DE YU-GI-OH! ---
@app.route("/api/importar_ydk", methods=["POST"])
def importar_ydk():
    datos = request.json or {}
    contenido = datos.get("contenido", "")
    if not contenido:
        return jsonify({"error": "Archivo vacío"}), 400

    main_ids = []
    extra_ids = []
    side_ids = []
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
            limpio = linea.lstrip("0")
            if limpio.isdigit():
                if seccion == "main":
                    main_ids.append(limpio)
                elif seccion == "extra":
                    extra_ids.append(limpio)
                elif seccion == "side":
                    side_ids.append(limpio)

    todos_unicos = list(set(main_ids + extra_ids + side_ids))
    if not todos_unicos:
        return jsonify({"main": [], "secondary": [], "side": []})

    ids_param = ",".join(todos_unicos)
    url = f"https://db.ygoprodeck.com/api/v7/cardinfo.php?id={ids_param}"
    mapa_cartas = {}

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            for c in r.json().get("data", []):
                carta_obj = formatear_carta_yugioh(c, usar_cache_img=True)
                mapa_cartas[str(c["id"])] = carta_obj
                for img_item in c.get("card_images", []):
                    if "id" in img_item:
                        mapa_cartas[str(img_item["id"])] = carta_obj
    except Exception as e:
        print(f"Error importando YDK: {e}")

    main_armado = [mapa_cartas[i] for i in main_ids if i in mapa_cartas]
    extra_armado = [mapa_cartas[i] for i in extra_ids if i in mapa_cartas]
    side_armado = [mapa_cartas[i] for i in side_ids if i in mapa_cartas]

    return jsonify({"main": main_armado, "secondary": extra_armado, "side": side_armado})


# --- ENDPOINT DE BÚSQUEDA AVANZADA MULTI-TCG (TEXTO + FILTROS NATIVOS) ---
@app.route("/api/buscar")
def buscar():
    juego = request.args.get("juego", "yugioh")
    nombre = request.args.get("q", "").strip()
    f1 = request.args.get("f1", "").strip()
    f2 = request.args.get("f2", "").strip()
    f3 = request.args.get("f3", "").strip()
    f4 = request.args.get("f4", "").strip()

    if not any([nombre, f1, f2, f3, f4]):
        return jsonify([])

    cartas = []

    try:
        # 1. YU-GI-OH! (f1=Atributo, f2=Raza, f3=Tipo Carta, f4=Nivel/Rank/Link)
        if juego == "yugioh":
            params = {"num": 40, "offset": 0}
            if nombre:
                params["fname"] = nombre
            if f1:
                params["attribute"] = f1
            if f2:
                params["race"] = f2
            if f3:
                params["type"] = f3
            if f4:
                if f3 == "Link Monster":
                    params["link"] = f4
                else:
                    params["level"] = f4

            r = requests.get(
                "https://db.ygoprodeck.com/api/v7/cardinfo.php",
                params=params,
                headers=HEADERS,
                timeout=12
            )
            if r.status_code == 200:
                for c in r.json().get("data", [])[:40]:
                    cartas.append(formatear_carta_yugioh(c, usar_cache_img=False))

        # 2. DIGIMON TCG (f1=Color, f2=Tipo, f3=Nivel)
        elif juego == "digimon":
            params = {"series": "Digimon Card Game"}
            if nombre:
                params["n"] = nombre
            if f1:
                params["color"] = f1
            if f2:
                params["type"] = f2
            if f3:
                params["level"] = f3

            r = requests.get(
                "https://digimoncard.io/api-public/search.php",
                params=params,
                headers=HEADERS,
                timeout=12
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for idx, c in enumerate(data[:40]):
                        codigo = c.get("cardnumber") or c.get("id") or f"unk_{idx}"
                        img = c.get("image_url") or f"https://images.digimoncard.io/images/cards/{codigo}.jpg"
                        tipo = c.get("type", "Digimon")
                        nom = c.get("name", "Digimon")
                        r_lbl, r_rk = normalizar_rareza("digimon", c.get("cardrarity") or c.get("rarity") or "Common")
                        cartas.append({
                            "id": f"DGM_{codigo}",
                            "raw_id": str(codigo),
                            "name": nom,
                            "game": "digimon",
                            "zone": "secondary" if tipo == "Digi-Egg" else "main",
                            "category": tipo,
                            "cost": a_entero(c.get("level") or c.get("play_cost")),
                            "power": a_entero(c.get("dp")),
                            "price": obtener_precio_tcg("digimon", nom, codigo),
                            "rarity": r_lbl,
                            "rarity_rank": r_rk,
                            "ban_status": "Unlimited",
                            "type_line": f"{tipo} / {c.get('color', '')} (Lv.{c.get('level', '-')})",
                            "desc": c.get("maineffect") or c.get("soureeffect") or "No effect",
                            "image": img
                        })

        # 3. MAGIC: THE GATHERING (f1=Color, f2=Tipo, f3=CMC, f4=Rareza)
        elif juego == "magic":
            partes_q = []
            if nombre:
                partes_q.append(nombre)
            if f1:
                if f1 == "M":
                    partes_q.append("c>=2")
                elif f1 == "C":
                    partes_q.append("c:c")
                else:
                    partes_q.append(f"c:{f1}")
            if f2:
                partes_q.append(f"t:{f2}")
            if f3:
                if f3 == "7+":
                    partes_q.append("cmc>=7")
                else:
                    partes_q.append(f"cmc={f3}")
            if f4:
                partes_q.append(f"r:{f4}")

            r = requests.get(
                "https://api.scryfall.com/cards/search",
                params={"q": " ".join(partes_q)},
                headers=HEADERS,
                timeout=12
            )
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

                    pr_obj = c.get("prices", {})
                    precio_raw = (
                        pr_obj.get("usd")
                        or pr_obj.get("usd_foil")
                        or pr_obj.get("usd_etched")
                        or pr_obj.get("eur")
                        or 0.0
                    )
                    r_lbl, r_rk = normalizar_rareza("magic", c.get("rarity", "common"))

                    cartas.append({
                        "id": f"MTG_{c['id']}",
                        "raw_id": str(c.get("collector_number", "")),
                        "name": c.get("name", ""),
                        "game": "magic",
                        "zone": "main",
                        "category": cat,
                        "cost": a_entero(c.get("cmc")),
                        "power": a_entero(c.get("power")),
                        "price": a_flotante(precio_raw),
                        "rarity": r_lbl,
                        "rarity_rank": r_rk,
                        "ban_status": "Unlimited",
                        "type_line": t_line,
                        "desc": c.get("oracle_text") or (c["card_faces"][0].get("oracle_text", "") if "card_faces" in c else ""),
                        "image": img
                    })

        # 4. CARDFIGHT!! VANGUARD (f1=Nación/Clan, f2=Grado, f3=Unidad)
        elif juego == "vanguard":
            incluir_zero = "zero" in nombre.lower()
            vistos = set()

            # Caso A: Exploración pura por categoría (ej: todas las cartas Murakumo o Dragon Empire)
            if not nombre and (f1 or (f2 and not f1)):
                categoria_objetivo = f"Category:{f1}" if f1 else f"Category:Grade {f2}"
                gcm_continue = None
                for _ in range(3):
                    params_cat = {
                        "action": "query",
                        "format": "json",
                        "generator": "categorymembers",
                        "gcmtitle": categoria_objetivo,
                        "gcmnamespace": 0,
                        "gcmlimit": 45,
                        "prop": "pageimages|revisions",
                        "piprop": "thumbnail|original",
                        "pithumbsize": 300,
                        "rvprop": "content",
                        "rvslots": "main"
                    }
                    if gcm_continue:
                        params_cat["gcmcontinue"] = gcm_continue

                    r_cat = requests.get(
                        "https://cardfight.fandom.com/api.php",
                        params=params_cat,
                        headers=HEADERS_BROWSER,
                        timeout=15
                    )
                    if r_cat.status_code != 200:
                        break
                    data_cat = r_cat.json()
                    pages = data_cat.get("query", {}).get("pages", {})
                    cartas.extend(_parsear_paginas_vanguard(pages, f2, f3, incluir_zero, vistos))
                    if len(cartas) >= 35:
                        break
                    gcm_continue = data_cat.get("continue", {}).get("gcmcontinue")
                    if not gcm_continue:
                        break
                cartas = cartas[:40]

            # Caso B: Búsqueda por texto combinada con Clan/Nación y/o Grado
            else:
                partes_vg = []
                if nombre:
                    partes_vg.append(nombre)
                if f1:
                    partes_vg.append(f'incategory:"{f1}"')
                if f2:
                    partes_vg.append(f'incategory:"Grade {f2}"')
                if f3:
                    partes_vg.append(f'"{f3}"')

                r_wiki = requests.get(
                    "https://cardfight.fandom.com/api.php",
                    params={
                        "action": "query",
                        "format": "json",
                        "generator": "search",
                        "gsrsearch": " ".join(partes_vg),
                        "gsrlimit": 40,
                        "gsrnamespace": 0,
                        "prop": "pageimages|revisions",
                        "piprop": "thumbnail|original",
                        "pithumbsize": 300,
                        "rvprop": "content",
                        "rvslots": "main"
                    },
                    headers=HEADERS_BROWSER,
                    timeout=15
                )
                if r_wiki.status_code == 200:
                    pages = r_wiki.json().get("query", {}).get("pages", {})
                    cartas = _parsear_paginas_vanguard(pages, f2, f3, incluir_zero, vistos)[:40]

        # 5. FINAL FANTASY TCG (f1=Elemento, f2=Tipo, f3=Costo CP, f4=Rareza)
        elif juego == "fftcg":
            global MEMORIA_FFTCG
            if not MEMORIA_FFTCG:
                ruta_ff = os.path.join(CACHE_DIR, "fftcg_cards_sqex.json")
                if os.path.exists(ruta_ff):
                    try:
                        with open(ruta_ff, "r", encoding="utf-8") as f:
                            data_ff = json.load(f)
                            MEMORIA_FFTCG = data_ff.get("cards", []) if isinstance(data_ff, dict) else data_ff
                    except Exception:
                        MEMORIA_FFTCG = []

                if not MEMORIA_FFTCG:
                    payload_sqex = {
                        "language": "en", "text": "", "type": [], "element": [],
                        "cost": [], "rarity": [], "power": [], "category_1": [],
                        "set": [], "multicard": "", "ex_burst": "", "code": "",
                        "special": "", "exactmatch": 0
                    }
                    headers_sqex = {
                        **HEADERS_BROWSER,
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": "https://fftcg.square-enix-games.com/en/card-browser"
                    }
                    try:
                        r_ff = requests.post(
                            "https://fftcg.square-enix-games.com/en/get-cards",
                            json=payload_sqex,
                            headers=headers_sqex,
                            timeout=30
                        )
                        if r_ff.status_code == 200:
                            data_ff = r_ff.json()
                            MEMORIA_FFTCG = data_ff.get("cards", []) if isinstance(data_ff, dict) else data_ff
                            if MEMORIA_FFTCG:
                                with open(ruta_ff, "w", encoding="utf-8") as f:
                                    json.dump(data_ff, f)
                    except Exception as e_ff:
                        print(f"[FFTCG] Error Square Enix: {e_ff}")

                if not MEMORIA_FFTCG:
                    try:
                        r_ffd = requests.get("https://ffdecks.com/api/cards/basic", headers=HEADERS_BROWSER, timeout=20)
                        if r_ffd.status_code == 200:
                            data_ff = r_ffd.json()
                            MEMORIA_FFTCG = data_ff.get("cards", []) if isinstance(data_ff, dict) else data_ff
                            if MEMORIA_FFTCG:
                                with open(ruta_ff, "w", encoding="utf-8") as f:
                                    json.dump(data_ff, f)
                    except Exception as e_ffd:
                        print(f"[FFTCG] Error FFDecks: {e_ffd}")

            termino_low = nombre.lower()
            for c in MEMORIA_FFTCG:
                nombre_carta = c.get("name_en") or c.get("name") or ""
                if termino_low and termino_low not in nombre_carta.lower():
                    continue

                elementos = c.get("element") or c.get("elements") or []
                if isinstance(elementos, str):
                    elementos = [elementos]
                if f1 and not any(f1.lower() in str(el).lower() for el in elementos):
                    continue

                tipo_ff = c.get("type_en") or c.get("type") or "Forward"
                if f2 and f2.lower() not in tipo_ff.lower():
                    continue

                costo_ff = a_entero(c.get("cost"))
                if f3:
                    if f3 == "7+":
                        if costo_ff < 7:
                            continue
                    elif costo_ff != a_entero(f3):
                        continue

                codigo = c.get("code") or c.get("serial_number") or "FF"
                rareza_ff = str(c.get("rarity") or (codigo[-1] if codigo and codigo[-1].isalpha() else "C")).strip()
                if f4 and rareza_ff.upper() != f4.upper():
                    continue

                imgs = c.get("images", {})
                img = ""
                if isinstance(imgs, dict):
                    full_list = imgs.get("full") or imgs.get("thumbs") or []
                    img = full_list[0] if isinstance(full_list, list) and full_list else (full_list if isinstance(full_list, str) else "")
                elif isinstance(c.get("image"), str):
                    img = c.get("image")

                texto_ef = c.get("text_en") or c.get("abilities") or ""
                texto_ef = re.sub(r"\[\[br\]\]", "\n", texto_ef, flags=re.IGNORECASE)
                texto_ef = re.sub(r"\[\[/?[^\]]+\]\]", "", texto_ef).strip()

                r_lbl, r_rk = normalizar_rareza("fftcg", rareza_ff)

                cartas.append({
                    "id": f"FF_{codigo}",
                    "raw_id": str(codigo),
                    "name": f"{nombre_carta} ({codigo})",
                    "game": "fftcg",
                    "zone": "main",
                    "category": tipo_ff,
                    "cost": costo_ff,
                    "power": a_entero(c.get("power")),
                    "price": obtener_precio_tcg("fftcg", nombre_carta, codigo),
                    "rarity": r_lbl,
                    "rarity_rank": r_rk,
                    "ban_status": "Unlimited",
                    "type_line": f"{tipo_ff} / {', '.join(elementos)}",
                    "desc": texto_ef,
                    "image": img
                })
                if len(cartas) >= 40:
                    break

        # 6. FLESH AND BLOOD (f1=Clase/Talento, f2=Tipo, f3=Pitch, f4=Costo)
        elif juego == "fab":
            global MEMORIA_FAB
            if not MEMORIA_FAB:
                MEMORIA_FAB = cargar_dataset_local(
                    "fab_cards.json",
                    [
                        "https://raw.githubusercontent.com/the-fab-cube/flesh-and-blood-cards/develop/json/english/card.json",
                        "https://raw.githubusercontent.com/the-fab-cube/flesh-and-blood-cards/main/json/english/card.json"
                    ],
                    timeout=45
                )

            termino_low = nombre.lower()
            for c in MEMORIA_FAB:
                nom_base = c.get("name", "")
                if termino_low and termino_low not in nom_base.lower():
                    continue

                tipos = c.get("types", [])
                tipos_low = [str(t).lower() for t in tipos]
                if f1 and f1.lower() not in tipos_low:
                    continue
                if f2 and f2.lower() not in tipos_low:
                    continue

                pitch = str(c.get("pitch", "")).strip()
                if f3 and pitch != f3:
                    continue

                costo_raw = str(c.get("cost", "")).strip()
                costo_num = a_entero(costo_raw)
                if f4:
                    if f4 == "4+":
                        if costo_num < 4:
                            continue
                    elif costo_raw != f4:
                        continue

                printings = c.get("printings", [])
                img = next((p.get("image_url") for p in printings if p.get("image_url")), "")
                if not img:
                    continue
                codigo = c.get("unique_id", "FAB")
                es_sec = any(t in tipos for t in ["Hero", "Weapon", "Equipment"])

                mejor_rareza = ("Common", 2)
                for p in printings:
                    r_lbl, r_rk = normalizar_rareza("fab", p.get("rarity", "C"))
                    if r_rk > mejor_rareza[1]:
                        mejor_rareza = (r_lbl, r_rk)

                cartas.append({
                    "id": f"FAB_{codigo}",
                    "raw_id": str(codigo),
                    "name": f"{nom_base}" + (f" (Pitch {pitch})" if pitch else ""),
                    "game": "fab",
                    "zone": "secondary" if es_sec else "main",
                    "category": tipos[0] if tipos else "Action",
                    "cost": costo_num,
                    "power": a_entero(c.get("power")),
                    "price": obtener_precio_tcg("fab", nom_base, codigo, pitch),
                    "rarity": mejor_rareza[0],
                    "rarity_rank": mejor_rareza[1],
                    "ban_status": "Unlimited",
                    "type_line": ", ".join(tipos),
                    "desc": c.get("functional_text_plain", ""),
                    "image": img
                })
                if len(cartas) >= 40:
                    break

    except Exception as e:
        print(f"Error en búsqueda de {juego}: {e}")

    return jsonify(cartas)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)