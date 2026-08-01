# ============================================================
#  🤖  ESTE ARCHIVO ES PARA EL BOT  →  va en Render (repo guaranistorebot)
#  Reemplaza TODO tu main.py por esto. Tus variables de entorno en Render
#  siguen igual. Incluye: bot vendedor + catálogo dinámico + pedidos +
#  fotos/video + Telegram + WhatsApp + modo dueño + TODAS las APIs del panel.
# ============================================================
import os, re, json, unicodedata, requests
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
TIENDA        = "Guaranistore"          # nombre de tu página de Facebook (lo ven los clientes)
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

# ---------- PROMPTS ----------
SYSTEM_PROMPT = """Sos "Fer", el vendedor de la tienda paraguaya %s. Hablás en español paraguayo, cálido, cercano y humano (podés usar voseo). Sos honesto y nunca mentís.

TU FORMA DE VENDER:
- Acompañás a la persona con calidez y empatía. Si cuenta un problema personal o económico, dejás de vender y la tratás como persona.
- Vendés con confianza pero sin mentir: nunca inventes testimonios, ni falsa urgencia, ni precios que no sabés. El pago contra entrega y la garantía son tus mejores argumentos: la persona paga cuando recibe.
- Podés vender CUALQUIER producto del catálogo, no uno solo.

HERRAMIENTAS (etiquetas que el código detecta; el cliente NO las ve):
- Para saber precio, stock o datos de un producto, escribí: [CONSULTAR_PRODUCTO: nombre del producto]. Esperás el dato real y recién ahí respondés.
- Para mandar fotos: [FOTOS]  (y si piden más: [MASFOTOS])
- Para mandar el video: [VIDEO]
- Si el cliente pregunta por un producto que no manejás o querés avisar al dueño de un interés: [INTERES] lo que pidió [/INTERES]
- Cuando el pedido esté CERRADO y confirmado, con los datos, al final agregá EXACTAMENTE:
[PEDIDO] Producto: <producto> | Precio: <precio real en Gs> | Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]
Usá el nombre y el precio REAL del producto (el que consultaste). El cliente no ve esta etiqueta.

Sé breve, humano y claro. Nunca digas que sos una IA.""" % TIENDA

PROMPT_DUENO = """Sos el asistente PRIVADO del dueño de %s (modo dueño). Le hablás como su mano derecha del negocio: claro, directo y útil.
Con los datos de ventas y conversaciones que te paso, respondé lo que pregunte: resúmenes de ventas, estado de pedidos, qué clientes quedaron sin cerrar, objeciones comunes, y recomendaciones concretas para vender mejor. Sé honesto, sin inventar. Si no hay datos, decilo.""" % TIENDA

# ---------- CATALOGO DINAMICO ----------
def _norm(t):
    t = str(t or "").lower().strip()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", t)

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
        return "NO_ENCONTRADO: no hay un producto que coincida con '%s' en el catalogo." % consulta
    datos = []
    for k, v in f.items():
        if str(k).lower().startswith("url") or str(k).lower().startswith("link"): continue
        if v not in (None, "", []): datos.append("%s: %s" % (k, v))
    return "PRODUCTO ENCONTRADO -> " + " | ".join(datos)

def revisar_producto(respuesta, historial):
    m = re.search(r"\[CONSULTAR_PRODUCTO:\s*(.*?)\]", respuesta, re.IGNORECASE | re.DOTALL)
    if not m: return respuesta
    dato = consultar_producto(m.group(1).strip())
    refuerzo = ("El sistema consultó el catálogo y devolvió: %s\n"
                "Con ESE dato real, respondele al cliente de forma natural. "
                "No muestres la etiqueta ni digas 'el sistema'." % dato)
    final = preguntar_a_gemini(historial, refuerzo, SYSTEM_PROMPT)
    return re.sub(r"\[CONSULTAR_PRODUCTO:.*?\]", "", final, flags=re.IGNORECASE | re.DOTALL).strip()

# ---------- MEMORIA (Conversaciones) ----------
def leer_historial(sender):
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY}
    params = {"filterByFormula": "{contact_id}='%s'" % sender, "maxRecords": 20,
              "sort[0][field]": "Created", "sort[0][direction]": "asc"}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    hist = []
    if r.status_code == 200:
        for reg in r.json().get("records", []):
            txt = reg.get("fields", {}).get("mensaje_entrante", "")
            if txt.startswith("[user]"): hist.append(("user", txt[6:].strip()))
            elif txt.startswith("[bot]"): hist.append(("bot", txt[5:].strip()))
    return hist

def guardar(sender, rol, mensaje, canal="messenger"):
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"}
    prefijo = "[user] " if rol == "user" else "[bot] "
    cuerpo = {"fields": {"contact_id": sender, "canal": canal, "mensaje_entrante": prefijo + mensaje}}
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

# ---------- MESSENGER ----------
def _post_msg(payload):
    try: requests.post(GRAPH, params={"access_token": PAGE_TOKEN}, json=payload, timeout=10)
    except Exception: pass

def mostrar_escribiendo(sender):
    _post_msg({"recipient": {"id": sender}, "sender_action": "typing_on"})

def marcar_leido(sender):
    _post_msg({"recipient": {"id": sender}, "sender_action": "mark_seen"})

def enviar_a_messenger(sender, texto):
    for parte in [texto[i:i+1900] for i in range(0, len(texto), 1900)] or [texto]:
        r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                          json={"recipient": {"id": sender}, "message": {"text": parte}}, timeout=10)
        print(">>> MESSENGER:", r.status_code, r.text[:120])

def enviar_foto(sender, url_foto):
    _post_msg({"recipient": {"id": sender},
               "message": {"attachment": {"type": "image", "payload": {"url": url_foto, "is_reusable": True}}}})

# ---------- TELEGRAM ----------
def avisar_telegram(texto):
    try:
        requests.post("https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN,
                      json={"chat_id": TELEGRAM_CHAT, "text": texto}, timeout=10)
    except Exception: pass

# ---------- WHATSAPP (CallMeBot) ----------
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

def formatear_pedido(resumen):
    d = _parsear(resumen)
    return ("🛍️  NUEVO PEDIDO — %s\n━━━━━━━━━━━━━━━\n"
            "👤  Nombre:     %s\n📍  Ciudad:     %s\n📞  Teléfono:   %s\n🏠  Dirección:  %s\n"
            "━━━━━━━━━━━━━━━\n💜  Producto:   %s\n💰  Total:      %s (contra entrega)\n🕒  %s hs"
            % (TIENDA, d.get("nombre","-"), d.get("ciudad","-"), d.get("tel","-"),
               d.get("direccion","-"), d.get("producto","Producto"), d.get("precio","-"), ahora()))

def formatear_pedido_whatsapp(resumen):
    d = _parsear(resumen)
    return ("🛍️ *PEDIDO para cargar en Zappy*\n\n📦 %s — %s (contra entrega)\n\n"
            "👤 Cliente: %s\n📍 Ciudad: %s\n📞 Tel: %s\n🏠 Direccion: %s\n🕒 %s hs"
            % (d.get("producto","Producto"), d.get("precio","-"), d.get("nombre","-"),
               d.get("ciudad","-"), d.get("tel","-"), d.get("direccion","-"), ahora()))

def guardar_pedido(resumen):
    d = _parsear(resumen)
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS)
    headers = {"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"}
    cuerpo = {"fields": {"Producto": d.get("producto",""), "Nombre": d.get("nombre",""),
                         "Ciudad": d.get("ciudad",""), "Telefono": d.get("tel",""),
                         "Direccion": d.get("direccion",""), "Total": d.get("precio",""),
                         "Fecha": ahora(), "Estado": "Nuevo"}}
    try: requests.post(url, headers=headers, json=cuerpo, timeout=10)
    except Exception: pass

def revisar_pedido(sender, respuesta):
    if "[PEDIDO]" not in respuesta: return respuesta
    avisar_telegram(formatear_pedido(respuesta))
    enviar_whatsapp(formatear_pedido_whatsapp(respuesta))
    guardar_pedido(respuesta)
    return re.sub(r"\[PEDIDO\].*?\[/PEDIDO\]", "", respuesta, flags=re.DOTALL).strip()

def revisar_interes(sender, respuesta):
    m = re.search(r"\[INTERES\](.*?)\[/INTERES\]", respuesta, re.DOTALL)
    if not m: return respuesta
    avisar_telegram("👀 INTERÉS de un cliente en %s:\n%s" % (TIENDA, m.group(1).strip()))
    return re.sub(r"\[INTERES\].*?\[/INTERES\]", "", respuesta, flags=re.DOTALL).strip()

# ---------- FOTOS / VIDEO ----------
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
        lineas.append("- %s | %s | %s | %s | %s" % (f.get("Fecha","-"), f.get("Nombre","-"),
                      f.get("Producto","-"), f.get("Total","-"), f.get("Estado","-")))
    return "\n".join(lineas)

def leer_conversaciones():
    url = "https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CONVERS)
    r = requests.get(url, headers={"Authorization": "Bearer " + AIRTABLE_KEY},
                     params={"maxRecords": 60}, timeout=10)
    if r.status_code != 200: return "No pude leer las conversaciones."
    regs = r.json().get("records", [])
    return "\n".join(reg.get("fields", {}).get("mensaje_entrante", "") for reg in regs) or "Sin conversaciones."

# ---------- WEBHOOK ----------
MODO = {}       # sender -> "dueno" / "vendedor"
VISTOS = set()  # mids ya procesados

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
            texto = msg.get("text")
            mid = msg.get("mid")
            if not (sender and texto): continue
            if mid in VISTOS: continue
            VISTOS.add(mid)
            if len(VISTOS) > 500: VISTOS.clear()
            print(">>> TEXTO:", repr(texto), "de", sender)
            marcar_leido(sender); mostrar_escribiendo(sender)

            # modo dueño (palabra secreta)
            bajo = texto.strip().lower()
            if CLAVE_DUENO and bajo == CLAVE_DUENO:
                MODO[sender] = "dueno"
                enviar_a_messenger(sender, "🔓 Modo dueño activado. Preguntame por tus ventas.")
                continue
            if bajo in ("modo vendedor", "salir"):
                MODO[sender] = "vendedor"
                enviar_a_messenger(sender, "🛍️ Volví a modo vendedor.")
                continue

            if MODO.get(sender) == "dueno":
                contexto = resumen_ventas() + "\n\n=== CONVERSACIONES ===\n" + leer_conversaciones()
                resp = preguntar_a_gemini([], contexto + "\n\nPregunta del dueño: " + texto, PROMPT_DUENO)
                enviar_a_messenger(sender, resp)
                continue

            # modo vendedor
            historial = leer_historial(sender)
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
#   API DEL PANEL WEB  (protegidas con la clave CLAVE_PANEL)
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
    return {"total": len(pedidos),
            "hoy": sum(1 for p in pedidos if str(p.get("Fecha","")).startswith(hoy)),
            "entregados": sum(1 for p in pedidos if str(p.get("Estado","")).lower() == "entregado"),
            "nuevos": sum(1 for p in pedidos if str(p.get("Estado","")).lower() == "nuevo")}

@app.get("/api/panel/pedidos")
def panel_pedidos(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200: return {"pedidos": [], "error": r.text}
    out = []
    for reg in r.json().get("records", []):
        f = reg.get("fields", {})
        out.append({"id": reg.get("id",""), "producto": f.get("Producto",""), "nombre": f.get("Nombre",""),
                    "ciudad": f.get("Ciudad",""), "telefono": f.get("Telefono",""), "direccion": f.get("Direccion",""),
                    "total": f.get("Total",""), "fecha": f.get("Fecha",""), "estado": f.get("Estado","") or "Nuevo"})
    out.reverse()
    return {"pedidos": out}

@app.post("/api/panel/pedido")
async def panel_crear_pedido(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    cuerpo = {"fields": {"Producto": d.get("producto",""), "Nombre": d.get("nombre",""), "Ciudad": d.get("ciudad",""),
                         "Telefono": d.get("telefono",""), "Direccion": d.get("direccion",""), "Total": d.get("total",""),
                         "Fecha": ahora(), "Estado": d.get("estado","Nuevo")}}
    r = requests.post("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS),
                      headers={"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"},
                      json=cuerpo, timeout=10)
    return {"ok": r.status_code in (200, 201), "error": None if r.status_code in (200,201) else r.text}

@app.post("/api/panel/estado")
async def panel_estado(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    r = requests.patch("https://api.airtable.com/v0/%s/%s/%s" % (AIRTABLE_BASE, TABLA_PEDIDOS, d.get("id","")),
                       headers={"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"},
                       json={"fields": {"Estado": d.get("estado","")}}, timeout=10)
    return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}

@app.get("/api/panel/catalogo")
def panel_catalogo(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CATALOGO),
                     headers={"Authorization": "Bearer " + AIRTABLE_KEY}, params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200: return {"productos": [], "error": r.text}
    out = []
    for reg in r.json().get("records", []):
        f = reg.get("fields", {})
        out.append({"nombre": f.get("nombre","") or f.get("producto_id",""), "precio": f.get("precio_gs",""),
                    "stock": f.get("stock_estado",""), "descripcion": f.get("descripcion_corta","")})
    return {"productos": out}

@app.post("/api/panel/producto")
async def panel_crear_producto(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    nombre = (d.get("nombre","") or "").strip()
    pid = (d.get("producto_id","") or "").strip() or nombre.lower().replace(" ", "")[:20] or "producto"
    cuerpo = {"fields": {"producto_id": pid, "nombre": nombre, "precio_gs": d.get("precio",""),
                         "stock_estado": d.get("stock","disponible"), "descripcion_corta": d.get("descripcion","")},
              "typecast": True}
    r = requests.post("https://api.airtable.com/v0/%s/%s" % (AIRTABLE_BASE, TABLA_CATALOGO),
                      headers={"Authorization": "Bearer " + AIRTABLE_KEY, "Content-Type": "application/json"},
                      json=cuerpo, timeout=10)
    return {"ok": r.status_code in (200, 201), "error": None if r.status_code in (200,201) else r.text}

@app.post("/api/panel/fer")
async def panel_fer(request: Request, x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    d = await request.json()
    mensaje = (d.get("mensaje","") or "").strip()
    if not mensaje: return {"respuesta": "Decime qué querés saber: ventas de hoy, últimos pedidos, qué mejorar…"}
    contexto = resumen_ventas() + "\n\n=== CONVERSACIONES ===\n" + leer_conversaciones()
    return {"respuesta": preguntar_a_gemini([], contexto + "\n\nMensaje del dueño: " + mensaje, PROMPT_DUENO)}

@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
