"""
================================================================
  FER BOT  —  versión en código (Python)
================================================================
Bot vendedor para Facebook Messenger. Reemplaza a ManyChat.
Vive prendido 24/7 en un servidor y contesta solo (incluso
cuando vos no tenés el celular).

Cómo piensa el bot, paso a paso:

   Cliente escribe en Messenger
        │
        ▼
   Este servidor recibe el mensaje  (el "webhook")
        │
        ├──► lee la charla anterior en Airtable   (la memoria)
        ├──► se lo pasa a Gemini con tu prompt     (el cerebro)
        ├──► le manda la respuesta al cliente      (Messenger)
        └──► guarda la charla de nuevo en Airtable

IMPORTANTE: en este archivo NO van tus claves. Las claves
(tokens y API keys) se cargan aparte, en el servidor, como
"variables de entorno". Así nadie las ve aunque vea el código.
Todo eso está explicado en el archivo README.md.
================================================================
"""

import os
import requests
from fastapi import FastAPI, Request, Response

app = FastAPI()

# ---------------------------------------------------------------
#  CLAVES  (se leen del servidor — NO se escriben acá adentro)
# ---------------------------------------------------------------
VERIFY_TOKEN   = os.environ.get("VERIFY_TOKEN", "fer123")  # una palabra que inventás vos
PAGE_TOKEN     = os.environ["PAGE_TOKEN"]        # token de tu página de Facebook
GEMINI_KEY     = os.environ["GEMINI_KEY"]        # API key de Gemini
AIRTABLE_KEY   = os.environ["AIRTABLE_KEY"]      # API key de Airtable
AIRTABLE_BASE  = os.environ["AIRTABLE_BASE"]     # id de tu base ZAPPY_BOT
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]    # token de tu bot de Telegram
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT"]     # tu chat id de Telegram

# ---------------------------------------------------------------
#  EL PROMPT DE FER
#  Pegá acá abajo tu prompt de vendedor (el mismo que ya usás
#  en Gemini). Dejalo entre las tres comillas.
# ---------------------------------------------------------------
SYSTEM_PROMPT = """
Sos Fer, el vendedor de Guaranístore.
(PEGÁ ACÁ tu prompt completo de vendedor)
"""


# ===============================================================
#  1) VERIFICACIÓN DEL WEBHOOK
#  Meta llama a esta dirección UNA vez para confirmar que el
#  servidor es tuyo. Solo hay que devolverle su "challenge".
# ===============================================================
@app.get("/webhook")
def verificar(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token incorrecto", status_code=403)


# ===============================================================
#  2) RECIBIR MENSAJES
#  Cada vez que un cliente escribe, Meta manda el mensaje acá.
# ===============================================================
@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    for entry in data.get("entry", []):
        for evento in entry.get("messaging", []):
            sender = evento["sender"]["id"]
            if "message" in evento and "text" in evento["message"]:
                texto = evento["message"]["text"]
                responder(sender, texto)
    return {"status": "ok"}


# ===============================================================
#  3) LA LÓGICA CENTRAL: qué hace el bot con cada mensaje
# ===============================================================
def responder(sender, texto):
    charla_previa = leer_historial(sender)
    respuesta = preguntar_a_gemini(charla_previa, texto)
    enviar_a_messenger(sender, respuesta)
    guardar(sender, "user", texto)
    guardar(sender, "model", respuesta)


# ---- MEMORIA: leer la charla anterior desde Airtable ----------
def leer_historial(sender):
    """
    Trae los últimos mensajes de este cliente.
    Asume que tu tabla 'Conversaciones' tiene estos campos:
       sender_id  (texto)   -> quién es el cliente
       rol        (texto)   -> "user" o "model"
       mensaje    (texto)   -> lo que se dijo
       creado     (fecha)   -> cuándo (para ordenar)
    Si tus campos se llaman distinto, avisame y lo ajusto.
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/Conversaciones"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    params = {
        "filterByFormula": f"{{sender_id}}='{sender}'",
        "sort[0][field]": "creado",
        "sort[0][direction]": "asc",
        "maxRecords": 20,
    }
    r = requests.get(url, headers=headers, params=params, timeout=10)
    registros = r.json().get("records", [])
    return [reg["fields"] for reg in registros]


# ---- MEMORIA: guardar un mensaje en Airtable ------------------
def guardar(sender, rol, mensaje):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/Conversaciones"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_KEY}",
        "Content-Type": "application/json",
    }
    cuerpo = {"fields": {"sender_id": sender, "rol": rol, "mensaje": mensaje}}
    requests.post(url, headers=headers, json=cuerpo, timeout=10)


# ---- CEREBRO: preguntarle a Gemini ----------------------------
def preguntar_a_gemini(charla_previa, texto_nuevo):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-flash-latest:generateContent?key={GEMINI_KEY}"
    )
    contenidos = []
    for m in charla_previa:
        contenidos.append({"role": m.get("rol", "user"),
                           "parts": [{"text": m.get("mensaje", "")}]})
    contenidos.append({"role": "user", "parts": [{"text": texto_nuevo}]})

    cuerpo = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contenidos,
    }
    r = requests.post(url, json=cuerpo, timeout=30)
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        # Si Gemini no contesta bien, mandamos algo por defecto
        return "Disculpá, se me trabó un segundo. ¿Me repetís?"


# ---- RESPUESTA: mandarle el mensaje al cliente ----------------
def enviar_a_messenger(sender, texto):
    url = f"https://graph.facebook.com/v21.0/me/messages?access_token={PAGE_TOKEN}"
    cuerpo = {"recipient": {"id": sender}, "message": {"text": texto}}
    requests.post(url, json=cuerpo, timeout=10)


# ---- AVISO: pasar un pedido a Telegram ------------------------
#  (Esto lo vamos a enganchar en el PASO 2, cuando el bot ya
#   esté vendiendo. Por ahora la función queda lista y esperando.)
def avisar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": texto}, timeout=10)


# ---- Ruta de prueba: para ver si el servidor está vivo --------
@app.get("/")
def inicio():
    return {"estado": "Fer está prendido y esperando mensajes 🟢"}
