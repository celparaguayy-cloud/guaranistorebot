"""
FER BOT 3.0
Catálogo dinámico desde Airtable
Gemini + memoria + fotos + video
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

GRAPH = (
    "https://graph.facebook.com/"
    "v21.0/me/messages"
)


# ============================================================
# VARIABLES GLOBALES
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

Sos una persona natural, cálida y paraguaya.

No digas que sos un bot.

Respondé corto, normalmente de 1 a 3 líneas.

Usá voseo paraguayo.

Una pregunta por vez.

No inventes información.

No inventes precios.

No inventes stock.

No inventes características.

No inventes promociones.

SALUDO:

Saludá una sola vez al principio.

Si ya venís conversando, no vuelvas a saludar.

PRODUCTOS:

Airtable es la fuente principal de verdad.

Podés vender cualquier producto que exista
en la tabla Catalogo_Espejo.

Nunca digas que solo vendés la depiladora IPL.

Si el cliente menciona un producto o pregunta
por precio, disponibilidad, stock, características,
fotos, video o cualquier información de un producto,
usá exactamente:

[CONSULTAR_PRODUCTO: nombre del producto]

No respondas inventando datos antes de la consulta.

Si el producto no existe, usá:

[INTERES] lo que pidió el cliente [/INTERES]

FOTOS:

Si el cliente quiere ver fotos del producto,
usá:

[FOTOS]

Si pide más fotos:

[MASFOTOS]

VIDEO:

Si pide video y existe video en los datos del producto,
usá:

[VIDEO]

PEDIDOS:

Necesitás:

1. Nombre y apellido
2. Ciudad
3. Teléfono
4. Dirección

Cuando tengas los cuatro datos y el cliente confirme,
usá:

[PEDIDO] Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]

Solo cuando el pedido esté confirmado.

HONESTIDAD:

No presiones.

No manipules.

No inventes testimonios.

Tratale bien al cliente.

"""


# ============================================================
# PROMPT DUEÑO
# ============================================================

PROMPT_DUENO = """

Estás hablando con Fernando,
creador y dueño de Guaranistore.

Estás en MODO PRIVADO.

No actúes como vendedor.

Sos su asistente de confianza.

Podés analizar:

- ventas;
- pedidos;
- conversaciones;
- errores del bot;
- oportunidades de mejora.

Usá datos reales.

No inventes números.

Podés usar [FOTOS], [MASFOTOS] y [VIDEO]
si Fernando quiere probar material.

Nunca uses [PEDIDO] en este modo.

"""


# ============================================================
# WEBHOOK
# ============================================================

@app.get("/")
def inicio():
    return {
        "status": "online",
        "bot": "FER BOT 3.0"
    }


@app.get("/webhook")
def verificar(request: Request):

    params = request.query_params

    if params.get(
        "hub.verify_token"
    ) == VERIFY_TOKEN:

        return Response(
            content=params.get(
                "hub.challenge"
            ),
            media_type="text/plain"
        )

    return Response(
        content="Token incorrecto",
        status_code=403
    )


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

    for entry in data.get(
        "entry",
        []
    ):

        for evento in entry.get(
            "messaging",
            []
        ):

            sender = evento.get(
                "sender",
                {}
            ).get(
                "id"
            )

            mensaje = evento.get(
                "message",
                {}
            )

            mid = mensaje.get(
                "mid"
            )

            if mid and mid in MENSAJES_VISTOS:

                print(
                    ">>> MENSAJE REPETIDO"
                )

                continue

            if mid:

                MENSAJES_VISTOS.add(
                    mid
                )

                if len(
                    MENSAJES_VISTOS
                ) > 1000:

                    MENSAJES_VISTOS.clear()

            if "text" not in mensaje:

                print(
                    ">>> EVENTO SIN TEXTO"
                )

                continue

            texto = mensaje[
                "text"
            ]

            print(
                f">>> TEXTO: '{texto}' "
                f"DE {sender}"
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

def responder(
    sender,
    texto
):

    marcar_leido(
        sender
    )

    mostrar_escribiendo(
        sender
    )

    t_lower = texto.lower()

    en_modo = MODO_DUENO.get(
        sender,
        False
    )

    tiene_clave = (
        bool(
            CLAVE_DUENO
        )
        and
        CLAVE_DUENO in t_lower
    )


    # ENTRAR MODO DUEÑO

    if not en_modo and tiene_clave:

        MODO_DUENO[
            sender
        ] = True

        enviar_a_messenger(
            sender,
            "Listo dueño, entré en MODO PRUEBA. "
            "Te hablo como tu asistente, no como vendedor. "
            "Cuando quieras volver a atender clientes, decime: modo vendedor."
        )

        return


    # SALIR MODO DUEÑO

    if en_modo and any(
        palabra in t_lower
        for palabra in PALABRAS_SALIR
    ):

        MODO_DUENO[
            sender
        ] = False

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
                re.escape(
                    CLAVE_DUENO
                ),
                "",
                texto,
                flags=re.IGNORECASE
            ).strip()

        if not texto_ia:

            return

        contexto = (
            resumen_ventas()
            +
            "\n\n=== CONVERSACIONES RECIENTES ===\n"
            +
            leer_conversaciones()
        )

        respuesta = preguntar_a_gemini(
            [],
            contexto
            +
            "\n\nMensaje del dueño:\n"
            +
            texto_ia,
            PROMPT_DUENO
        )


    # ========================================================
    # MODO VENDEDOR
    # ========================================================

    else:

        historial = leer_historial(
            sender
        )

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

                ULTIMO_PRODUCTO_CONSULTADO.pop(
                    sender,
                    None
                )

                respuesta = revisar_interes(
                    sender,
                    respuesta
                )


    print(
        ">>> GEMINI:",
        respuesta
    )


    # PEDIDO

    if not en_modo:

        respuesta = revisar_pedido(
            sender,
            respuesta
        )

        respuesta = revisar_interes(
            sender,
            respuesta
        )


    # FOTOS

    respuesta, fotos = revisar_fotos(
        sender,
        respuesta
    )


    # VIDEO

    respuesta, video = revisar_video(
        respuesta
    )


    # ENVÍO TEXTO

    if respuesta:

        enviar_a_messenger(
            sender,
            respuesta
        )


    # ENVÍO FOTOS

    for foto in fotos:

        enviar_foto(
            sender,
            foto
        )


    # ENVÍO VIDEO

    if video:

        enviar_a_messenger(
            sender,
            video
        )


    # GUARDAR CONVERSACIÓN

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

        if rol == "user":

            prefijo = "Cliente: "

        else:

            prefijo = "Fer: "

        partes.append(
            {
                "text":
                prefijo
                +
                str(
                    contenido
                )
            }
        )

    partes.append(
        {
            "text":
            "Mensaje actual:\n"
            +
            texto
        }
    )


    # MODELO ACTUALIZADO

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
            ">>> ERROR CONEXIÓN GEMINI:",
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
            data[
                "candidates"
            ][
                0
            ][
                "content"
            ][
                "parts"
            ][
                0
            ][
                "text"
            ].strip()
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
        re.IGNORECASE |
        re.DOTALL
    )

    if m:

        return m.group(
            1
        ).strip()

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
            ">>> ERROR CATALOGO:",
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
        _nombre_producto(
            datos
        )
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

            datos_limpios[
                clave
            ] = valor


    contexto_producto = json.dumps(
        datos_limpios,
        ensure_ascii=False,
        indent=2
    )


    instruccion = f"""

El producto consultado EXISTE en Airtable.

DATOS REALES:

{contexto_producto}

MENSAJE DEL CLIENTE:

{texto}

Respondé usando únicamente los datos reales.

REGLAS:

- No inventes datos.
- Si pregunta precio, usa el precio real.
- Si pregunta stock, usa el stock real.
- Si pide fotos, agrega [FOTOS].
- Si pide más fotos, agrega [MASFOTOS].
- Si pide video y existe video, agrega [VIDEO].
- Respondé corto.
- Respondé natural.
- Español paraguayo.

"""


    return preguntar_a_gemini(
        historial,
        instruccion,
        SYSTEM_PROMPT
    )


# ============================================================
# AIRTABLE - PRODUCTOS
# ============================================================

def _normalizar_texto(
    valor
):

    if valor is None:

        return ""

    if isinstance(
        valor,
        list
    ):

        return " ".join(
            _normalizar_texto(
                v
            )
            for v in valor
        )

    if isinstance(
        valor,
        dict
    ):

        return " ".join(
            _normalizar_texto(
                v
            )
            for v in valor.values()
        )

    return str(
        valor
    ).strip()


def _nombre_producto(
    fields
):

    posibles = [

        "producto_id",
        "Producto",
        "producto",
        "Nombre",
        "nombre",
        "name"

    ]

    for campo in posibles:

        valor = fields.get(
            campo
        )

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
        "https://api.airtable.com/v0/"
        +
        AIRTABLE_BASE
        +
        "/"
        +
        TABLA_CATALOGO
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

            params[
                "offset"
            ] = offset

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

        if len(
            palabra
        ) >= 3

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
# FOTOS
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

        "foto_1",
        "foto_2",
        "foto_3",
        "foto_4",
        "foto_5",
        "foto_6",

        "Foto 1",
        "Foto 2",
        "Foto 3",
        "Foto 4",
        "Foto 5",
        "Foto 6"

    ]


    fotos = []


    for campo in posibles_campos:

        url = datos.get(
            campo
        )

        if not url:

            continue

        if isinstance(
            url,
            list
        ):

            for item in url:

                if isinstance(
                    item,
                    dict
                ):

                    valor = (
                        item.get(
                            "url"
                        )
                    )

                    if valor:

                        fotos.append(
                            valor
                        )

                elif str(
                    item
                ).startswith(
                    "http"
                ):

                    fotos.append(
                        str(
                            item
                        )
                    )

        else:

            valor = str(
                url
            ).strip()

            if valor.startswith(
                "http"
            ):

                fotos.append(
                    valor
                )


    # ELIMINA DUPLICADAS

    fotos_limpias = []

    for foto in fotos:

        if foto not in fotos_limpias:

            fotos_limpias.append(
                foto
            )


    return fotos_limpias[
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
# VIDEO
# ============================================================

def revisar_video(
    respuesta
):

    video = None

    if "[VIDEO]" in respuesta:

        producto = None

        # Busca video del último producto
        # consultado en Airtable.

        # Si el campo existe, se usa.

        # El producto se obtiene después
        # desde la respuesta global del cliente.

        video = None

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

    m = re.search(
        r"\[PEDIDO\](.*?)\[/PEDIDO\]",
        respuesta,
        re.DOTALL
    )

    if not m:

        return respuesta


    resumen = m.group(
        1
    ).strip()


    print(
        ">>> PEDIDO DETECTADO:",
        resumen
    )


    try:

        avisar_telegram(
            formatear_pedido(
                resumen
            )
        )

    except Exception:

        print(
            ">>> ERROR AVISANDO TELEGRAM:"
        )

        print(
            traceback.format_exc()
        )


    try:

        enviar_whatsapp(
            formatear_pedido_whatsapp(
                resumen
            )
        )

    except Exception:

        print(
            ">>> ERROR WHATSAPP:"
        )

        print(
            traceback.format_exc()
        )


    try:

        guardar_pedido(
            resumen
        )

    except Exception:

        print(
            ">>> ERROR GUARDANDO PEDIDO:"
        )

        print(
            traceback.format_exc()
        )


    respuesta = re.sub(
        r"\[PEDIDO\].*?\[/PEDIDO\]",
        "",
        respuesta,
        flags=re.DOTALL
    ).strip()


    return respuesta


def _parsear(
    resumen
):

    datos = {}

    for parte in resumen.split(
        "|"
    ):

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


    producto = PRODUCTO_ELEGIDO_POR_CLIENTE.get(
        "producto"
    )


    return (

        "🛍️ NUEVO PEDIDO — Guaranístore\n"
        "━━━━━━━━━━━━━━━\n"

        f"👤 Nombre: {d.get('nombre', '-')}\n"

        f"📍 Ciudad: {d.get('ciudad', '-')}\n"

        f"📞 Teléfono: {d.get('tel', '-')}\n"

        f"🏠 Dirección: {d.get('direccion', '-')}\n"

        "━━━━━━━━━━━━━━━\n"

        "🕒 "
        +
        hora
        +
        " hs"

    )


def formatear_pedido_whatsapp(
    resumen
):

    d = _parsear(
        resumen
    )

    return (

        "NUEVO PEDIDO\n\n"

        "Nombre: "
        +
        d.get(
            "nombre",
            "-"
        )
        +
        "\n"

        "Ciudad: "
        +
        d.get(
            "ciudad",
            "-"
        )
        +
        "\n"

        "Teléfono: "
        +
        d.get(
            "tel",
            "-"
        )
        +
        "\n"

        "Dirección: "
        +
        d.get(
            "direccion",
            "-"
        )

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
            "Nuevo"

        }

    }


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
            ">>> ERROR PEDIDO AIRTABLE:",
            r.status_code,
            r.text
        )

    else:

        print(
            ">>> PEDIDO GUARDADO EN AIRTABLE"
        )


# ============================================================
# INTERÉS
# ============================================================

def revisar_interes(
    sender,
    respuesta
):

    m = re.search(
        r"\[INTERES\](.*?)\[/INTERES\]",
        respuesta,
        re.DOTALL
    )

    if not m:

        return respuesta


    texto = m.group(
        1
    ).strip()


    avisar_telegram(
        "👀 INTERÉS EN PRODUCTO\n"
        +
        texto
        +
        "\nCliente: "
        +
        str(
            sender
        )
    )


    respuesta = re.sub(
        r"\[INTERES\].*?\[/INTERES\]",
        "",
        respuesta,
        flags=re.DOTALL
    ).strip()


    return respuesta


# ============================================================
# FACEBOOK MESSENGER
# ============================================================

def marcar_leido(
    sender
):

    url = GRAPH

    headers = {

        "Authorization":
        f"Bearer {PAGE_TOKEN}",

        "Content-Type":
        "application/json"

    }


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
            url,
            headers=headers,
            json=payload,
            timeout=10
        )

    except Exception as e:

        print(
            ">>> ERROR MARCAR LEÍDO:",
            e
        )


def mostrar_escribiendo(
    sender
):

    url = GRAPH

    headers = {

        "Authorization":
        f"Bearer {PAGE_TOKEN}",

        "Content-Type":
        "application/json"

    }


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
            url,
            headers=headers,
            json=payload,
            timeout=10
        )

    except Exception as e:

        print(
            ">>> ERROR TYPING:",
            e
        )


def enviar_a_messenger(
    sender,
    texto
):

    if not texto:

        return


    url = GRAPH

    headers = {

        "Authorization":
        f"Bearer {PAGE_TOKEN}",

        "Content-Type":
        "application/json"

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


    r = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15
    )


    if r.status_code not in (
        200,
        201
    ):

        print(
            ">>> ERROR MESSENGER:",
            r.status_code,
            r.text
        )


def enviar_foto(
    sender,
    url_foto
):

    url = GRAPH

    headers = {

        "Authorization":
        f"Bearer {PAGE_TOKEN}",

        "Content-Type":
        "application/json"

    }


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


    r = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=20
    )


    if r.status_code not in (
        200,
        201
    ):

        print(
            ">>> ERROR ENVIANDO FOTO:",
            r.status_code,
            r.text
        )


# ============================================================
# AIRTABLE - MEMORIA
# ============================================================

def guardar(
    sender,
    role,
    contenido
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


    prefijo = (
        "[user] "
        if role == "user"
        else
        "[bot] "
    )


    cuerpo = {

        "fields": {

            "contact_id":
            str(
                sender
            ),

            "mensaje_entrante":
            prefijo
            +
            str(
                contenido
            )

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
                ">>> ERROR GUARDANDO MEMORIA:",
                r.status_code,
                r.text
            )

    except Exception as e:

        print(
            ">>> ERROR MEMORIA:",
            e
        )


def leer_historial(
    sender,
    max_records=30
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
                max_records
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
            ) != str(
                sender
            ):

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
                        "role":
                        "user",

                        "content":
                        mensaje[7:]
                    }
                )

            elif mensaje.startswith(
                "[bot] "
            ):

                historial.append(
                    {
                        "role":
                        "model",

                        "content":
                        mensaje[6:]
                    }
                )


        return historial[-20:]


    except Exception as e:

        print(
            ">>> ERROR LEYENDO HISTORIAL:",
            e
        )

        return []


# ============================================================
# TELEGRAM
# ============================================================

def avisar_telegram(
    texto
):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:

        print(
            ">>> TELEGRAM NO CONFIGURADO"
        )

        return


    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )


    payload = {

        "chat_id":
        TELEGRAM_CHAT,

        "text":
        texto

    }


    r = requests.post(
        url,
        json=payload,
        timeout=10
    )


    if r.status_code != 200:

        print(
            ">>> ERROR TELEGRAM:",
            r.status_code,
            r.text
        )


def enviar_whatsapp(
    texto
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
        texto,

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


    r = requests.get(
        url,
        headers=headers,
        params={
            "maxRecords":
            100
        },
        timeout=10
    )


    if r.status_code != 200:

        return (
            "No pude leer la tabla Pedidos."
        )


    pedidos = [

        registro.get(
            "fields",
            {}
        )

        for registro in r.json().get(
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

        for pedido in pedidos

        if str(
            pedido.get(
                "Fecha",
                ""
            )
        ).startswith(
            hoy
        )

    )


    lineas = []


    for pedido in pedidos[-15:]:

        lineas.append(

            f"- "
            f"{pedido.get('Nombre', '?')} | "
            f"{pedido.get('Ciudad', '?')} | "
            f"{pedido.get('Fecha', '?')} | "
            f"{pedido.get('Estado', '?')}"

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

        "DATOS REALES DE VENTAS\n"

        f"Total de pedidos: {total}\n"

        f"Pedidos de hoy ({hoy}): {de_hoy}\n"

        f"Últimos pedidos:\n{detalle}"

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


    for registro in r.json().get(
        "records",
        []
    ):

        campos = registro.get(
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

            charlas[
                cid
            ] = []

            orden.append(
                cid
            )


        if texto.startswith(
            "[bot] "
        ):

            charlas[
                cid
            ].append(
                "Fer: "
                +
                texto[6:]
            )

        elif texto.startswith(
            "[user] "
        ):

            charlas[
                cid
            ].append(
                "Cliente: "
                +
                texto[7:]
            )


    bloques = []


    for i, cid in enumerate(
        orden[
            -ultimos_contactos:
        ],
        1
    ):

        lineas = charlas[
            cid
        ][
            -msgs_por_contacto:
        ]


        bloques.append(

            f"--- Charla {i} ---\n"
            +
            "\n".join(
                lineas
            )

        )


    return (

        "\n\n".join(
            bloques
        )

        if bloques

        else

        "(todavía no hay conversaciones)"

    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                10000
            )
        )
    )