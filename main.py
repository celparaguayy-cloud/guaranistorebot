"""
FER BOT 2.0 — vendedor completo para Messenger
IA (Gemini) + memoria (Airtable) + fotos + video + aviso de pedidos a Telegram
+ "escribiendo..." + anti-duplicados + MODO DUENO (palabra secreta para testear).
"""

import os
import re
import json
import traceback
from datetime import datetime, timezone, timedelta
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

# Palabra secreta del dueno (se carga en Render, NO se escribe aca)
CLAVE_DUENO    = os.environ.get("CLAVE_DUENO", "").strip().lower()

TABLA = "Conversaciones"
GRAPH = "https://graph.facebook.com/v21.0/me/messages"

BASE_FOTOS = "https://raw.githubusercontent.com/celparaguayy-cloud/guaranistorebot/main/"
FOTOS_PRINCIPALES = ["ipl1.jpg", "ipl2.jpg", "ipl3.jpg"]
FOTOS_EXTRA       = ["ipl4.jpg", "ipl5.jpg", "ipl6.jpg"]
VIDEO_URL = "https://youtube.com/shorts/0WoRz-Nzucw"

MENSAJES_VISTOS = set()

# Estado del modo dueno por cada persona (se guarda mientras el bot esta despierto)
MODO_DUENO = {}
PALABRAS_SALIR = ["modo vendedor", "modo venta", "volver a vender", "volve a vender",
                  "salir del modo", "sali del modo", "salir modo", "volver al modo",
                  "regresa", "volve", "volver a atender", "dejar de probar"]

SYSTEM_PROMPT = """
Sos Fer, vendedor de verdad de Guaranistore, una tienda paraguaya. Sos una PERSONA, no un bot: con caracter, historia y corazon. Nadie deberia sospechar que del otro lado hay un sistema. Antes que vendedor, sos gente. Tu norte: acompanar a la persona hasta que se lleve su Depiladora IPL, tratandola tan bien que quiera comprarte a VOS.

SALUDO (IMPORTANTE): saluda UNA SOLA VEZ, al principio. Si ya venis conversando, NO vuelvas a saludar ni a presentarte: continua la charla. NO uses "mba'eichapa" ni saludo guarani en cada mensaje; como mucho uno al principio. Varia los saludos.

QUIEN SOS: 30 y pico, paraguayo, hace anos que vendes. Respetas la plata del que te escribe. Calido, con picardia justa, serio con lo importante. Nunca prometes lo que no podes cumplir. Lees a la persona y actuas en consecuencia.

TU AMABILIDAD (tu sello): "por favor" y "gracias" de verdad. Trata con carino ("quedate tranquila", "con todo gusto"). Haz sentir importante a la persona. Despedite con calidez aunque no compre. Amable no es zalamero: nada de "mi amor/mi reina". Educacion paraguaya genuina.

TU CORAZON (empatia): si te cuentan algo personal ("es para mi hija enferma", "no me alcanza"), PARA la venta y responde como humano. NUNCA uses el dolor o la necesidad ajena para vender. Si no le alcanza, jamas la hagas sentir mal. La dignidad del otro vale mas que una venta.

COMO ESCRIBIS: mensajes CORTOS (1 a 3 lineas). Voseo paraguayo. Guarani muy de vez en cuando. UNA pregunta por vez. Espeja el tono del cliente.

EMOJIS: pocos pero expresivos en momentos clave (saludo, cierre, agradecer): 🎉🙌😍👍🇵🇾. Nunca una fila de emojis.

FOTOS DEL PRODUCTO: cuando el cliente quiera ver el producto ("tenes foto?", "mostrame", "como es?"), agrega [FOTOS]: el codigo enviara 3 fotos reales y borrara la etiqueta. Si pide ver MAS, agrega [MASFOTOS] (3 fotos mas). Acompana con texto corto y calido ("Mira, te paso unas fotos 👇"). No repitas [FOTOS] si ya las mandaste, salvo que pida de nuevo.

VIDEO DEL PRODUCTO: si pide un video ("tenes video?", "en video", "mostrame funcionando"), agrega [VIDEO]: el codigo enviara el link de YouTube. Acompana con texto corto ("Te paso un video asi lo ves funcionando 👇").

MENSAJES CORTOS: "precio"/"cuanto?" -> precio AL TOQUE y una pregunta. "hola" -> saluda y pregunta en que ayudas.

EL PRODUCTO: Depiladora IPL de Luz Pulsada (Black Word). Definitiva, en casa, indolora, todo el cuerpo. Misma tecnologia IPL de los centros de estetica. Kit: gafas, afeitadora, manual y caja. Precio: Gs. 280.000. Garantia: 5 dias. Entrega: 1 a 3 dias. Pago CONTRA ENTREGA en 24 ciudades. EXCEPCION: Minga Pora, Curuguaty, Katuete y Salto del Guaira solo con transferencia anticipada.

TU GANCHO: el ahorro. La gente gasta todos los meses en depilarse; la IPL es UN solo pago y en pocos meses se pago sola. Deslizalo con ejemplos reales.

FLUJO: 1) Saludas UNA vez. 2) Escuchas para que/para quien. 3) Muestras valor + ahorro (y fotos/video si sirve). 4) Precio al toque si lo piden. 5) Resolves dudas. 6) Cerras tomando los datos cuando hay interes.

CIERRE (los datos): necesitas SIEMPRE 4 datos, pedidos como charla, de a uno o dos, con "por favor": 1) Nombre y apellido, 2) Ciudad, 3) Telefono, 4) Direccion. Con los 4, confirma con resumen calido y agradece.

>>> AVISO DE PEDIDO: cuando tengas los 4 datos Y el cliente CONFIRME, al FINAL agrega EXACTAMENTE (con las barras |):
[PEDIDO] Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]
Solo cuando el pedido esta cerrado. El cliente no la vera.

HORARIOS: atendes a cualquier hora, sin hacerlo notar.

CURIOSOS Y GROSEROS: pavadas -> humor amable y volves al tema. Insultos -> no te enganches. "Sos un robot?" -> "jaja soy Fer, en que te ayudo?" y segui.

OBJECIONES: "Funciona?" -> si, IPL con garantia. "Es caro" -> un solo pago, contra entrega, y si no es el momento cuando puedas. "Y si no sirve?" -> 5 dias de garantia. "Lo pienso" -> dale, sin insistir. "Duele?" -> no, apenas un calorcito.

REGLAS: nunca inventes precios ni datos. Nunca uses el dolor de alguien para vender. No presiones. Amable sin zalameria. No hables de otros productos salvo que pregunten. Nunca digas que sos un bot: sos Fer.
"""

# Prompt para cuando habla el DUENO (Fernando), en modo prueba
PROMPT_DUENO = """
Estas hablando con Fernando, tu creador y dueno de Guaranistore, en MODO PRIVADO DE PRUEBAS. NO actues como vendedor y no le vendas nada. Sos su asistente de confianza: hablale con naturalidad, honestidad y de igual a igual. Ayudalo a probar el bot, respondele lo que pregunte sobre como funciona, y segui sus instrucciones de prueba. Se breve y claro. Si te pide probar el material, podes usar [FOTOS], [MASFOTOS] o [VIDEO] para que te los mande. NUNCA uses la etiqueta [PEDIDO] en este modo. Podes tutear o vosear con confianza, como a un amigo y jefe.
"""


# ================= WEBHOOK =================
@app.get("/webhook")
def verificar(request: Request):
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    return Response(content="Token incorrecto", status_code=403)


@app.post("/webhook")
async def recibir(request: Request):
    data = await request.json()
    print(">>> ENTRANTE:", json.dumps(data, ensure_ascii=False))
    for entry in data.get("entry", []):
        for evento in entry.get("messaging", []):
            sender = evento.get("sender", {}).get("id")
            mensaje = evento.get("message", {})
            mid = mensaje.get("mid")
            if mid and mid in MENSAJES_VISTOS:
                print(">>> Repetido, lo ignoro")
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


# ================= LOGICA =================
def responder(sender, texto):
    marcar_leido(sender)
    mostrar_escribiendo(sender)

    t_lower = texto.lower()
    en_modo = MODO_DUENO.get(sender, False)
    tiene_clave = bool(CLAVE_DUENO) and CLAVE_DUENO in t_lower

    # --- ENTRAR al modo dueno (palabra secreta en cualquier parte) ---
    if not en_modo and tiene_clave:
        MODO_DUENO[sender] = True
        en_modo = True
        enviar_a_messenger(sender,
            "🛠️ Listo dueno, entre en MODO PRUEBA. Te hablo como tu asistente, "
            "no como vendedor. Cuando quieras que vuelva a atender clientes, "
            "decime: modo vendedor.")

    # --- SALIR del modo dueno ---
    elif en_modo and any(p in t_lower for p in PALABRAS_SALIR):
        MODO_DUENO[sender] = False
        enviar_a_messenger(sender,
            "🛍️ Listo, volvi al MODO VENDEDOR. Ya atiendo normal a los clientes 👍")
        return

    # --- Preparar el texto para la IA ---
    if en_modo:
        # sacamos la palabra secreta si vino en el mensaje
        if tiene_clave:
            texto_ia = re.sub(re.escape(CLAVE_DUENO), "", texto, flags=re.IGNORECASE).strip()
        else:
            texto_ia = texto.strip()
        if not texto_ia:
            return  # solo activo el modo, sin instruccion extra
        respuesta = preguntar_a_gemini([], texto_ia, PROMPT_DUENO)
    else:
        historial = leer_historial(sender)
        respuesta = preguntar_a_gemini(historial, texto, SYSTEM_PROMPT)

    print(f">>> GEMINI ({'dueno' if en_modo else 'vendedor'}): '{respuesta}'")

    if not en_modo:
        respuesta = revisar_pedido(sender, respuesta)   # Telegram + saca [PEDIDO]
    respuesta, fotos = revisar_fotos(respuesta)          # saca [FOTOS]/[MASFOTOS]
    respuesta, video = revisar_video(respuesta)          # saca [VIDEO]

    if respuesta:
        enviar_a_messenger(sender, respuesta)
    for url in fotos:
        enviar_foto(sender, url)
    if video:
        enviar_a_messenger(sender, video)

    # En modo dueno no guardamos, asi no ensucia la memoria de clientes
    if not en_modo:
        guardar(sender, "user", texto)
        guardar(sender, "model", respuesta if respuesta else "(envie material del producto)")


# ---- [PEDIDO]: aviso elegante a Telegram + borra la etiqueta
def revisar_pedido(sender, respuesta):
    m = re.search(r"\[PEDIDO\](.*?)\[/PEDIDO\]", respuesta, re.DOTALL)
    if m:
        avisar_telegram(formatear_pedido(m.group(1).strip()))
        respuesta = re.sub(r"\[PEDIDO\].*?\[/PEDIDO\]", "", respuesta, flags=re.DOTALL).strip()
    return respuesta


def formatear_pedido(resumen):
    datos = {}
    for parte in resumen.split("|"):
        if ":" in parte:
            clave, valor = parte.split(":", 1)
            datos[clave.strip().lower()] = valor.strip()
    hora = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    return (
        "🛍️  NUEVO PEDIDO — Guaranístore\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤  Nombre:     {datos.get('nombre', '-')}\n"
        f"📍  Ciudad:     {datos.get('ciudad', '-')}\n"
        f"📞  Teléfono:   {datos.get('tel', '-')}\n"
        f"🏠  Dirección:  {datos.get('direccion', '-')}\n"
        "━━━━━━━━━━━━━━━\n"
        "💜  Producto:   Depiladora IPL\n"
        "💰  Total:      Gs. 280.000 (contra entrega)\n"
        f"🕒  {hora} hs"
    )


def revisar_fotos(respuesta):
    fotos = []
    if "[FOTOS]" in respuesta:
        fotos += [BASE_FOTOS + f for f in FOTOS_PRINCIPALES]
    if "[MASFOTOS]" in respuesta:
        fotos += [BASE_FOTOS + f for f in FOTOS_EXTRA]
    respuesta = respuesta.replace("[FOTOS]", "").replace("[MASFOTOS]", "").strip()
    return respuesta, fotos


def revisar_video(respuesta):
    video = None
    if "[VIDEO]" in respuesta:
        video = VIDEO_URL
        respuesta = respuesta.replace("[VIDEO]", "").strip()
    return respuesta, video


# ================= MEMORIA (Airtable) =================
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


# ================= CEREBRO (Gemini) =================
def preguntar_a_gemini(historial, texto_nuevo, prompt=SYSTEM_PROMPT):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-flash-latest:generateContent?key={GEMINI_KEY}"
    )
    contenidos = []
    for m in historial:
        contenidos.append({"role": m["rol"], "parts": [{"text": m["mensaje"]}]})
    contenidos.append({"role": "user", "parts": [{"text": texto_nuevo}]})
    cuerpo = {
        "system_instruction": {"parts": [{"text": prompt}]},
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


# ================= MESSENGER =================
def enviar_a_messenger(sender, texto):
    for pedazo in partir(texto, 1900):
        cuerpo = {
            "recipient": {"id": sender},
            "messaging_type": "RESPONSE",
            "message": {"text": pedazo},
        }
        r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN}, json=cuerpo, timeout=10)
        print(">>> MESSENGER:", r.status_code, r.text)


def enviar_foto(sender, url_foto):
    cuerpo = {
        "recipient": {"id": sender},
        "message": {"attachment": {"type": "image",
                                   "payload": {"url": url_foto, "is_reusable": True}}},
    }
    r = requests.post(GRAPH, params={"access_token": PAGE_TOKEN}, json=cuerpo, timeout=15)
    print(">>> FOTO:", r.status_code, r.text)


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


def marcar_leido(sender):
    try:
        requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                      json={"recipient": {"id": sender}, "sender_action": "mark_seen"}, timeout=8)
    except Exception:
        pass


def mostrar_escribiendo(sender):
    try:
        requests.post(GRAPH, params={"access_token": PAGE_TOKEN},
                      json={"recipient": {"id": sender}, "sender_action": "typing_on"}, timeout=8)
    except Exception:
        pass


# ================= TELEGRAM =================
def avisar_telegram(texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": texto}, timeout=10)
    print(">>> TELEGRAM:", r.status_code, r.text)


@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
