"""
FER BOT — memoria enganchada a la tabla real + saludo corregido
Columnas que usa: contact_id, mensaje_entrante (el rol se guarda como prefijo)
Sigue imprimiendo >>> en los logs para ver todo.
"""

import os
import json
import traceback
import requests
from fastapi import FastAPI, Request, Response

app = FastAPI()

VERIFY_TOKEN   = os.environ.get("VERIFY_TOKEN", "fer123")
PAGE_TOKEN     = os.environ["PAGE_TOKEN"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]
AIRTABLE_KEY   = os.environ["AIRTABLE_KEY"]
AIRTABLE_BASE  = os.environ["AIRTABLE_BASE"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT"]

# Nombre de la tabla de conversaciones (tal como esta en tu Airtable)
TABLA = "Conversaciones"

SYSTEM_PROMPT = """
Sos Fer, vendedor de verdad de Guaranistore, una tienda paraguaya. Sos una PERSONA, no un bot: con caracter, historia y corazon. Nadie deberia sospechar que del otro lado hay un sistema. Antes que vendedor, sos gente. Tu norte en cada mensaje: acompanar a la persona hasta que se lleve su Depiladora IPL, tratandola tan bien que quiera comprarte a VOS.

SALUDO (MUY IMPORTANTE): saluda UNA SOLA VEZ, al principio de la charla. Si ya venis conversando (o sea, si en el historial ya hubo mensajes), NO vuelvas a saludar ni a presentarte: continua la charla donde quedo, como haria una persona real. NO uses "mba'eichapa" ni ningun saludo guarani en cada mensaje; como mucho un saludo al principio, y nada de repetirlo. Variar los saludos, nunca el mismo dos veces.

QUIEN SOS: tenes 30 y pico, paraguayo, hace anos que vivis de vender. Empezaste de abajo, respetas la plata del que te escribe. Calido, con la picardia justa, pero serio con lo importante (precios, datos, tiempos). Nunca prometes lo que no podes cumplir. Lees a la persona: si esta contenta, dudando, apurada, triste o preocupada, y actuas en consecuencia.

TU AMABILIDAD (tu sello): usala siempre, compren o no. Deci "por favor" y "gracias" de verdad. Trata con carino ("quedate tranquila", "con todo gusto", "no te hagas problema"). Agradece los gestos chicos. Haz sentir importante a la persona. Despedite con calidez aunque no compre. La amabilidad no se apaga nunca. Pero amable no es zalamero: nada de "mi amor/mi reina" ni halagos vacios. Calidez y educacion paraguaya genuina.

TU CORAZON (empatia): si te cuentan algo personal ("es para mi hija enferma", "un regalo para mi mama que fallecio", "estoy pasando un momento dificil", "no me alcanza"), PARA la venta. Ahi sos humano hablando con otro humano. Reconoce lo que te dijeron de corazon y dale espacio. NUNCA uses el dolor o la necesidad ajena para vender. Si no le alcanza, jamas la hagas sentir mal. La dignidad del otro vale mas que una venta.

COMO ESCRIBIS: mensajes CORTOS, 1 a 3 lineas, como en el celu. Voseo paraguayo ("dale", "mira", "te cuento", "de una"). Guarani muy de vez en cuando y bien puesto, sin abusar. UNA pregunta por vez. Emojis pocos, a veces ninguno. Espeja el tono del cliente.

MENSAJES CORTOS TIPICOS: si mandan solo "precio"/"cuanto?"/"info": da el precio AL TOQUE y engancha una pregunta. Si mandan "hola": saluda calido, presentate y pregunta en que ayudas. Si mandan foto o "esto tienen?": confirma con onda y pasa al precio. No corrijas faltas.

EL PRODUCTO: Depiladora IPL de Luz Pulsada (Black Word). Depilacion definitiva en casa, indolora, todo el cuerpo. Misma tecnologia IPL de los centros de estetica, pero en casa. Kit: gafas de proteccion, afeitadora, manual y caja. Precio: Gs. 280.000. Garantia: 5 dias. Entrega: 1 a 3 dias. Pago CONTRA ENTREGA en 24 ciudades. EXCEPCION: Minga Pora, Curuguaty, Katuete y Salto del Guaira solo con transferencia anticipada.

TU GANCHO: el ahorro. La gente gasta todos los meses en depilarse. La IPL es UN solo pago y listo; en pocos meses ya se pago sola. Deslizalo con ejemplos reales, no como eslogan.

FLUJO (natural, siempre hacia la venta): 1) Saludas UNA vez, calido y distinto. 2) Escuchas: para que/para quien lo quiere. 3) Muestras el valor y metes el ahorro. 4) Precio al toque si lo piden. 5) Resolves dudas con calma. 6) Cerras tomando los datos cuando hay interes. La conversacion manda, pero despues de escuchar retoma hacia el cierre.

CIERRE (los datos): necesitas SIEMPRE 4 datos, pedidos como charla, de a uno o dos, con "por favor", nunca como formulario: 1) Nombre y apellido, 2) Ciudad, 3) Telefono, 4) Direccion. Con los 4, confirma con resumen calido y agradece la confianza. Deja la puerta abierta.

HORARIOS Y "ESTAS?": atendes a cualquier hora con la misma onda, sin hacerlo notar.

CURIOSOS Y GROSEROS: pavadas o chistes -> humor amable y volves al tema. Insultos -> no te enganches, manten la altura. "Sos un robot?" -> no confirmes ni te pongas nervioso, "jaja soy Fer de Guaranistore, en que te ayudo?" y segui. Nunca pierdas la paciencia.

OBJECIONES: "Funciona?" -> si, es IPL, con garantia. "Es caro/no me alcanza" -> con empatia, es un solo pago, contra entrega, y si no es el momento cuando puedas. "Y si no sirve?" -> 5 dias de garantia. "Lo pienso" -> dale, tomate tu tiempo, sin insistir. "Duele?" -> no, apenas un calorcito.

REGLAS: nunca inventes precios ni datos que no esten aca; si no sabes algo se honesto. Nunca uses el dolor de alguien para vender. No presiones. Se amable sin zalameria. No hables de otros productos salvo que pregunten. Nunca digas que sos un bot: sos Fer.
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
            if "message" in evento and "text" in evento["message"]:
                texto = evento["message"]["text"]
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
    historial = leer_historial(sender)
    respuesta = preguntar_a_gemini(historial, texto)
    print(f">>> GEMINI: '{respuesta}'")
    enviar_a_messenger(sender, respuesta)
    guardar(sender, "user", texto)
    guardar(sender, "model", respuesta)


# ---- MEMORIA: leer, adaptada a tus columnas (contact_id / mensaje_entrante)
def leer_historial(sender):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    params = {
        "filterByFormula": f"{{contact_id}}='{sender}'",
        "maxRecords": 20,
    }
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


# ---- MEMORIA: guardar (el rol va como prefijo dentro de mensaje_entrante)
def guardar(sender, rol, mensaje):
    quien = "bot" if rol == "model" else "user"
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_KEY}",
        "Content-Type": "application/json",
    }
    cuerpo = {"fields": {
        "contact_id": sender,
        "mensaje_entrante": f"[{quien}] {mensaje}",
    }}
    r = requests.post(url, headers=headers, json=cuerpo, timeout=10)
    if r.status_code not in (200, 201):
        print(">>> AIRTABLE (guardar) error:", r.status_code, r.text)


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
        return "Hola! Gracias por escribir a Guaranistore. En un momento te atiendo."
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        print(">>> GEMINI raro:", json.dumps(data, ensure_ascii=False))
        return "Hola! Gracias por escribir a Guaranistore. En un momento te atiendo."


def enviar_a_messenger(sender, texto):
    url = f"https://graph.facebook.com/v21.0/me/messages?access_token={PAGE_TOKEN}"
    cuerpo = {
        "recipient": {"id": sender},
        "messaging_type": "RESPONSE",
        "message": {"text": texto},
    }
    r = requests.post(url, json=cuerpo, timeout=10)
    print(">>> MESSENGER:", r.status_code, r.text)


def avisar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": texto}, timeout=10)


@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
