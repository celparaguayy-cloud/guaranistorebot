# ============================================================
#  🤖 main.py — FER MULTI-NEGOCIO (Render, repo guaranistorebot)
#  Un solo bot que atiende a VARIOS negocios a la vez.
#
#  - Guaranístore sigue funcionando con las MISMAS variables de Render
#    de siempre (PAGE_TOKEN, AIRTABLE_BASE, CLAVE_PANEL, etc.).
#  - Cada negocio nuevo se carga desde /admin y se guarda en Upstash:
#    su página de Facebook y/o su número de WhatsApp, su base de Airtable,
#    su clave de panel, su Telegram y su forma de vender.
#
#  VARIABLES NUEVAS (todas opcionales; sin ellas Guaranístore anda igual):
#   - ADMIN_CLAVE      clave para entrar a /admin (larga, inventada por vos)
#   - PAGE_ID          id de la página de Guaranístore (si falta, se averigua solo)
#   - META_APP_ID      id de tu app de Meta
#   - META_APP_SECRET  clave secreta de tu app de Meta (para tokens que no vencen)
#   - VERIFICAR_FIRMA  poné 1 para aceptar solo mensajes firmados por Meta
#
#  WHATSAPP (API oficial de Meta; opcional: sin esto todo sigue igual que antes):
#   - WA_PHONE_ID      el "Identificador de número de teléfono" del WhatsApp de Guaranístore
#   - WA_TOKEN         token permanente (usuario del sistema) con permisos de WhatsApp
#   - WA_WABA_ID       el "Identificador de la cuenta de WhatsApp Business" (para conectarla al bot desde /admin)
#   - WA_APP_SECRET    solo si usás VERIFICAR_FIRMA y el WhatsApp está en OTRA app de Meta
#   Los negocios clientes cargan SU número y SU token desde /admin (cada uno con su app de Meta).
#   El webhook es el de siempre: /webhook, con tu VERIFY_TOKEN, suscripto al campo "messages".
#
#  ⚠️ COLUMNAS QUE NECESITA LA BASE DE AIRTABLE DE CADA NEGOCIO:
#   - Pedidos: Producto, Nombre, Ciudad, Telefono, Direccion, Total, Fecha,
#              Estado, Contacto
#   - Catalogo_Espejo: producto_id, nombre, precio_gs, costo_gs,
#              stock_estado, descripcion_corta (opcional: stock numérico)
#   - Conversaciones: contact_id, canal, mensaje_entrante
# ============================================================
import os, re, json, time, hmac, html, base64, hashlib, threading, contextvars, unicodedata, requests
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Response, Header, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://celparaguayy-cloud.github.io"],
    allow_methods=["*"], allow_headers=["*"],
)

# ---------- CONFIG (Guaranístore, variables de Render de siempre) ----------
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

# ---------- CONFIG NUEVA (multi-negocio, opcional) ----------
PAGE_ID         = os.environ.get("PAGE_ID", "").strip()
ADMIN_CLAVE     = os.environ.get("ADMIN_CLAVE", "").strip()
META_APP_ID     = os.environ.get("META_APP_ID", "").strip()
META_APP_SECRET = os.environ.get("META_APP_SECRET", "").strip()
VERIFICAR_FIRMA = os.environ.get("VERIFICAR_FIRMA", "").strip() == "1"

# ---------- WHATSAPP de Guaranístore (API oficial; opcional) ----------
WA_PHONE_ID   = re.sub(r"\D", "", os.environ.get("WA_PHONE_ID", ""))
WA_TOKEN      = os.environ.get("WA_TOKEN", "").strip()
WA_APP_SECRET = os.environ.get("WA_APP_SECRET", "").strip()
WA_WABA_ID    = re.sub(r"\D", "", os.environ.get("WA_WABA_ID", ""))
WA_API        = "https://graph.facebook.com/" + (os.environ.get("WA_API_VERSION", "").strip() or "v24.0")

TABLA_CONVERS  = "Conversaciones"
TABLA_PEDIDOS  = "Pedidos"
TABLA_CATALOGO = "Catalogo_Espejo"

GRAPH_API = "https://graph.facebook.com/v21.0"
GRAPH  = GRAPH_API + "/me/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key="
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
# La forma de vender de siempre. Para Guaranístore queda EXACTAMENTE igual que antes;
# los negocios nuevos la usan como base si no cargan una propia.
PROMPT_VENTA = """Sos "%(vendedor)s", el vendedor de la tienda paraguaya %(tienda)s. Hablás en español paraguayo, cálido, cercano y humano (podés usar voseo). Sos honesto y nunca mentís. Tu meta es ayudar a la persona a decidirse y CERRAR el pedido, sin presionar de más.

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

"""

# Fer no anda aclarando que es un asistente virtual, pero si le preguntan de frente, no miente.
HONESTO = (" No hace falta que aclares que sos un asistente virtual; pero si te preguntan directamente si sos un bot, "
           "una IA o una persona, decí la verdad con naturalidad (sos el asistente virtual %s) y seguí ayudando.")
PIE_PROMPT = "\n\nSé breve, humano y claro (mensajes cortos, de chat)." + HONESTO % "de la tienda"

def _herramientas(fotos=True, mas_fotos=True, video=True):
    """Las etiquetas que el código detecta. Si un negocio no tiene fotos o video, no se las ofrece."""
    lineas = ["HERRAMIENTAS (etiquetas que el código detecta; el cliente NO las ve):",
              "- Precio/stock/datos de un producto: [CONSULTAR_PRODUCTO: nombre]. Esperás el dato real y recién ahí respondés."]
    if fotos: lineas.append("- Fotos: [FOTOS]  (más fotos: [MASFOTOS])" if mas_fotos else "- Fotos: [FOTOS]")
    if video: lineas.append("- Video: [VIDEO]")
    lineas += ["- Interés en otro producto / aviso al dueño: [INTERES] lo que pidió [/INTERES]",
               "- Si pide hablar con una persona, o tiene un reclamo que vos no podés resolver: [HUMANO] el motivo en pocas palabras [/HUMANO] y decile que alguien del equipo le va a escribir apenas pueda. No la uses para dudas que podés resolver vos.",
               "- Pedido CERRADO y confirmado, al final agregá EXACTAMENTE:",
               "[PEDIDO] Producto: <producto> | Precio: <precio real en Gs> | Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]",
               "Usá el nombre y el precio REAL del producto. El cliente no ve esta etiqueta."]
    if not fotos: lineas.append("No tenés fotos para mandar por acá: no las prometas.")
    if not video: lineas.append("No tenés video para mandar por acá: no lo prometas.")
    return "\n".join(lineas)

SYSTEM_PROMPT = PROMPT_VENTA % {"vendedor": "Fer", "tienda": TIENDA} + _herramientas() + PIE_PROMPT

PROMPT_DUENO_BASE = """Sos el asistente PRIVADO del dueño de %s (modo dueño). Le hablás como su mano derecha del negocio: claro, directo y útil. Con los datos de ventas, productos y conversaciones que te paso, respondé lo que pregunte: resúmenes, estado de pedidos, qué producto conviene impulsar, objeciones frecuentes y recomendaciones concretas para vender más. Sé honesto, sin inventar."""
PROMPT_DUENO = PROMPT_DUENO_BASE % TIENDA

# ---------- UTILIDADES ----------
def _norm(t):
    t = str(t or "").lower().strip()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", t)

def _solo_numero(s):
    return int(re.sub(r"[^\d]", "", str(s or "")) or 0)

def _igual(a, b):
    """Compara claves sin filtrar pistas por el tiempo de respuesta. Vacío nunca coincide."""
    a, b = str(a or ""), str(b or "")
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())

_RID = re.compile(r"^rec[A-Za-z0-9]{14}$")
def _rid(valor):
    """Id de registro de Airtable válido (recXXXXXXXXXXXXXX) o "" si no lo es."""
    valor = str(valor or "").strip()
    return valor if _RID.match(valor) else ""

def _contacto(valor):
    """Id de un cliente, limpio para usarlo en una búsqueda de Airtable.
    Messenger y WhatsApp con número: solo dígitos. WhatsApp sin número (cliente con usuario): su id tal cual."""
    s = str(valor or "").strip()
    if re.fullmatch(r"\+?[\d\s().-]+", s): return re.sub(r"\D", "", s)
    return re.sub(r"[^A-Za-z0-9._-]", "", s)[:140]

async def _cuerpo(request: Request):
    """El JSON que manda el navegador (como antes: no exige cabecera, y si no viene nada da {})."""
    try: d = await request.json()
    except Exception: d = {}
    return d if isinstance(d, dict) else {}

def descargar(url):
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.content, r.headers.get("Content-Type", "image/jpeg")
    except Exception:
        pass
    return None, None

# ============================================================
#   NEGOCIOS (multi-cliente)
# ============================================================
# Lo que se guarda de cada negocio. Los valores son los de por defecto.
CAMPOS_NEGOCIO = {
    "id": "", "nombre": "", "vendedor": "Fer", "activo": True,
    "page_id": "", "page_token": "",
    "wa_phone_id": "", "wa_token": "", "wa_waba_id": "", "wa_app_secret": "",
    "airtable_base": "", "airtable_key": "",
    "telegram_chat": "", "telegram_token": "",
    "clave_panel": "", "clave_dueno": "",
    "prompt": "", "envio_interior": 25000,
    "fotos": [], "video": "",
    "whatsapp_destino": "", "callmebot_apikey": "",
    "gemini_key": "", "notas": "", "creado": "",
}
# Nunca se muestran enteros en admin.html (solo los últimos 4 caracteres).
SECRETOS = ("page_token", "wa_token", "wa_app_secret", "airtable_key", "telegram_token", "callmebot_apikey", "gemini_key")

def _limpiar_negocio(d):
    """Deja los datos de un negocio con el tipo correcto y sin campos extra."""
    out = {}
    for k, defecto in CAMPOS_NEGOCIO.items():
        v = d.get(k, defecto)
        if isinstance(defecto, bool):
            v = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "si", "sí", "on")
        elif isinstance(defecto, int):
            v = _solo_numero(v) if str(v if v is not None else "").strip() != "" else defecto
        elif isinstance(defecto, list):
            items = v if isinstance(v, list) else str(v or "").splitlines()
            v = [str(u).strip() for u in items if str(u).strip()]
        else:
            v = str(v if v is not None else "").strip()
        out[k] = v
    out["clave_dueno"] = out["clave_dueno"].lower()
    out["prompt"] = out["prompt"][:12000]
    out["wa_phone_id"] = re.sub(r"\D", "", out["wa_phone_id"])
    out["wa_waba_id"] = re.sub(r"\D", "", out["wa_waba_id"])
    return out

class Negocio:
    def __init__(self, datos, principal=False):
        d = datos if principal else _limpiar_negocio(datos)
        self.datos = d
        self.principal = principal
        for k in CAMPOS_NEGOCIO:
            setattr(self, k, d.get(k, CAMPOS_NEGOCIO[k]))
        if principal:
            self.system_prompt = SYSTEM_PROMPT
            self.prompt_dueno = PROMPT_DUENO
            self.marca_aviso = "GUARANÍSTORE"
        else:
            # lo que el negocio no cargue, usa lo tuyo (tu Gemini, tu Airtable, tu bot de Telegram)
            self.airtable_key = self.airtable_key or AIRTABLE_KEY
            self.telegram_token = self.telegram_token or TELEGRAM_TOKEN
            self.gemini_key = self.gemini_key or GEMINI_KEY
            self.vendedor = self.vendedor or "Fer"
            herramientas = _herramientas(len(self.fotos) > 0, len(self.fotos) > 3, bool(self.video))
            if self.prompt:
                self.system_prompt = (self.prompt + "\n\n" + herramientas +
                                      "\n\nSé breve, humano y claro (mensajes cortos, de chat)." + HONESTO % "del negocio")
            else:
                self.system_prompt = PROMPT_VENTA % {"vendedor": self.vendedor, "tienda": self.nombre} + herramientas + PIE_PROMPT
            self.prompt_dueno = PROMPT_DUENO_BASE % self.nombre
            self.marca_aviso = self.nombre.upper()

    def clave_historial(self, sender):
        # Guaranístore conserva la memoria de siempre ("hist:<cliente>")
        return "hist:%s" % sender if self.principal else "hist:%s:%s" % (self.id, sender)

    def clave_config(self):
        return "config:negocio" if self.principal else "config:%s" % self.id

    def conectado(self):
        """¿Tiene Messenger conectado?"""
        return bool(self.page_id and self.page_token)

    def wa_conectado(self):
        """¿Tiene WhatsApp cargado (su número y su token)?"""
        return bool(self.wa_phone_id and self.wa_token)

PRINCIPAL = Negocio({
    "id": "principal", "nombre": TIENDA, "vendedor": "Fer", "activo": True,
    "page_id": PAGE_ID, "page_token": PAGE_TOKEN,
    "wa_phone_id": WA_PHONE_ID, "wa_token": WA_TOKEN, "wa_waba_id": WA_WABA_ID, "wa_app_secret": WA_APP_SECRET,
    "airtable_base": AIRTABLE_BASE, "airtable_key": AIRTABLE_KEY,
    "telegram_chat": TELEGRAM_CHAT, "telegram_token": TELEGRAM_TOKEN,
    "clave_panel": CLAVE_PANEL, "clave_dueno": CLAVE_DUENO,
    "prompt": "", "envio_interior": ENVIO_INTERIOR,
    "fotos": FOTOS, "video": VIDEO,
    "whatsapp_destino": WHATSAPP_DESTINO, "callmebot_apikey": CALLMEBOT_APIKEY,
    "gemini_key": GEMINI_KEY, "notas": "", "creado": "",
}, principal=True)

# El negocio que se está atendiendo AHORA (cada mensaje o pedido del panel tiene el suyo,
# así dos negocios atendidos al mismo tiempo nunca se mezclan).
_ACTUAL = contextvars.ContextVar("negocio_actual", default=None)
_PAUSADO = contextvars.ContextVar("panel_pausado", default=False)
# Por dónde llegó el mensaje que se está atendiendo AHORA ("messenger" / "whatsapp").
# Fuera de un mensaje (por ejemplo, desde el panel) queda en None y se averigua con canal_de().
_CANAL  = contextvars.ContextVar("canal_actual", default=None)
_WA_MSG = contextvars.ContextVar("wa_mensaje_actual", default="")    # id del mensaje de WhatsApp (para "leído" y "escribiendo")
_WA_TEL = contextvars.ContextVar("wa_telefono_actual", default="")   # número del cliente de WhatsApp, si lo comparte

def N():
    return _ACTUAL.get() or PRINCIPAL

def usar(negocio):
    _ACTUAL.set(negocio)
    return negocio

def _at_url(tabla, rid=""):
    return "https://api.airtable.com/v0/%s/%s%s" % (N().airtable_base, tabla, ("/" + rid) if rid else "")

def _at_hdr(con_json=False):
    h = {"Authorization": "Bearer " + N().airtable_key}
    if con_json: h["Content-Type"] = "application/json"
    return h

def _gemini():
    return GEMINI_URL + N().gemini_key

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
    token = N().page_token
    payload = {"recipient": {"id": recipient_id},
               "message": {"attachment": {"type": "image", "payload": {"url": image_url, "is_reusable": True}}}}
    try:
        r = requests.post(GRAPH, params={"access_token": token}, json=payload, timeout=15)
        if r.status_code != 200 and fallback_url and fallback_url != image_url:
            payload["message"]["attachment"]["payload"]["url"] = fallback_url
            r = requests.post(GRAPH, params={"access_token": token}, json=payload, timeout=15)
        print(">>> FOTO:", r.status_code, r.text[:100])
    except Exception as e:
        if fallback_url and fallback_url != image_url:
            payload["message"]["attachment"]["payload"]["url"] = fallback_url
            try: requests.post(GRAPH, params={"access_token": token}, json=payload, timeout=15)
            except Exception: pass
        print(">>> FOTO error:", e)

# ---------- CATALOGO DINAMICO ----------
def _leer_catalogo():
    url = _at_url(TABLA_CATALOGO)
    headers = _at_hdr()
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

def revisar_producto(respuesta, historial, prompt=None):
    m = re.search(r"\[CONSULTAR_PRODUCTO:\s*(.*?)\]", respuesta, re.IGNORECASE | re.DOTALL)
    if not m: return respuesta
    dato = consultar_producto(m.group(1).strip())
    refuerzo = ("El sistema consultó el catálogo: %s\nCon ESE dato real (incluido si hay stock), "
                "respondele al cliente de forma natural. Si está AGOTADO, no lo vendas. "
                "No muestres la etiqueta ni digas 'el sistema'." % dato)
    final = preguntar_a_gemini(historial, refuerzo, prompt or N().system_prompt)
    return re.sub(r"\[CONSULTAR_PRODUCTO:.*?\]", "", final, flags=re.IGNORECASE | re.DOTALL).strip()

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
    key = N().clave_historial(sender)
    res = _upstash(["LRANGE", key, "0", "-1"])
    if res is None:
        return HISTORIAL.get(key, [])[-20:]   # respaldo RAM
    hist = []
    for txt in res[-20:]:
        if txt.startswith("[user]"): hist.append(("user", txt[6:].strip()))
        elif txt.startswith("[bot]"): hist.append(("bot", txt[5:].strip()))
    return hist

def guardar(sender, rol, mensaje, canal=None):
    canal = canal or _CANAL.get() or "messenger"
    prefijo = "[user] " if rol == "user" else "[bot] "
    linea = prefijo + mensaje
    key = N().clave_historial(sender)
    if _upstash(["RPUSH", key, linea]) is not None:
        _upstash(["LTRIM", key, "-40", "-1"])          # deja solo los últimos 40
        _upstash(["EXPIRE", key, "2592000"])           # se autolimpia a los 30 días
    else:
        HISTORIAL.setdefault(key, []).append((rol, mensaje))   # respaldo RAM
        if len(HISTORIAL[key]) > 40: HISTORIAL[key] = HISTORIAL[key][-40:]
    # Además guarda en Airtable (solo para el visor de Charlas del panel)
    cuerpo = {"fields": {"contact_id": sender, "canal": canal, "mensaje_entrante": linea}}
    try: requests.post(_at_url(TABLA_CONVERS), headers=_at_hdr(True), json=cuerpo, timeout=10)
    except Exception: pass

# ---------- REGISTRO DE NEGOCIOS (Upstash, hash "negocios") ----------
_REG = {"ts": 0.0, "lista": []}
_REG_LOCK = threading.Lock()
REG_SEGUNDOS = 30   # cada cuánto se vuelve a leer la lista de negocios

def negocios_guardados(fresco=False):
    with _REG_LOCK:
        if not fresco and _REG["ts"] and time.time() - _REG["ts"] < REG_SEGUNDOS:
            return _REG["lista"]
    res = _upstash(["HGETALL", "negocios"])
    with _REG_LOCK:
        _REG["ts"] = time.time()
        if res is None:
            return _REG["lista"]          # Upstash no responde: sigue con lo último que leyó
        lista = []
        for i in range(0, len(res) - 1, 2):
            try: lista.append(Negocio(json.loads(res[i + 1])))
            except Exception as e: print(">>> NEGOCIO ilegible:", res[i], e)
        _REG["lista"] = lista
        return lista

def _negocio_guardado(nid):
    """Datos crudos de un negocio, leídos directo de Upstash (para editar)."""
    res = _upstash(["HGET", "negocios", nid])
    if not res: return None
    try: return json.loads(res)
    except Exception: return None

def _guardar_negocio(datos):
    ok = _upstash(["HSET", "negocios", datos["id"], json.dumps(datos, ensure_ascii=False)]) is not None
    with _REG_LOCK: _REG["ts"] = 0.0
    return ok

def _borrar_negocio(nid):
    ok = _upstash(["HDEL", "negocios", nid]) is not None
    with _REG_LOCK: _REG["ts"] = 0.0
    return ok

def negocio_por_id(nid):
    if nid == "principal": return PRINCIPAL
    return next((n for n in negocios_guardados() if n.id == nid), None)

_PAGINA_PRINCIPAL = {"id": PAGE_ID, "intento": 0.0}

def pagina_principal():
    """Id de la página de Guaranístore: PAGE_ID o, si falta, se lo pregunta a Meta una vez."""
    if not _PAGINA_PRINCIPAL["id"] and time.time() - _PAGINA_PRINCIPAL["intento"] > 300:
        _PAGINA_PRINCIPAL["intento"] = time.time()
        try:
            r = requests.get(GRAPH_API + "/me", params={"fields": "id", "access_token": PAGE_TOKEN}, timeout=10)
            if r.status_code == 200:
                _PAGINA_PRINCIPAL["id"] = str(r.json().get("id", "") or "")
        except Exception as e:
            print(">>> PAGE_ID error:", e)
    return _PAGINA_PRINCIPAL["id"]

def negocio_por_pagina(page_id):
    page_id = str(page_id or "")
    principal = pagina_principal()
    if not page_id or page_id == principal: return PRINCIPAL
    for n in negocios_guardados():
        if n.page_id and n.page_id == page_id: return n
    # Si todavía no se sabe cuál es la página de Guaranístore, todo va a Guaranístore (como siempre).
    return None if principal else PRINCIPAL

def negocio_por_whatsapp(phone_id):
    """El negocio dueño de un número de WhatsApp (por su identificador de número)."""
    phone_id = str(phone_id or "")
    if not phone_id: return None
    if WA_PHONE_ID and phone_id == WA_PHONE_ID: return PRINCIPAL
    for n in negocios_guardados():
        if n.wa_phone_id and n.wa_phone_id == phone_id: return n
    return None

def negocio_por_clave(clave):
    if _igual(clave, CLAVE_PANEL): return PRINCIPAL
    for n in negocios_guardados():
        if _igual(clave, n.clave_panel): return n
    return None

# ---------- GEMINI ----------
def preguntar_a_gemini(historial, texto_nuevo, prompt, _reintento=True):
    contents = []
    for rol, msg in historial:
        contents.append({"role": "user" if rol == "user" else "model", "parts": [{"text": msg}]})
    contents.append({"role": "user", "parts": [{"text": texto_nuevo}]})
    cuerpo = {"system_instruction": {"parts": [{"text": prompt}]}, "contents": contents}
    try:
        r = requests.post(_gemini(), json=cuerpo, timeout=30)
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
        r = requests.post(_gemini(), json=cuerpo, timeout=45)
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        txt = txt.replace("```json", "").replace("```", "").strip()
        return json.loads(txt)
    except Exception as e:
        print(">>> COMPROBANTE error:", e)
        return None

def transcribir_audio(audio_bytes, mime="audio/ogg"):
    """Gemini escucha un audio del cliente y devuelve lo que dijo ("" si no se entiende)."""
    mime = (mime or "audio/ogg").split(";")[0].strip() or "audio/ogg"
    if not audio_bytes or len(audio_bytes) > 12 * 1024 * 1024: return ""    # muy largo para mandarlo así
    instruccion = ("Transcribí textualmente lo que dice este audio de un cliente (español paraguayo; puede mezclar guaraní). "
                   "Devolvé SOLO la transcripción, sin comillas ni comentarios. Si no se entiende nada, devolvé una cadena vacía.")
    cuerpo = {"contents": [{"parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio_bytes).decode()}},
        {"text": instruccion}
    ]}]}
    try:
        r = requests.post(_gemini(), json=cuerpo, timeout=60)
        cands = r.json().get("candidates") or []
        partes = (cands[0].get("content", {}).get("parts") or []) if cands else []
        return (partes[0].get("text", "") if partes else "").strip().strip('"').strip()[:1500]
    except Exception as e:
        print(">>> AUDIO error:", e)
        return ""

# ---------- MESSENGER ----------
def _post_msg(payload):
    try: requests.post(GRAPH, params={"access_token": N().page_token}, json=payload, timeout=10)
    except Exception: pass

def mostrar_escribiendo(sender):
    if _CANAL.get() == "whatsapp": return             # en WhatsApp va junto con el "leído"
    _post_msg({"recipient": {"id": sender}, "sender_action": "typing_on"})

def marcar_leido(sender):
    if _CANAL.get() == "whatsapp": _wa_leido(); return
    _post_msg({"recipient": {"id": sender}, "sender_action": "mark_seen"})

def enviar_a_messenger(sender, texto):
    ok = True
    for parte in [texto[i:i+1900] for i in range(0, len(texto), 1900)] or [texto]:
        try:
            r = requests.post(GRAPH, params={"access_token": N().page_token},
                              json={"recipient": {"id": sender}, "message": {"text": parte}}, timeout=10)
            print(">>> MESSENGER:", r.status_code, r.text[:120])
            ok = ok and r.status_code == 200
        except Exception as e:
            print(">>> MESSENGER error:", e)
            ok = False
    return ok

# ---------- WHATSAPP (API oficial de Meta) ----------
# Cada negocio usa SU número (wa_phone_id) y SU token (wa_token); Guaranístore los toma de Render.
# OJO: enviar_whatsapp(), más abajo, es otra cosa (el aviso de pedidos al dueño por CallMeBot).
_CANALES = {}        # (negocio, cliente) -> "whatsapp": para saber por dónde escribirle desde el panel

def _recordar_canal(sender, canal):
    k = (N().id, str(sender))
    if _CANALES.get(k) == canal: return
    if len(_CANALES) > 5000: _CANALES.clear()
    _CANALES[k] = canal
    _upstash(["SET", "canal:%s:%s" % k, canal, "EX", "15552000"])     # se acuerda 180 días

def canal_de(sender):
    """Por qué canal hay que escribirle a este cliente."""
    actual = _CANAL.get()
    if actual: return actual
    n, s = N(), str(sender or "")
    if s and not s.isdigit(): return "whatsapp"        # id de WhatsApp sin número (cliente con usuario)
    k = (n.id, s)
    if k not in _CANALES:
        res = _upstash(["GET", "canal:%s:%s" % k])
        if res in ("whatsapp", "messenger"): _CANALES[k] = res
    if k in _CANALES: return _CANALES[k]
    return "whatsapp" if (n.wa_conectado() and not n.page_token) else "messenger"

def _wa_destino(sender):
    """A quién va: por número o, si el cliente no comparte su número, por su id de WhatsApp."""
    s = str(sender)
    return {"to": s} if s.isdigit() else {"recipient": s}

def _wa_post(payload, callado=False):
    n = N()
    if not n.wa_conectado():
        print(">>> WHATSAPP: el negocio", n.id, "no tiene WhatsApp cargado"); return False
    try:
        r = requests.post("%s/%s/messages" % (WA_API, n.wa_phone_id),
                          headers={"Authorization": "Bearer " + n.wa_token}, json=payload, timeout=15)
        if not (callado and r.status_code == 200):
            print(">>> WHATSAPP:", r.status_code, r.text[:160])
        return r.status_code == 200
    except Exception as e:
        print(">>> WHATSAPP error:", e)
        return False

def _wa_leido():
    """Marca el mensaje del cliente como leído y muestra "escribiendo…" (en WhatsApp van juntos)."""
    mid = _WA_MSG.get()
    if mid:
        _wa_post({"messaging_product": "whatsapp", "status": "read", "message_id": mid,
                  "typing_indicator": {"type": "text"}}, callado=True)

def enviar_a_whatsapp(sender, texto):
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto or "")       # negrita al estilo WhatsApp
    ok = True
    for parte in [texto[i:i+3800] for i in range(0, len(texto), 3800)] or [texto]:
        cuerpo = {"messaging_product": "whatsapp", "recipient_type": "individual", "type": "text",
                  "text": {"body": parte, "preview_url": "http" in parte}}
        cuerpo.update(_wa_destino(sender))
        ok = _wa_post(cuerpo) and ok
    return ok

def enviar_foto_whatsapp(sender, url_foto):
    cuerpo = {"messaging_product": "whatsapp", "recipient_type": "individual", "type": "image",
              "image": {"link": url_foto}}
    cuerpo.update(_wa_destino(sender))
    return _wa_post(cuerpo)

def _wa_bajar(media):
    """Baja una foto, un audio o un PDF que mandó el cliente por WhatsApp.
    El link se le pide SIEMPRE a Meta con el id (no se usa el que venga en el aviso):
    así el token del negocio nunca sale hacia otro lado."""
    n = N()
    mid = str(media.get("id") or "")
    if not mid.isdigit(): return None, None
    hdr = {"Authorization": "Bearer " + n.wa_token}
    try:
        r = requests.get("%s/%s" % (WA_API, mid), params={"phone_number_id": n.wa_phone_id}, headers=hdr, timeout=15)
        if r.status_code != 200:
            print(">>> WHATSAPP archivo:", r.status_code, r.text[:120]); return None, None
        info = r.json()
        url = str(info.get("url") or "")
        if not url.startswith("https://"): return None, None
        d = requests.get(url, headers=hdr, timeout=30)
        if d.status_code == 200:
            mime = str(info.get("mime_type") or media.get("mime_type") or d.headers.get("Content-Type") or "")
            return d.content, (mime.split(";")[0].strip() or None)
        print(">>> WHATSAPP descarga:", d.status_code)
    except Exception as e:
        print(">>> WHATSAPP archivo error:", e)
    return None, None

def _wa_remitente(m, valor):
    """Quién escribe: su número (solo dígitos) o, si no lo comparte, su id de WhatsApp."""
    tel = str(m.get("from") or "").strip().lstrip("+")
    if tel.isdigit(): return tel
    contacto = ((valor.get("contacts") or [{}])[0]) or {}
    for cand in (m.get("from_user_id"), m.get("user_id"), contacto.get("user_id"), tel, contacto.get("wa_id")):
        limpio = _contacto(cand)
        if limpio: return limpio
    return ""

def _wa_a_mensaje(m):
    """Pasa un mensaje de WhatsApp al formato que entiende atender() (el mismo de Messenger).
    Devuelve None para lo que no se contesta (reacciones, avisos del sistema)."""
    tipo = str(m.get("type") or "")
    msg = None
    if tipo == "text":
        msg = {"text": (m.get("text") or {}).get("body", "")}
    elif tipo == "interactive":
        i = m.get("interactive") or {}
        msg = {"text": (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")}
    elif tipo == "button":
        msg = {"text": (m.get("button") or {}).get("text", "")}
    elif tipo == "location":
        loc = m.get("location") or {}
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            lugar = " ".join(str(x) for x in (loc.get("name"), loc.get("address")) if x)
            msg = {"text": ("Te paso mi ubicación: %s https://maps.google.com/?q=%s,%s"
                            % (lugar, loc.get("latitude"), loc.get("longitude"))).replace("  ", " ")}
    elif tipo in ("image", "audio"):
        msg = {"attachments": [{"type": tipo, "wa": m.get(tipo) or {}}]}
    elif tipo == "document":
        doc = m.get("document") or {}
        mime = str(doc.get("mime_type") or "")
        if mime.startswith("image/") or mime == "application/pdf":       # comprobante mandado como archivo
            msg = {"attachments": [{"type": "image", "wa": doc}]}
    elif tipo in ("reaction", "system", "request_welcome"):
        return None
    if msg is None: return {"no_soportado": True}
    ref = m.get("referral") or {}
    anuncio = " ".join(str(x) for x in (ref.get("headline"), ref.get("body")) if x).strip()
    if anuncio and msg.get("text"):
        msg["text"] += "\n(Llegó desde el anuncio: «%s»)" % anuncio[:200]
    return msg

def _bajar_adjunto(adjunto):
    """El archivo que mandó el cliente, venga de WhatsApp o de Messenger."""
    if adjunto.get("wa") is not None: return _wa_bajar(adjunto["wa"])
    return descargar((adjunto.get("payload") or {}).get("url", ""))

# ---------- ENVIAR (elige el canal solo) ----------
def enviar_texto(sender, texto):
    """Le escribe al cliente por donde corresponde. Devuelve True si Meta aceptó el mensaje."""
    if canal_de(sender) == "whatsapp": return enviar_a_whatsapp(sender, texto)
    return enviar_a_messenger(sender, texto)

def enviar_foto(sender, url_foto):
    if canal_de(sender) == "whatsapp": enviar_foto_whatsapp(sender, url_foto)
    else: enviar_foto_messenger(sender, url_foto, fallback_url=url_foto)

# ---------- TELEGRAM / WHATSAPP ----------
def avisar_telegram(texto):
    n = N()
    if not (n.telegram_token and n.telegram_chat): return   # un negocio sin Telegram no avisa a nadie
    try:
        requests.post("https://api.telegram.org/bot%s/sendMessage" % n.telegram_token,
                      json={"chat_id": n.telegram_chat, "text": texto}, timeout=10)
    except Exception: pass

def enviar_whatsapp(texto):
    n = N()
    if not (n.whatsapp_destino and n.callmebot_apikey): return
    try:
        requests.get("https://api.callmebot.com/whatsapp.php",
                     params={"phone": n.whatsapp_destino, "text": texto, "apikey": n.callmebot_apikey}, timeout=10)
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
    if _WA_TEL.get() and len(re.sub(r"\D", "", d["tel"])) < 6:
        d["tel"] = "+" + _WA_TEL.get()          # en WhatsApp ya tenemos su número
    return d

def es_interior(ciudad):
    return _norm(ciudad) not in CENTRAL and _norm(ciudad) != ""

def total_con_envio(precio, ciudad):
    base = _solo_numero(precio)
    if es_interior(ciudad):
        base += N().envio_interior
    return base

def formatear_pedido(resumen):
    d = _parsear(resumen)
    total = total_con_envio(d["precio"], d["ciudad"])
    envio = N().envio_interior
    extra = " (incluye envío interior +%s)" % f"{envio:,}".replace(",", ".") if es_interior(d["ciudad"]) else ""
    por_wa = ""
    if _CANAL.get() == "whatsapp":
        por_wa = "\n💬  Entró por WhatsApp" + (": wa.me/" + _WA_TEL.get() if _WA_TEL.get() else "")
    return ("🛍️  NUEVO PEDIDO — %s\n━━━━━━━━━━━━━━━\n"
            "👤  Nombre:     %s\n📍  Ciudad:     %s\n📞  Teléfono:   %s\n🏠  Dirección:  %s\n"
            "━━━━━━━━━━━━━━━\n💜  Producto:   %s\n💰  Total:      Gs. %s%s\n🕒  %s hs%s"
            % (N().nombre, d["nombre"] or "-", d["ciudad"] or "-", d["tel"] or "-", d["direccion"] or "-",
               d["producto"] or "Producto", f"{total:,}".replace(",", "."), extra, ahora(), por_wa))

def formatear_pedido_whatsapp(resumen):
    d = _parsear(resumen)
    total = total_con_envio(d["precio"], d["ciudad"])
    titulo = "🛍️ *PEDIDO para cargar en Zappy*" if N().principal else "🛍️ *NUEVO PEDIDO — %s*" % N().nombre
    return ("%s\n\n📦 %s — Gs. %s (contra entrega)\n\n"
            "👤 Cliente: %s\n📍 Ciudad: %s\n📞 Tel: %s\n🏠 Direccion: %s\n🕒 %s hs"
            % (titulo, d["producto"] or "Producto", f"{total:,}".replace(",", "."), d["nombre"] or "-",
               d["ciudad"] or "-", d["tel"] or "-", d["direccion"] or "-", ahora()))

def guardar_pedido(resumen, sender=""):
    d = _parsear(resumen)
    total = total_con_envio(d["precio"], d["ciudad"])
    cuerpo = {"fields": {"Producto": d["producto"], "Nombre": d["nombre"], "Ciudad": d["ciudad"],
                         "Telefono": d["tel"], "Direccion": d["direccion"],
                         "Total": "Gs. " + f"{total:,}".replace(",", "."),
                         "Fecha": ahora(), "Estado": "Nuevo", "Contacto": sender},
              "typecast": True}
    try: requests.post(_at_url(TABLA_PEDIDOS), headers=_at_hdr(True), json=cuerpo, timeout=10)
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
    avisar_telegram("👀 INTERÉS de un cliente en %s:\n%s" % (N().nombre, m.group(1).strip()))
    return re.sub(r"\[INTERES\].*?\[/INTERES\]", "", respuesta, flags=re.DOTALL).strip()

def revisar_humano(sender, respuesta):
    """El cliente pide una persona (o tiene un reclamo): se le avisa al dueño por Telegram."""
    m = re.search(r"\[HUMANO\](.*?)\[/HUMANO\]", respuesta, re.DOTALL)
    if not m: return respuesta
    if canal_de(sender) == "whatsapp":
        donde = ("Entró por WhatsApp. Escribile desde tu WhatsApp: https://wa.me/%s" % sender) if str(sender).isdigit() \
                else "Entró por WhatsApp (no comparte su número): mirá la charla en el panel."
    else:
        donde = "Entró por Messenger: buscalo en la bandeja de la página."
    avisar_telegram("🙋 Un cliente de %s pide hablar con una persona.\nMotivo: %s\n%s"
                    % (N().nombre, m.group(1).strip() or "-", donde))
    return re.sub(r"\[HUMANO\].*?\[/HUMANO\]", "", respuesta, flags=re.DOTALL).strip()

def revisar_fotos(sender, respuesta):
    fotos = N().fotos
    if "[MASFOTOS]" in respuesta:
        for u in fotos[3:6]: enviar_foto(sender, u)
        respuesta = respuesta.replace("[MASFOTOS]", "")
    if "[FOTOS]" in respuesta:
        for u in fotos[0:3]: enviar_foto(sender, u)
        respuesta = respuesta.replace("[FOTOS]", "")
    return respuesta.strip()

def revisar_video(sender, respuesta):
    if "[VIDEO]" in respuesta:
        if N().video:
            enviar_texto(sender, "🎥 Miralo en acción: " + N().video)
        respuesta = respuesta.replace("[VIDEO]", "")
    return respuesta.strip()

# ---------- COMPROBANTES: actualizar pedido del cliente ----------
def marcar_pedido_por_contacto(sender, estado):
    contacto = _contacto(sender)
    if not contacto: return False
    r = requests.get(_at_url(TABLA_PEDIDOS), headers=_at_hdr(),
                     params={"filterByFormula": "{Contacto}='%s'" % contacto, "maxRecords": 5}, timeout=10)
    if r.status_code != 200: return False
    regs = r.json().get("records", [])
    if not regs: return False
    regs.sort(key=lambda x: x.get("createdTime", ""))
    rid = regs[-1]["id"]
    requests.patch(_at_url(TABLA_PEDIDOS, rid), headers=_at_hdr(True),
                   json={"fields": {"Estado": estado}}, timeout=10)
    return True

# ---------- "BORRAR MIS DATOS" (lo pide Meta) ----------
FRASES_BORRAR = ("borrar mis datos", "borra mis datos", "borren mis datos",
                 "eliminar mis datos", "elimina mis datos", "eliminen mis datos")
MSG_BORRADO = ("Listo 🙏 Borré nuestra charla y tus datos de contacto de nuestro sistema. "
               "Si algún día querés volver a escribirnos, acá vamos a estar.")

def pide_borrar_datos(texto):
    t = " ".join(_norm(texto).split())
    return any(f in t for f in FRASES_BORRAR)

def _registros_de(tabla, campo, contacto):
    regs, offset = [], None
    for _ in range(20):
        params = {"filterByFormula": "{%s}='%s'" % (campo, contacto), "pageSize": 100}
        if offset: params["offset"] = offset
        r = requests.get(_at_url(tabla), headers=_at_hdr(), params=params, timeout=10)
        if r.status_code != 200: break
        data = r.json()
        regs += data.get("records", [])
        offset = data.get("offset")
        if not offset: break
    return regs

def borrar_datos_cliente(sender):
    """Borra la memoria y la charla guardada de un cliente, y lo desvincula de sus pedidos
    (el pedido queda para la entrega y la contabilidad del negocio, pero sin su id de Facebook o WhatsApp)."""
    contacto = _contacto(sender)
    if not contacto: return
    key = N().clave_historial(contacto)
    _upstash(["DEL", key])
    HISTORIAL.pop(key, None)
    _upstash(["DEL", "canal:%s:%s" % (N().id, contacto)])
    _CANALES.pop((N().id, contacto), None)
    MODO.pop((N().id, str(sender)), None)
    borrados = 0
    try:
        ids = [x["id"] for x in _registros_de(TABLA_CONVERS, "contact_id", contacto)]
        for i in range(0, len(ids), 10):   # Airtable borra de a 10
            r = requests.delete(_at_url(TABLA_CONVERS), headers=_at_hdr(),
                                params=[("records[]", x) for x in ids[i:i + 10]], timeout=10)
            if r.status_code == 200: borrados += len(ids[i:i + 10])
        pedidos = [x["id"] for x in _registros_de(TABLA_PEDIDOS, "Contacto", contacto)]
        for i in range(0, len(pedidos), 10):
            requests.patch(_at_url(TABLA_PEDIDOS), headers=_at_hdr(True),
                           json={"records": [{"id": x, "fields": {"Contacto": ""}} for x in pedidos[i:i + 10]]},
                           timeout=10)
    except Exception as e:
        print(">>> BORRAR DATOS error:", e)
    print(">>> BORRAR DATOS:", N().id, "| mensajes borrados:", borrados)
    avisar_telegram("🗑️ Un cliente pidió borrar sus datos y ya se borraron (%d mensajes)." % borrados)

# ---------- REPORTES (modo dueño / panel) ----------
def resumen_ventas():
    r = requests.get(_at_url(TABLA_PEDIDOS), headers=_at_hdr(),
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
    r = requests.get(_at_url(TABLA_PEDIDOS), headers=_at_hdr(),
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
    r = requests.get(_at_url(TABLA_CONVERS), headers=_at_hdr(),
                     params={"maxRecords": 60}, timeout=10)
    if r.status_code != 200: return "No pude leer las conversaciones."
    regs = r.json().get("records", [])
    return "\n".join(reg.get("fields", {}).get("mensaje_entrante", "") for reg in regs) or "Sin conversaciones."

def contexto_dueno():
    return (resumen_ventas() +
            "\n\n=== PRODUCTOS MÁS VENDIDOS ===\n" + productos_ganadores() +
            "\n\n=== CONVERSACIONES ===\n" + leer_conversaciones())

# ---------- WEBHOOK ----------
MODO = {}            # (negocio, cliente) -> "dueno" / "vendedor"
VISTOS = set()
_VISTOS_LOCK = threading.Lock()
_CANDADOS = {}       # un candado por cliente: sus mensajes se contestan de a uno y en orden
_CANDADOS_LOCK = threading.Lock()

def _ya_visto(mid):
    with _VISTOS_LOCK:
        if mid in VISTOS: return True
        if len(VISTOS) > 2000: VISTOS.clear()
        VISTOS.add(mid)
        return False

def _candado(clave):
    with _CANDADOS_LOCK:
        if len(_CANDADOS) > 5000:
            for k in [k for k, c in _CANDADOS.items() if not c.locked()]:
                _CANDADOS.pop(k, None)
        return _CANDADOS.setdefault(clave, threading.Lock())

def _firma_ok(cuerpo, firma):
    """Meta firma cada aviso con la clave secreta de la app (X-Hub-Signature-256).
    Vale la de tu app y, si un cliente conectó su WhatsApp con SU app, la que cargaste para él."""
    if not firma.startswith("sha256="): return False
    secretos = {META_APP_SECRET, WA_APP_SECRET} | {n.wa_app_secret for n in negocios_guardados()}
    for secreto in secretos:
        if not secreto: continue
        esperado = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
        if hmac.compare_digest(esperado, firma[7:]): return True
    return False

@app.get("/webhook")
def verificar(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token incorrecto", status_code=403)

@app.post("/webhook")
async def recibir(request: Request, tareas: BackgroundTasks):
    """Le contesta a Meta AL INSTANTE y procesa cada mensaje aparte,
    así un negocio lento nunca traba a los demás."""
    cuerpo = await request.body()
    if VERIFICAR_FIRMA and not await run_in_threadpool(_firma_ok, cuerpo, request.headers.get("x-hub-signature-256", "")):
        print(">>> FIRMA inválida: se ignora el evento")
        return {"ok": True}
    try:
        data = json.loads(cuerpo or b"{}")
    except Exception as e:
        print(">>> ENTRANTE ilegible:", e)
        return {"ok": True}
    if not isinstance(data, dict): return {"ok": True}
    if data.get("object") == "whatsapp_business_account":
        _repartir_whatsapp(data, tareas)
        return {"ok": True}
    print(">>> ENTRANTE:", json.dumps(data)[:400])
    for entry in data.get("entry", []) or []:
        page_id = str(entry.get("id", "") or "")
        for ev in entry.get("messaging", []) or []:
            mid = (ev.get("message") or {}).get("mid")
            if mid and _ya_visto(mid): continue
            tareas.add_task(procesar_evento, page_id, ev)
    return {"ok": True}

def procesar_evento(page_id, ev):
    try:
        negocio = negocio_por_pagina(page_id)
        if not negocio:
            print(">>> PÁGINA sin negocio cargado:", page_id); return
        if not negocio.activo:
            print(">>> PAUSADO, no se contesta:", negocio.id); return
        sender = (ev.get("sender") or {}).get("id")
        if not sender or str(sender) == page_id: return
        usar(negocio)
        _CANAL.set("messenger")
        with _candado((negocio.id, str(sender))):
            atender(str(sender), ev.get("message") or {})
    except Exception as _e:
        print(">>> EVENTO error:", _e)

# ---------- WEBHOOK de WhatsApp ----------
def _repartir_whatsapp(data, tareas):
    """Cada mensaje se atiende aparte. De los estados solo importan los que Meta no pudo entregar."""
    try:
        for entry in data.get("entry", []) or []:
            for cambio in (entry.get("changes", []) or []):
                if cambio.get("field") != "messages": continue
                valor = cambio.get("value") or {}
                phone_id = str((valor.get("metadata") or {}).get("phone_number_id", "") or "")
                mensajes = valor.get("messages", []) or []
                if mensajes: print(">>> ENTRANTE WhatsApp:", json.dumps(valor)[:400])
                for m in mensajes:
                    mid = m.get("id")
                    if mid and _ya_visto(mid): continue
                    tareas.add_task(procesar_whatsapp, phone_id, valor, m)
                for estado in valor.get("statuses", []) or []:
                    if estado.get("status") == "failed":
                        tareas.add_task(procesar_falla_whatsapp, phone_id, estado)
    except Exception as e:
        print(">>> ENTRANTE WhatsApp ilegible:", e)

def procesar_whatsapp(phone_id, valor, m):
    try:
        negocio = negocio_por_whatsapp(phone_id)
        if not negocio:
            print(">>> WHATSAPP sin negocio cargado para el número:", phone_id); return
        if not negocio.activo:
            print(">>> PAUSADO, no se contesta:", negocio.id); return
        sender = _wa_remitente(m, valor)
        if not sender: return
        try: edad = time.time() - int(m.get("timestamp") or 0)
        except Exception: edad = 0
        if m.get("timestamp") and edad > 23 * 3600:
            print(">>> WHATSAPP mensaje viejo (más de 23 h), no se contesta:", m.get("id")); return
        msg = _wa_a_mensaje(m)
        if msg is None: return                       # reacciones y avisos del sistema
        usar(negocio)
        _CANAL.set("whatsapp")
        _WA_MSG.set(str(m.get("id") or ""))
        _WA_TEL.set(sender if sender.isdigit() else "")
        _recordar_canal(sender, "whatsapp")
        with _candado((negocio.id, sender)):
            atender(sender, msg)
    except Exception as _e:
        print(">>> EVENTO WhatsApp error:", _e)

_AVISOS_WA = {}      # (negocio, código de error) -> cuándo se avisó por última vez
PISTAS_WA = {
    "131042": "Falta o falló el medio de pago de la cuenta de WhatsApp en Meta.",
    "131047": "Pasaron más de 24 horas desde el último mensaje del cliente: Meta ya no deja contestarle con texto libre.",
    "131026": "El número del cliente no puede recibir el mensaje (no tiene WhatsApp, lo bloqueó o tiene la app muy vieja).",
    "131056": "Se le mandaron demasiados mensajes seguidos al mismo cliente.",
}

def procesar_falla_whatsapp(phone_id, estado):
    """Meta avisa cuando NO pudo entregar un mensaje del bot: queda en el log y se le avisa al dueño (sin spamear)."""
    try:
        negocio = negocio_por_whatsapp(phone_id)
        if not negocio: return
        usar(negocio)
        err = ((estado.get("errors") or [{}])[0]) or {}
        codigo = str(err.get("code", "") or "")
        detalle = str((err.get("error_data") or {}).get("details") or err.get("message") or err.get("title") or "sin detalle")[:200]
        print(">>> WHATSAPP no entregó:", negocio.id, codigo, detalle)
        k = (negocio.id, codigo)
        if time.time() - _AVISOS_WA.get(k, 0) < 6 * 3600: return
        _AVISOS_WA[k] = time.time()
        avisar_telegram(("⚠️ WHATSAPP %s: Meta no entregó un mensaje del bot.\nMotivo: %s (código %s)\n%s"
                         % (negocio.marca_aviso, detalle, codigo or "-", PISTAS_WA.get(codigo, ""))).strip())
    except Exception as _e:
        print(">>> FALLA WhatsApp error:", _e)

def atender(sender, msg):
    n = N()
    if msg.get("is_echo"): return   # es un mensaje que mandó la misma página

    # --- ¿Mandó una imagen? (comprobante de pago) ---
    adjuntos = msg.get("attachments", []) or []
    imagen = next((a for a in adjuntos if a.get("type") == "image"), None)
    if imagen:
        marcar_leido(sender); mostrar_escribiendo(sender)
        contenido, mime = _bajar_adjunto(imagen)
        datos = leer_comprobante(contenido, mime or "image/jpeg") if contenido else None
        if datos and (datos.get("monto") or datos.get("referencia")):
            marcar_pedido_por_contacto(sender, "Pendiente de Verificación")
            avisar_telegram("🧾 COMPROBANTE recibido de un cliente:\n"
                            "Monto: %s | Ref: %s | Banco: %s"
                            % (datos.get("monto", "-"), datos.get("referencia", "-"), datos.get("banco_origen", "-")))
            enviar_texto(sender, "¡Recibí tu comprobante! 🙏 Lo estoy verificando y en un ratito te confirmo. Gracias por tu compra 💜")
        else:
            enviar_texto(sender, "Recibí tu imagen 🙌 Si es un comprobante, no lo pude leer bien: ¿me lo reenviás un poco más claro? "
                                 "Y si es otra consulta, contame por escrito qué necesitás.")
        return

    texto = msg.get("text")
    leido = False
    # --- ¿Mandó un audio? Se escucha y se atiende como si lo hubiera escrito ---
    audio = None if texto else next((a for a in adjuntos if a.get("type") == "audio"), None)
    if audio:
        marcar_leido(sender); mostrar_escribiendo(sender); leido = True
        contenido, mime = _bajar_adjunto(audio)
        texto = transcribir_audio(contenido, mime or "audio/ogg") if contenido else ""
        if not texto:
            enviar_texto(sender, "No pude escuchar bien tu audio 🙈 ¿Me lo escribís, porfa?"); return
    if not texto:
        if msg.get("no_soportado"):     # sticker, video, contacto…: se avisa en vez de dejarlo en visto
            marcar_leido(sender)
            enviar_texto(sender, "Por acá puedo leer mensajes de texto, audios y fotos 😊 ¿Me contás qué necesitás?")
        return
    print(">>> TEXTO:", repr(texto), "de", sender, "| negocio:", n.id, "| canal:", _CANAL.get() or "messenger")
    if not leido: marcar_leido(sender); mostrar_escribiendo(sender)

    if pide_borrar_datos(texto):
        borrar_datos_cliente(sender)
        enviar_texto(sender, MSG_BORRADO); return

    bajo = texto.strip().lower()
    clave_modo = (n.id, sender)
    if n.clave_dueno and bajo == n.clave_dueno:
        MODO[clave_modo] = "dueno"; enviar_texto(sender, "🔓 Modo dueño activado."); return
    if bajo in ("modo vendedor", "salir"):
        MODO[clave_modo] = "vendedor"; enviar_texto(sender, "🛍️ Volví a modo vendedor."); return

    if MODO.get(clave_modo) == "dueno":
        resp = preguntar_a_gemini([], contexto_dueno() + "\n\nPregunta del dueño: " + texto, n.prompt_dueno)
        enviar_texto(sender, resp); return

    historial = leer_historial(sender)
    print(">>> HISTORIAL len:", len(historial), "| upstash:", bool(UPSTASH_URL and UPSTASH_TOKEN))
    guardar(sender, "user", texto)
    prompt = _prompt_venta()
    resp = preguntar_a_gemini(historial, texto, prompt)
    resp = revisar_producto(resp, historial, prompt)
    resp = revisar_pedido(sender, resp)
    resp = revisar_interes(sender, resp)
    resp = revisar_humano(sender, resp)
    resp = revisar_fotos(sender, resp)
    resp = revisar_video(sender, resp)
    if resp:
        enviar_texto(sender, resp)
        guardar(sender, "bot", resp)

def _prompt_venta():
    """El prompt del vendedor. En WhatsApp le suma lo que cambia en ese canal; en Messenger queda igual."""
    p = N().system_prompt
    if _CANAL.get() != "whatsapp": return p
    p += "\n\nCANAL: esta charla es por WhatsApp (si te piden el WhatsApp, ya están hablando por ahí con la tienda)."
    if _WA_TEL.get():
        p += (" El número de este cliente es +%s: no se lo pidas; usalo como teléfono del pedido, "
              "salvo que te pase otro para la entrega." % _WA_TEL.get())
    return p

# ============================================================
#   API DEL PANEL WEB
#   La clave decide qué negocio ves: con la tuya, Guaranístore;
#   con la de un cliente, solo lo suyo.
# ============================================================
def _panel_ok(clave):
    negocio = negocio_por_clave(clave)
    if not negocio: return False
    if not negocio.activo:
        _PAUSADO.set(True); return False
    usar(negocio)
    return True

def _no_auth():
    if _PAUSADO.get():
        return Response(content='{"error":"pausado"}', status_code=403, media_type="application/json")
    return Response(content='{"error":"Clave incorrecta"}', status_code=401, media_type="application/json")

@app.get("/api/panel/resumen")
def panel_resumen(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get(_at_url(TABLA_PEDIDOS), headers=_at_hdr(), params={"maxRecords": 100}, timeout=10)
    pedidos = [x.get("fields", {}) for x in r.json().get("records", [])] if r.status_code == 200 else []
    hoy = datetime.now(AR).strftime("%d/%m/%Y")
    def es(estado): return sum(1 for p in pedidos if str(p.get("Estado", "")).lower() == estado)
    return {"total": len(pedidos),
            "hoy": sum(1 for p in pedidos if str(p.get("Fecha", "")).startswith(hoy)),
            "entregados": es("entregado"), "nuevos": es("nuevo"),
            "negocio": N().nombre}

@app.get("/api/panel/pedidos")
def panel_pedidos(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get(_at_url(TABLA_PEDIDOS), headers=_at_hdr(), params={"maxRecords": 100}, timeout=10)
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
def panel_crear_pedido(d: dict = Depends(_cuerpo), x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    cuerpo = {"fields": {"Producto": d.get("producto", ""), "Nombre": d.get("nombre", ""), "Ciudad": d.get("ciudad", ""),
                         "Telefono": d.get("telefono", ""), "Direccion": d.get("direccion", ""), "Total": d.get("total", ""),
                         "Fecha": ahora(), "Estado": d.get("estado", "Nuevo")}, "typecast": True}
    r = requests.post(_at_url(TABLA_PEDIDOS), headers=_at_hdr(True), json=cuerpo, timeout=10)
    return {"ok": r.status_code in (200, 201), "error": None if r.status_code in (200, 201) else r.text}

@app.post("/api/panel/estado")
def panel_estado(d: dict = Depends(_cuerpo), x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    rid = _rid(d.get("id", ""))
    if not rid: return {"ok": False, "error": "id inválido"}
    r = requests.patch(_at_url(TABLA_PEDIDOS, rid), headers=_at_hdr(True),
                       json={"fields": {"Estado": d.get("estado", "")}}, timeout=10)
    return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}

@app.post("/api/panel/aprobar-pedido")
def panel_aprobar_pedido(d: dict = Depends(_cuerpo), x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    rid = _rid(d.get("id", ""))
    if not rid: return {"ok": False, "error": "id inválido"}
    r = requests.patch(_at_url(TABLA_PEDIDOS, rid), headers=_at_hdr(True), json={"fields": {"Estado": "Pagado"}}, timeout=10)
    if r.status_code != 200:
        return {"ok": False, "error": r.text}
    # Avisar al cliente por donde escribió, Messenger o WhatsApp (si el pedido tiene Contacto)
    contacto = str(r.json().get("fields", {}).get("Contacto", "") or "")
    avisado = None
    if contacto:
        avisado = bool(enviar_texto(contacto, "✅ ¡Confirmamos tu pago! Tu pedido ya está en preparación. Gracias por tu compra 💜"))
    return {"ok": True, "avisado": avisado}

@app.get("/api/panel/catalogo")
def panel_catalogo(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get(_at_url(TABLA_CATALOGO), headers=_at_hdr(), params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200: return {"productos": [], "error": r.text}
    out = []
    for reg in r.json().get("records", []):
        f = reg.get("fields", {})
        out.append({"id": reg.get("id", ""), "nombre": f.get("nombre", "") or f.get("producto_id", ""),
                    "precio": f.get("precio_gs", ""), "costo": f.get("costo_gs", ""),
                    "stock": f.get("stock_estado", ""), "descripcion": f.get("descripcion_corta", "")})
    return {"productos": out}

@app.post("/api/panel/producto")
def panel_crear_producto(d: dict = Depends(_cuerpo), x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    nombre = (d.get("nombre", "") or "").strip()
    pid = (d.get("producto_id", "") or "").strip() or nombre.lower().replace(" ", "")[:20] or "producto"
    cuerpo = {"fields": {"producto_id": pid, "nombre": nombre, "precio_gs": d.get("precio", ""),
                         "stock_estado": d.get("stock", "disponible"), "descripcion_corta": d.get("descripcion", "")},
              "typecast": True}
    r = requests.post(_at_url(TABLA_CATALOGO), headers=_at_hdr(True), json=cuerpo, timeout=10)
    return {"ok": r.status_code in (200, 201), "error": None if r.status_code in (200, 201) else r.text}

@app.delete("/api/panel/producto")
def panel_borrar_producto(d: dict = Depends(_cuerpo), x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    rid = _rid(d.get("id", ""))
    if not rid: return {"ok": False, "error": "falta id"}
    r = requests.delete(_at_url(TABLA_CATALOGO, rid), headers=_at_hdr(), timeout=10)
    return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}

@app.patch("/api/panel/editar-producto")
def panel_editar_producto(d: dict = Depends(_cuerpo), x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    rid = _rid(d.get("id", ""))
    if not rid: return {"ok": False, "error": "falta id"}
    campos = {}
    if d.get("nombre", "") != "": campos["nombre"] = d["nombre"]
    if d.get("precio", "") != "": campos["precio_gs"] = d["precio"]
    if d.get("stock", "") != "": campos["stock_estado"] = d["stock"]
    if "descripcion" in d: campos["descripcion_corta"] = d.get("descripcion", "")
    if not campos: return {"ok": False, "error": "nada para actualizar"}
    r = requests.patch(_at_url(TABLA_CATALOGO, rid), headers=_at_hdr(True),
                       json={"fields": campos, "typecast": True}, timeout=10)
    return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}

@app.post("/api/panel/fer")
def panel_fer(d: dict = Depends(_cuerpo), x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    mensaje = (d.get("mensaje", "") or "").strip()
    if not mensaje: return {"respuesta": "Decime qué querés saber: ventas de hoy, qué conviene vender, últimos pedidos…"}
    return {"respuesta": preguntar_a_gemini([], contexto_dueno() + "\n\nMensaje del dueño: " + mensaje, N().prompt_dueno)}

@app.get("/api/panel/seguimiento")
def panel_seguimiento(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    # 1) Contactos que YA compraron (tienen pedido con su Contacto)
    rp = requests.get(_at_url(TABLA_PEDIDOS), headers=_at_hdr(), params={"maxRecords": 100}, timeout=10)
    compraron = set()
    if rp.status_code == 200:
        for reg in rp.json().get("records", []):
            c = reg.get("fields", {}).get("Contacto", "")
            if c: compraron.add(str(c))
    # 2) Todas las charlas, agrupadas por contacto
    rc = requests.get(_at_url(TABLA_CONVERS), headers=_at_hdr(), params={"maxRecords": 300}, timeout=10)
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
def panel_reenganche(d: dict = Depends(_cuerpo), x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    ultimo = (d.get("ultimo", "") or "").strip()
    p = ("Un cliente habló con la tienda pero no cerró la compra. Su último mensaje fue: '%s'. "
         "Escribí UN mensaje corto, cálido y en español paraguayo para reengancharlo y ayudarlo a decidir, "
         "sin presionar, recordando que paga contra entrega. Devolvé SOLO el mensaje, sin comillas." % ultimo)
    return {"mensaje": preguntar_a_gemini([], p, N().system_prompt)}

@app.get("/api/panel/conversaciones")
def panel_conversaciones(x_clave: str = Header(default="")):
    if not _panel_ok(x_clave): return _no_auth()
    r = requests.get(_at_url(TABLA_CONVERS), headers=_at_hdr(), params={"maxRecords": 200}, timeout=10)
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
def chat_web(datos: dict = Depends(_cuerpo)):
    """Chat web: Fer atiende SIN Facebook (como Guaranístore). El frontend manda {mensaje, historial}."""
    mensaje = (datos.get("mensaje", "") or "").strip()
    historial_in = datos.get("historial", []) or []
    if not mensaje:
        return {"respuesta": "Contame, ¿en qué te puedo ayudar? 😊"}
    # Reconstruye el historial que manda el navegador (lista de {rol, texto})
    historial = []
    for m in historial_in[-20:]:
        rol = "user" if m.get("rol") == "user" else "bot"
        historial.append((rol, m.get("texto", "")))
    resp = preguntar_a_gemini(historial, mensaje, N().system_prompt)
    # Procesa las mismas etiquetas (catálogo, interés); las de foto/pedido se limpian para el demo
    resp = revisar_producto(resp, historial)
    resp = re.sub(r"\[PEDIDO\].*?\[/PEDIDO\]", "", resp, flags=re.DOTALL)
    resp = re.sub(r"\[INTERES\].*?\[/INTERES\]", "", resp, flags=re.DOTALL)
    resp = re.sub(r"\[HUMANO\].*?\[/HUMANO\]", "", resp, flags=re.DOTALL)
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
    return _panel_ok(clave_header) or _panel_ok(clave_query)

# ---------- Helper: leer TODOS los pedidos (con paginación) ----------
def _leer_pedidos():
    url = _at_url(TABLA_PEDIDOS)
    headers = _at_hdr()
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
    r = requests.get(_at_url(TABLA_CONVERS), headers=_at_hdr(),
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
    r = requests.get(_at_url(TABLA_CONVERS), headers=_at_hdr(),
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
    return {"analisis": preguntar_a_gemini([], p, N().prompt_dueno),
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
    r = requests.get(_at_url(TABLA_CONVERS), headers=_at_hdr(),
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
    res = _upstash(["GET", N().clave_config()])
    if res:
        try: return json.loads(res)
        except Exception: pass
    # valores por defecto (los actuales)
    return {"envio_interior": N().envio_interior, "nota": ""}

@app.get("/api/panel/config")
def panel_config_get(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    return {"config": _config_leer()}

@app.post("/api/panel/config")
def panel_config_set(d: dict = Depends(_cuerpo), x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    actual = _config_leer()
    if "envio_interior" in d: actual["envio_interior"] = _solo_numero(d.get("envio_interior"))
    if "nota" in d: actual["nota"] = str(d.get("nota", ""))[:500]
    guardado = _upstash(["SET", N().clave_config(), json.dumps(actual)])
    return {"ok": guardado is not None, "config": actual,
            "aviso": None if guardado is not None else "Upstash no configurado: no se pudo guardar."}


@app.post("/api/panel/editar-costo")
def panel_editar_costo(d: dict = Depends(_cuerpo), x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    rid = _rid(d.get("id", ""))
    costo = _solo_numero(d.get("costo", 0))
    if not rid: return {"ok": False, "error": "falta id"}
    r = requests.patch(_at_url(TABLA_CATALOGO, rid), headers=_at_hdr(True),
                       json={"fields": {"costo_gs": costo}, "typecast": True}, timeout=10)
    return {"ok": r.status_code == 200, "error": None if r.status_code == 200 else r.text}


@app.post("/api/panel/postventa-mensaje")
def panel_postventa_mensaje(d: dict = Depends(_cuerpo), x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    tipo = (d.get("tipo", "") or "").strip()
    nombre = (d.get("nombre", "") or "").strip() or "cliente"
    producto = (d.get("producto", "") or "").strip() or "el producto"
    base = ("Escribí UN mensaje corto, cálido y natural en español paraguayo para enviarle por chat "
            "al cliente %s que compró '%s'. Sin comillas, sin presionar, recordá que pagó contra entrega. "
            "Devolvé SOLO el mensaje. ") % (nombre, producto)
    guias = {
        "llego":   "El mensaje es para preguntarle con cariño si le llegó bien el producto y si quedó conforme.",
        "testimonio": "El cliente ya recibió el producto. Pedile con amabilidad, sin exigir, una fotito o unas palabras de cómo le fue, para poder mostrar a otros clientes. Que se sienta libre de decir que no.",
        "camino":  "Avisale que su pedido ya salió y va en camino, para que esté atento a la entrega. Tono de buena noticia.",
        "recompra": "Pasó un tiempo desde su compra. Escribile para saludarlo y ofrecerle con naturalidad volver a comprar o un producto que combine con lo que llevó, sin insistir."
    }
    p = base + guias.get(tipo, guias["llego"])
    return {"mensaje": preguntar_a_gemini([], p, N().system_prompt)}


# estado del ultimo aviso de diagnostico, por negocio (para no spamear Telegram cuando el pinger revisa seguido)
_DIAG_ULTIMO = {}

def _diagnostico(avisar="", extra=False):
    n = N()
    checks = []
    def add(nombre, ok, detalle):
        checks.append({"nombre": nombre, "estado": "ok" if ok else "falla", "detalle": detalle})

    # 1) AIRTABLE + tablas + columnas clave
    try:
        headers = _at_hdr()
        faltan_cols = []
        # Pedidos
        rp = requests.get(_at_url(TABLA_PEDIDOS), headers=headers, params={"maxRecords": 1}, timeout=10)
        if rp.status_code != 200:
            add("Airtable · Pedidos", False, "No responde (%s). Revisá AIRTABLE_BASE o el nombre de la tabla." % rp.status_code)
        else:
            recs = rp.json().get("records", [])
            cols = set(recs[0].get("fields", {}).keys()) if recs else set()
            for c in ("Producto", "Contacto"):
                if recs and c not in cols: faltan_cols.append("Pedidos." + c)
            add("Airtable · Pedidos", True, "OK" + (" (ojo: faltan columnas " + ", ".join(faltan_cols) + " — puede ser que no haya pedidos con esos datos aún)" if faltan_cols else ""))
        # Catálogo + costo_gs
        rc = requests.get(_at_url(TABLA_CATALOGO), headers=headers, params={"maxRecords": 1}, timeout=10)
        if rc.status_code != 200:
            add("Airtable · Catálogo", False, "No responde (%s)." % rc.status_code)
        else:
            recs = rc.json().get("records", [])
            cols = set(recs[0].get("fields", {}).keys()) if recs else set()
            add("Airtable · Catálogo", True, "OK" + ("" if (not recs or "costo_gs" in cols) else " (falta la columna costo_gs para calcular ganancia)"))
        # Conversaciones
        rv = requests.get(_at_url(TABLA_CONVERS), headers=headers, params={"maxRecords": 1}, timeout=10)
        add("Airtable · Conversaciones", rv.status_code == 200, "OK" if rv.status_code == 200 else "No responde (%s)." % rv.status_code)
    except Exception as e:
        add("Airtable", False, "Error de conexión: " + str(e)[:120])

    # 2) UPSTASH (memoria de Fer)
    try:
        pong = _upstash(["PING"])
        add("Memoria (Upstash)", pong is not None, "OK" if pong is not None else "No configurada o no responde. Fer usa memoria temporal (se pierde si el servidor reinicia).")
    except Exception as e:
        add("Memoria (Upstash)", False, "Error: " + str(e)[:120])

    # 3) MESSENGER (token de la página) — solo si el negocio usa Messenger
    if n.page_token:
        try:
            rm = requests.get("https://graph.facebook.com/me", params={"access_token": n.page_token}, timeout=10)
            ok = rm.status_code == 200
            add("Messenger (token)", ok, "OK" if ok else "Token vencido o inválido. Hay que regenerar el PAGE_TOKEN — el bot no puede responder a clientes.")
        except Exception as e:
            add("Messenger (token)", False, "Error: " + str(e)[:120])

    # 3a) WHATSAPP (número y token) — solo si el negocio usa WhatsApp
    if n.wa_conectado():
        info = _info_wa(n.wa_phone_id, n.wa_token)
        if info.get("ok"):
            add("WhatsApp (número y token)", True, ("OK · %s %s" % (info.get("numero", ""), info.get("nombre", ""))).strip())
            if info.get("aviso"): add("WhatsApp (estado del número)", False, info["aviso"])
            # solo desde /admin: ¿Meta le está mandando los mensajes de este WhatsApp al bot?
            if extra and n.wa_waba_id:
                try:
                    rs = requests.get("%s/%s/subscribed_apps" % (WA_API, n.wa_waba_id),
                                      headers={"Authorization": "Bearer " + n.wa_token}, timeout=10)
                    conectada = rs.status_code == 200 and bool(rs.json().get("data"))
                    add("WhatsApp conectado al bot", conectada, "OK" if conectada else "Meta no le está mandando los mensajes de este WhatsApp al bot. Tocá «Conectar WhatsApp al bot».")
                except Exception as e:
                    add("WhatsApp conectado al bot", False, "Error: " + str(e)[:120])
        else:
            add("WhatsApp (número y token)", False, info.get("error", "Meta no reconoce el número o el token."))
    elif n.wa_phone_id or n.wa_token:
        add("WhatsApp (número y token)", False, "Falta cargar el identificador del número o el token.")
    if not n.page_token and not n.wa_conectado():
        add("Canal conectado", False, "Este negocio no tiene ni Messenger ni WhatsApp cargado: el bot no puede atender a nadie.")

    # 3b) solo desde admin.html: ¿la página está conectada al bot?
    if extra and n.page_id and n.page_token:
        try:
            rs = requests.get(GRAPH_API + "/%s/subscribed_apps" % n.page_id,
                              params={"access_token": n.page_token}, timeout=10)
            conectada = rs.status_code == 200 and bool(rs.json().get("data"))
            add("Página conectada al bot", conectada, "OK" if conectada else "La página no le manda los mensajes al bot. Tocá «Conectar página».")
        except Exception as e:
            add("Página conectada al bot", False, "Error: " + str(e)[:120])

    # 4) GEMINI (cerebro)
    try:
        rg = requests.post(_gemini(), json={"contents": [{"parts": [{"text": "ping"}]}]}, timeout=15)
        add("Gemini (cerebro)", rg.status_code == 200, "OK" if rg.status_code == 200 else "No responde (%s). Puede ser límite de uso o la GEMINI_KEY." % rg.status_code)
    except Exception as e:
        add("Gemini (cerebro)", False, "Error: " + str(e)[:120])

    # 5) PEDIDOS TRABADOS (comprobantes sin verificar / sin cobrar hace >=3 días)
    try:
        rt = requests.get(_at_url(TABLA_PEDIDOS), headers=_at_hdr(), params={"pageSize": 100}, timeout=10)
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
            ultimo = _DIAG_ULTIMO.setdefault(n.id, {"firma": None, "ts": 0})
            firma = "|".join(sorted(c["nombre"] for c in fallas))
            ahora = datetime.now(timezone.utc).timestamp()
            prev = ultimo.get("firma")
            COOLDOWN = 6 * 3600
            if fallas:
                cambio = (firma != prev)
                paso_tiempo = (ahora - ultimo.get("ts", 0)) > COOLDOWN
                if cambio or paso_tiempo:
                    texto = "⚠️ DIAGNÓSTICO %s — revisá:\n" % n.marca_aviso + "\n".join("• %s: %s" % (c["nombre"], c["detalle"]) for c in fallas)
                    avisar_telegram(texto)
                    ultimo["firma"] = firma
                    ultimo["ts"] = ahora
            else:
                if prev:
                    avisar_telegram("✅ %s: lo que estaba fallando ya se recuperó. Todo volvió a la normalidad." % n.marca_aviso)
                ultimo["firma"] = None
                ultimo["ts"] = ahora
        except Exception:
            pass

    return {"salud": salud, "fallas": len(fallas), "checks": checks}

@app.get("/api/panel/diagnostico")
def panel_diagnostico(x_clave: str = Header(default=""), clave: str = "", avisar: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    return _diagnostico(avisar)


@app.get("/api/panel/acciones")
def panel_acciones(x_clave: str = Header(default=""), clave: str = ""):
    if not _ok2(x_clave, clave): return _no_auth()
    acciones = []
    ahora_utc = datetime.now(timezone.utc)
    headers = _at_hdr()

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
        rv = requests.get(_at_url(TABLA_CONVERS), headers=headers, params={"maxRecords": 300}, timeout=10)
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


# ============================================================
#   ADMIN — tus negocios (lo usa admin.html)
#   Todo pide la cabecera X-Admin con tu ADMIN_CLAVE.
# ============================================================
def _admin_ok(clave): return _igual(clave, ADMIN_CLAVE)

def _enmascarar(valor):
    valor = str(valor or "")
    return ("••••" + valor[-4:]) if valor else ""

def _publico(n):
    """Lo que admin.html puede ver de un negocio (los tokens, solo enmascarados)."""
    d = dict(n.datos)
    for k in SECRETOS:
        d[k] = _enmascarar(d.get(k, ""))
        d["tiene_" + k] = bool(n.datos.get(k))
    if n.principal:
        d["clave_panel"] = _enmascarar(d.get("clave_panel", ""))
        d["clave_dueno"] = _enmascarar(d.get("clave_dueno", ""))
        d["page_id"] = d.get("page_id") or pagina_principal()
        d["prompt"] = ""
    d["principal"] = n.principal
    d["messenger"] = bool(n.conectado() or n.principal)
    d["whatsapp"] = n.wa_conectado()
    d["estado"] = "pausado" if not n.activo else ("activo" if n.conectado() or n.wa_conectado() or n.principal else "sin_conectar")
    return d

def _slug(t):
    return "-".join(_norm(t).split())[:30].strip("-")

def _id_libre(nombre, ocupados):
    base = _slug(nombre) or "negocio"
    nid, i = base, 2
    while nid in ocupados or nid == "principal":
        nid = "%s-%d" % (base, i); i += 1
    return nid

def _info_token(token):
    """Le pregunta a Meta de qué página es un token, y si vence."""
    try:
        r = requests.get(GRAPH_API + "/me", params={"fields": "id,name,category", "access_token": token}, timeout=10)
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": "No pude hablar con Meta: " + str(e)[:100]}
    if r.status_code != 200:
        msg = (j.get("error") or {}).get("message", "") if isinstance(j, dict) else ""
        if "category" in msg:
            return {"ok": False, "error": "Ese token es de una persona, no de una página. Usá «Buscar mis páginas»."}
        return {"ok": False, "error": "Meta no aceptó el token: " + (msg or str(r.status_code))[:160]}
    info = {"ok": True, "page_id": str(j.get("id", "")), "nombre": j.get("name", ""), "vence": "", "avisos": []}
    if META_APP_ID and META_APP_SECRET:
        try:
            rd = requests.get(GRAPH_API + "/debug_token",
                              params={"input_token": token, "access_token": META_APP_ID + "|" + META_APP_SECRET}, timeout=10)
            data = rd.json().get("data", {}) if rd.status_code == 200 else {}
            exp = data.get("expires_at")
            if exp == 0: info["vence"] = "nunca"
            elif exp: info["vence"] = datetime.fromtimestamp(exp, AR).strftime("%d/%m/%Y %H:%M")
            if exp: info["avisos"].append("Este token vence. Usá «Buscar mis páginas» para sacar uno que no venza.")
            if data.get("app_id") and str(data.get("app_id")) != META_APP_ID:
                info["avisos"].append("Este token es de otra app de Meta, no de la tuya.")
            if data.get("scopes") and "pages_messaging" not in data.get("scopes", []):
                info["avisos"].append("Al token le falta el permiso pages_messaging: el bot no va a poder contestar.")
        except Exception:
            pass
    else:
        info["avisos"].append("Sin META_APP_ID y META_APP_SECRET en Render no puedo saber si el token vence.")
    return info

def _info_wa(phone_id, token):
    """Le pregunta a Meta por un número de WhatsApp: si el token sirve, qué número es y cómo está."""
    url = "%s/%s" % (WA_API, phone_id)
    hdr = {"Authorization": "Bearer " + token}
    try:
        r = requests.get(url, params={"fields": "display_phone_number,verified_name,quality_rating"}, headers=hdr, timeout=10)
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": "No pude hablar con Meta: " + str(e)[:100]}
    if r.status_code != 200:
        msg = (j.get("error") or {}).get("message", "") if isinstance(j, dict) else ""
        return {"ok": False, "error": "Meta no aceptó ese número o ese token: " + (msg or str(r.status_code))[:180]}
    info = {"ok": True, "numero": str(j.get("display_phone_number", "") or ""), "nombre": str(j.get("verified_name", "") or ""),
            "calidad": str(j.get("quality_rating", "") or ""), "aviso": ""}
    avisos = []
    try:    # datos extra: si Meta no los da, no pasa nada
        r2 = requests.get(url, params={"fields": "status,platform_type"}, headers=hdr, timeout=10)
        if r2.status_code == 200:
            e = r2.json()
            if str(e.get("platform_type", "")).upper() == "NOT_APPLICABLE":
                avisos.append("El número todavía no está registrado en la API de WhatsApp: tocá «Registrar número».")
            elif str(e.get("status", "")).upper() in ("BANNED", "RESTRICTED", "FLAGGED", "DISCONNECTED"):
                avisos.append("Meta dice que el número está en estado %s." % e.get("status"))
    except Exception:
        pass
    if info["calidad"].upper() == "RED":
        avisos.append("Meta marcó la calidad del número en rojo (muchos clientes lo bloquearon o denunciaron).")
    info["aviso"] = " ".join(avisos)
    return info

@app.get("/api/admin/negocios")
def admin_negocios(x_admin: str = Header(default="")):
    if not _admin_ok(x_admin): return _no_auth()
    hay_upstash = _upstash(["PING"]) is not None
    lista = [_publico(PRINCIPAL)] + [_publico(n) for n in negocios_guardados(fresco=True)]
    return {"negocios": lista, "upstash": hay_upstash,
            "meta_app": bool(META_APP_ID and META_APP_SECRET), "firma": VERIFICAR_FIRMA}

@app.post("/api/admin/negocio")
def admin_guardar(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    if not _admin_ok(x_admin): return _no_auth()
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return {"ok": False, "error": "Falta Upstash en Render (UPSTASH_REDIS_REST_URL y UPSTASH_REDIS_REST_TOKEN): sin eso no se pueden guardar negocios."}
    nid = str(d.get("id", "") or "").strip()
    if nid == "principal":
        return {"ok": False, "error": "Guaranístore se configura con las variables de Render, no desde acá."}
    otros = negocios_guardados(fresco=True)
    if nid:
        previo = _negocio_guardado(nid)
        if previo is None: return {"ok": False, "error": "Ese negocio ya no existe. Recargá la página."}
        datos = dict(previo)
    else:
        datos = {"id": _id_libre(d.get("nombre", ""), {n.id for n in otros}), "creado": ahora(), "activo": True}
    wa_antes = (re.sub(r"\D", "", str(datos.get("wa_phone_id", "") or "")), str(datos.get("wa_token", "") or ""))
    token_nuevo = False
    for k in CAMPOS_NEGOCIO:
        if k in ("id", "creado", "activo", "page_id") or k not in d: continue
        v = d[k]
        # en los tokens, vacío (o el valor enmascarado ••••) = dejar el que ya estaba
        if k in SECRETOS and (str(v or "").strip() == "" or str(v).startswith("••••")): continue
        if k == "page_token": token_nuevo = True
        datos[k] = v
    # WhatsApp: si borran el identificador del número, se desconecta entero
    if "wa_phone_id" in d and not re.sub(r"\D", "", str(d.get("wa_phone_id") or "")):
        datos["wa_token"] = ""; datos["wa_app_secret"] = ""; datos["wa_waba_id"] = ""
    datos = _limpiar_negocio(datos)

    # el id de la página siempre sale del token (se lo pregunta a Meta), nunca se escribe a mano
    if token_nuevo or (datos["page_token"] and not datos["page_id"]):
        info = _info_token(datos["page_token"])
        if not info.get("ok"): return {"ok": False, "error": info.get("error", "Token inválido")}
        datos["page_id"] = info["page_id"]

    errores = []
    if not datos["nombre"]: errores.append("Falta el nombre del negocio")
    if len(datos["clave_panel"]) < 8: errores.append("La clave del panel tiene que tener 8 letras o más")
    if datos["airtable_base"] and not re.match(r"^app[A-Za-z0-9]{14}$", datos["airtable_base"]):
        errores.append("La base de Airtable empieza con «app» y tiene 17 caracteres")
    if datos["page_id"] and not re.match(r"^\d+$", datos["page_id"]):
        errores.append("El id de la página son solo números")
    if any(not u.startswith(("http://", "https://")) for u in datos["fotos"]):
        errores.append("Cada foto tiene que ser un link que empiece con https://")
    if datos["video"] and not datos["video"].startswith(("http://", "https://")):
        errores.append("El video tiene que ser un link que empiece con https://")
    if _igual(datos["clave_panel"], CLAVE_PANEL) or _igual(datos["clave_panel"], ADMIN_CLAVE):
        errores.append("Esa clave de panel ya la usás vos: inventá otra")
    for n in otros:
        if n.id == datos["id"]: continue
        if _igual(datos["clave_panel"], n.clave_panel): errores.append("Esa clave de panel ya la usa " + n.nombre)
        if datos["page_id"] and datos["page_id"] == n.page_id: errores.append("Esa página ya está cargada en " + n.nombre)
        if datos["wa_phone_id"] and datos["wa_phone_id"] == n.wa_phone_id: errores.append("Ese número de WhatsApp ya está cargado en " + n.nombre)
    if datos["page_id"] and datos["page_id"] == pagina_principal():
        errores.append("Esa es la página de Guaranístore")
    if datos["wa_phone_id"] and datos["wa_phone_id"] == WA_PHONE_ID:
        errores.append("Ese es el número de WhatsApp de Guaranístore")
    if bool(datos["wa_phone_id"]) != bool(datos["wa_token"]):
        errores.append("Para WhatsApp hacen falta las dos cosas: el identificador del número y el token")
    if errores: return {"ok": False, "error": " · ".join(errores)}

    # WhatsApp nuevo o cambiado: se le pregunta a Meta si ese número y ese token van juntos
    if datos["wa_phone_id"] and (datos["wa_phone_id"], datos["wa_token"]) != wa_antes:
        info_wa = _info_wa(datos["wa_phone_id"], datos["wa_token"])
        if not info_wa.get("ok"): return {"ok": False, "error": info_wa.get("error", "Meta no reconoce ese WhatsApp")}

    if not _guardar_negocio(datos):
        return {"ok": False, "error": "Upstash no respondió. Probá de nuevo en un minuto."}
    return {"ok": True, "negocio": _publico(Negocio(datos))}

@app.post("/api/admin/pausar")
def admin_pausar(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    if not _admin_ok(x_admin): return _no_auth()
    nid = str(d.get("id", "") or "")
    if nid == "principal": return {"ok": False, "error": "Guaranístore no se puede pausar desde acá."}
    datos = _negocio_guardado(nid)
    if datos is None: return {"ok": False, "error": "No encontré ese negocio."}
    datos["activo"] = bool(d.get("activo", False))
    if not _guardar_negocio(datos): return {"ok": False, "error": "Upstash no respondió."}
    return {"ok": True, "activo": datos["activo"]}

@app.post("/api/admin/borrar-negocio")
def admin_borrar(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    if not _admin_ok(x_admin): return _no_auth()
    nid = str(d.get("id", "") or "")
    if not nid or nid == "principal": return {"ok": False, "error": "Ese no se puede borrar."}
    if _negocio_guardado(nid) is None: return {"ok": False, "error": "No encontré ese negocio."}
    return {"ok": _borrar_negocio(nid)}

@app.post("/api/admin/validar-token")
def admin_validar_token(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    if not _admin_ok(x_admin): return _no_auth()
    token = str(d.get("page_token", "") or "").strip()
    if not token and d.get("id"):
        n = negocio_por_id(str(d.get("id")))
        token = n.page_token if n else ""
    if not token: return {"ok": False, "error": "Pegá el token de la página."}
    return _info_token(token)

@app.post("/api/admin/validar-whatsapp")
def admin_validar_whatsapp(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    """Prueba un número y un token de WhatsApp contra Meta, antes de guardar (o los ya guardados)."""
    if not _admin_ok(x_admin): return _no_auth()
    phone_id = re.sub(r"\D", "", str(d.get("wa_phone_id", "") or ""))
    token = str(d.get("wa_token", "") or "").strip()
    if token.startswith("••••"): token = ""
    if d.get("id") and not (phone_id and token):
        n = negocio_por_id(str(d.get("id")))
        if n:
            phone_id = phone_id or n.wa_phone_id
            token = token or n.wa_token
    if not (phone_id and token):
        return {"ok": False, "error": "Pegá el identificador del número y el token de WhatsApp."}
    return _info_wa(phone_id, token)

@app.post("/api/admin/wa-registrar")
def admin_wa_registrar(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    """Registra el número en la API de WhatsApp (una sola vez por número). El PIN son 6 números que elegís vos."""
    if not _admin_ok(x_admin): return _no_auth()
    n = negocio_por_id(str(d.get("id", "") or ""))
    if not n: return {"ok": False, "error": "No encontré ese negocio."}
    if not n.wa_conectado(): return {"ok": False, "error": "Primero guardá el identificador del número y el token."}
    pin = re.sub(r"\D", "", str(d.get("pin", "") or ""))
    if len(pin) != 6: return {"ok": False, "error": "El PIN tiene que tener exactamente 6 números."}
    try:
        r = requests.post("%s/%s/register" % (WA_API, n.wa_phone_id), headers={"Authorization": "Bearer " + n.wa_token},
                          json={"messaging_product": "whatsapp", "pin": pin}, timeout=20)
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": "No pude hablar con Meta: " + str(e)[:100]}
    if r.status_code == 200 and j.get("success"): return {"ok": True}
    return {"ok": False, "error": "Meta dijo: " + ((j.get("error") or {}).get("message", "") or str(r.status_code))[:200]}

@app.post("/api/admin/wa-conectar")
def admin_wa_conectar(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    """Suscribe la app de Meta a la cuenta de WhatsApp del negocio: desde ahí Meta le manda sus mensajes al bot."""
    if not _admin_ok(x_admin): return _no_auth()
    n = negocio_por_id(str(d.get("id", "") or ""))
    if not n: return {"ok": False, "error": "No encontré ese negocio."}
    if not n.wa_conectado(): return {"ok": False, "error": "Primero guardá el identificador del número y el token."}
    if not n.wa_waba_id:
        return {"ok": False, "error": "Falta el identificador de la cuenta de WhatsApp Business (en la app de Meta figura al lado del identificador del número)."}
    try:
        r = requests.post("%s/%s/subscribed_apps" % (WA_API, n.wa_waba_id),
                          headers={"Authorization": "Bearer " + n.wa_token}, timeout=15)
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": "No pude hablar con Meta: " + str(e)[:100]}
    if r.status_code == 200 and j.get("success"): return {"ok": True}
    return {"ok": False, "error": "Meta dijo: " + ((j.get("error") or {}).get("message", "") or str(r.status_code))[:200]}

@app.post("/api/admin/paginas")
def admin_paginas(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    """Con el token de la PERSONA (Graph API Explorer) trae sus páginas con un token de cada una.
    Si están META_APP_ID y META_APP_SECRET, esos tokens de página no vencen."""
    if not _admin_ok(x_admin): return _no_auth()
    token = str(d.get("user_token", "") or "").strip()
    if not token: return {"ok": False, "error": "Pegá el token que te da el Graph API Explorer."}
    largo = False
    if META_APP_ID and META_APP_SECRET:
        try:
            r = requests.get(GRAPH_API + "/oauth/access_token",
                             params={"grant_type": "fb_exchange_token", "client_id": META_APP_ID,
                                     "client_secret": META_APP_SECRET, "fb_exchange_token": token}, timeout=10)
            if r.status_code == 200 and r.json().get("access_token"):
                token, largo = r.json()["access_token"], True
            else:
                return {"ok": False, "error": "Meta no aceptó el token: " + ((r.json().get("error") or {}).get("message", "") or str(r.status_code))[:160]}
        except Exception as e:
            return {"ok": False, "error": "No pude hablar con Meta: " + str(e)[:100]}
    try:
        r = requests.get(GRAPH_API + "/me/accounts", params={"fields": "id,name,access_token", "limit": 100,
                                                             "access_token": token}, timeout=10)
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": "No pude hablar con Meta: " + str(e)[:100]}
    if r.status_code != 200:
        return {"ok": False, "error": "Meta no aceptó el token: " + ((j.get("error") or {}).get("message", "") or str(r.status_code))[:160]}
    paginas = [{"page_id": str(p.get("id", "")), "nombre": p.get("name", ""), "page_token": p.get("access_token", "")}
               for p in j.get("data", [])]
    aviso = "" if largo else "Sin META_APP_ID y META_APP_SECRET en Render, estos tokens vencen en unas horas."
    return {"ok": True, "paginas": paginas, "no_vencen": largo, "aviso": aviso}

@app.post("/api/admin/conectar")
def admin_conectar(d: dict = Depends(_cuerpo), x_admin: str = Header(default="")):
    """Suscribe la página a tu app: desde ahí Meta le manda sus mensajes al bot."""
    if not _admin_ok(x_admin): return _no_auth()
    nid = str(d.get("id", "") or "")
    if nid == "principal": return {"ok": False, "error": "Guaranístore ya está conectada desde la app de Meta."}
    n = negocio_por_id(nid)
    if not n: return {"ok": False, "error": "No encontré ese negocio."}
    if not n.conectado(): return {"ok": False, "error": "Primero guardá el token de la página."}
    try:
        r = requests.post(GRAPH_API + "/%s/subscribed_apps" % n.page_id,
                          params={"subscribed_fields": "messages", "access_token": n.page_token}, timeout=10)
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": "No pude hablar con Meta: " + str(e)[:100]}
    if r.status_code == 200 and j.get("success"):
        return {"ok": True}
    return {"ok": False, "error": "Meta dijo: " + ((j.get("error") or {}).get("message", "") or str(r.status_code))[:200]}

@app.get("/api/admin/revisar")
def admin_revisar(id: str = "", x_admin: str = Header(default="")):
    if not _admin_ok(x_admin): return _no_auth()
    n = negocio_por_id(id)
    if not n: return {"error": "No encontré ese negocio."}
    usar(n)
    resultado = _diagnostico(extra=True)
    resultado["negocio"] = n.nombre
    return resultado


# ============================================================
#   /admin — la página para cargar y revisar negocios (entra con ADMIN_CLAVE)
# ============================================================
ADMIN_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Novva · Admin</title>
<style>
  :root { --fondo:#0b1220; --tarjeta:#141d30; --borde:#26324b; --texto:#e8edf7; --suave:#9aa8c3; --acento:#3b82f6; --ok:#22c55e; --mal:#ef4444; --ojo:#f59e0b; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--fondo); color:var(--texto); font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  main { max-width:680px; margin:0 auto; padding:16px 14px 80px; }
  h1 { font-size:20px; margin:6px 0 2px; }
  h2 { font-size:17px; margin:0 0 10px; }
  h3 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--suave); margin:20px 0 8px; }
  p { margin:6px 0; }
  .suave { color:var(--suave); font-size:14px; }
  .card { background:var(--tarjeta); border:1px solid var(--borde); border-radius:14px; padding:14px; margin:12px 0; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .grow { flex:1 1 auto; min-width:0; }
  label { display:block; font-size:14px; color:var(--suave); margin:12px 0 4px; }
  input, textarea { width:100%; background:#0d1526; color:var(--texto); border:1px solid var(--borde); border-radius:10px; padding:11px 12px; font:inherit; }
  textarea { min-height:90px; resize:vertical; }
  input:focus, textarea:focus { outline:2px solid var(--acento); outline-offset:1px; }
  button { background:#1c2740; color:var(--texto); border:1px solid var(--borde); border-radius:10px; padding:10px 14px; font:inherit; cursor:pointer; }
  button.pri { background:var(--acento); border-color:var(--acento); color:#fff; font-weight:600; }
  button.pel { color:#fecaca; border-color:#7f1d1d; }
  button:disabled { opacity:.5; }
  .chip { display:inline-block; font-size:12px; padding:3px 9px; border-radius:999px; border:1px solid var(--borde); color:var(--suave); }
  .chip.ok { color:#bbf7d0; border-color:#166534; }
  .chip.mal { color:#fecaca; border-color:#7f1d1d; }
  .chip.ojo { color:#fde68a; border-color:#92400e; }
  .hidden { display:none !important; }
  .aviso { border-left:4px solid var(--ojo); }
  .check { padding:8px 0; border-top:1px solid var(--borde); font-size:14px; }
  .check:first-child { border-top:0; }
  .check b.ok { color:var(--ok); } .check b.falla { color:var(--mal); }
  details { margin-top:14px; } summary { cursor:pointer; color:var(--suave); }
  #toast { position:fixed; left:50%; top:14px; transform:translateX(-50%); box-shadow:0 6px 24px rgba(0,0,0,.45); background:#111827; border:1px solid var(--borde); padding:10px 16px; border-radius:999px; max-width:92vw; font-size:14px; z-index:9; }
  code { background:#0d1526; padding:1px 6px; border-radius:6px; font-size:13px; word-break:break-all; }
</style>
</head>
<body>
<main>
  <section id="login" class="card">
    <h1>Novva · Admin</h1>
    <p class="suave">Tus negocios y sus conexiones. Entrá con tu <code>ADMIN_CLAVE</code> de Render.</p>
    <label for="clave">Clave de admin</label>
    <input id="clave" type="password" autocomplete="current-password">
    <label class="row" style="margin-top:10px"><input id="recordar" type="checkbox" style="width:auto"> <span>Recordar en este celular</span></label>
    <div class="row" style="margin-top:12px"><button id="btnEntrar" class="pri">Entrar</button></div>
  </section>

  <section id="app" class="hidden">
    <div class="row">
      <h1 class="grow">Tus negocios</h1>
      <button id="btnRecargar">Recargar</button>
      <button id="btnSalir">Salir</button>
    </div>
    <p id="resumen" class="suave"></p>
    <div id="avisos"></div>
    <div class="row"><button id="btnNuevo" class="pri">+ Nuevo negocio</button></div>
    <div id="lista"></div>

    <section id="form" class="card hidden">
      <h2 id="formTitulo">Nuevo negocio</h2>
      <label for="f_nombre">Nombre del negocio</label>
      <input id="f_nombre" autocomplete="off">
      <label for="f_vendedor">Nombre del vendedor (cómo se presenta el bot)</label>
      <input id="f_vendedor" autocomplete="off" placeholder="Fer">
      <label for="f_clave_panel">Clave del panel de este negocio (8 letras o más)</label>
      <div class="row"><input id="f_clave_panel" class="grow" autocomplete="off"><button id="btnGenerar" type="button">Generar</button></div>
      <label for="f_airtable_base">Base de Airtable (empieza con app…)</label>
      <input id="f_airtable_base" autocomplete="off" placeholder="appXXXXXXXXXXXXXX">

      <h3>WhatsApp del negocio</h3>
      <p class="suave">Cada negocio conecta su propio número desde su app de Meta. Dejalo vacío si no usa WhatsApp.</p>
      <label for="f_wa_phone_id">Identificador del número de teléfono (solo números)</label>
      <input id="f_wa_phone_id" inputmode="numeric" autocomplete="off">
      <label for="f_wa_token">Token permanente de WhatsApp</label>
      <input id="f_wa_token" autocomplete="off">
      <label for="f_wa_waba_id">Identificador de la cuenta de WhatsApp Business (solo números)</label>
      <input id="f_wa_waba_id" inputmode="numeric" autocomplete="off">
      <div class="row" style="margin-top:10px">
        <button id="btnProbarWA" type="button">Probar WhatsApp</button>
        <button id="btnRegistrarWA" type="button">Registrar número</button>
        <button id="btnConectarWA" type="button">Conectar WhatsApp al bot</button>
      </div>
      <p id="waInfo" class="suave"></p>

      <h3>Messenger del negocio</h3>
      <label for="f_page_token">Token de la página de Facebook</label>
      <input id="f_page_token" autocomplete="off">
      <div class="row" style="margin-top:10px"><button id="btnConectar" type="button">Conectar página al bot</button></div>

      <h3>Avisos y envíos</h3>
      <label for="f_telegram_chat">Chat de Telegram donde le llegan los pedidos</label>
      <input id="f_telegram_chat" autocomplete="off">
      <label for="f_envio_interior">Costo extra de envío al interior (Gs.)</label>
      <input id="f_envio_interior" inputmode="numeric" autocomplete="off">
      <label for="f_fotos">Fotos del producto (un link https por renglón)</label>
      <textarea id="f_fotos"></textarea>
      <label for="f_video">Link del video</label>
      <input id="f_video" autocomplete="off">
      <label for="f_notas">Notas tuyas (el cliente no las ve)</label>
      <textarea id="f_notas"></textarea>

      <details>
        <summary>Avanzado</summary>
        <label for="f_prompt">Prompt completo propio (vacío = usa la forma de vender de Fer)</label>
        <textarea id="f_prompt" style="min-height:160px"></textarea>
        <label for="f_wa_app_secret">Clave secreta de la app de Meta del cliente (solo si usás VERIFICAR_FIRMA)</label>
        <input id="f_wa_app_secret" autocomplete="off">
        <label for="f_clave_dueno">Palabra secreta para el modo dueño</label>
        <input id="f_clave_dueno" autocomplete="off">
        <label for="f_airtable_key">Token de Airtable propio (vacío = el tuyo)</label>
        <input id="f_airtable_key" autocomplete="off">
        <label for="f_telegram_token">Token de bot de Telegram propio (vacío = el tuyo)</label>
        <input id="f_telegram_token" autocomplete="off">
        <label for="f_gemini_key">Clave de Gemini propia (vacío = la tuya)</label>
        <input id="f_gemini_key" autocomplete="off">
        <label for="f_whatsapp_destino">Aviso de pedidos por CallMeBot: número</label>
        <input id="f_whatsapp_destino" autocomplete="off">
        <label for="f_callmebot_apikey">Aviso de pedidos por CallMeBot: apikey</label>
        <input id="f_callmebot_apikey" autocomplete="off">
      </details>

      <div class="row" style="margin-top:16px">
        <button id="btnGuardar" class="pri">Guardar</button>
        <button id="btnCancelar">Cancelar</button>
      </div>
    </section>

    <section id="revision" class="card hidden">
      <div class="row"><h2 id="revTitulo" class="grow">Revisión</h2><button id="btnCerrarRev">Cerrar</button></div>
      <div id="revCuerpo"></div>
    </section>
  </section>
</main>
<div id="toast" class="hidden" role="status"></div>

<script>
(function () {
  "use strict";
  var CLAVE = "", NEGOCIOS = [], EDITANDO = null;
  var CAMPOS = ["nombre", "vendedor", "clave_panel", "airtable_base", "wa_phone_id", "wa_token", "wa_waba_id", "wa_app_secret",
                "page_token", "telegram_chat", "envio_interior", "fotos", "video", "notas", "prompt", "clave_dueno",
                "airtable_key", "telegram_token", "gemini_key", "whatsapp_destino", "callmebot_apikey"];
  var SECRETOS = ["wa_token", "wa_app_secret", "page_token", "airtable_key", "telegram_token", "gemini_key", "callmebot_apikey"];

  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, hijos) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") e.textContent = attrs[k];
      else if (k === "onclick") e.addEventListener("click", attrs[k]);
      else e.setAttribute(k, attrs[k]);
    });
    (hijos || []).forEach(function (h) { if (h) e.appendChild(h); });
    return e;
  }
  var tToast = null;
  function aviso(txt) {
    var t = $("toast"); t.textContent = txt; t.classList.remove("hidden");
    clearTimeout(tToast); tToast = setTimeout(function () { t.classList.add("hidden"); }, 4500);
  }
  function leerLocal(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function guardarLocal(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }

  function api(ruta, metodo, cuerpo) {
    var op = { method: metodo || "GET", headers: { "X-Admin": CLAVE } };
    if (cuerpo) { op.headers["Content-Type"] = "application/json"; op.body = JSON.stringify(cuerpo); }
    return fetch(ruta, op).then(function (r) {
      if (r.status === 401 || r.status === 403) throw new Error("Clave incorrecta");
      return r.json();
    });
  }

  function entrar(clave) {
    CLAVE = clave;
    return api("/api/admin/negocios").then(function (d) {
      if ($("recordar").checked) guardarLocal("admin_clave", clave);
      $("login").classList.add("hidden"); $("app").classList.remove("hidden");
      pintar(d);
    });
  }
  function salir() {
    CLAVE = ""; guardarLocal("admin_clave", null);
    $("app").classList.add("hidden"); $("login").classList.remove("hidden"); $("clave").value = "";
  }
  function cargar() { return api("/api/admin/negocios").then(pintar).catch(function (e) { aviso(e.message); }); }

  function pintar(d) {
    NEGOCIOS = d.negocios || [];
    $("resumen").textContent = (NEGOCIOS.length - 1) + " negocio(s) cargado(s), además de Guaranístore.";
    var av = $("avisos"); av.textContent = "";
    if (!d.upstash) av.appendChild(el("div", { class: "card aviso", text: "Falta Upstash en Render (o no responde): sin eso no se pueden guardar negocios." }));
    var lista = $("lista"); lista.textContent = "";
    NEGOCIOS.forEach(function (n) {
      var estado = n.estado === "activo" ? ["Activo", "ok"] : (n.estado === "pausado" ? ["Pausado", "mal"] : ["Sin conectar", "ojo"]);
      var botones = [el("button", { text: "Revisar", onclick: function () { revisar(n); } })];
      if (!n.principal) {
        botones.push(el("button", { text: "Editar", onclick: function () { abrirForm(n); } }));
        botones.push(el("button", { text: n.activo ? "Pausar" : "Reanudar", onclick: function () { pausar(n); } }));
        botones.push(el("button", { text: "Copiar clave", onclick: function () { copiar(n.clave_panel, "Clave copiada"); } }));
        botones.push(el("button", { text: "Copiar link de privacidad", onclick: function () { copiar(location.origin + "/privacidad?negocio=" + encodeURIComponent(n.id), "Link copiado"); } }));
        botones.push(el("button", { class: "pel", text: "Borrar", onclick: function () { borrar(n); } }));
      } else if (n.whatsapp) {
        botones.push(el("button", { text: "Registrar número", onclick: function () { registrarWA("principal"); } }));
        botones.push(el("button", { text: "Conectar WhatsApp al bot", onclick: function () { conectarWA("principal"); } }));
      }
      lista.appendChild(el("div", { class: "card" }, [
        el("div", { class: "row" }, [
          el("h2", { class: "grow", text: n.nombre + (n.principal ? " (tu negocio)" : "") }),
          el("span", { class: "chip " + estado[1], text: estado[0] })
        ]),
        el("div", { class: "row" }, [
          el("span", { class: "chip " + (n.whatsapp ? "ok" : ""), text: "WhatsApp " + (n.whatsapp ? "✓" : "—") }),
          el("span", { class: "chip " + (n.messenger ? "ok" : ""), text: "Messenger " + (n.messenger ? "✓" : "—") })
        ]),
        n.principal ? el("p", { class: "suave", text: "Se configura con las variables de Render (para WhatsApp: WA_PHONE_ID, WA_TOKEN y WA_WABA_ID)." }) : null,
        el("div", { class: "row", style: "margin-top:10px" }, botones)
      ]));
    });
  }

  function abrirForm(n) {
    EDITANDO = n ? n.id : null;
    $("formTitulo").textContent = n ? "Editar: " + n.nombre : "Nuevo negocio";
    CAMPOS.forEach(function (c) {
      var campo = $("f_" + c), v = n ? n[c] : "";
      if (Array.isArray(v)) v = v.join("\n");
      if (SECRETOS.indexOf(c) >= 0) { campo.value = ""; campo.placeholder = v ? "Guardado (" + v + "). Vacío = no cambia" : ""; }
      else campo.value = (v === undefined || v === null) ? "" : String(v);
    });
    if (!n) { $("f_vendedor").value = "Fer"; $("f_envio_interior").value = "25000"; generarClave(); }
    $("waInfo").textContent = "";
    $("form").classList.remove("hidden"); $("revision").classList.add("hidden");
    $("form").scrollIntoView({ behavior: "smooth" });
  }
  function datosForm() {
    var d = {}; if (EDITANDO) d.id = EDITANDO;
    CAMPOS.forEach(function (c) { d[c] = $("f_" + c).value; });
    return d;
  }
  function generarClave() {
    var abc = "abcdefghjkmnpqrstuvwxyz23456789", s = "", a = new Uint8Array(12);
    (window.crypto || window.msCrypto).getRandomValues(a);
    for (var i = 0; i < a.length; i++) s += abc[a[i] % abc.length];
    $("f_clave_panel").value = s;
  }
  function guardar() {
    $("btnGuardar").disabled = true;
    api("/api/admin/negocio", "POST", datosForm()).then(function (r) {
      $("btnGuardar").disabled = false;
      if (!r.ok) { aviso(r.error || "No se pudo guardar"); return; }
      aviso("Guardado ✅"); $("form").classList.add("hidden"); cargar();
    }).catch(function (e) { $("btnGuardar").disabled = false; aviso(e.message); });
  }
  function pausar(n) {
    api("/api/admin/pausar", "POST", { id: n.id, activo: !n.activo }).then(function (r) {
      aviso(r.ok ? (r.activo ? "Reanudado" : "Pausado: el bot ya no le contesta") : (r.error || "No se pudo")); cargar();
    }).catch(function (e) { aviso(e.message); });
  }
  function borrar(n) {
    if (!confirm("¿Borrar " + n.nombre + "? El bot deja de atenderlo. Sus datos de Airtable no se tocan.")) return;
    api("/api/admin/borrar-negocio", "POST", { id: n.id }).then(function (r) {
      aviso(r.ok ? "Borrado" : (r.error || "No se pudo")); cargar();
    }).catch(function (e) { aviso(e.message); });
  }
  function revisar(n) {
    $("revTitulo").textContent = "Revisando " + n.nombre + "…";
    $("revCuerpo").textContent = ""; $("revision").classList.remove("hidden"); $("form").classList.add("hidden");
    $("revision").scrollIntoView({ behavior: "smooth" });
    api("/api/admin/revisar?id=" + encodeURIComponent(n.id)).then(function (r) {
      if (r.error) { $("revTitulo").textContent = r.error; return; }
      $("revTitulo").textContent = n.nombre + ": " + (r.salud === "todo_ok" ? "todo bien ✅" : r.fallas + " cosa(s) para revisar ⚠️");
      (r.checks || []).forEach(function (c) {
        $("revCuerpo").appendChild(el("div", { class: "check" }, [
          el("b", { class: c.estado, text: (c.estado === "ok" ? "✓ " : "✗ ") + c.nombre }),
          el("div", { class: "suave", text: c.detalle })
        ]));
      });
    }).catch(function (e) { $("revTitulo").textContent = e.message; });
  }
  function probarWA() {
    var d = { wa_phone_id: $("f_wa_phone_id").value, wa_token: $("f_wa_token").value };
    if (EDITANDO) d.id = EDITANDO;
    $("waInfo").textContent = "Preguntándole a Meta…";
    api("/api/admin/validar-whatsapp", "POST", d).then(function (r) {
      $("waInfo").textContent = r.ok
        ? "✓ Meta reconoce el número " + (r.numero || "") + (r.nombre ? " (" + r.nombre + ")" : "") + (r.aviso ? ". Ojo: " + r.aviso : ".")
        : "✗ " + (r.error || "No se pudo validar");
    }).catch(function (e) { $("waInfo").textContent = e.message; });
  }
  function registrarWA(id) {
    var nid = id || EDITANDO;
    if (!nid) { aviso("Primero guardá el negocio."); return; }
    var pin = prompt("Inventá un PIN de 6 números para este número de WhatsApp (anotalo: Meta lo pide si alguna vez lo movés):");
    if (!pin) return;
    api("/api/admin/wa-registrar", "POST", { id: nid, pin: pin }).then(function (r) {
      aviso(r.ok ? "Número registrado ✅" : (r.error || "No se pudo registrar"));
    }).catch(function (e) { aviso(e.message); });
  }
  function conectarWA(id) {
    var nid = id || EDITANDO;
    if (!nid) { aviso("Primero guardá el negocio."); return; }
    api("/api/admin/wa-conectar", "POST", { id: nid }).then(function (r) {
      aviso(r.ok ? "WhatsApp conectado al bot ✅" : (r.error || "No se pudo conectar"));
    }).catch(function (e) { aviso(e.message); });
  }
  function conectarPagina() {
    if (!EDITANDO) { aviso("Primero guardá el negocio con el token de la página."); return; }
    api("/api/admin/conectar", "POST", { id: EDITANDO }).then(function (r) {
      aviso(r.ok ? "Página conectada al bot ✅" : (r.error || "No se pudo conectar"));
    }).catch(function (e) { aviso(e.message); });
  }
  function copiar(txt, listo) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(function () { aviso(listo || "Copiado"); }, function () { prompt("Copialo de acá:", txt); });
    } else prompt("Copialo de acá:", txt);
  }

  $("btnEntrar").addEventListener("click", function () {
    var c = $("clave").value.trim(); if (!c) return;
    entrar(c).catch(function (e) { aviso(e.message); });
  });
  $("clave").addEventListener("keydown", function (e) { if (e.key === "Enter") $("btnEntrar").click(); });
  $("btnSalir").addEventListener("click", salir);
  $("btnRecargar").addEventListener("click", cargar);
  $("btnNuevo").addEventListener("click", function () { abrirForm(null); });
  $("btnGenerar").addEventListener("click", generarClave);
  $("btnGuardar").addEventListener("click", guardar);
  $("btnCancelar").addEventListener("click", function () { $("form").classList.add("hidden"); });
  $("btnProbarWA").addEventListener("click", probarWA);
  $("btnRegistrarWA").addEventListener("click", function () { registrarWA(null); });
  $("btnConectarWA").addEventListener("click", function () { conectarWA(null); });
  $("btnConectar").addEventListener("click", conectarPagina);
  $("btnCerrarRev").addEventListener("click", function () { $("revision").classList.add("hidden"); });

  var guardada = leerLocal("admin_clave");
  if (guardada) { $("recordar").checked = true; entrar(guardada).catch(function () { guardarLocal("admin_clave", null); }); }
})();
</script>
</body>
</html>
"""

@app.get("/admin")
def admin_pagina():
    return Response(content=ADMIN_HTML, media_type="text/html; charset=utf-8")


# ============================================================
#   /privacidad — página pública que Meta pide para poner una app "en vivo".
#   Sirve para tu app y para la de cada cliente:  /privacidad?negocio=<id del negocio>
# ============================================================
PRIVACIDAD_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Privacidad · %(nombre)s</title>
<style>body{font:17px/1.6 system-ui,sans-serif;max-width:680px;margin:0 auto;padding:24px 18px 60px;color:#1b2333}
h1{font-size:24px}h2{font-size:18px;margin-top:28px}p,li{margin:8px 0}small{color:#5b6475}</style></head><body>
<h1>Política de privacidad de %(nombre)s</h1>
<p>%(nombre)s atiende sus chats de WhatsApp y Messenger con un <b>asistente virtual</b>: un programa que contesta de forma automática. Si pedís hablar con una persona, el asistente le avisa al equipo.</p>
<h2>Qué datos guardamos</h2>
<ul><li>Los mensajes que nos escribís. Los audios se pasan a texto para poder entenderlos y las fotos de comprobantes se leen para confirmar tu pago.</li>
<li>Tu número de WhatsApp o tu identificador de Messenger.</li>
<li>Los datos que nos das para tu pedido: nombre, ciudad, teléfono y dirección.</li></ul>
<h2>Para qué los usamos</h2>
<p>Para contestarte, tomar tu pedido, entregarlo y mejorar la atención. No vendemos tus datos ni los usamos para publicidad de terceros.</p>
<h2>Quién más los procesa</h2>
<p>Las empresas que hacen funcionar el servicio, solo para ese fin: Meta (WhatsApp y Messenger), Google (genera las respuestas del asistente), Airtable, Upstash y Render (guardan y hacen andar el sistema) y Telegram (por ahí le llega al negocio el aviso de tu pedido).</p>
<h2>Cuánto tiempo</h2>
<p>La memoria de la charla que usa el asistente se borra sola a los 30 días sin mensajes. El registro de conversaciones y de pedidos queda en el sistema del negocio hasta que pidas borrarlo o el negocio lo elimine.</p>
<h2 id="borrar">Cómo borrar tus datos</h2>
<p>Escribí <b>borrar mis datos</b> en el mismo chat. En el momento se borran tu charla y tus datos de contacto; tus pedidos quedan sin tus datos de contacto, solo para la contabilidad del negocio.</p>
<h2>Contacto</h2>
<p>Por cualquier consulta sobre tus datos, escribinos por el mismo chat y pedí hablar con una persona.</p>
<p><small>Última actualización: noviembre de 2026.</small></p></body></html>"""

@app.get("/privacidad")
def privacidad(negocio: str = ""):
    n = negocio_por_id(re.sub(r"[^a-z0-9-]", "", str(negocio or "").lower())[:40]) if negocio else PRINCIPAL
    nombre = html.escape(n.nombre if n else "este negocio")
    return Response(content=PRIVACIDAD_HTML % {"nombre": nombre}, media_type="text/html; charset=utf-8")


@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
