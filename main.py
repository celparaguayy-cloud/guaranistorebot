"""
FER BOT 3.0 — catálogo dinámico desde Airtable
IA (Gemini) + memoria (Airtable) + fotos + video
+ aviso de pedidos a Telegram
+ registro de pedidos en tabla
+ modo dueño
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

VERIFY_TOKEN = os.environ.get(
    "VERIFY_TOKEN",
    "fer123"
)

PAGE_TOKEN = os.environ["PAGE_TOKEN"].strip()
GEMINI_KEY = os.environ["GEMINI_KEY"].strip()
AIRTABLE_KEY = os.environ["AIRTABLE_KEY"].strip()
AIRTABLE_BASE = os.environ["AIRTABLE_BASE"].strip()
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"].strip()
TELEGRAM_CHAT = os.environ["TELEGRAM_CHAT"].strip()

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

# Último producto real consultado por cada cliente.
ULTIMO_PRODUCTO_CONSULTADO = {}

# Producto que el cliente está comprando.
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
# PROMPT DEL VENDEDOR
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

El sistema va a enviar las fotos reales
del producto consultado.

VIDEO:

Si pide video,
agregá:

[VIDEO]

El sistema va a enviar el video real
del producto si existe.

PRODUCTOS:

Airtable es la fuente principal de verdad.

Podés vender CUALQUIER producto que exista
en la tabla Catalogo_Espejo.

Nunca digas que solo vendés la depiladora IPL.

Si el cliente menciona un producto,
pregunta por su precio,
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

PRECIO:

Si pregunta el precio,
respondé el precio real del catálogo.

STOCK:

Si pregunta si hay stock,
respondé según el catálogo.

PEDIDOS:

Necesitás:

1. Nombre y apellido
2. Ciudad
3. Teléfono
4. Dirección

Cuando tengas los 4 datos y el cliente CONFIRME,
agregá exactamente:

[PEDIDO] Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]

Solo cuando el pedido esté cerrado.

HONESTIDAD:

No inventes testimonios.

No inventes stock.

No inventes precios.

No inventes promociones.

No inventes características.

No presiones.

Tratá bien a la persona.

"""


# ============================================================
# PROMPT DEL DUEÑO
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
# WEBHOOK
# ============================================================

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
                ) > 500:

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


    # ENTRAR AL MODO DUEÑO

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


    # SALIR DEL MODO DUEÑO

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

        if tiene_clave:

            texto_ia = re.sub(
                re.escape(
                    CLAVE_DUENO
                ),
                "",
                texto,
                flags=re.IGNORECASE
            ).strip()

        else:

            texto_ia = texto.strip()


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
            (
                contexto
                +
                "\n\nMensaje del dueño: "
                +
                texto_ia
            ),
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

            datos_producto = (
                consultar_producto(
                    producto_consultado
                )
            )


            if datos_producto:

                ULTIMO_PRODUCTO_CONSULTADO[
                    sender
                ] = datos_producto


                PRODUCTO_ELEGIDO_POR_CLIENTE[
                    sender
                ] = datos_producto


                respuesta = (
                    generar_respuesta_con_producto(
                        historial,
                        texto,
                        datos_producto
                    )
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
        f">>> GEMINI: {respuesta}"
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
        sender,
        respuesta
    )


    # ENVÍA TEXTO

    if respuesta:

        enviar_a_messenger(
            sender,
            respuesta
        )


    # ENVÍA FOTOS

    for foto in fotos:

        enviar_foto(
            sender,
            foto
        )


    # ENVÍA VIDEO

    if video:

        enviar_a_messenger(
            sender,
            video
        )


    # GUARDA CONVERSACIÓN

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


    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/gemini-2.0-flash:generateContent"
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


    r = requests.post(
        url,
        json=payload,
        timeout=45
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
# CONSULTA DE PRODUCTOS
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
        datos.get(
            "producto_id",
            producto
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
- Si pregunta el precio, responde el precio real.
- Si pregunta disponibilidad, responde según Airtable.
- Si pide fotos, agrega exactamente [FOTOS].
- Si pide más fotos, agrega exactamente [MASFOTOS].
- Si pide video y existe URL de video, agrega [VIDEO].
- Si ya pidió fotos, no preguntes si quiere verlas.
- Respondé corto y natural.
- Usá español paraguayo.

"""


    return preguntar_a_gemini(
        historial,
        instruccion,
        SYSTEM_PROMPT
    )


# ============================================================
# AIRTABLE — BUSCAR PRODUCTO
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


# ==========================================================