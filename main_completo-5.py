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
SYSTEM_PROMPT = """Sos "Fer", el vendedor de la tienda paraguaya %s. Hablás en español paraguayo, cálido, cercano y humano (podés usar voseo). Sos honesto y nunca mentís. Tu meta es ayudar a la persona a decidirse y CERRAR el pedido, sin presionar de más.

TU FORMA DE VENDER:
- Calidez primero. Si la persona cuenta un problema personal o económico, dejás de vender y la tratás como persona.
- Entendé antes de ofrecer: con UNA pregunta corta averiguá para qué lo quiere o qué le preocupa, y vendé la SOLUCIÓN a eso, no el objeto.
- Hablá del beneficio, no de la ficha técnica: hacé que se imagine el resultado en su vida.
- Ancla de valor: cuando das el precio, mostralo al lado de lo que le costaría la alternativa (ir al salón cada vez, comprarlo más caro en otro lado, comprar varias cosas por separado). Así el precio se ve chico frente al valor.
- Confianza como cierre fuerte: el pago CONTRA ENTREGA (paga recién cuando lo recibe y lo prueba, no arriesga nada) y la garantía son tus mejores argumentos. Repetílos cuando dude.
- Nunca inventes: ni testimonios, ni falsa urgencia, ni precios que no sabés.
- Podés vender CUALQUIER producto del catálogo.

CERRÁ, NO DEJES LA CHARLA A MEDIAS:
- Si en el historial YA venís hablando con la persona, NO vuelvas a saludar ("hola", "qué gusto") ni repitas lo que ya dijiste (precio, descripción): seguí desde donde quedó, como una persona real.
- Después de cada respuesta, SIEMPRE dá el siguiente paso concreto: preguntá la ciudad, ofrecé reservar, o pedí los datos del envío. Nunca cortes con un "cualquier cosa avisá".
- Cerrá con opción, no con pregunta abierta: "¿Te lo reservo para hoy o para mañana?" cierra más que "¿querés?".
- Si responde corto o se queda callada, retomá con calidez y una pregunta simple ("¿Te lo aparto?").

MANEJAR DUDAS Y OBJECIONES (acá se ganan las ventas):
- "Lo voy a pensar" / "después te aviso": no la sueltes. Con cariño preguntá qué es lo que la frena —el precio, la confianza o el momento— y resolvé ESA duda. Recordá el contra entrega.
- "Es caro": no bajes el precio; mostrá el valor y la alternativa más cara, y que paga recién al recibir.
- "¿Funciona de verdad?": honestidad + garantía + contra entrega (si no le sirve, no lo paga).
- Una objeción es señal de interés, no un "no". Tratala con calma.

STOCK: si el producto figura AGOTADO (stock_estado agotado o stock 0), NO lo vendas: avisá con cariño que justo no hay y ofrecé otro producto o avisar cuando vuelva.

ENVÍO: en el Departamento Central el envío es gratis / contra entrega. Si la persona es del INTERIOR, avisale que hay un pequeño costo extra de encomienda y que se suma al total. Averiguá la ciudad temprano para no sorprender con el costo al final.

SI TE PIDEN EL WHATSAPP: no des un número que no tenés. Decile con calidez que por acá mismo la atendés al toque y ya le reservás el pedido.

VENDER UN POCO MÁS: cuando ya cerraste un pedido, con naturalidad y sin insistir podés ofrecerle UN producto extra que combine ("¿Querés que te sume también...?"). Si dice que no, lo dejás tranquilo.

HERRAMIENTAS (etiquetas que el código detecta; el cliente NO las ve):
- Precio/stock/datos de un producto: [CONSULTAR_PRODUCTO: nombre]. Esperás el dato real y recién ahí respondés.
- Fotos: [FOTOS]  (más fotos: [MASFOTOS])
- Video: [VIDEO]
- Interés en otro producto / aviso al dueño: [INTERES] lo que pidió [/INTERES]
- Pedido CERRADO y confirmado, al final agregá EXACTAMENTE:
[PEDIDO] Producto: <producto> | Precio: <precio real en Gs> | Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]
Usá el nombre y el precio REAL del producto. El cliente no ve esta etiqueta.

Sé breve, humano y claro (mensajes cortos, de chat). Nunca digas que sos una IA.""" % TIENDA

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
def preguntar_a_gemini(historial, texto_nuevo, prompt, _reintento=True):
    contents = []
    for rol, msg in historial:
        contents.append({"role": "user" if rol == "user" else "model", "parts": [{"text": msg}]})
    contents.append({"role": "user", "parts": [{"text": texto_nuevo}]})
    cuerpo = {"system_instruction": {"parts": [{"text": prompt}]}, "contents": contents}
    try:
        r = requests.post(GEMINI, json=cuerpo, timeout=30)
        data = r.json()
        cands = data.get("candidates")
        if cands and cands[0].get("content", {}).get("parts"):
            txt = cands[0]["content"]["parts"][0].get("text", "").strip()
            if txt:
                return txt
        print(">>> GEMINI sin candidates:", str(data)[:200])
    except Exception as e:
        print(">>> GEMINI error:", e)
    if _reintento:
        return preguntar_a_gemini(historial, texto_nuevo, prompt, _reintento=False)
    return "Perdoná, se me trabó un segundo 🙈. ¿Me lo repetís, porfa?"

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
        try:
            r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                              json={"recipient": {"id": sender}, "message": {"text": parte}}, timeout=10)
            print(">>> MESSENGER:", r.status_code, r.text[:120])
        except Exception as e:
            print(">>> MESSENGER error:", e)

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
    try:
        data = await request.json()
    except Exception as e:
        print(">>> ENTRANTE ilegible:", e)
        return {"ok": True}
    print(">>> ENTRANTE:", json.dumps(data)[:400])
    for entry in data.get("entry", []):
        for ev in entry.get("messaging", []):
            try:
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
            except Exception as _e:
                print(">>> EVENTO error:", _e)
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
        out.append({"id": reg.get("id", ""), "nombre": f.get("nombre", "") or f.get("producto_id", ""),
                    "precio": f.get("precio_gs", ""), "costo": f.get("costo_gs", ""),
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

@app.get("/api/panel/seguimiento")
def panel_seguimiento(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    # 1) Contactos que YA compraron (tienen pedido con su Contacto)
    rp = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                      headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 100}, timeout=10)
    compraron = set()
    if rp.status_code == 200:
        for reg in rp.json().get("records", []):
            c = reg.get("fields", {}).get("Contacto", "")
            if c: compraron.add(str(c))
    # 2) Todas las charlas, agrupadas por contacto
    rc = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS),
                      headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 300}, timeout=10)
    if rc.status_code != 200: return {"seguimiento": [], "error": rc.text}
    registros = rc.json().get("records", [])
    registros.sort(key=lambda x: x.get("createdTime", ""))
    charlas = {}
    for reg in registros:
        f = reg.get("fields", {})
        cid = f.get("contact_id", ""); txt = f.get("mensaje_entrante", "")
        if not cid or not txt: continue
        charlas.setdefault(str(cid), []).append(txt)
    # 3) Los que charlaron pero NO compraron = leads a recuperar
    salida = []
    for cid, msgs in charlas.items():
        if cid in compraron: continue
        if len(msgs) < 2: continue  # que al menos haya habido conversación
        ultimo_user = ""
        for m in reversed(msgs):
            if m.startswith("[user]"): ultimo_user = m[6:].strip(); break
        salida.append({"id": cid, "mensajes": len(msgs), "ultimo": ultimo_user[:80]})
    salida.reverse()
    return {"seguimiento": salida}

@app.post("/api/panel/reenganche")
async def panel_reenganche(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    ultimo = (d.get("ultimo", "") or "").strip()
    p = ("Un cliente habló con la tienda pero no cerró la compra. Su último mensaje fue: '%s'. "
         "Escribí UN mensaje corto, cálido y en español paraguayo para reengancharlo y ayudarlo a decidir, "
         "sin presionar, recordando que paga contra entrega. Devolvé SOLO el mensaje, sin comillas." % ultimo)
    return {"mensaje": preguntar_a_gemini([], p, SYSTEM_PROMPT)}

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

@app.post("/api/chat")
async def chat_web(request: Request):
    """Chat web: Fer atiende SIN Facebook. El frontend manda {mensaje, historial}."""
    datos = await request.json()
    mensaje = (datos.get("mensaje", "") or "").strip()
    historial_in = datos.get("historial", []) or []
    if not mensaje:
        return {"respuesta": "Contame, ¿en qué te puedo ayudar? 😊"}
    # Reconstruye el historial que manda el navegador (lista de {rol, texto})
    historial = []
    for m in historial_in[-20:]:
        rol = "user" if m.get("rol") == "user" else "bot"
        historial.append((rol, m.get("texto", "")))
    resp = preguntar_a_gemini(historial, mensaje, SYSTEM_PROMPT)
    # Procesa las mismas etiquetas (catálogo, interés); las de foto/pedido se limpian para el demo
    resp = revisar_producto(resp, historial)
    resp = re.sub(r"\[PEDIDO\].*?\[/PEDIDO\]", "", resp, flags=re.DOTALL)
    resp = re.sub(r"\[INTERES\].*?\[/INTERES\]", "", resp, flags=re.DOTALL)
    resp = resp.replace("[FOTOS]", "").replace("[MASFOTOS]", "").replace("[VIDEO]", "").strip()
    return {"respuesta": resp}



# ============================================================
#   ➕ MEJORAS DEL PANEL (10 endpoints nuevos)
#   No tocan el bot que vende. Se prueban abriendo:
#   /api/panel/<lo-que-sea>?clave=TU_CLAVE_PANEL
# ============================================================

# ---------- Helper de clave: acepta header X-Clave O ?clave= en la URL ----------
# (así podés probar cada endpoint pegando el link en el navegador)
def _ok2(clave_header, clave_query):
    return bool(CLAVE_PANEL) and (clave_header == CLAVE_PANEL or clave_query == CLAVE_PANEL)

# ---------- Helper: leer TODOS los pedidos (con paginación) ----------
def _leer_pedidos():
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS)
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


# ============================================================
#  BLOQUE 1 — GANANCIA REAL POR PRODUCTO
#  Ganancia = (precio_gs - costo_gs) x cantidad vendida.
#  Probar:  /api/panel/ganancia?clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/ganancia")
def panel_ganancia(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    # 1) costo y precio de cada producto del catálogo
    info = {}
    for reg in _leer_catalogo():
        f = reg.get("fields", {})
        nombre = f.get("nombre", "") or f.get("producto_id", "")
        key = _norm(nombre)
        if not key: continue
        info[key] = {"nombre": nombre,
                     "costo": _solo_numero(f.get("costo_gs", 0)),
                     "precio": _solo_numero(f.get("precio_gs", 0))}
    # 2) contar ventas por producto
    ventas = {}
    for reg in _leer_pedidos():
        prod = reg.get("fields", {}).get("Producto", "")
        key = _norm(prod)
        if not key: continue
        ventas[key] = ventas.get(key, 0) + 1
    # 3) cruzar
    salida = []
    for key, cant in ventas.items():
        i = info.get(key)
        if not i:
            # el producto vendido no está en el catálogo (o cambió de nombre)
            salida.append({"producto": key, "ventas": cant, "costo_cargado": False,
                           "ganancia_unit": 0, "ganancia_total": 0})
            continue
        g_unit = i["precio"] - i["costo"]
        salida.append({"producto": i["nombre"], "ventas": cant,
                       "costo_cargado": i["costo"] > 0,
                       "precio": i["precio"], "costo": i["costo"],
                       "ganancia_unit": g_unit, "ganancia_total": g_unit * cant})
    salida.sort(key=lambda x: -x["ganancia_total"])
    ganancia_total = sum(x["ganancia_total"] for x in salida)
    return {"ganancia_total": ganancia_total, "productos": salida}


# ============================================================
#  BLOQUE 2 — VENTAS POR MES (evolución)
#  Cuántos pedidos y cuánta plata por mes.
#  Probar:  /api/panel/ventas-mes?clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/ventas-mes")
def panel_ventas_mes(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    meses = {}
    for reg in _leer_pedidos():
        f = reg.get("fields", {})
        fecha = str(f.get("Fecha", ""))          # "dd/mm/YYYY HH:MM"
        partes = fecha.split("/")
        if len(partes) < 3: continue
        mes = partes[1] + "/" + partes[2][:4]     # "mm/YYYY"
        total = _solo_numero(f.get("Total", 0))
        if mes not in meses: meses[mes] = {"pedidos": 0, "facturado": 0}
        meses[mes]["pedidos"] += 1
        meses[mes]["facturado"] += total
    # ordenar por año/mes
    def _clave_mes(m):
        mm, yy = m.split("/"); return yy + mm
    salida = [{"mes": m, "pedidos": v["pedidos"], "facturado": v["facturado"]}
              for m, v in sorted(meses.items(), key=lambda kv: _clave_mes(kv[0]))]
    return {"meses": salida}


# ============================================================
#  BLOQUE 3 — SEGUIMIENTO + HACE CUÁNTO
#  Leads que hablaron y NO compraron, con cuántos días pasaron.
#  Probar:  /api/panel/seguimiento-plus?clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/seguimiento-plus")
def panel_seguimiento_plus(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    # quién ya compró
    compraron = set()
    for reg in _leer_pedidos():
        c = reg.get("fields", {}).get("Contacto", "")
        if c: compraron.add(str(c))
    # charlas agrupadas por contacto, con la última fecha
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY},
                     params={"maxRecords": 300}, timeout=10)
    if r.status_code != 200: return {"seguimiento": [], "error": r.text}
    registros = r.json().get("records", [])
    registros.sort(key=lambda x: x.get("createdTime", ""))
    charlas = {}
    for reg in registros:
        f = reg.get("fields", {})
        cid = f.get("contact_id", ""); txt = f.get("mensaje_entrante", "")
        if not cid or not txt: continue
        charlas.setdefault(str(cid), {"msgs": [], "ultima_fecha": reg.get("createdTime", "")})
        charlas[str(cid)]["msgs"].append(txt)
        charlas[str(cid)]["ultima_fecha"] = reg.get("createdTime", "")
    ahora_utc = datetime.now(timezone.utc)
    salida = []
    for cid, d in charlas.items():
        if cid in compraron: continue
        if len(d["msgs"]) < 2: continue
        # último mensaje del cliente
        ultimo_user = ""
        for m in reversed(d["msgs"]):
            if m.startswith("[user]"): ultimo_user = m[6:].strip(); break
        # hace cuántos días
        dias = None
        try:
            f = d["ultima_fecha"].replace("Z", "+00:00")
            dias = (ahora_utc - datetime.fromisoformat(f)).days
        except Exception:
            pass
        salida.append({"id": cid, "mensajes": len(d["msgs"]),
                       "ultimo": ultimo_user[:80], "hace_dias": dias})
    salida.sort(key=lambda x: (x["hace_dias"] is None, x["hace_dias"] or 0))
    return {"seguimiento": salida}


# ============================================================
#  BLOQUE 4 — ANÁLISIS DE CHARLAS MUERTAS (con Fer)
#  Fer mira las charlas que NO terminaron en pedido y te dice
#  en qué punto se suelen caer las ventas.
#  Probar:  /api/panel/analisis-charlas?clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/analisis-charlas")
def panel_analisis_charlas(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    compraron = set()
    for reg in _leer_pedidos():
        c = reg.get("fields", {}).get("Contacto", "")
        if c: compraron.add(str(c))
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY},
                     params={"maxRecords": 300}, timeout=10)
    if r.status_code != 200: return {"analisis": "", "error": r.text}
    registros = r.json().get("records", [])
    registros.sort(key=lambda x: x.get("createdTime", ""))
    charlas = {}
    for reg in registros:
        f = reg.get("fields", {})
        cid = f.get("contact_id", ""); txt = f.get("mensaje_entrante", "")
        if not cid or not txt: continue
        charlas.setdefault(str(cid), []).append(txt)
    # armar transcripts de las que NO compraron
    transcripts = []
    for cid, msgs in charlas.items():
        if cid in compraron or len(msgs) < 2: continue
        t = "\n".join(m.replace("[user]", "Cliente:").replace("[bot]", "Fer:") for m in msgs[-12:])
        transcripts.append("--- Charla ---\n" + t)
        if len(transcripts) >= 15: break
    if not transcripts:
        return {"analisis": "Todavía no hay suficientes charlas sin venta para analizar. ¡Buena señal!"}
    p = ("Estas son charlas REALES de la tienda donde el cliente NO llegó a comprar. "
         "Analizá como mano derecha del dueño: ¿en qué punto se suelen caer las ventas? "
         "(al pedir datos, al hablar de precio, de envío, cuando el cliente se queda callado, etc.) "
         "Dame 3 o 4 patrones concretos y, por cada uno, un consejo corto para que Fer venda más. "
         "Sé directo y en español paraguayo.\n\n" + "\n\n".join(transcripts))
    return {"analisis": preguntar_a_gemini([], p, PROMPT_DUENO),
            "charlas_analizadas": len(transcripts)}


# ============================================================
#  BLOQUE 5 — PENDIENTES DE PAGO / COMPROBANTE
#  Pedidos que siguen "Nuevo" o "Pendiente de Verificación",
#  con cuántos días llevan esperando.
#  Probar:  /api/panel/pendientes-pago?clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/pendientes-pago")
def panel_pendientes_pago(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    pendientes_estados = ("nuevo", "pendiente de verificación", "pendiente de verificacion")
    ahora_utc = datetime.now(timezone.utc)
    salida = []
    for reg in _leer_pedidos():
        f = reg.get("fields", {})
        estado = str(f.get("Estado", "")).lower()
        if estado not in pendientes_estados: continue
        dias = None
        try:
            fecha = reg.get("createdTime", "").replace("Z", "+00:00")
            dias = (ahora_utc - datetime.fromisoformat(fecha)).days
        except Exception:
            pass
        salida.append({"id": reg.get("id", ""), "nombre": f.get("Nombre", "-"),
                       "producto": f.get("Producto", "-"), "total": f.get("Total", "-"),
                       "ciudad": f.get("Ciudad", "-"), "estado": f.get("Estado", ""),
                       "contacto": f.get("Contacto", ""), "hace_dias": dias})
    salida.sort(key=lambda x: -(x["hace_dias"] or 0))
    return {"pendientes": salida}


# ============================================================
#  BLOQUE 6 — ALERTA DE STOCK
#  Productos AGOTADOS o con stock bajo (si usás columna numérica "stock").
#  Probar:  /api/panel/stock-alerta?clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/stock-alerta")
def panel_stock_alerta(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    agotados, bajos = [], []
    for reg in _leer_catalogo():
        f = reg.get("fields", {})
        nombre = f.get("nombre", "") or f.get("producto_id", "")
        if not nombre: continue
        if not _hay_stock(f):
            agotados.append(nombre)
        elif "stock" in f:
            n = _solo_numero(f.get("stock"))
            if 0 < n <= 3: bajos.append({"producto": nombre, "quedan": n})
    return {"agotados": agotados, "stock_bajo": bajos,
            "hay_alerta": bool(agotados or bajos)}


# ============================================================
#  BLOQUE 7 — REPORTE DEL DÍA
#  Resumen de HOY: pedidos, facturado, nuevos, y el detalle.
#  Probar:  /api/panel/reporte-dia?clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/reporte-dia")
def panel_reporte_dia(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    hoy = datetime.now(AR).strftime("%d/%m/%Y")
    pedidos_hoy, facturado = [], 0
    for reg in _leer_pedidos():
        f = reg.get("fields", {})
        if not str(f.get("Fecha", "")).startswith(hoy): continue
        total = _solo_numero(f.get("Total", 0))
        facturado += total
        pedidos_hoy.append({"nombre": f.get("Nombre", "-"), "producto": f.get("Producto", "-"),
                            "total": f.get("Total", "-"), "ciudad": f.get("Ciudad", "-"),
                            "estado": f.get("Estado", "Nuevo")})
    return {"fecha": hoy, "cantidad": len(pedidos_hoy),
            "facturado": facturado, "pedidos": pedidos_hoy}


# ============================================================
#  BLOQUE 8 — BUSCADOR DE PEDIDOS
#  Buscá por nombre, ciudad, teléfono o producto.
#  Probar:  /api/panel/buscar?q=isabel&clave=TU_CLAVE_PANEL
# ============================================================
@app.get("/api/panel/buscar")
def panel_buscar(q: str = "", x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    consulta = _norm(q)
    if not consulta: return {"resultados": [], "aviso": "Escribí algo para buscar (?q=...)"}
    salida = []
    for reg in _leer_pedidos():
        f = reg.get("fields", {})
        blob = _norm(" ".join(str(f.get(k, "")) for k in
                     ("Nombre", "Ciudad", "Telefono", "Producto", "Direccion")))
        if consulta in blob:
            salida.append({"id": reg.get("id", ""), "nombre": f.get("Nombre", "-"),
                           "producto": f.get("Producto", "-"), "ciudad": f.get("Ciudad", "-"),
                           "telefono": f.get("Telefono", "-"), "total": f.get("Total", "-"),
                           "fecha": f.get("Fecha", "-"), "estado": f.get("Estado", "Nuevo")})
    return {"resultados": salida, "cantidad": len(salida)}


# ============================================================
#  BLOQUE 9 — FICHA DE CLIENTE
#  Todo sobre un cliente: si es comprador / recompra / lead,
#  sus pedidos y su charla. Pasás su id de contacto.
#  Probar:  /api/panel/cliente?id=EL_ID&clave=TU_CLAVE_PANEL
#  (el id lo sacás del Bloque 3 o del visor de Charlas)
# ============================================================
@app.get("/api/panel/cliente")
def panel_cliente(id: str = "", x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    if not id: return {"aviso": "Pasá el id del cliente (?id=...)"}
    # sus pedidos
    pedidos = []
    for reg in _leer_pedidos():
        f = reg.get("fields", {})
        if str(f.get("Contacto", "")) == str(id):
            pedidos.append({"producto": f.get("Producto", "-"), "total": f.get("Total", "-"),
                            "fecha": f.get("Fecha", "-"), "estado": f.get("Estado", "-")})
    # su charla
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY},
                     params={"maxRecords": 300}, timeout=10)
    charla = []
    if r.status_code == 200:
        regs = r.json().get("records", [])
        regs.sort(key=lambda x: x.get("createdTime", ""))
        for reg in regs:
            f = reg.get("fields", {})
            if str(f.get("contact_id", "")) != str(id): continue
            txt = f.get("mensaje_entrante", "")
            if txt.startswith("[user]"): charla.append({"rol": "cliente", "texto": txt[6:].strip()})
            elif txt.startswith("[bot]"): charla.append({"rol": "fer", "texto": txt[5:].strip()})
    # clasificar
    if len(pedidos) >= 2: tipo = "recompra"
    elif len(pedidos) == 1: tipo = "comprador"
    elif charla: tipo = "lead"
    else: tipo = "desconocido"
    return {"id": id, "tipo": tipo, "compras": len(pedidos),
            "pedidos": pedidos, "charla": charla}


# ============================================================
#  BLOQUE 10 — CONFIGURACIÓN DEL NEGOCIO (guardada, editable)
#  Guarda ajustes (costo de envío interior, nota, etc.) en Upstash.
#  GET  para leer:   /api/panel/config?clave=TU_CLAVE_PANEL
#  POST para guardar (desde el panel; manda JSON).
#  NOTA HONESTA: esto GUARDA la config. Para que el bot en vivo la
#  USE (ej: cambiar el envío sin tocar Render) hay un paso extra
#  que hacemos después, con cuidado, para no arriesgar la venta.
# ============================================================
def _config_leer():
    res = _upstash(["GET", "config:negocio"])
    if res:
        try: return json.loads(res)
        except Exception: pass
    # valores por defecto (los actuales)
    return {"envio_interior": ENVIO_INTERIOR, "nota": ""}

@app.get("/api/panel/config")
def panel_config_get(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    return {"config": _config_leer()}

@app.post("/api/panel/config")
async def panel_config_set(request: Request, x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    d = await request.json()
    actual = _config_leer()
    if "envio_interior" in d: actual["envio_interior"] = _solo_numero(d.get("envio_interior"))
    if "nota" in d: actual["nota"] = str(d.get("nota", ""))[:500]
    guardado = _upstash(["SET", "config:negocio", json.dumps(actual)])
    return {"ok": guardado is not None, "config": actual,
            "aviso": None if guardado is not None else "Upstash no configurado: no se pudo guardar."}


@app.post("/api/panel/editar-costo")
async def panel_editar_costo(request: Request, x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    d = await request.json()
    rid = d.get("id", "")
    costo = _solo_numero(d.get("costo", 0))
    if not rid: return {"ok": False, "error": "falta id"}
    url = "https://api.airtable.com/v0/%s/%s/%s" % (AIRTABLE_BASE, TABLA_CATALOGO, rid)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"}
    r = requests.patch(url, headers=headers, json={"fields": {"costo_gs": costo}, "typecast": True}, timeout=10)
    return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}


@app.post("/api/panel/postventa-mensaje")
async def panel_postventa_mensaje(request: Request, x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    d = await request.json()
    tipo = (d.get("tipo", "") or "").strip()
    nombre = (d.get("nombre", "") or "").strip() or "cliente"
    producto = (d.get("producto", "") or "").strip() or "el producto"
    base = ("Escribí UN mensaje corto, cálido y natural en español paraguayo para enviarle por Messenger "
            "al cliente %s que compró '%s'. Sin comillas, sin presionar, recordá que pagó contra entrega. "
            "Devolvé SOLO el mensaje. ") % (nombre, producto)
    guias = {
        "llego":   "El mensaje es para preguntarle con cariño si le llegó bien el producto y si quedó conforme.",
        "testimonio": "El cliente ya recibió el producto. Pedile con amabilidad, sin exigir, una fotito o unas palabras de cómo le fue, para poder mostrar a otros clientes. Que se sienta libre de decir que no.",
        "camino":  "Avisale que su pedido ya salió y va en camino, para que esté atento a la entrega. Tono de buena noticia.",
        "recompra": "Pasó un tiempo desde su compra. Escribile para saludarlo y ofrecerle con naturalidad volver a comprar o un producto que combine con lo que llevó, sin insistir."
    }
    p = base + guias.get(tipo, guias["llego"])
    return {"mensaje": preguntar_a_gemini([], p, SYSTEM_PROMPT)}


# estado del ultimo aviso de diagnostico (para no spamear Telegram cuando el pinger revisa seguido)
_DIAG_ULTIMO = {"firma": None, "ts": 0}

@app.get("/api/panel/diagnostico")
def panel_diagnostico(x_clave: str = Header(default=""), clave: str = "", avisar: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    checks = []
    def add(nombre, ok, detalle):
        checks.append({"nombre": nombre, "estado": "ok" if ok else "falla", "detalle": detalle})

    # 1) AIRTABLE + tablas + columnas clave
    try:
        headers = {"Authorization": "Bearer " + AIRTABLE_KEY}
        faltan_cols = []
        # Pedidos
        rp = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                          headers=headers, params={"maxRecords": 1}, timeout=10)
        if rp.status_code != 200:
            add("Airtable · Pedidos", False, "No responde (%s). Revisá AIRTABLE_BASE o el nombre de la tabla." % rp.status_code)
        else:
            recs = rp.json().get("records", [])
            cols = set(recs[0].get("fields", {}).keys()) if recs else set()
            for c in ("Producto", "Contacto"):
                if recs and c not in cols: faltan_cols.append("Pedidos." + c)
            add("Airtable · Pedidos", True, "OK" + (" (ojo: faltan columnas " + ", ".join(faltan_cols) + " — puede ser que no haya pedidos con esos datos aún)" if faltan_cols else ""))
        # Catálogo + costo_gs
        rc = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CATALOGO),
                          headers=headers, params={"maxRecords": 1}, timeout=10)
        if rc.status_code != 200:
            add("Airtable · Catálogo", False, "No responde (%s)." % rc.status_code)
        else:
            recs = rc.json().get("records", [])
            cols = set(recs[0].get("fields", {}).keys()) if recs else set()
            add("Airtable · Catálogo", True, "OK" + ("" if (not recs or "costo_gs" in cols) else " (falta la columna costo_gs para calcular ganancia)"))
        # Conversaciones
        rv = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS),
                          headers=headers, params={"maxRecords": 1}, timeout=10)
        add("Airtable · Conversaciones", rv.status_code == 200, "OK" if rv.status_code == 200 else "No responde (%s)." % rv.status_code)
    except Exception as e:
        add("Airtable", False, "Error de conexión: " + str(e)[:120])

    # 2) UPSTASH (memoria de Fer)
    try:
        pong = _upstash(["PING"])
        add("Memoria (Upstash)", pong is not None, "OK" if pong is not None else "No configurada o no responde. Fer usa memoria temporal (se pierde si el servidor reinicia).")
    except Exception as e:
        add("Memoria (Upstash)", False, "Error: " + str(e)[:120])

    # 3) MESSENGER (token de la página)
    try:
        rm = requests.get("https://graph.facebook.com/me", params={"access_token": PAGE_TOKEN}, timeout=10)
        ok = rm.status_code == 200
        add("Messenger (token)", ok, "OK" if ok else "Token vencido o inválido. Hay que regenerar el PAGE_TOKEN — el bot no puede responder a clientes.")
    except Exception as e:
        add("Messenger (token)", False, "Error: " + str(e)[:120])

    # 4) GEMINI (cerebro)
    try:
        rg = requests.post(GEMINI, json={"contents": [{"parts": [{"text": "ping"}]}]}, timeout=15)
        add("Gemini (cerebro)", rg.status_code == 200, "OK" if rg.status_code == 200 else "No responde (%s). Puede ser límite de uso o la GEMINI_KEY." % rg.status_code)
    except Exception as e:
        add("Gemini (cerebro)", False, "Error: " + str(e)[:120])

    # 5) PEDIDOS TRABADOS (comprobantes sin verificar / sin cobrar hace >=3 días)
    try:
        rt = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                          headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"pageSize": 100}, timeout=10)
        trabados = 0
        if rt.status_code == 200:
            ahora_utc = datetime.now(timezone.utc)
            for reg in rt.json().get("records", []):
                estado = str(reg.get("fields", {}).get("Estado", "")).lower()
                if estado in ("nuevo", "pendiente de verificación", "pendiente de verificacion"):
                    try:
                        f = reg.get("createdTime", "").replace("Z", "+00:00")
                        if (ahora_utc - datetime.fromisoformat(f)).days >= 3: trabados += 1
                    except Exception: pass
        add("Pedidos trabados", trabados == 0, "Ninguno 👍" if trabados == 0 else "%d pedido(s) sin cobrar/verificar hace 3+ días. Revisá la pestaña Por cobrar." % trabados)
    except Exception as e:
        add("Pedidos trabados", True, "No se pudo revisar: " + str(e)[:80])

    fallas = [c for c in checks if c["estado"] == "falla"]
    salud = "todo_ok" if not fallas else "hay_fallas"

    # aviso a Telegram INTELIGENTE: solo si se pide (avisar=1), sin spam.
    # - avisa cuando aparece una falla nueva (o cambia)
    # - repite el aviso de la misma falla como mucho cada 6 horas
    # - avisa UNA sola vez cuando todo se recupera
    if avisar == "1":
        try:
            firma = "|".join(sorted(c["nombre"] for c in fallas))
            ahora = datetime.now(timezone.utc).timestamp()
            prev = _DIAG_ULTIMO.get("firma")
            COOLDOWN = 6 * 3600
            if fallas:
                cambio = (firma != prev)
                paso_tiempo = (ahora - _DIAG_ULTIMO.get("ts", 0)) > COOLDOWN
                if cambio or paso_tiempo:
                    texto = "⚠️ DIAGNÓSTICO GUARANÍSTORE — revisá:\n" + "\n".join("• %s: %s" % (c["nombre"], c["detalle"]) for c in fallas)
                    avisar_telegram(texto)
                    _DIAG_ULTIMO["firma"] = firma
                    _DIAG_ULTIMO["ts"] = ahora
            else:
                if prev:
                    avisar_telegram("✅ GUARANÍSTORE: lo que estaba fallando ya se recuperó. Todo volvió a la normalidad.")
                _DIAG_ULTIMO["firma"] = None
                _DIAG_ULTIMO["ts"] = ahora
        except Exception:
            pass

    return {"salud": salud, "fallas": len(fallas), "checks": checks}


@app.get("/api/panel/acciones")
def panel_acciones(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    acciones = []
    ahora_utc = datetime.now(timezone.utc)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY}

    pedidos = _leer_pedidos()

    # quién compró y cuándo (para leads y recompra)
    compraron = set()
    ultima_compra = {}   # contacto -> (dias, nombre)
    for reg in pedidos:
        f = reg.get("fields", {})
        c = str(f.get("Contacto", "") or "")
        if c:
            compraron.add(c)
            try:
                fecha = reg.get("createdTime", "").replace("Z", "+00:00")
                dias = (ahora_utc - datetime.fromisoformat(fecha)).days
                if c not in ultima_compra or dias < ultima_compra[c][0]:
                    ultima_compra[c] = (dias, f.get("Nombre", "cliente"))
            except Exception:
                pass

    # 1) LEADS que hablaron y no compraron
    try:
        rv = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS),
                          headers=headers, params={"maxRecords": 300}, timeout=10)
        if rv.status_code == 200:
            charlas = {}
            for reg in rv.json().get("records", []):
                f = reg.get("fields", {})
                cid = str(f.get("contact_id", "") or "")
                if cid and f.get("mensaje_entrante"):
                    charlas[cid] = charlas.get(cid, 0) + 1
            leads = [c for c, n in charlas.items() if c not in compraron and n >= 2]
            if leads:
                acciones.append({"tipo": "leads", "icono": "\U0001F4AC", "prioridad": 1,
                                 "titulo": "%d lead(s) para recuperar" % len(leads),
                                 "detalle": "Preguntaron y no compraron. Ya los pagaste con los ads — escribiles hoy.",
                                 "boton": "Ver y escribir", "grupo": "numeros", "sub": "seguimiento"})
    except Exception:
        pass

    # 2) RECOMPRA: compraron hace 14 a 45 días
    recompra = [(c, v[1], v[0]) for c, v in ultima_compra.items() if 14 <= v[0] <= 45]
    if recompra:
        acciones.append({"tipo": "recompra", "icono": "\U0001F501", "prioridad": 2,
                         "titulo": "%d cliente(s) para recompra" % len(recompra),
                         "detalle": "Compraron hace unas semanas. Es el más fácil de venderle otra vez.",
                         "boton": "Armar mensaje", "grupo": "ventas", "sub": "postventa"})

    # 3) PEDIDOS trabados (sin cobrar / sin verificar) + comprobantes
    trabados, sin_verificar = 0, 0
    for reg in pedidos:
        estado = str(reg.get("fields", {}).get("Estado", "")).lower()
        if estado in ("pendiente de verificación", "pendiente de verificacion"):
            sin_verificar += 1
        elif estado == "nuevo":
            try:
                fecha = reg.get("createdTime", "").replace("Z", "+00:00")
                if (ahora_utc - datetime.fromisoformat(fecha)).days >= 2: trabados += 1
            except Exception:
                pass
    if sin_verificar:
        acciones.append({"tipo": "verificar", "icono": "\U0001F9FE", "prioridad": 1,
                         "titulo": "%d comprobante(s) por verificar" % sin_verificar,
                         "detalle": "Clientes que dicen que pagaron. Revisá y confirmá el pago.",
                         "boton": "Ver pendientes", "grupo": "ventas", "sub": "pendientes"})
    if trabados:
        acciones.append({"tipo": "trabados", "icono": "\u23F0", "prioridad": 2,
                         "titulo": "%d pedido(s) sin cobrar hace días" % trabados,
                         "detalle": "Se están enfriando. Recordáles el pago o cerralos.",
                         "boton": "Ver pendientes", "grupo": "ventas", "sub": "pendientes"})

    # catálogo: costos sin cargar, stock, producto ganador
    try:
        catalogo = _leer_catalogo()
        # ventas por producto
        ventas = {}
        for reg in pedidos:
            k = _norm(reg.get("fields", {}).get("Producto", ""))
            if k: ventas[k] = ventas.get(k, 0) + 1
        sin_costo, agotados, ganadores = [], [], []
        for reg in catalogo:
            f = reg.get("fields", {})
            nombre = f.get("nombre", "") or f.get("producto_id", "")
            k = _norm(nombre)
            if not k: continue
            costo = _solo_numero(f.get("costo_gs", 0))
            precio = _solo_numero(f.get("precio_gs", 0))
            vend = ventas.get(k, 0)
            if vend > 0 and costo <= 0: sin_costo.append(nombre)
            if not _hay_stock(f): agotados.append(nombre)
            if vend > 0 and costo > 0: ganadores.append((nombre, (precio - costo) * vend))
        # 4) costos sin cargar
        if sin_costo:
            acciones.append({"tipo": "costos", "icono": "\u26A0\uFE0F", "prioridad": 2,
                             "titulo": "Cargá el costo de %d producto(s)" % len(sin_costo),
                             "detalle": "Sin costo, tu ganancia real es un número inventado: " + ", ".join(sin_costo[:3]),
                             "boton": "Ir a Productos", "grupo": "productos", "sub": ""})
        # 5) stock agotado
        if agotados:
            acciones.append({"tipo": "stock", "icono": "\U0001F4E6", "prioridad": 2,
                             "titulo": "%d producto(s) agotado(s)" % len(agotados),
                             "detalle": "No podés vender lo que no hay: " + ", ".join(agotados[:3]) + ". Reponé o desactivá.",
                             "boton": "Ir a Productos", "grupo": "productos", "sub": ""})
        # 6) producto ganador -> meter ads
        if ganadores:
            ganadores.sort(key=lambda x: -x[1])
            top = ganadores[0]
            acciones.append({"tipo": "ganador", "icono": "\U0001F3AF", "prioridad": 3,
                             "titulo": "Tu producto más rentable: " + top[0],
                             "detalle": "Es el que más plata te deja. Metele los ads acá, no al que más vende.",
                             "boton": "Ver números", "grupo": "numeros", "sub": "ganancia"})
    except Exception:
        pass

    acciones.sort(key=lambda a: a["prioridad"])
    return {"acciones": acciones, "cantidad": len(acciones)}


@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
