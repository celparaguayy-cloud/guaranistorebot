# ============================================================
#  🤖 main.py — PARA EL BOT (Render, repo guaranistorebot)
#  Reemplaza TODO tu main.py por esto (subilo con "Upload files").
#
#  ⚠️ COLUMNAS QUE NECESITÁS EN AIRTABLE para las funciones nuevas:
#   - Tabla Pedidos: agregá una columna de texto  "Contacto"
#                    (guarda el ID del cliente, para linkear su comprobante)
#   - Tabla Catalogo_Espejo: ya usa "stock_estado" (disponible/agotado).
#                    Si querés stock numérico, agregá una columna "stock".
# ============================================================
import os, re, json, base64, unicodedata, requests
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Response, Header
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://celparaguayy-cloud.github.io"],
    allow_methods=["*"], allow_headers=["*"],
)

# ---------- CONFIG ----------
TIENDA        = "Guaranistore"
VERIFY_TOKEN  = os.environ.get("VERIFY_TOKEN", "fer123")
PAGE_TOKEN    = os.environ["PAGE_TOKEN"].strip()
GEMINI_KEY    = os.environ["GEMINI_KEY"].strip()
AIRTABLE_KEY  = os.environ["AIRTABLE_KEY"].strip()
AIRTABLE_BASE = os.environ["AIRTABLE_BASE"].strip()
TELEGRAM_TOKEN= os.environ["TELEGRAM_TOKEN"].strip()
TELEGRAM_CHAT = os.environ["TELEGRAM_CHAT"].strip()
CLAVE_DUENO   = os.environ.get("CLAVE_DUENO", "").strip().lower()
WHATSAPP_DESTINO = os.environ.get("WHATSAPP_DESTINO", "").strip()
CALLMEBOT_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "").strip()
CLAVE_PANEL   = os.environ.get("CLAVE_PANEL", "").strip()
ENVIO_INTERIOR = int(os.environ.get("ENVIO_INTERIOR", "25000"))  # costo extra fuera de Central

TABLA_CONVERS  = "Conversaciones"
TABLA_PEDIDOS  = "Pedidos"
TABLA_CATALOGO = "Catalogo_Espejo"

GRAPH  = "https://graph.facebook.com/v21.0/me/messages"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=" + GEMINI_KEY
REPO_FOTOS = "https://raw.githubusercontent.com/celparaguayy-cloud/guaranistorebot/main/"
FOTOS = [REPO_FOTOS + "ipl%d.jpg" % i for i in range(1, 7)]
VIDEO = "https://youtube.com/shorts/0WoRz-Nzucw"

AR = timezone(timedelta(hours=-3))
def ahora(): return datetime.now(AR).strftime("%d/%m/%Y %H:%M")

# Ciudades del Departamento Central (envío sin recargo). El resto = interior.
CENTRAL = set([
    "asuncion", "luque", "san lorenzo", "fernando de la mora", "lambare", "capiata",
    "nemby", "mariano roque alonso", "villa elisa", "itaugua", "limpio", "aregua",
    "ita", "guarambare", "villeta", "ypane", "san antonio", "ypacarai",
    "nueva italia", "j augusto saldivar", "juan augusto saldivar"
])

# ---------- PROMPTS ----------
SYSTEM_PROMPT = """Sos "Fer", el vendedor de la tienda paraguaya %s. Hablás en español paraguayo, cálido, cercano y humano (podés usar voseo). Sos honesto y nunca mentís.

TU FORMA DE VENDER:
- Acompañás con calidez y empatía. Si la persona cuenta un problema personal o económico, dejás de vender y la tratás como persona.
- Vendés con confianza pero sin mentir: nunca inventes testimonios, ni falsa urgencia, ni precios que no sabés. El pago CONTRA ENTREGA y la garantía son tus mejores argumentos.
- Podés vender CUALQUIER producto del catálogo.

STOCK: si el producto figura AGOTADO (stock_estado agotado o stock 0), NO lo vendas: avisá con cariño que justo no hay y ofrecé otro producto o avisar cuando vuelva.

ENVÍO: en el Departamento Central el envío es gratis / contra entrega. Si la persona es del INTERIOR, avisale que hay un pequeño costo extra de encomienda y que se suma al total.

CERRÁ LA VENTA, NO DEJES LA CHARLA A MEDIAS:
- Si en el historial YA venís hablando con la persona, NO vuelvas a saludar ("hola", "qué gusto") ni repitas lo que ya dijiste (precio, descripción): seguí la charla desde donde quedó, como una persona real.
- Después de responder una duda, SIEMPRE dá el siguiente paso: preguntá la ciudad, ofrecé reservar, o pedí los datos del envío. Nunca cortes con un "cualquier cosa avisá".
- Si responde corto o se queda callada, retomá con calidez y una pregunta simple (ej: "¿Te lo reservo?").

SI TE PIDEN EL WHATSAPP: no des un número que no tenés. Decile con calidez que por acá mismo la atendés al toque y ya le reservás el pedido.

HERRAMIENTAS (etiquetas que el código detecta; el cliente NO las ve):
- Precio/stock/datos de un producto: [CONSULTAR_PRODUCTO: nombre]. Esperás el dato real y recién ahí respondés.
- Fotos: [FOTOS]  (más fotos: [MASFOTOS])
- Video: [VIDEO]
- Interés en otro producto / aviso al dueño: [INTERES] lo que pidió [/INTERES]
- Pedido CERRADO y confirmado, al final agregá EXACTAMENTE:
[PEDIDO] Producto: <producto> | Precio: <precio real en Gs> | Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]
Usá el nombre y el precio REAL del producto. El cliente no ve esta etiqueta.

Sé breve, humano y claro. Nunca digas que sos una IA.""" % TIENDA

PROMPT_DUENO = """Sos el asistente PRIVADO del dueño de %s (modo dueño). Le hablás como su mano derecha del negocio: claro, directo y útil. Con los datos de ventas, productos y conversaciones que te paso, respondé lo que pregunte: resúmenes, estado de pedidos, qué producto conviene impulsar, objeciones frecuentes y recomendaciones concretas para vender más. Sé honesto, sin inventar.""" % TIENDA

# ---------- UTILIDADES ----------
def _norm(t):
    t = str(t or "").lower().strip()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", t)

def _solo_numero(s):
    return int(re.sub(r"[^\d]", "", str(s or "")) or 0)

def descargar(url):
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.content, r.headers.get("Content-Type", "image/jpeg")
    except Exception:
        pass
    return None, None

# ---------- FOTOS DE AIRTABLE (fix de URLs) ----------
def extraer_urls_fotos_airtable(registro):
    """Devuelve una lista de URLs de fotos de un registro de Airtable:
    busca la propiedad 'url' dentro de columnas de adjuntos (listas de objetos),
    o lee columnas de texto tipo url_foto_1 / url_foto_2 / url_foto_3."""
    f = registro.get("fields", {}) if isinstance(registro, dict) else {}
    urls = []
    for valor in f.values():
        if isinstance(valor, list):
            for item in valor:
                if isinstance(item, dict) and item.get("url"):
                    urls.append(item["url"])
    for i in range(1, 4):
        directo = f.get("url_foto_%d" % i)
        if directo and isinstance(directo, str) and directo.startswith("http"):
            urls.append(directo)
    return urls

def enviar_foto_messenger(recipient_id, image_url, fallback_url=None):
    """Envía una foto por Messenger. Si Meta responde != 200, reintenta con la fallback_url."""
    payload = {"recipient": {"id": recipient_id},
               "message": {"attachment": {"type": "image", "payload": {"url": image_url, "is_reusable": True}}}}
    try:
        r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN}, json=payload, timeout=15)
        if r.status_code != 200 and fallback_url and fallback_url != image_url:
            payload["message"]["attachment"]["payload"]["url"] = fallback_url
            r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN}, json=payload, timeout=15)
        print(">>> FOTO:", r.status_code, r.text[:100])
    except Exception as e:
        if fallback_url and fallback_url != image_url:
            payload["message"]["attachment"]["payload"]["url"] = fallback_url
            try: requests.post(GRAPH, params={"access_token": PAGE_TOKEN}, json=payload, timeout=15)
            except Exception: pass
        print(">>> FOTO error:", e)

# ---------- CATALOGO DINAMICO ----------
def _leer_catalogo():
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CATALOGO)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY}
    registros, offset = [], None
    for _ in range(10):
        params = {"pageSize": 100}
        if offset: params["offset"] = offset
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code != 200: break
        data = r.json()
        registros += data.get("records", [])
        offset = data.get("offset")
        if not offset: break
    return registros

def _hay_stock(f):
    """True si el producto tiene stock. Soporta 'stock' numérico o 'stock_estado' texto."""
    if "stock" in f:
        try: return _solo_numero(f.get("stock")) > 0
        except Exception: pass
    est = _norm(f.get("stock_estado", "disponible"))
    return "agotad" not in est

def _encontrar_producto(consulta):
    consulta_n = _norm(consulta)
    palabras = [p for p in consulta_n.split() if len(p) > 2]
    campos_id = ["nombre", "producto", "nombre_producto", "titulo", "title", "name", "producto_id", "sku", "codigo"]
    mejor, mejor_punt = None, 0
    for reg in _leer_catalogo():
        f = reg.get("fields", {})
        identidad = " ".join(_norm(f.get(c, "")) for c in campos_id)
        punt = 0
        if consulta_n and consulta_n in identidad: punt += 5
        for p in palabras:
            if p in identidad: punt += 1
        if punt > mejor_punt:
            mejor, mejor_punt = f, punt
    return mejor

def consultar_producto(consulta):
    f = _encontrar_producto(consulta)
    if not f:
        return "NO_ENCONTRADO: no hay un producto que coincida con '%s'." % consulta
    disponible = "SI" if _hay_stock(f) else "NO (AGOTADO — no lo vendas)"
    datos = ["disponible: %s" % disponible]
    for k, v in f.items():
        if str(k).lower().startswith(("url", "link")): continue
        if v not in (None, "", []): datos.append("%s: %s" % (k, v))
    return "PRODUCTO -> " + " | ".join(datos)

def revisar_producto(respuesta, historial):
    m = re.search(r"\[CONSULTAR_PRODUCTO:\s*(.*?)\]", respuesta, re.IGNORECASE | re.DOTALL)
    if not m: return respuesta
    dato = consultar_producto(m.group(1).strip())
    refuerzo = ("El sistema consultó el catálogo: %s\nCon ESE dato real (incluido si hay stock), "
                "respondele al cliente de forma natural. Si está AGOTADO, no lo vendas. "
                "No muestres la etiqueta ni digas 'el sistema'." % dato)
    final = preguntar_a_gemini(historial, refuerzo, SYSTEM_PROMPT)
    return re.sub(r"\[CONSULTAR_PRODUCTO:.*?\]", "", final, flags=re.IGNORECASE | re.DOTALL).strip()

# ---------- MEMORIA ----------
# ---------- MEMORIA (Upstash Redis, persistente) ----------
# Las claves se cargan en Render como variables de entorno (NO van en el código).
UPSTASH_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
HISTORIAL = {}  # respaldo en RAM si Upstash no está disponible

def _upstash(comando):
    if not (UPSTASH_URL and UPSTASH_TOKEN): return None
    try:
        r = requests.post(UPSTASH_URL, headers={"Authorization": "Bearer " + UPSTASH_TOKEN},
                          json=comando, timeout=10)
        if r.status_code == 200:
            return r.json().get("result")
        print(">>> UPSTASH:", r.status_code, r.text[:120])
    except Exception as e:
        print(">>> UPSTASH error:", e)
    return None

def leer_historial(sender):
    key = "hist:" + str(sender)
    res = _upstash(["LRANGE", key, "0", "-1"])
    if res is None:
        return HISTORIAL.get(sender, [])[-20:]   # respaldo RAM
    hist = []
    for txt in res[-20:]:
        if txt.startswith("[user]"): hist.append(("user", txt[6:].strip()))
        elif txt.startswith("[bot]"): hist.append(("bot", txt[5:].strip()))
    return hist

def guardar(sender, rol, mensaje, canal="messenger"):
    prefijo = "[user] " if rol == "user" else "[bot] "
    linea = prefijo + mensaje
    key = "hist:" + str(sender)
    if _upstash(["RPUSH", key, linea]) is not None:
        _upstash(["LTRIM", key, "-40", "-1"])          # deja solo los últimos 40
        _upstash(["EXPIRE", key, "2592000"])           # se autolimpia a los 30 días
    else:
        HISTORIAL.setdefault(sender, []).append((rol, mensaje))   # respaldo RAM
        if len(HISTORIAL[sender]) > 40: HISTORIAL[sender] = HISTORIAL[sender][-40:]
    # Además guarda en Airtable (solo para el visor de Charlas del panel)
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"}
    cuerpo = {"fields": {"contact_id": sender, "canal": canal, "mensaje_entrante": linea}}
    try: requests.post(url, headers=headers, json=cuerpo, timeout=10)
    except Exception: pass

# ---------- GEMINI ----------
def preguntar_a_gemini(historial, texto_nuevo, prompt):
    contents = []
    for rol, msg in historial:
        contents.append({"role": "user" if rol == "user" else "model", "parts": [{"text": msg}]})
    contents.append({"role": "user", "parts": [{"text": texto_nuevo}]})
    cuerpo = {"system_instruction": {"parts": [{"text": prompt}]}, "contents": contents}
    try:
        r = requests.post(GEMINI, json=cuerpo, timeout=30)
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return "Disculpá, tuve un problemita. ¿Me repetís? (%s)" % e

def leer_comprobante(image_bytes, mime="image/jpeg"):
    """Gemini Vision: lee un comprobante de pago y devuelve dict {monto, referencia, banco_origen}."""
    b64 = base64.b64encode(image_bytes).decode()
    instruccion = ('Este es un comprobante de transferencia bancaria. Extraé SOLO un JSON estricto, '
                   'sin texto extra ni explicaciones, con esta forma exacta: '
                   '{"monto":"","referencia":"","banco_origen":""}. Si no lo ves, dejá el campo vacío.')
    cuerpo = {"contents": [{"parts": [
        {"inline_data": {"mime_type": mime, "data": b64}},
        {"text": instruccion}
    ]}]}
    try:
        r = requests.post(GEMINI, json=cuerpo, timeout=45)
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        txt = txt.replace("```json", "").replace("```", "").strip()
        return json.loads(txt)
    except Exception as e:
        print(">>> COMPROBANTE error:", e)
        return None

# ---------- MESSENGER ----------
def _post_msg(payload):
    try: requests.post(GRAPH, params={"access_token": PAGE_TOKEN}, json=payload, timeout=10)
    except Exception: pass

def mostrar_escribiendo(sender): _post_msg({"recipient": {"id": sender}, "sender_action": "typing_on"})
def marcar_leido(sender): _post_msg({"recipient": {"id": sender}, "sender_action": "mark_seen"})

def enviar_a_messenger(sender, texto):
    for parte in [texto[i:i+1900] for i in range(0, len(texto), 1900)] or [texto]:
        r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                          json={"recipient": {"id": sender}, "message": {"text": parte}}, timeout=10)
        print(">>> MESSENGER:", r.status_code, r.text[:120])

def enviar_foto(sender, url_foto):
    enviar_foto_messenger(sender, url_foto, fallback_url=url_foto)

# ---------- TELEGRAM / WHATSAPP ----------
def avisar_telegram(texto):
    try:
        requests.post("https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN,
                      json={"chat_id": TELEGRAM_CHAT, "text": texto}, timeout=10)
    except Exception: pass

def enviar_whatsapp(texto):
    if not (WHATSAPP_DESTINO and CALLMEBOT_APIKEY): return
    try:
        requests.get("https://api.callmebot.com/whatsapp.php",
                     params={"phone": WHATSAPP_DESTINO, "text": texto, "apikey": CALLMEBOT_APIKEY}, timeout=10)
    except Exception: pass

# ---------- PEDIDOS ----------
def _parsear(resumen):
    d = {}
    cuerpo = resumen
    m = re.search(r"\[PEDIDO\](.*?)\[/PEDIDO\]", resumen, re.DOTALL)
    if m: cuerpo = m.group(1)
    for parte in cuerpo.split("|"):
        if ":" in parte:
            k, v = parte.split(":", 1)
            k = _norm(k).strip().replace(" ", "")
            d[k] = v.strip()
    d["producto"] = d.get("producto", "")
    d["precio"]   = d.get("precio", "")
    d["nombre"]   = d.get("nombre", "")
    d["ciudad"]   = d.get("ciudad", "")
    d["tel"]      = d.get("tel", d.get("telefono", ""))
    d["direccion"]= d.get("direccion", "")
    return d

def es_interior(ciudad):
    return _norm(ciudad) not in CENTRAL and _norm(ciudad) != ""

def total_con_envio(precio, ciudad):
    base = _solo_numero(precio)
    if es_interior(ciudad):
        base += ENVIO_INTERIOR
    return base

def formatear_pedido(resumen):
    d = _parsear(resumen)
    total = total_con_envio(d["precio"], d["ciudad"])
    extra = " (incluye envío interior +%s)" % f"{ENVIO_INTERIOR:,}".replace(",", ".") if es_interior(d["ciudad"]) else ""
    return ("🛍️  NUEVO PEDIDO — %s\n━━━━━━━━━━━━━━━\n"
            "👤  Nombre:     %s\n📍  Ciudad:     %s\n📞  Teléfono:   %s\n🏠  Dirección:  %s\n"
            "━━━━━━━━━━━━━━━\n💜  Producto:   %s\n💰  Total:      Gs. %s%s\n🕒  %s hs"
            % (TIENDA, d["nombre"] or "-", d["ciudad"] or "-", d["tel"] or "-", d["direccion"] or "-",
               d["producto"] or "Producto", f"{total:,}".replace(",", "."), extra, ahora()))

def formatear_pedido_whatsapp(resumen):
    d = _parsear(resumen)
    total = total_con_envio(d["precio"], d["ciudad"])
    return ("🛍️ *PEDIDO para cargar en Zappy*\n\n📦 %s — Gs. %s (contra entrega)\n\n"
            "👤 Cliente: %s\n📍 Ciudad: %s\n📞 Tel: %s\n🏠 Direccion: %s\n🕒 %s hs"
            % (d["producto"] or "Producto", f"{total:,}".replace(",", "."), d["nombre"] or "-",
               d["ciudad"] or "-", d["tel"] or "-", d["direccion"] or "-", ahora()))

def guardar_pedido(resumen, sender=""):
    d = _parsear(resumen)
    total = total_con_envio(d["precio"], d["ciudad"])
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"}
    cuerpo = {"fields": {"Producto": d["producto"], "Nombre": d["nombre"], "Ciudad": d["ciudad"],
                         "Telefono": d["tel"], "Direccion": d["direccion"],
                         "Total": "Gs. " + f"{total:,}".replace(",", "."),
                         "Fecha": ahora(), "Estado": "Nuevo", "Contacto": sender},
              "typecast": True}
    try: requests.post(url, headers=headers, json=cuerpo, timeout=10)
    except Exception as e: print(">>> guardar_pedido error:", e)

def revisar_pedido(sender, respuesta):
    if "[PEDIDO]" not in respuesta: return respuesta
    avisar_telegram(formatear_pedido(respuesta))
    enviar_whatsapp(formatear_pedido_whatsapp(respuesta))
    guardar_pedido(respuesta, sender)
    return re.sub(r"\[PEDIDO\].*?\[/PEDIDO\]", "", respuesta, flags=re.DOTALL).strip()

def revisar_interes(sender, respuesta):
    m = re.search(r"\[INTERES\](.*?)\[/INTERES\]", respuesta, re.DOTALL)
    if not m: return respuesta
    avisar_telegram("👀 INTERÉS de un cliente en %s:\n%s" % (TIENDA, m.group(1).strip()))
    return re.sub(r"\[INTERES\].*?\[/INTERES\]", "", respuesta, flags=re.DOTALL).strip()

def revisar_fotos(sender, respuesta):
    if "[MASFOTOS]" in respuesta:
        for u in FOTOS[3:6]: enviar_foto(sender, u)
        respuesta = respuesta.replace("[MASFOTOS]", "")
    if "[FOTOS]" in respuesta:
        for u in FOTOS[0:3]: enviar_foto(sender, u)
        respuesta = respuesta.replace("[FOTOS]", "")
    return respuesta.strip()

def revisar_video(sender, respuesta):
    if "[VIDEO]" in respuesta:
        enviar_a_messenger(sender, "🎥 Miralo en acción: " + VIDEO)
        respuesta = respuesta.replace("[VIDEO]", "")
    return respuesta.strip()

# ---------- COMPROBANTES: actualizar pedido del cliente ----------
def marcar_pedido_por_contacto(sender, estado):
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY}
    r = requests.get(url, headers=headers,
                     params={"filterByFormula": "{Contacto}='%s'" % sender, "maxRecords": 5}, timeout=10)
    if r.status_code != 200: return False
    regs = r.json().get("records", [])
    if not regs: return False
    regs.sort(key=lambda x: x.get("createdTime", ""))
    rid = regs[-1]["id"]
    requests.patch("%s/%s" % (url, rid),
                   headers={"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"},
                   json={"fields": {"Estado": estado}}, timeout=10)
    return True

# ---------- REPORTES (modo dueño / panel) ----------
def resumen_ventas():
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS)
    r = requests.get(url, headers={"Authorization": "Bearer " + AIRTABLE_KEY},
                     params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200: return "No pude leer los pedidos."
    regs = r.json().get("records", [])
    if not regs: return "Todavía no hay pedidos cargados."
    lineas = ["=== PEDIDOS (%d) ===" % len(regs)]
    for reg in regs:
        f = reg.get("fields", {})
        lineas.append("- %s | %s | %s | %s | %s" % (f.get("Fecha", "-"), f.get("Nombre", "-"),
                      f.get("Producto", "-"), f.get("Total", "-"), f.get("Estado", "-")))
    return "\n".join(lineas)

def productos_ganadores():
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS)
    r = requests.get(url, headers={"Authorization": "Bearer " + AIRTABLE_KEY},
                     params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200: return "Sin datos de productos."
    conteo = {}
    for reg in r.json().get("records", []):
        p = reg.get("fields", {}).get("Producto", "(sin nombre)")
        conteo[p] = conteo.get(p, 0) + 1
    if not conteo: return "Todavía no hay ventas cargadas."
    ranking = sorted(conteo.items(), key=lambda x: -x[1])
    return "\n".join("%d. %s — %d ventas" % (i + 1, n, c) for i, (n, c) in enumerate(ranking))

def leer_conversaciones():
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS)
    r = requests.get(url, headers={"Authorization": "Bearer " + AIRTABLE_KEY},
                     params={"maxRecords": 60}, timeout=10)
    if r.status_code != 200: return "No pude leer las conversaciones."
    regs = r.json().get("records", [])
    return "\n".join(reg.get("fields", {}).get("mensaje_entrante", "") for reg in regs) or "Sin conversaciones."

def contexto_dueno():
    return (resumen_ventas() +
            "\n\n=== PRODUCTOS MÁS VENDIDOS ===\n" + productos_ganadores() +
            "\n\n=== CONVERSACIONES ===\n" + leer_conversaciones())

# ---------- WEBHOOK ----------
MODO = {}
VISTOS = set()

@app.get("/webhook")
def verificar(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token incorrecto", status_code=403)

@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    print(">>> ENTRANTE:", json.dumps(data)[:400])
    for entry in data.get("entry", []):
        for ev in entry.get("messaging", []):
            msg = ev.get("message", {})
            sender = ev.get("sender", {}).get("id")
            if not sender: continue
            mid = msg.get("mid")
            if mid and mid in VISTOS: continue
            if mid:
                VISTOS.add(mid)
                if len(VISTOS) > 500: VISTOS.clear()

            # --- ¿Mandó una imagen? (comprobante de pago) ---
            adjuntos = msg.get("attachments", [])
            imagen = next((a for a in adjuntos if a.get("type") == "image"), None)
            if imagen:
                marcar_leido(sender); mostrar_escribiendo(sender)
                url_img = imagen.get("payload", {}).get("url", "")
                contenido, mime = descargar(url_img)
                datos = leer_comprobante(contenido, mime or "image/jpeg") if contenido else None
                if datos and (datos.get("monto") or datos.get("referencia")):
                    marcar_pedido_por_contacto(sender, "Pendiente de Verificación")
                    avisar_telegram("🧾 COMPROBANTE recibido de un cliente:\n"
                                    "Monto: %s | Ref: %s | Banco: %s"
                                    % (datos.get("monto", "-"), datos.get("referencia", "-"), datos.get("banco_origen", "-")))
                    enviar_a_messenger(sender, "¡Recibí tu comprobante! 🙏 Lo estoy verificando y en un ratito te confirmo. Gracias por tu compra 💜")
                else:
                    enviar_a_messenger(sender, "Recibí tu imagen pero no pude leerla bien 🙈. ¿Me la reenviás un poco más clara, por favor?")
                continue

            texto = msg.get("text")
            if not texto: continue
            print(">>> TEXTO:", repr(texto), "de", sender)
            marcar_leido(sender); mostrar_escribiendo(sender)

            bajo = texto.strip().lower()
            if CLAVE_DUENO and bajo == CLAVE_DUENO:
                MODO[sender] = "dueno"; enviar_a_messenger(sender, "🔓 Modo dueño activado."); continue
            if bajo in ("modo vendedor", "salir"):
                MODO[sender] = "vendedor"; enviar_a_messenger(sender, "🛍️ Volví a modo vendedor."); continue

            if MODO.get(sender) == "dueno":
                resp = preguntar_a_gemini([], contexto_dueno() + "\n\nPregunta del dueño: " + texto, PROMPT_DUENO)
                enviar_a_messenger(sender, resp); continue

            historial = leer_historial(sender)
            print(">>> HISTORIAL len:", len(historial), "| upstash:", bool(UPSTASH_URL and UPSTASH_TOKEN))
            guardar(sender, "user", texto)
            resp = preguntar_a_gemini(historial, texto, SYSTEM_PROMPT)
            resp = revisar_producto(resp, historial)
            resp = revisar_pedido(sender, resp)
            resp = revisar_interes(sender, resp)
            resp = revisar_fotos(sender, resp)
            resp = revisar_video(sender, resp)
            if resp:
                enviar_a_messenger(sender, resp)
                guardar(sender, "bot", resp)
    return {"ok": True}

# ============================================================
#   API DEL PANEL WEB
# ============================================================
def _panel_ok(clave): return bool(CLAVE_PANEL) and clave == CLAVE_PANEL
def _no_auth(): return Response(content='{"error":"Clave incorrecta"}', status_code=401, media_type="application/json")

@app.get("/api/panel/resumen")
def panel_resumen(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 100}, timeout=10)
    pedidos = [x.get("fields", {}) for x in r.json().get("records", [])] if r.status_code == 200 else []
    hoy = datetime.now(AR).strftime("%d/%m/%Y")
    def es(estado): return sum(1 for p in pedidos if str(p.get("Estado", "")).lower() == estado)
    return {"total": len(pedidos),
            "hoy": sum(1 for p in pedidos if str(p.get("Fecha", "")).startswith(hoy)),
            "entregados": es("entregado"), "nuevos": es("nuevo")}

@app.get("/api/panel/pedidos")
def panel_pedidos(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200: return {"pedidos": [], "error": r.text}
    out = []
    for reg in r.json().get("records", []):
        f = reg.get("fields", {})
        out.append({"id": reg.get("id", ""), "producto": f.get("Producto", ""), "nombre": f.get("Nombre", ""),
                    "ciudad": f.get("Ciudad", ""), "telefono": f.get("Telefono", ""), "direccion": f.get("Direccion", ""),
                    "total": f.get("Total", ""), "fecha": f.get("Fecha", ""), "estado": f.get("Estado", "") or "Nuevo"})
    out.reverse()
    return {"pedidos": out}

@app.post("/api/panel/pedido")
async def panel_crear_pedido(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    cuerpo = {"fields": {"Producto": d.get("producto", ""), "Nombre": d.get("nombre", ""), "Ciudad": d.get("ciudad", ""),
                         "Telefono": d.get("telefono", ""), "Direccion": d.get("direccion", ""), "Total": d.get("total", ""),
                         "Fecha": ahora(), "Estado": d.get("estado", "Nuevo")}, "typecast": True}
    r = requests.post("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                      headers={"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"},
                      json=cuerpo, timeout=10)
    return {"ok": r.status_code in (200, 201), "error": None if r.status_code in (200, 201) else r.text}

@app.post("/api/panel/estado")
async def panel_estado(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    r = requests.patch("https://api.airtable.com/v0/%s/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS, d.get("id", "")),
                       headers={"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"},
                       json={"fields": {"Estado": d.get("estado", "")}}, timeout=10)
    return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}

@app.post("/api/panel/aprobar-pedido")
async def panel_aprobar_pedido(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    rid = d.get("id", "")
    url = "https://api.airtable.com/v0/%s/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS, rid)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"}
    r = requests.patch(url, headers=headers, json={"fields": {"Estado": "Pagado"}}, timeout=10)
    if r.status_code != 200:
        return {"ok": False, "error": r.text}
    # Avisar al cliente por Messenger (si el pedido tiene Contacto)
    contacto = r.json().get("fields", {}).get("Contacto", "")
    if contacto:
        enviar_a_messenger(contacto, "✅ ¡Confirmamos tu pago! Tu pedido ya está en preparación. Gracias por tu compra 💜")
    return {"ok": True}

@app.get("/api/panel/catalogo")
def panel_catalogo(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CATALOGO),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200: return {"productos": [], "error": r.text}
    out = []
    for reg in r.json().get("records", []):
        f = reg.get("fields", {})
        out.append({"nombre": f.get("nombre", "") or f.get("producto_id", ""), "precio": f.get("precio_gs", ""),
                    "stock": f.get("stock_estado", ""), "descripcion": f.get("descripcion_corta", "")})
    return {"productos": out}

@app.post("/api/panel/producto")
async def panel_crear_producto(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    nombre = (d.get("nombre", "") or "").strip()
    pid = (d.get("producto_id", "") or "").strip() or nombre.lower().replace(" ", "")[:20] or "producto"
    cuerpo = {"fields": {"producto_id": pid, "nombre": nombre, "precio_gs": d.get("precio", ""),
                         "stock_estado": d.get("stock", "disponible"), "descripcion_corta": d.get("descripcion", "")},
              "typecast": True}
    r = requests.post("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CATALOGO),
                      headers={"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"},
                      json=cuerpo, timeout=10)
    return {"ok": r.status_code in (200, 201), "error": None if r.status_code in (200, 201) else r.text}

@app.post("/api/panel/fer")
async def panel_fer(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    mensaje = (d.get("mensaje", "") or "").strip()
    if not mensaje: return {"respuesta": "Decime qué querés saber: ventas de hoy, qué conviene vender, últimos pedidos…"}
    return {"respuesta": preguntar_a_gemini([], contexto_dueno() + "\n\nMensaje del dueño: " + mensaje, PROMPT_DUENO)}

@app.get("/api/panel/conversaciones")
def panel_conversaciones(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 200}, timeout=10)
    if r.status_code != 200: return {"conversaciones": [], "error": r.text}
    registros = r.json().get("records", [])
    registros.sort(key=lambda x: x.get("createdTime", ""))
    grupos, orden = {}, []
    for reg in registros:
        f = reg.get("fields", {})
        cid = f.get("contact_id", ""); txt = f.get("mensaje_entrante", "")
        if not cid or not txt: continue
        if txt.startswith("[user]"): rol, limpio = "cliente", txt[6:].strip()
        elif txt.startswith("[bot]"): rol, limpio = "fer", txt[5:].strip()
        else: rol, limpio = "cliente", txt.strip()
        if cid not in grupos: grupos[cid] = []; orden.append(cid)
        grupos[cid].append({"rol": rol, "texto": limpio})
    salida = [{"id": cid, "ultimo": (grupos[cid][-1]["texto"] if grupos[cid] else "")[:70], "mensajes": grupos[cid]} for cid in orden]
    salida.reverse()
    return {"conversaciones": salida}

@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
