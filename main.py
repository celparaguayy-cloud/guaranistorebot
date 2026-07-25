"""
FER BOT — versión con DIAGNÓSTICO
Ahora HABLA en los logs: escribe cada paso con >>> para ver dónde se traba.
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

SYSTEM_PROMPT = """
Sos Fer, el vendedor de Guaranistore.
(PEGA ACA tu prompt completo de vendedor)
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
    print(">>> MENSAJE ENTRANTE DE FACEBOOK:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    for entry in data.get("entry", []):
        for evento in entry.get("messaging", []):
            sender = evento.get("sender", {}).get("id")
            if "message" in evento and "text" in evento["message"]:
                texto = evento["message"]["text"]
                print(f">>> TEXTO RECIBIDO: '{texto}' de {sender}")
                try:
                    responder(sender, texto)
                except Exception:
                    print(">>> ERROR DENTRO DE RESPONDER:")
                    print(traceback.format_exc())
            else:
                print(">>> Evento sin texto (lo ignoro):", evento)
    return {"status": "ok"}


def responder(sender, texto):
    charla_previa = leer_historial(sender)
    respuesta = preguntar_a_gemini(charla_previa, texto)
    print(f">>> GEMINI CONTESTO: '{respuesta}'")
    enviar_a_messenger(sender, respuesta)
    guardar(sender, "user", texto)
    guardar(sender, "model", respuesta)


def leer_historial(sender):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/Conversaciones"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    params = {
        "filterByFormula": f"{{sender_id}}='{sender}'",
        "sort[0][field]": "creado",
        "sort[0][direction]": "asc",
        "maxRecords": 20,
    }
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        print(">>> AIRTABLE (leer) error:", r.status_code, r.text)
        return []
    return [reg["fields"] for reg in r.json().get("records", [])]


def guardar(sender, rol, mensaje):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/Conversaciones"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_KEY}",
        "Content-Type": "application/json",
    }
    cuerpo = {"fields": {"sender_id": sender, "rol": rol, "mensaje": mensaje}}
    r = requests.post(url, headers=headers, json=cuerpo, timeout=10)
    if r.status_code not in (200, 201):
        print(">>> AIRTABLE (guardar) error:", r.status_code, r.text)


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
    print(">>> MESSENGER respondio:", r.status_code, r.text)


def avisar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": texto}, timeout=10)


@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
