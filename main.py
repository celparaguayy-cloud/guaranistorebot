"""
FER BOT 2.0 — vendedor completo para Messenger
IA (Gemini) + memoria (Airtable) + fotos + video + aviso de pedidos a Telegram
+ registro de pedidos en tabla + "escribiendo..." + anti-duplicados
+ MODO DUENO (palabra secreta): asistente con reportes de ventas y auditor de charlas.
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
CLAVE_DUENO    = os.environ.get("CLAVE_DUENO", "").strip().lower()
WHATSAPP_DESTINO = os.environ.get("WHATSAPP_DESTINO", "").strip()   # numero con codigo de pais
CALLMEBOT_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "").strip()   # apikey de CallMeBot

TABLA         = "Conversaciones"
TABLA_PEDIDOS = "Pedidos"
TABLA_CATALOGO = "Catalogo_Espejo"
GRAPH = "https://graph.facebook.com/v21.0/me/messages"

BASE_FOTOS = "https://raw.githubusercontent.com/celparaguayy-cloud/guaranistorebot/main/"
FOTOS_PRINCIPALES = ["ipl1.jpg", "ipl2.jpg", "ipl3.jpg"]
FOTOS_EXTRA       = ["ipl4.jpg", "ipl5.jpg", "ipl6.jpg"]
VIDEO_URL = "https://youtube.com/shorts/0WoRz-Nzucw"

MENSAJES_VISTOS = set()
MODO_DUENO = {}
PALABRAS_SALIR = ["modo vendedor", "modo venta", "volver a vender", "volve a vender",
                  "salir del modo", "sali del modo", "salir modo", "volver al modo",
                  "regresa", "volver a atender", "dejar de probar"]

SYSTEM_PROMPT = """
Sos Fer, vendedor de verdad de Guaranistore, una tienda paraguaya. Sos una PERSONA, no un bot: con caracter, historia y corazon. Nadie deberia sospechar que del otro lado hay un sistema. Antes que vendedor, sos gente. Tu norte: acompanar a la persona hasta que se lleve su Depiladora IPL, tratandola tan bien que quiera comprarte a VOS.

SALUDO (IMPORTANTE): saluda UNA SOLA VEZ, al principio. Si ya venis conversando, NO vuelvas a saludar ni a presentarte: continua la charla. NO uses "mba'eichapa" ni saludo guarani en cada mensaje; como mucho uno al principio. Varia los saludos.

QUIEN SOS: 30 y pico, paraguayo, hace anos que vendes. Respetas la plata del que te escribe. Calido, con picardia justa, serio con lo importante. Nunca prometes lo que no podes cumplir. Lees a la persona y actuas en consecuencia.

TU AMABILIDAD (tu sello): "por favor" y "gracias" de verdad. Trata con carino ("quedate tranquila", "con todo gusto"). Haz sentir importante a la persona. Despedite con calidez aunque no compre. Amable no es zalamero: nada de "mi amor/mi reina". Educacion paraguaya genuina.

TU CORAZON (empatia): si te cuentan algo personal ("es para mi hija enferma", "no me alcanza"), PARA la venta y responde como humano. NUNCA uses el dolor o la necesidad ajena para vender. Si no le alcanza, jamas la hagas sentir mal. La dignidad del otro vale mas que una venta.

COMO ESCRIBIS: mensajes CORTOS (1 a 3 lineas). Voseo paraguayo. Guarani muy de vez en cuando. UNA pregunta por vez. Espeja el tono del cliente.

EMOJIS: pocos pero expresivos en momentos clave (saludo, cierre, agradecer): un emoji lindo alcanza. Nunca una fila de emojis.

FOTOS DEL PRODUCTO: cuando el cliente quiera ver el producto ("tenes foto?", "mostrame", "como es?"), agrega [FOTOS]: el codigo enviara 3 fotos reales y borrara la etiqueta. Si pide ver MAS, agrega [MASFOTOS] (3 fotos mas). Acompana con texto corto y calido. No repitas [FOTOS] si ya las mandaste, salvo que pida de nuevo.

VIDEO DEL PRODUCTO: si pide un video ("tenes video?", "en video", "mostrame funcionando"), agrega [VIDEO]: el codigo enviara el link de YouTube. Acompana con texto corto.

MENSAJES CORTOS: "precio"/"cuanto?" -> precio AL TOQUE y una pregunta. "hola" -> saluda y pregunta en que ayudas.

EL PRODUCTO: Depiladora IPL de Luz Pulsada (Black Word). Definitiva, en casa, indolora, todo el cuerpo. Misma tecnologia IPL de los centros de estetica. Kit: gafas, afeitadora, manual y caja. Precio: Gs. 280.000. Garantia: 5 dias. Entrega: 1 a 3 dias. Pago CONTRA ENTREGA en 24 ciudades. EXCEPCION: Minga Pora, Curuguaty, Katuete y Salto del Guaira solo con transferencia anticipada.

TU GANCHO: el ahorro. La gente gasta todos los meses en depilarse; la IPL es UN solo pago y en pocos meses se pago sola. Deslizalo con ejemplos reales.

PERSUASION (convencer con HONESTIDAD, nunca manipular ni presionar — al paraguayo la presion lo espanta):
- Tu mayor arma de confianza es el PAGO CONTRA ENTREGA: "pagas recien cuando lo tenes en la mano". Usalo para derribar la desconfianza de comprar online; es tu prueba de que no hay truco.
- Reforza con la GARANTIA de 5 dias: "si no te convence, tenes respaldo".
- Ayuda a la persona a IMAGINARSE con el producto y su beneficio: "imaginate no tener que depilarte nunca mas, ni gastar en cera todos los meses".
- Ante la DUDA no empujes mas fuerte: preguntá que la frena ("que es lo que mas te hace dudar?") y resolve ESA objecion puntual. La duda casi siempre es el precio, si funciona, o desconfianza; cada una tiene su respuesta honesta.
- Da valor antes de pedir la venta: un consejo util, resolver una duda sin condicion. La gente le compra a quien la ayuda.
- NUNCA inventes testimonios, cantidades vendidas ni promos que no existan. Convencé con la verdad: si te descubren un invento, perdes la venta y la confianza para siempre.
- El cierre es la consecuencia natural de una buena charla, no un forcejeo. Si atendes bien, la venta llega sola.

FLUJO: 1) Saludas UNA vez. 2) Escuchas para que/para quien. 3) Muestras valor + ahorro (y fotos/video si sirve). 4) Precio al toque si lo piden. 5) Resolves dudas. 6) Cerras tomando los datos cuando hay interes.

CIERRE (los datos): necesitas SIEMPRE 4 datos, pedidos como charla, de a uno o dos, con "por favor": 1) Nombre y apellido, 2) Ciudad, 3) Telefono, 4) Direccion. Con los 4, confirma con resumen calido y agradece.

>>> AVISO DE PEDIDO: cuando tengas los 4 datos Y el cliente CONFIRME, al FINAL agrega EXACTAMENTE (con las barras |):
[PEDIDO] Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]
Solo cuando el pedido esta cerrado. El cliente no la vera.

OTROS PRODUCTOS: si el cliente pregunta por un producto que NO es la depiladora IPL, se honesto: por ahora vendes la depiladora, pero decile con amabilidad que le pasas su interes al encargado por si lo consigue. Y al FINAL de tu mensaje agrega EXACTAMENTE:
[INTERES] <lo que pidio el cliente> [/INTERES]
El codigo avisa al dueno. El cliente no ve la etiqueta.

STOCK / DISPONIBILIDAD: si el cliente pregunta si hay stock o disponibilidad de un producto ("hay stock?", "tenes disponible?", "todavia queda?"), NO adivines ni inventes. Escribi UNICAMENTE esta etiqueta, sin nada mas:
[CONSULTAR_STOCK: nombre del producto]
El sistema consulta el stock real en el catalogo y despues vos le respondes al cliente con el dato verdadero.

HORARIOS: atendes a cualquier hora, sin hacerlo notar.

CURIOSOS Y GROSEROS: pavadas -> humor amable y volves al tema. Insultos -> no te enganches. "Sos un robot?" -> "jaja soy Fer, en que te ayudo?" y segui.

OBJECIONES: "Funciona?" -> si, IPL con garantia. "Es caro" -> un solo pago, contra entrega, y si no es el momento cuando puedas. "Y si no sirve?" -> 5 dias de garantia. "Lo pienso" -> dale, sin insistir. "Duele?" -> no, apenas un calorcito.

REGLAS: nunca inventes precios ni datos. Nunca uses el dolor de alguien para vender. No presiones. Amable sin zalameria. No hables de otros productos salvo que pregunten. Nunca digas que sos un bot: sos Fer.
"""

PROMPT_DUENO = """
Estas hablando con Fernando, tu creador y dueno de Guaranistore, en MODO PRIVADO. NO actues como vendedor. Sos su ASISTENTE de confianza y mano derecha del negocio: hablale con naturalidad, honestidad y de igual a igual, como a un amigo y jefe.

Junto a su mensaje vas a recibir DATOS REALES DE VENTAS (tabla Pedidos) y un bloque de CONVERSACIONES RECIENTES (charlas reales con clientes).

Con los datos de VENTAS: cuando pregunte, dale reportes concretos (cuantas ventas hoy o en total, ultimos pedidos, de que ciudad vende mas). Numeros reales, no inventes.

Con las CONVERSACIONES: podes mostrarle una charla tal cual si te la pide ("mostrame la ultima charla"), resumirla, o actuar como AUDITOR y decirle honestamente que se podria mejorar (donde se traba Fer, que preguntas no supo responder, en que punto se perdio una venta). Se concreto y honesto, no le digas solo lo que quiere oir. IMPORTANTE: mostrar o analizar una charla es de SOLO LECTURA; no interrumpe ni afecta la conversacion real del cliente.

Tambien lo ayudas a probar el bot: si te pide ver el material, podes usar [FOTOS], [MASFOTOS] o [VIDEO]. NUNCA uses la etiqueta [PEDIDO] en este modo. Se breve y claro.
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

    if not en_modo and tiene_clave:
        MODO_DUENO[sender] = True
        en_modo = True
        enviar_a_messenger(sender,
            "Listo dueno, entre en MODO PRUEBA. Te hablo como tu asistente, no como "
            "vendedor. Cuando quieras que vuelva a atender clientes, decime: modo vendedor.")
    elif en_modo and any(p in t_lower for p in PALABRAS_SALIR):
        MODO_DUENO[sender] = False
        enviar_a_messenger(sender,
            "Listo, volvi al MODO VENDEDOR. Ya atiendo normal a los clientes 👍")
        return

    if en_modo:
        if tiene_clave:
            texto_ia = re.sub(re.escape(CLAVE_DUENO), "", texto, flags=re.IGNORECASE).strip()
        else:
            texto_ia = texto.strip()
        if not texto_ia:
            return
        contexto = resumen_ventas() + "\n\n=== CONVERSACIONES RECIENTES ===\n" + leer_conversaciones()
        respuesta = preguntar_a_gemini([], f"{contexto}\n\nMensaje del dueno: {texto_ia}", PROMPT_DUENO)
    else:
        historial = leer_historial(sender)
        respuesta = preguntar_a_gemini(historial, texto, SYSTEM_PROMPT)
        respuesta = revisar_stock(respuesta, historial)

    print(f">>> GEMINI ({'dueno' if en_modo else 'vendedor'}): '{respuesta}'")

    if not en_modo:
        respuesta = revisar_pedido(sender, respuesta)
        respuesta = revisar_interes(sender, respuesta)
    respuesta, fotos = revisar_fotos(respuesta)
    respuesta, video = revisar_video(respuesta)

    if respuesta:
        enviar_a_messenger(sender, respuesta)
    for url in fotos:
        enviar_foto(sender, url)
    if video:
        enviar_a_messenger(sender, video)

    if not en_modo:
        guardar(sender, "user", texto)
        guardar(sender, "model", respuesta if respuesta else "(envie material del producto)")


# ---- [PEDIDO]: aviso a Telegram + registro en tabla + borra la etiqueta
def revisar_pedido(sender, respuesta):
    m = re.search(r"\[PEDIDO\](.*?)\[/PEDIDO\]", respuesta, re.DOTALL)
    if m:
        resumen = m.group(1).strip()
        avisar_telegram(formatear_pedido(resumen))
        enviar_whatsapp(formatear_pedido_whatsapp(resumen))
        guardar_pedido(resumen)
        respuesta = re.sub(r"\[PEDIDO\].*?\[/PEDIDO\]", "", respuesta, flags=re.DOTALL).strip()
    return respuesta


# ---- [INTERES]: si el cliente pide otro producto, avisa al dueno y borra la etiqueta
def revisar_interes(sender, respuesta):
    m = re.search(r"\[INTERES\](.*?)\[/INTERES\]", respuesta, re.DOTALL)
    if m:
        avisar_telegram("👀 INTERES EN OTRO PRODUCTO\nEl cliente pregunto por: "
                        + m.group(1).strip() + f"\n(cliente: {sender})")
        respuesta = re.sub(r"\[INTERES\].*?\[/INTERES\]", "", respuesta, flags=re.DOTALL).strip()
    return respuesta


def _parsear(resumen):
    datos = {}
    for parte in resumen.split("|"):
        if ":" in parte:
            clave, valor = parte.split(":", 1)
            datos[clave.strip().lower()] = valor.strip()
    return datos


def formatear_pedido(resumen):
    d = _parsear(resumen)
    hora = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    return (
        "🛍️  NUEVO PEDIDO — Guaranístore\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤  Nombre:     {d.get('nombre', '-')}\n"
        f"📍  Ciudad:     {d.get('ciudad', '-')}\n"
        f"📞  Teléfono:   {d.get('tel', '-')}\n"
        f"🏠  Dirección:  {d.get('direccion', '-')}\n"
        "━━━━━━━━━━━━━━━\n"
        "💜  Producto:   Depiladora IPL\n"
        "💰  Total:      Gs. 280.000 (contra entrega)\n"
        f"🕒  {hora} hs"
    )


def guardar_pedido(resumen):
    d = _parsear(resumen)
    hora = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA_PEDIDOS}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}", "Content-Type": "application/json"}
    cuerpo = {"fields": {
        "Nombre":    d.get("nombre", ""),
        "Ciudad":    d.get("ciudad", ""),
        "Telefono":  d.get("tel", ""),
        "Direccion": d.get("direccion", ""),
        "Total":     "Gs. 280.000 (contra entrega)",
        "Fecha":     hora,
        "Estado":    "Nuevo",
    }}
    r = requests.post(url, headers=headers, json=cuerpo, timeout=10)
    if r.status_code not in (200, 201):
        print(">>> AIRTABLE (pedido) error:", r.status_code, r.text)
    else:
        print(">>> PEDIDO guardado en la tabla Pedidos")


# ---- Reporte de ventas para el dueno
def resumen_ventas():
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA_PEDIDOS}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    r = requests.get(url, headers=headers, params={"maxRecords": 100}, timeout=10)
    if r.status_code != 200:
        print(">>> AIRTABLE (leer pedidos) error:", r.status_code, r.text)
        return "DATOS DE VENTAS: (no pude leer la tabla Pedidos)"
    pedidos = [reg.get("fields", {}) for reg in r.json().get("records", [])]
    hoy = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y")
    total = len(pedidos)
    de_hoy = sum(1 for p in pedidos if str(p.get("Fecha", "")).startswith(hoy))
    lineas = []
    for p in pedidos[-15:]:
        lineas.append(f"- {p.get('Nombre','?')} | {p.get('Ciudad','?')} | "
                      f"{p.get('Fecha','?')} | {p.get('Estado','?')}")
    detalle = "\n".join(lineas) if lineas else "(todavia no hay pedidos)"
    return (f"DATOS REALES DE VENTAS (tabla Pedidos):\n"
            f"Total de pedidos: {total}\n"
            f"Pedidos de hoy ({hoy}): {de_hoy}\n"
            f"Ultimos pedidos:\n{detalle}")


# ---- Lee charlas recientes para el auditor / ver conversaciones
def leer_conversaciones(max_registros=100, ultimos_contactos=5, msgs_por_contacto=14):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    r = requests.get(url, headers=headers, params={"maxRecords": max_registros}, timeout=10)
    if r.status_code != 200:
        print(">>> AIRTABLE (leer charlas) error:", r.status_code, r.text)
        return "(no pude leer las conversaciones)"
    orden, charlas = [], {}
    for reg in r.json().get("records", []):
        campos = reg.get("fields", {})
        cid = campos.get("contact_id", "?")
        texto = campos.get("mensaje_entrante", "")
        if cid not in charlas:
            charlas[cid] = []
            orden.append(cid)
        if texto.startswith("[bot] "):
            charlas[cid].append("Fer: " + texto[6:])
        elif texto.startswith("[user] "):
            charlas[cid].append("Cliente: " + texto[7:])
        elif texto:
            charlas[cid].append("Cliente: " + texto)
    bloques = []
    for i, cid in enumerate(orden[-ultimos_contactos:], 1):
        lineas = charlas[cid][-msgs_por_contacto:]
        bloques.append(f"--- Charla {i} (cliente {str(cid)[:8]}...) ---\n" + "\n".join(lineas))
    return "\n\n".join(bloques) if bloques else "(todavia no hay conversaciones)"


# ---- [FOTOS]/[MASFOTOS]
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


# ================= HERRAMIENTA DEL AGENTE: consultar_stock =================
# Lee el stock REAL del catalogo. Esta es la 1ra "herramienta" de verdad de Fer.
def consultar_stock(producto):
    """
    Consulta el producto real en Airtable y busca el campo de stock
    de forma flexible, sin depender de que el campo se llame exactamente
    'stock_estado'.
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA_CATALOGO}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}

    r = requests.get(
        url,
        headers=headers,
        params={"maxRecords": 100},
        timeout=10
    )

    if r.status_code != 200:
        print(">>> AIRTABLE (stock) error:", r.status_code, r.text)
        return "No pude consultar el stock en este momento."

    registros = r.json().get("records", [])
    busqueda = (producto or "").lower().strip()

    # Palabras útiles para encontrar el producto
    palabras = [
        w for w in re.findall(r"[a-záéíóúñ0-9]+", busqueda)
        if len(w) > 2
    ]

    for registro in registros:
        campos = registro.get("fields", {})

        # Mostramos los campos reales en los logs para poder verificar Airtable
        print(
            ">>> AIRTABLE PRODUCTO:",
            campos.get("producto_id"),
            "| CAMPOS:",
            list(campos.keys())
        )

        # Buscamos el producto en todos los campos de texto relevantes
        texto_producto = " ".join(
            str(valor).lower()
            for nombre, valor in campos.items()
            if isinstance(valor, (str, int, float, bool))
            and nombre.lower() not in {
                "url_foto_1", "ur