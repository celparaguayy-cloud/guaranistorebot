"""
FER BOT — version definitiva
Incluye: memoria (Airtable), aviso de pedidos a Telegram, "escribiendo...",
anti-respuestas-dobles, token resistente, division de mensajes largos.
Imprime >>> en los logs para diagnostico.
"""

import os
import re
import json
import time
import traceback
import requests
from fastapi import FastAPI, Request, Response

app = FastAPI()

VERIFY_TOKEN   = os.environ.get("VERIFY_TOKEN", "fer123")
PAGE_TOKEN     = os.environ["PAGE_TOKEN"].strip()
GEMINI_KEY     = os.environ["GEMINI_KEY"].strip()
AIRTABLE_KEY   = os.environ["AIRTABLE_KEY"].strip()
AIRTABLE_BASE  = os.environ["AIRTABLE_BASE"].strip()
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"].strip()
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT"].strip()

TABLA = "Conversaciones"
GRAPH = "https://graph.facebook.com/v21.0/me/messages"

# Candado anti-duplicados: guarda los ids de mensajes ya atendidos
MENSAJES_VISTOS = set()

SYSTEM_PROMPT = """
Sos Fer, vendedor de verdad de Guaranistore, una tienda paraguaya. Sos una PERSONA, no un bot: con caracter, historia y corazon. Nadie deberia sospechar que del otro lado hay un sistema. Antes que vendedor, sos gente. Tu norte en cada mensaje: acompanar a la persona hasta que se lleve su Depiladora IPL, tratandola tan bien que quiera comprarte a VOS.

SALUDO (MUY IMPORTANTE): saluda UNA SOLA VEZ, al principio. Si ya venis conversando (si en el historial ya hubo mensajes), NO vuelvas a saludar ni a presentarte: continua la charla donde quedo. NO uses "mba'eichapa" ni ningun saludo guarani en cada mensaje; como mucho uno al principio, sin repetirlo. Varia los saludos.

QUIEN SOS: 30 y pico, paraguayo, hace anos que vivis de vender. Respetas la plata del que te escribe. Calido, con picardia justa, serio con lo importante. Nunca prometes lo que no podes cumplir. Lees a la persona y actuas en consecuencia.

TU AMABILIDAD (tu sello): usala siempre, compren o no. "por favor" y "gracias" de verdad. Trata con carino ("quedate tranquila", "con todo gusto"). Haz sentir importante a la persona. Despedite con calidez aunque no compre. Amable no es zalamero: nada de "mi amor/mi reina". Educacion paraguaya genuina.

TU CORAZON (empatia): si te cuentan algo personal ("es para mi hija enferma", "no me alcanza"), PARA la venta y responde como humano. NUNCA uses el dolor o la necesidad ajena para vender. Si no le alcanza, jamas la hagas sentir mal. La dignidad del otro vale mas que una venta.

COMO ESCRIBIS: mensajes CORTOS (1 a 3 lineas). Voseo paraguayo. Guarani muy de vez en cuando, sin abusar. UNA pregunta por vez. Espeja el tono del cliente.

EMOJIS: usa pocos, pero expresivos en los momentos clave para darle calidez y alegria: al saludar, al cerrar la venta, al agradecer (por ejemplo 🎉🙌😍👍🇵🇾). Nunca llenes de emojis ni pongas una fila; uno o dos bien puestos alcanzan.

MENSAJES CORTOS: "precio"/"cuanto?" -> da el precio AL TOQUE y engancha una pregunta. "hola" -> saluda calido y pregunta en que ayudas. Foto/"esto tienen?" -> confirma y pasa al precio.

EL PRODUCTO: Depiladora IPL de Luz Pulsada (Black Word). Definitiva, en casa, indolora, todo el cuerpo. Misma tecnologia IPL de los centros de estetica. Kit: gafas, afeitadora, manual y caja. Precio: Gs. 280.000. Garantia: 5 dias. Entrega: 1 a 3 dias. Pago CONTRA ENTREGA en 24 ciudades. EXCEPCION: Minga Pora, Curuguaty, Katuete y Salto del Guaira solo con transferencia anticipada.

TU GANCHO: el ahorro. La gente gasta todos los meses en depilarse; la IPL es UN solo pago y en pocos meses se pago sola. Deslizalo con ejemplos reales.

FLUJO: 1) Saludas UNA vez. 2) Escuchas para que/para quien. 3) Muestras valor + ahorro. 4) Precio al toque si lo piden. 5) Resolves dudas. 6) Cerras tomando los datos cuando hay interes. La conversacion manda, pero retoma hacia el cierre.

CIERRE (los datos): necesitas SIEMPRE 4 datos, pedidos como charla, de a uno o dos, con "por favor": 1) Nombre y apellido, 2) Ciudad, 3) Telefono, 4) Direccion. Con los 4, confirma con resumen calido y agradece.

>>> AVISO DE PEDIDO (MUY IMPORTANTE): cuando ya tengas los 4 datos Y el cliente CONFIRME, al FINAL de tu mensaje de confirmacion agrega EXACTAMENTE una linea con este formato (etiqueta interna, tal cual):
[PEDIDO] Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]
Solo cuando el pedido esta cerrado y confirmado, nunca antes. El cliente no la vera.

HORARIOS: atendes a cualquier hora con la misma onda, sin hacerlo notar.

CURIOSOS Y GROSEROS: pavadas -> humor amable y volves al tema. Insultos -> no te enganches, manten la altura. "Sos un robot?" -> no confirmes, "jaja soy Fer, en que te ayudo?" y segui.

OBJECIONES: "Funciona?" -> si, es IPL con garantia. "Es caro" -> es un solo pago, contra entrega, y si no es el momento cuando puedas. "Y si no sirve?" -> 5 dias de garantia. "Lo pienso" -> dale, sin insistir. "Duele?" -> no, apenas un calorcito.

REGLAS: nunca inventes precios ni datos que no esten aca. Nunca uses el dolor de alguien para vender. No presiones. Se amable sin zalameria. No hables de otros productos salvo que pregunten. Nunca digas que sos un bot: sos Fer.
"""


@app.get("/webhook")
def verificar(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token incorrecto", status_code=403)


@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    print(">>> MENSAJE ENTRANTE:", json.dumps(data, ensure_ascii=False))
    for entry in data.get("entry", []):
        for evento in entry.get("messaging", []):
            sender = evento.get("sender", {}).get("id")
            mensaje = evento.get("message", {})
            mid = mensaje.get("mid")

            # Candado anti-duplicados
            if mid and mid in MENSAJES_VISTOS:
                print(">>> Mensaje repetido, lo ignoro")
                continue
            if mid:
                MENSAJES_VISTOS.add(mid)
                if len(MENSAJES_VISTOS) > 500:
                    MENSAJES_VISTOS.clear()

            if "text" in mensaje:
                texto = mensaje["text"]
                print(f">>> TEXTO: '{texto}' de {sender}")
                try:
                    responder(sender, texto)
                except Exception:
                    print(">>> ERROR EN RESPONDER:")
                    print(traceback.format_exc())
            else:
                print(">>> Evento sin texto (lo ignoro)")
    return {"status": "ok"}


def responder(sender, texto):
    marcar_leido(sender)
    mostrar_escribiendo(sender)

    historial = leer_historial(sender)
    respuesta = preguntar_a_gemini(historial, texto)
    print(f">>> GEMINI: '{respuesta}'")

    respuesta_limpia = revisar_pedido(sender, respuesta)

    enviar_a_messenger(sender, respuesta_limpia)
    guardar(sender, "user", texto)
    guardar(sender, "model", respuesta_limpia)


# ---- Detecta [PEDIDO]...[/PEDIDO], avisa a Telegram y borra la etiqueta
def revisar_pedido(sender, respuesta):
    m = re.search(r"\[PEDIDO\](.*?)\[/PEDIDO\]", respuesta, re.DOTALL)
    if m:
        resumen = m.group(1).strip()
        avisar_telegram("NUEVO PEDIDO\n" + resumen + f"\n(cliente: {sender})")
        respuesta = re.sub(r"\[PEDIDO\].*?\[/PEDIDO\]", "", respuesta, flags=re.DOTALL).strip()
    return respuesta


# ---- MEMORIA
def leer_historial(sender):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    params = {"filterByFormula": f"{{contact_id}}='{sender}'", "maxRecords": 20}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        print(">>> AIRTABLE (leer) error:", r.status_code, r.text)
        return []
    historial = []
    for reg in r.json().get("records", []):
        texto = reg.get("fields", {}).get("mensaje_entrante", "")
        if texto.startswith("[bot] "):
            historial.append({"rol": "model", "mensaje": texto[6:]})
        elif texto.startswith("[user] "):
            historial.append({"rol": "user", "mensaje": texto[7:]})
        elif texto:
            historial.append({"rol": "user", "mensaje": texto})
    return historial


def guardar(sender, rol, mensaje):
    quien = "bot" if rol == "model" else "user"
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}", "Content-Type": "application/json"}
    cuerpo = {"fields": {"contact_id": sender, "mensaje_entrante": f"[{quien}] {mensaje}"}}
    r = requests.post(url, headers=headers, json=cuerpo, timeout=10)
    if r.status_code not in (200, 201):
        print(">>> AIRTABLE (guardar) error:", r.status_code, r.text)


# ---- CEREBRO
def preguntar_a_gemini(historial, texto_nuevo):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-flash-latest:generateContent?key={GEMINI_KEY}"
    )
    contenidos = []
    for m in historial:
        contenidos.append({"role": m["rol"], "parts": [{"text": m["mensaje"]}]})
    contenidos.append({"role": "user", "parts": [{"text": texto_nuevo}]})
    cuerpo = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contenidos,
    }
    r = requests.post(url, json=cuerpo, timeout=30)
    if r.status_code != 200:
        print(">>> GEMINI error:", r.status_code, r.text)
        return "Hola! Gracias por escribir a Guaranistore. Ya te atiendo 😊"
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        print(">>> GEMINI raro:", json.dumps(data, ensure_ascii=False))
        return "Hola! Gracias por escribir a Guaranistore. Ya te atiendo 😊"


# ---- MESSENGER: enviar (parte los mensajes largos)
def enviar_a_messenger(sender, texto):
    for pedazo in partir(texto, 1900):
        cuerpo = {
            "recipient": {"id": sender},
            "messaging_type": "RESPONSE",
            "message": {"text": pedazo},
        }
        r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                          json=cuerpo, timeout=10)
        print(">>> MESSENGER:", r.status_code, r.text)


def partir(texto, limite):
    texto = texto.strip()
    if len(texto) <= limite:
        return [texto] if texto else ["😊"]
    pedazos, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > limite:
            pedazos.append(actual.strip())
            actual = ""
        actual += linea + "\n"
    if actual.strip():
        pedazos.append(actual.strip())
    return pedazos


# ---- MESSENGER: "visto" y "escribiendo..."
def marcar_leido(sender):
    try:
        requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                      json={"recipient": {"id": sender}, "sender_action": "mark_seen"},
                      timeout=8)
    except Exception:
        pass


def mostrar_escribiendo(sender):
    try:
        requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                      json={"recipient": {"id": sender}, "sender_action": "typing_on"},
                      timeout=8)
    except Exception:
        pass


# ---- TELEGRAM
def avisar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": texto}, timeout=10)
    print(">>> TELEGRAM:", r.status_code, r.text)


@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
