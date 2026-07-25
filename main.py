"""
FER BOT 3.0
Catálogo dinámico desde Airtable
Gemini + memoria Airtable + fotos + video
Pedidos + Telegram + modo dueño
"""

import os
import re
import json
import traceback
from datetime import datetime, timezone, timedelta

import requests
from fastapi import FastAPI, Request, Response


app = FastAPI()


# ============================================================
# CONFIGURACIÓN
# ============================================================

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "fer123").strip()

PAGE_TOKEN = os.environ["PAGE_TOKEN"].strip()
GEMINI_KEY = os.environ["GEMINI_KEY"].strip()
AIRTABLE_KEY = os.environ["AIRTABLE_KEY"].strip()
AIRTABLE_BASE = os.environ["AIRTABLE_BASE"].strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT", "").strip()

CLAVE_DUENO = os.environ.get(
    "CLAVE_DUENO",
    ""
).strip().lower()

WHATSAPP_DESTINO = os.environ.get(
    "WHATSAPP_DESTINO",
    ""
).strip()

CALLMEBOT_APIKEY = os.environ.get(
    "CALLMEBOT_APIKEY",
    ""
).strip()


TABLA = "Conversaciones"
TABLA_PEDIDOS = "Pedidos"
TABLA_CATALOGO = "Catalogo_Espejo"

GRAPH = "https://graph.facebook.com/v21.0/me/messages"


# ============================================================
# MEMORIA TEMPORAL
# ============================================================

MENSAJES_VISTOS = set()

MODO_DUENO = {}

ULTIMO_PRODUCTO_CONSULTADO = {}

PRODUCTO_ELEGIDO_POR_CLIENTE = {}


PALABRAS_SALIR = [
    "modo vendedor",
    "modo venta",
    "volver a vender",
    "volve a vender",
    "salir del modo",
    "sali del modo",
    "salir modo",
    "volver al modo",
    "regresa",
    "volver a atender",
    "dejar de probar",
]


# ============================================================
# PROMPT VENDEDOR
# ============================================================

SYSTEM_PROMPT = """

Sos Fer, vendedor de verdad de Guaranistore,
una tienda paraguaya.

Sos una PERSONA, no un bot.

Sos natural, cálido, paraguayo y vendedor,
pero nunca presionás ni inventás datos.

SALUDO:

Saludá UNA SOLA VEZ al principio.

Si ya venís conversando, NO vuelvas a saludar
ni a presentarte.

COMO ESCRIBIS:

- Mensajes cortos.
- De 1 a 3 líneas normalmente.
- Voseo paraguayo.
- Una pregunta por vez.
- Pocos emojis.
- Soná natural.
- No escribas como robot.

FOTOS:

Cuando el cliente quiera ver fotos del producto,
agregá exactamente:

[FOTOS]

Si pide más fotos después,
agregá exactamente:

[MASFOTOS]

VIDEO:

Si pide video,
agregá exactamente:

[VIDEO]

PRODUCTOS:

Airtable es la fuente principal de verdad.

Podés vender CUALQUIER producto que exista
en la tabla Catalogo_Espejo.

Nunca digas que solo vendés la depiladora IPL.

Si el cliente menciona un producto,
pregunta por precio,
stock,
disponibilidad,
características,
fotos,
video
o cualquier dato,

usá exactamente:

[CONSULTAR_PRODUCTO: nombre del producto]

No inventes datos.

Si el producto no existe,
usá:

[INTERES] lo que pidió el cliente [/INTERES]

PEDIDOS:

Necesitás:

1. Nombre y apellido
2. Ciudad
3. Teléfono
4. Dirección

Cuando tengas los 4 datos y el cliente CONFIRME,
agregá exactamente:

[PEDIDO] Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]

No inventes precios.
No inventes stock.
No inventes promociones.
No inventes características.
No inventes testimonios.

Tratà bien a la persona.
No presiones.
"""


# ============================================================
# PROMPT DUEÑO
# ============================================================

PROMPT_DUENO = """

Estás hablando con Fernando,
creador y dueño de Guaranistore,
en MODO PRIVADO.

No actúes como vendedor.

Sos su asistente de confianza.

Hablale con naturalidad,
honestidad y de igual a igual.

Vas a recibir datos reales de ventas
y conversaciones recientes.

Podés:

- mostrar reportes;
- resumir ventas;
- mostrar conversaciones;
- auditar charlas;
- señalar errores;
- ayudar a probar el bot.

No inventes números.

No uses [PEDIDO] en este modo.

Podés usar:

[FOTOS]
[MASFOTOS]
[VIDEO]

si Fernando quiere probar material.

"""


# ============================================================
# RUTA PRINCIPAL
# ============================================================

@app.get("/")
def inicio():
    return {
        "status": "online",
        "bot": "FER BOT 3.0"
    }


# ============================================================
# WEBHOOK VERIFICACIÓN
# ============================================================

@app.get("/webhook")
def verificar(request: Request):

    params = request.query_params

    if params.get("hub.verify_token") == VERIFY_TOKEN:

        return Response(
            content=params.get("hub.challenge"),
            media_type="text/plain"
        )

    return Response(
        content="Token incorrecto",
        status_code=403
    )


# ============================================================
# WEBHOOK MENSAJES
# ============================================================

@app.post("/webhook")
async def recibir(request: Request):

    data = await request.json()

    print(
        ">>> ENTRANTE:",
        json.dumps(
            data,
            ensure_ascii=False
        )
    )

    for entry in data.get("entry", []):

        for evento in entry.get("messaging", []):

            sender = evento.get(
                "sender",
                {}
            ).get("id")

            mensaje = evento.get(
                "message",
                {}
            )

            mid = mensaje.get("mid")

            if mid and mid in MENSAJES_VISTOS:

                print(">>> MENSAJE REPETIDO")

                continue

            if mid:

                MENSAJES_VISTOS.add(mid)

                if len(MENSAJES_VISTOS) > 500:

                    MENSAJES_VISTOS.clear()

            if "text" not in mensaje:

                print(">>> EVENTO SIN TEXTO")

                continue

            texto = mensaje["text"]

            print(
                f">>> TEXTO: '{texto}' DE {sender}"
            )

            try:

                responder(
                    sender,
                    texto
                )

            except Exception:

                print(
                    ">>> ERROR EN RESPONDER:"
                )

                print(
                    traceback.format_exc()
                )

    return {
        "status": "ok"
    }


# ============================================================
# RESPONDER
# ============================================================

def responder(sender, texto):

    marcar_leido(sender)

    mostrar_escribiendo(sender)

    t_lower = texto.lower()

    en_modo = MODO_DUENO.get(
        sender,
        False
    )

    tiene_clave = (
        bool(CLAVE_DUENO)
        and CLAVE_DUENO in t_lower
    )


    # ========================================================
    # ENTRAR AL MODO DUEÑO
    # ========================================================

    if not en_modo and tiene_clave:

        MODO_DUENO[sender] = True

        enviar_a_messenger(
            sender,
            "Listo dueño, entré en MODO PRUEBA. "
            "Te hablo como tu asistente, no como vendedor. "
            "Cuando quieras volver a atender clientes, decime: modo vendedor."
        )

        return


    # ========================================================
    # SALIR DEL MODO DUEÑO
    # ========================================================

    if en_modo and any(
        palabra in t_lower
        for palabra in PALABRAS_SALIR
    ):

        MODO_DUENO[sender] = False

        enviar_a_messenger(
            sender,
            "Listo, volví al MODO VENDEDOR. "
            "Ya atiendo normal a los clientes 👍"
        )

        return


    # ========================================================
    # MODO DUEÑO
    # ========================================================

    if en_modo:

        texto_ia = texto

        if tiene_clave:

            texto_ia = re.sub(
                re.escape(CLAVE_DUENO),
                "",
                texto,
                flags=re.IGNORECASE
            ).strip()

        if not texto_ia:

            return

        contexto = (
            resumen_ventas()
            + "\n\n=== CONVERSACIONES RECIENTES ===\n"
            + leer_conversaciones()
        )

        respuesta = preguntar_a_gemini(
            [],
            contexto
            + "\n\nMensaje del dueño:\n"
            + texto_ia,
            PROMPT_DUENO
        )


    # ========================================================
    # MODO VENDEDOR
    # ========================================================

    else:

        historial = leer_historial(sender)

        respuesta = preguntar_a_gemini(
            historial,
            texto,
            SYSTEM_PROMPT
        )

        producto_consultado = (
            extraer_producto_consultado(
                respuesta
            )
        )

        if producto_consultado:

            datos_producto = consultar_producto(
                producto_consultado
            )

            if datos_producto:

                ULTIMO_PRODUCTO_CONSULTADO[
                    sender
                ] = datos_producto

                PRODUCTO_ELEGIDO_POR_CLIENTE[
                    sender
                ] = datos_producto

                respuesta = generar_respuesta_con_producto(
                    historial,
                    texto,
                    datos_producto
                )

            else:

                respuesta = (
                    f"No encontré {producto_consultado} "
                    "en el catálogo actual. "
                    "[INTERES] "
                    + texto
                    + " [/INTERES]"
                )


    print(
        ">>> GEMINI:",
        respuesta
    )


    # ========================================================
    # PEDIDO
    # ========================================================

    if not en_modo:

        respuesta = revisar_pedido(
            sender,
            respuesta
        )

        respuesta = revisar_interes(
            sender,
            respuesta
        )


    # ========================================================
    # FOTOS
    # ========================================================

    respuesta, fotos = revisar_fotos(
        sender,
        respuesta
    )


    # ========================================================
    # VIDEO
    # ========================================================

    respuesta, video = revisar_video(
        sender,
        respuesta
    )


    # ========================================================
    # ENVIAR TEXTO
    # ========================================================

    if respuesta:

        enviar_a_messenger(
            sender,
            respuesta
        )


    # ========================================================
    # ENVIAR FOTOS
    # ========================================================

    for foto in fotos:

        enviar_foto(
            sender,
            foto
        )


    # ========================================================
    # ENVIAR VIDEO
    # ========================================================

    if video:

        enviar_a_messenger(
            sender,
            video
        )


    # ========================================================
    # GUARDAR CONVERSACIÓN
    # ========================================================

    if not en_modo:

        guardar(
            sender,
            "user",
            texto
        )

        guardar(
            sender,
            "model",
            respuesta
            if respuesta
            else
            "(envió material del producto)"
        )


# ============================================================
# GEMINI
# ============================================================

def preguntar_a_gemini(
    historial,
    texto,
    system_prompt
):

    partes = []

    partes.append(
        {
            "text": system_prompt
        }
    )

    for item in historial[-20:]:

        rol = item.get(
            "role",
            "user"
        )

        contenido = item.get(
            "content",
            ""
        )

        prefijo = (
            "Cliente: "
            if rol == "user"
            else
            "Fer: "
        )

        partes.append(
            {
                "text":
                prefijo
                + str(contenido)
            }
        )

    partes.append(
        {
            "text":
            "Mensaje actual:\n"
            + texto
        }
    )


    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/gemini-2.5-flash:generateContent"
        f"?key={GEMINI_KEY}"
    )


    payload = {

        "contents": [

            {
                "parts": partes
            }

        ],

        "generationConfig": {

            "temperature": 0.7,

            "maxOutputTokens": 500

        }

    }


    try:

        r = requests.post(
            url,
            json=payload,
            timeout=45
        )

    except Exception as e:

        print(
            ">>> ERROR CONECTANDO GEMINI:",
            e
        )

        return (
            "Perdón, tuve un pequeño problema "
            "para responderte. "
            "¿Me escribís de nuevo, por favor?"
        )


    if r.status_code != 200:

        print(
            ">>> GEMINI ERROR:",
            r.status_code,
            r.text
        )

        return (
            "Perdón, tuve un pequeño problema "
            "para responderte. "
            "¿Me escribís de nuevo, por favor?"
        )


    data = r.json()


    try:

        return (
            data["candidates"][0]
            ["content"]["parts"][0]
            ["text"]
            .strip()
        )

    except Exception:

        print(
            ">>> RESPUESTA GEMINI INESPERADA:",
            data
        )

        return (
            "Perdón, no pude procesar eso ahora. "
            "¿Me escribís de nuevo, por favor?"
        )


# ============================================================
# PRODUCTOS
# ============================================================

def extraer_producto_consultado(
    respuesta
):

    m = re.search(
        r"\[CONSULTAR_PRODUCTO:\s*(.*?)\]",
        respuesta,
        re.IGNORECASE | re.DOTALL
    )

    if m:

        return m.group(1).strip()

    return None


def consultar_producto(
    producto
):

    datos, error = (
        _encontrar_producto_en_catalogo(
            producto
        )
    )

    if error:

        print(
            ">>> ERROR CONSULTANDO PRODUCTO:",
            error
        )

        return None

    if not datos:

        print(
            ">>> PRODUCTO NO ENCONTRADO:",
            producto
        )

        return None

    print(
        ">>> PRODUCTO ENCONTRADO:",
        _nombre_producto(datos)
    )

    return datos


def generar_respuesta_con_producto(
    historial,
    texto,
    datos
):

    datos_limpios = {}

    for clave, valor in datos.items():

        if valor not in (
            None,
            "",
            [],
            {}
        ):

            datos_limpios[clave] = valor


    contexto_producto = json.dumps(
        datos_limpios,
        ensure_ascii=False,
        indent=2
    )


    instruccion = f"""

El producto consultado EXISTE
en el catálogo de Airtable.

DATOS REALES DEL PRODUCTO:

{contexto_producto}

MENSAJE DEL CLIENTE:

{texto}

Respondé usando únicamente
los datos reales del producto.

REGLAS:

- No inventes precio.
- No inventes stock.
- No inventes características.
- Si pregunta precio, usa el precio real.
- Si pregunta disponibilidad, usa el dato real.
- Si pide fotos, agrega exactamente [FOTOS].
- Si pide más fotos, agrega exactamente [MASFOTOS].
- Si pide video, agrega [VIDEO] solamente si existe una URL de video.
- Respondé corto y natural.
- Usá español paraguayo.

"""


    return preguntar_a_gemini(
        historial,
        instruccion,
        SYSTEM_PROMPT
    )


# ============================================================
# BUSCAR PRODUCTO EN AIRTABLE
# ============================================================

def _normalizar_texto(valor):

    if valor is None:

        return ""

    if isinstance(valor, list):

        return " ".join(
            _normalizar_texto(v)
            for v in valor
        )

    if isinstance(valor, dict):

        return " ".join(
            _normalizar_texto(v)
            for v in valor.values()
        )

    return str(valor).strip()


def _nombre_producto(fields):

    posibles = [

        "producto_id",
        "Producto",
        "producto",
        "Nombre",
        "nombre",
        "name"

    ]

    for campo in posibles:

        valor = fields.get(campo)

        if valor not in (
            None,
            ""
        ):

            return _normalizar_texto(
                valor
            )

    return ""


def _encontrar_producto_en_catalogo(
    producto
):

    url = (
        f"https://api.airtable.com/v0/"
        f"{AIRTABLE_BASE}/"
        f"{TABLA_CATALOGO}"
    )

    headers = {

        "Authorization":
        f"Bearer {AIRTABLE_KEY}"

    }

    registros = []

    offset = None


    for _ in range(10):

        params = {
            "pageSize": 100
        }

        if offset:

            params["offset"] = offset


        r = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=10
        )


        if r.status_code != 200:

            print(
                ">>> AIRTABLE CATALOGO ERROR:",
                r.status_code,
                r.text
            )

            return (
                None,
                "No pude consultar el catálogo."
            )


        data = r.json()


        registros.extend(
            data.get(
                "records",
                []
            )
        )


        offset = data.get(
            "offset"
        )


        if not offset:

            break


    consulta = _normalizar_texto(
        producto
    ).lower()


    consulta = re.sub(
        r"\s+",
        " ",
        consulta
    ).strip()


    # COINCIDENCIA EXACTA

    for registro in registros:

        fields = registro.get(
            "fields",
            {}
        )

        nombre = _nombre_producto(
            fields
        ).lower()


        if nombre == consulta:

            return fields, None


    # COINCIDENCIA PARCIAL

    for registro in registros:

        fields = registro.get(
            "fields",
            {}
        )

        nombre = _nombre_producto(
            fields
        ).lower()


        if (
            consulta in nombre
            or
            nombre in consulta
        ):

            return fields, None


    # COINCIDENCIA POR PALABRAS

    palabras = [

        palabra

        for palabra in re.findall(
            r"[a-záéíóúñ0-9]+",
            consulta,
            flags=re.IGNORECASE
        )

        if len(palabra) >= 3

    ]


    mejor = None

    mejor_puntaje = 0


    for registro in registros:

        fields = registro.get(
            "fields",
            {}
        )

        nombre = _nombre_producto(
            fields
        ).lower()


        palabras_nombre = set(
            re.findall(
                r"[a-záéíóúñ0-9]+",
                nombre,
                flags=re.IGNORECASE
            )
        )


        puntaje = sum(
            1
            for palabra in palabras
            if palabra in palabras_nombre
        )


        if puntaje > mejor_puntaje:

            mejor = fields

            mejor_puntaje = puntaje


    if mejor:

        return mejor, None


    return None, None


# ============================================================
# FOTOS DINÁMICAS
# ============================================================

def obtener_fotos_producto(
    datos,
    cantidad=3,
    desde=0
):

    posibles_campos = [

        "url_foto_1",
        "url_foto_2",
        "url_foto_3",
        "url_foto_4",
        "url_foto_5",
        "url_foto_6",

        "URL_Foto_1",
        "URL_Foto_2",
        "URL_Foto_3",
        "URL_Foto_4",
        "URL_Foto_5",
        "URL_Foto_6",

        "foto_1",
        "foto_2",
        "foto_3",
        "foto_4",
        "foto_5",
        "foto_6",

    ]


    fotos = []


    for campo in posibles_campos:

        url = datos.get(
            campo
        )


        if url:

            url = str(
                url
            ).strip()


            if url.startswith(
                "http"
            ):

                if url not in fotos:

                    fotos.append(
                        url
                    )


    return fotos[
        desde:
        desde + cantidad
    ]


def revisar_fotos(
    sender,
    respuesta
):

    fotos = []

    producto = (
        ULTIMO_PRODUCTO_CONSULTADO.get(
            sender
        )
    )


    if "[FOTOS]" in respuesta:

        if producto:

            fotos += obtener_fotos_producto(
                producto,
                cantidad=3,
                desde=0
            )


    if "[MASFOTOS]" in respuesta:

        if producto:

            fotos += obtener_fotos_producto(
                producto,
                cantidad=3,
                desde=3
            )


    respuesta = (
        respuesta
        .replace(
            "[FOTOS]",
            ""
        )
        .replace(
            "[MASFOTOS]",
            ""
        )
        .strip()
    )


    return respuesta, fotos


# ============================================================
# VIDEO DINÁMICO
# ============================================================

def revisar_video(
    sender,
    respuesta
):

    video = None

    producto = (
        ULTIMO_PRODUCTO_CONSULTADO.get(
            sender
        )
    )


    if "[VIDEO]" in respuesta and producto:

        posibles_campos = [

            "url_video",
            "URL_video",
            "video",
            "Video",
            "url_video_1",
            "URL Video",

        ]


        for campo in posibles_campos:

            url = producto.get(
                campo
            )


            if url:

                url = str(
                    url
                ).strip()


                if url.startswith(
                    "http"
                ):

                    video = url

                    break


    respuesta = (
        respuesta
        .replace(
            "[VIDEO]",
            ""
        )
        .strip()
    )


    return respuesta, video


# ============================================================
# PEDIDOS
# ============================================================

def revisar_pedido(
    sender,
    respuesta
):

    patron = (
        r"\[PEDIDO\](.*?)"
        r"\[/PEDIDO\]"
    )


    m = re.search(
        patron,
        respuesta,
        re.DOTALL
    )


    if m:

        resumen = m.group(
            1
        ).strip()


        texto_pedido = (
            formatear_pedido(
                resumen
            )
        )


        avisar_telegram(
            texto_pedido
        )


        enviar_whatsapp(
            formatear_pedido_whatsapp(
                resumen
            )
        )


        guardar_pedido(
            resumen
        )


        respuesta = re.sub(
            patron,
            "",
            respuesta,
            flags=re.DOTALL
        ).strip()


    return respuesta


def _parsear(
    resumen
):

    datos = {}


    for parte in resumen.split("|"):

        if ":" in parte:

            clave, valor = parte.split(
                ":",
                1
            )


            datos[
                clave.strip().lower()
            ] = valor.strip()


    return datos


def formatear_pedido(
    resumen
):

    d = _parsear(
        resumen
    )


    hora = datetime.now(
        timezone(
            timedelta(
                hours=-3
            )
        )
    ).strftime(
        "%d/%m/%Y %H:%M"
    )


    producto = (
        PRODUCTO_ELEGIDO_POR_CLIENTE.get(
            "ultimo"
        )
    )


    return (

        "🛍️ NUEVO PEDIDO — Guaranístore\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 Nombre: {d.get('nombre', '-')}\n"
        f"📍 Ciudad: {d.get('ciudad', '-')}\n"
        f"📞 Teléfono: {d.get('tel', '-')}\n"
        f"🏠 Dirección: {d.get('direccion', '-')}\n"
        "━━━━━━━━━━━━━━━\n"
        "🛒 Pedido confirmado\n"
        f"🕒 {hora} hs"

    )


def formatear_pedido_whatsapp(
    resumen
):

    d = _parsear(
        resumen
    )


    return (

        "🛍️ NUEVO PEDIDO\n\n"
        f"Nombre: {d.get('nombre', '-')}\n"
        f"Ciudad: {d.get('ciudad', '-')}\n"
        f"Teléfono: {d.get('tel', '-')}\n"
        f"Dirección: {d.get('direccion', '-')}"

    )


def guardar_pedido(
    resumen
):

    d = _parsear(
        resumen
    )


    hora = datetime.now(
        timezone(
            timedelta(
                hours=-3
            )
        )
    ).strftime(
        "%d/%m/%Y %H:%M"
    )


    url = (
        f"https://api.airtable.com/v0/"
        f"{AIRTABLE_BASE}/"
        f"{TABLA_PEDIDOS}"
    )


    headers = {

        "Authorization":
        f"Bearer {AIRTABLE_KEY}",

        "Content-Type":
        "application/json"

    }


    cuerpo = {

        "fields": {

            "Nombre":
            d.get(
                "nombre",
                ""
            ),

            "Ciudad":
            d.get(
                "ciudad",
                ""
            ),

            "Telefono":
            d.get(
                "tel",
                ""
            ),

            "Direccion":
            d.get(
                "direccion",
                ""
            ),

            "Fecha":
            hora,

            "Estado":
            "Nuevo",

        }

    }


    try:

        r = requests.post(
            url,
            headers=headers,
            json=cuerpo,
            timeout=10
        )


        if r.status_code not in (
            200,
            201
        ):

            print(
                ">>> ERROR GUARDANDO PEDIDO:",
                r.status_code,
                r.text
            )

        else:

            print(
                ">>> PEDIDO GUARDADO"
            )


    except Exception as e:

        print(
            ">>> ERROR AIRTABLE PEDIDO:",
            e
        )


# ============================================================
# INTERÉS
# ============================================================

def revisar_interes(
    sender,
    respuesta
):

    patron = (
        r"\[INTERES\](.*?)"
        r"\[/INTERES\]"
    )


    m = re.search(
        patron,
        respuesta,
        re.DOTALL
    )


    if m:

        texto_interes = (
            m.group(
                1
            ).strip()
        )


        avisar_telegram(

            "👀 INTERÉS EN PRODUCTO\n"
            + texto_interes
            + f"\nCliente: {sender}"

        )


        respuesta = re.sub(
            patron,
            "",
            respuesta,
            flags=re.DOTALL
        ).strip()


    return respuesta


# ============================================================
# AIRTABLE — MEMORIA
# ============================================================

def guardar(
    sender,
    role,
    texto
):

    url = (
        f"https://api.airtable.com/v0/"
        f"{AIRTABLE_BASE}/"
        f"{TABLA}"
    )


    headers = {

        "Authorization":
        f"Bearer {AIRTABLE_KEY}",

        "Content-Type":
        "application/json"

    }


    if role == "user":

        mensaje = (
            "[user] "
            + texto
        )

    else:

        mensaje = (
            "[bot] "
            + texto
        )


    cuerpo = {

        "fields": {

            "contact_id":
            str(sender),

            "mensaje_entrante":
            mensaje,

            "Fecha":
            datetime.now(
                timezone(
                    timedelta(
                        hours=-3
                    )
                )
            ).isoformat()

        }

    }


    try:

        r = requests.post(
            url,
            headers=headers,
            json=cuerpo,
            timeout=10
        )


        if r.status_code not in (
            200,
            201
        ):

            print(
                ">>> AIRTABLE GUARDAR ERROR:",
                r.status_code,
                r.text
            )


    except Exception as e:

        print(
            ">>> ERROR GUARDANDO:",
            e
        )


def leer_historial(
    sender,
    limite=20
):

    url = (
        f"https://api.airtable.com/v0/"
        f"{AIRTABLE_BASE}/"
        f"{TABLA}"
    )


    headers = {

        "Authorization":
        f"Bearer {AIRTABLE_KEY}"

    }


    try:

        r = requests.get(
            url,
            headers=headers,
            params={
                "maxRecords": 100
            },
            timeout=10
        )


        if r.status_code != 200:

            return []


        registros = r.json().get(
            "records",
            []
        )


        historial = []


        for registro in registros:

            fields = registro.get(
                "fields",
                {}
            )


            if str(
                fields.get(
                    "contact_id",
                    ""
                )
            ) != str(sender):

                continue


            mensaje = fields.get(
                "mensaje_entrante",
                ""
            )


            if mensaje.startswith(
                "[user] "
            ):

                historial.append(
                    {
                        "role": "user",
                        "content": mensaje[7:]
                    }
                )


            elif mensaje.startswith(
                "[bot] "
            ):

                historial.append(
                    {
                        "role": "model",
                        "content": mensaje[6:]
                    }
                )


        return historial[-limite:]


    except Exception as e:

        print(
            ">>> ERROR LEYENDO HISTORIAL:",
            e
        )

        return []


# ============================================================
# REPORTES
# ============================================================

def resumen_ventas():

    url = (
        f"https://api.airtable.com/v0/"
        f"{AIRTABLE_BASE}/"
        f"{TABLA_PEDIDOS}"
    )


    headers = {

        "Authorization":
        f"Bearer {AIRTABLE_KEY}"

    }


    try:

        r = requests.get(
            url,
            headers=headers,
            params={
                "maxRecords": 100
            },
            timeout=10
        )


        if r.status_code != 200:

            return (
                "No pude leer la tabla Pedidos."
            )


        pedidos = [

            reg.get(
                "fields",
                {}
            )

            for reg in r.json().get(
                "records",
                []
            )

        ]


        hoy = datetime.now(
            timezone(
                timedelta(
                    hours=-3
                )
            )
        ).strftime(
            "%d/%m/%Y"
        )


        total = len(
            pedidos
        )


        de_hoy = sum(

            1

            for p in pedidos

            if str(
                p.get(
                    "Fecha",
                    ""
                )
            ).startswith(
                hoy
            )

        )


        lineas = []


        for p in pedidos[-15:]:

            lineas.append(

                f"- "
                f"{p.get('Nombre', '?')} | "
                f"{p.get('Ciudad', '?')} | "
                f"{p.get('Fecha', '?')} | "
                f"{p.get('Estado', '?')}"

            )


        detalle = (
            "\n".join(
                lineas
            )
            if lineas
            else
            "(todavía no hay pedidos)"
        )


        return (

            "DATOS REALES DE VENTAS:\n"
            f"Total de pedidos: {total}\n"
            f"Pedidos de hoy: {de_hoy}\n"
            f"Últimos pedidos:\n{detalle}"

        )


    except Exception as e:

        print(
            ">>> ERROR VENTAS:",
            e
        )

        return (
            "No pude leer los datos de ventas."
        )


def leer_conversaciones(
    max_registros=100,
    ultimos_contactos=5,
    msgs_por_contacto=14
):

    url = (
        f"https://api.airtable.com/v0/"
        f"{AIRTABLE_BASE}/"
        f"{TABLA}"
    )


    headers = {

        "Authorization":
        f"Bearer {AIRTABLE_KEY}"

    }


    try:

        r = requests.get(
            url,
            headers=headers,
            params={
                "maxRecords":
                max_registros
            },
            timeout=10
        )


        if r.status_code != 200:

            return (
                "No pude leer las conversaciones."
            )


        orden = []

        charlas = {}


        for reg in r.json().get(
            "records",
            []
        ):


            campos = reg.get(
                "fields",
                {}
            )


            cid = campos.get(
                "contact_id",
                "?"
            )


            texto = campos.get(
                "mensaje_entrante",
                ""
            )


            if cid not in charlas:

                charlas[cid] = []

                orden.append(cid)


            if texto.startswith(
                "[bot] "
            ):

                charlas[cid].append(
                    "Fer: "
                    + texto[6:]
                )


            elif texto.startswith(
                "[user] "
            ):

                charlas[cid].append(
                    "Cliente: "
                    + texto[7:]
                )


        bloques = []


        for i, cid in enumerate(
            orden[-ultimos_contactos:],
            1
        ):


            lineas = charlas[cid][
                -msgs_por_contacto:
            ]


            bloques.append(

                f"--- Charla {i} ---\n"
                + "\n".join(lineas)

            )


        return (

            "\n\n".join(
                bloques
            )

            if bloques

            else

            "(todavía no hay conversaciones)"

        )


    except Exception as e:

        print(
            ">>> ERROR CONVERSACIONES:",
            e
        )

        return (
            "No pude leer las conversaciones."
        )


# ============================================================
# FACEBOOK MESSENGER
# ============================================================

def enviar_a_messenger(
    sender,
    texto
):

    url = GRAPH

    params = {

        "access_token":
        PAGE_TOKEN

    }


    payload = {

        "recipient": {

            "id":
            sender

        },

        "message": {

            "text":
            texto

        }

    }


    try:

        r = requests.post(
            url,
            params=params,
            json=payload,
            timeout=15
        )


        print(
            ">>> MESSENGER:",
            r.status_code,
            r.text
        )


    except Exception as e:

        print(
            ">>> ERROR MESSENGER:",
            e
        )


def enviar_foto(
    sender,
    url_foto
):

    payload = {

        "recipient": {

            "id":
            sender

        },

        "message": {

            "attachment": {

                "type":
                "image",

                "payload": {

                    "url":
                    url_foto,

                    "is_reusable":
                    True

                }

            }

        }

    }


    try:

        r = requests.post(
            GRAPH,
            params={
                "access_token":
                PAGE_TOKEN
            },
            json=payload,
            timeout=20
        )


        print(
            ">>> FOTO:",
            r.status_code,
            r.text
        )


    except Exception as e:

        print(
            ">>> ERROR FOTO:",
            e
        )


def marcar_leido(
    sender
):

    payload = {

        "recipient": {

            "id":
            sender

        },

        "sender_action":
        "mark_seen"

    }


    try:

        requests.post(
            GRAPH,
            params={
                "access_token":
                PAGE_TOKEN
            },
            json=payload,
            timeout=10
        )

    except Exception as e:

        print(
            ">>> ERROR MARCAR LEIDO:",
            e
        )


def mostrar_escribiendo(
    sender
):

    payload = {

        "recipient": {

            "id":
            sender

        },

        "sender_action":
        "typing_on"

    }


    try:

        requests.post(
            GRAPH,
            params={
                "access_token":
                PAGE_TOKEN
            },
            json=payload,
            timeout=10
        )

    except Exception as e:

        print(
            ">>> ERROR TYPING:",
            e
        )


# ============================================================
# TELEGRAM
# ============================================================

def avisar_telegram(
    mensaje
):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:

        print(
            ">>> TELEGRAM NO CONFIGURADO"
        )

        return


    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )


    try:

        r = requests.post(
            url,
            json={

                "chat_id":
                TELEGRAM_CHAT,

                "text":
                mensaje

            },
            timeout=10
        )


        print(
            ">>> TELEGRAM:",
            r.status_code,
            r.text
        )


    except Exception as e:

        print(
            ">>> ERROR TELEGRAM:",
            e
        )


# ============================================================
# WHATSAPP OPCIONAL
# ============================================================

def enviar_whatsapp(
    mensaje
):

    if not WHATSAPP_DESTINO:

        return

    if not CALLMEBOT_APIKEY:

        return


    url = (
        "https://api.callmebot.com/"
        "whatsapp.php"
    )


    params = {

        "phone":
        WHATSAPP_DESTINO,

        "text":
        mensaje,

        "apikey":
        CALLMEBOT_APIKEY

    }


    try:

        requests.get(
            url,
            params=params,
            timeout=15
        )


    except Exception as e:

        print(
            ">>> ERROR WHATSAPP:",
            e
        )