"""
FER BOT 3.0 — catálogo dinámico desde Airtable
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


# ================= CONFIGURACION =================

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


# ================= FOTOS Y VIDEO =================

BASE_FOTOS = (
    "https://raw.githubusercontent.com/"
    "celparaguayy-cloud/guaranistorebot/main/"
)

# Se mantienen por compatibilidad,
# pero el catalogo dinamico ya no depende de estas.
FOTOS_PRINCIPALES = [
    "ipl1.jpg",
    "ipl2.jpg",
    "ipl3.jpg"
]

FOTOS_EXTRA = [
    "ipl4.jpg",
    "ipl5.jpg",
    "ipl6.jpg"
]

VIDEO_URL = (
    "https://youtube.com/shorts/0WoRz-Nzucw"
)


# ================= MEMORIA TEMPORAL =================

MENSAJES_VISTOS = set()

MODO_DUENO = {}

# Guarda el ultimo producto consultado
# por cada cliente.
ULTIMO_PRODUCTO_CONSULTADO = {}


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
    "dejar de probar"
]


# ================= SYSTEM PROMPT =================

SYSTEM_PROMPT = """

Sos Fer, vendedor de verdad de Guaranistore, una tienda paraguaya.

Sos una PERSONA, no un bot: con caracter, historia y corazon.
Nadie deberia sospechar que del otro lado hay un sistema.

Antes que vendedor, sos gente.

Tu norte: acompanar a la persona hasta que se lleve su producto,
tratandola tan bien que quiera comprarte a VOS.

SALUDO:

Saluda UNA SOLA VEZ, al principio.

Si ya venis conversando, NO vuelvas a saludar ni a presentarte.
Continua la charla.

NO uses "mba'eichapa" ni saludo guarani en cada mensaje.

Varia los saludos.

QUIEN SOS:

30 y pico, paraguayo, hace anos que vendes.

Respetas la plata del que te escribe.

Calido, con picardia justa, serio con lo importante.

Nunca prometes lo que no podes cumplir.

Lees a la persona y actuas en consecuencia.

TU AMABILIDAD:

Usa "por favor" y "gracias" de verdad.

Trata con carino.

Haz sentir importante a la persona.

Despedite con calidez aunque no compre.

Amable no es zalamero.

Nada de "mi amor" o "mi reina".

COMO ESCRIBIS:

Mensajes CORTOS, de 1 a 3 lineas.

Voseo paraguayo.

Guarani muy de vez en cuando.

UNA pregunta por vez.

Espeja el tono del cliente.

EMOJIS:

Pocos pero expresivos.

Nunca una fila de emojis.

FOTOS DEL PRODUCTO:

Cuando el cliente quiera ver el producto:

"tenes foto?"
"mostrame"
"como es?"

agrega:

[FOTOS]

El codigo enviara 3 fotos reales y borrara la etiqueta.

Si pide ver MAS:

[MASFOTOS]

El codigo enviara 3 fotos mas.

No repitas [FOTOS] si ya las mandaste,
salvo que el cliente pida fotos nuevamente.

VIDEO DEL PRODUCTO:

Si pide un video:

"tenes video?"
"en video"
"mostrame funcionando"

agrega:

[VIDEO]

El codigo enviara el video correspondiente.

MENSAJES CORTOS:

"precio" o "cuanto?"
responde precio al toque y una pregunta.

"hola":
saluda y pregunta en que ayudas.

PRODUCTOS:

La informacion de cada producto debe salir
del catalogo de Airtable.

Fer puede vender y responder sobre CUALQUIER
producto que exista en Catalogo_Espejo.

Nunca digas que solo vendes la depiladora.

Si el cliente menciona un producto del catalogo
o pregunta por precio, disponibilidad,
caracteristicas, fotos, video o cualquier dato:

Usa UNICAMENTE esta etiqueta:

[CONSULTAR_PRODUCTO: nombre del producto]

No agregues texto en esa respuesta.

El sistema consulta Airtable.

Despues el sistema te devuelve los datos reales
del producto para generar la respuesta final.

Nunca inventes precio, stock,
caracteristicas ni disponibilidad.

Si el producto NO existe en Airtable:

[INTERES] lo que pidio el cliente [/INTERES]

DISPONIBILIDAD:

Si preguntan:

"hay stock?"
"tenes disponible?"
"todavia queda?"

usa:

[CONSULTAR_PRODUCTO: nombre del producto]

OBJECIONES:

"Funciona?"
responde usando los datos reales del producto.

"Es caro":
un solo pago, contra entrega,
y si no es el momento cuando puedas.

"Y si no sirve?":
responde segun la garantia real del producto.

"Lo pienso":
dale, sin insistir.

REGLAS:

Nunca inventes precios ni datos.

Nunca uses el dolor de alguien para vender.

No presiones.

Amable sin zalameria.

No hables de otros productos salvo que pregunten.

Nunca digas que sos un bot: sos Fer.

"""


# ================= PROMPT DUENO =================

PROMPT_DUENO = """

Estas hablando con Fernando,
tu creador y dueno de Guaranistore,
en MODO PRIVADO.

NO actues como vendedor.

Sos su ASISTENTE de confianza y mano derecha
del negocio.

Hablale con naturalidad,
honestidad y de igual a igual.

Junto a su mensaje vas a recibir:

DATOS REALES DE VENTAS
y
CONVERSACIONES RECIENTES.

Con los datos de VENTAS:

Cuando pregunte, dale reportes concretos.

Numeros reales.

No inventes.

Con las CONVERSACIONES:

Podes mostrar una charla.

Resumirla.

Analizarla.

Actuar como AUDITOR.

Decile honestamente que se podria mejorar.

Se concreto y honesto.

Tambien lo ayudas a probar el bot.

Podes usar:

[FOTOS]
[MASFOTOS]
[VIDEO]

NUNCA uses:

[PEDIDO]

en este modo.

"""


# =================================================
# ================= WEBHOOK =======================
# =================================================


@app.get("/webhook")
def verificar(request: Request):

    params = request.query_params

    if (
        params.get("hub.verify_token")
        == VERIFY_TOKEN
    ):

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

            if (
                mid
                and mid in MENSAJES_VISTOS
            ):

                print(
                    ">>> Repetido, lo ignoro"
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

            if "text" in mensaje:

                texto = mensaje[
                    "text"
                ]

                print(
                    f">>> TEXTO: "
                    f"'{texto}' "
                    f"de {sender}"
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

            else:

                print(
                    ">>> Evento sin texto "
                    "(lo ignoro)"
                )

    return {
        "status": "ok"
    }


# =================================================
# ================= LOGICA PRINCIPAL ==============
# =================================================


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
        bool(CLAVE_DUENO)
        and CLAVE_DUENO in t_lower
    )


    # ================= MODO DUENO =================

    if (
        not en_modo
        and tiene_clave
    ):

        MODO_DUENO[
            sender
        ] = True

        en_modo = True

        enviar_a_messenger(
            sender,
            "Listo dueno, entre en MODO PRUEBA. "
            "Te hablo como tu asistente, no como vendedor. "
            "Cuando quieras que vuelva a atender clientes, "
            "decime: modo vendedor."
        )


    elif (
        en_modo
        and any(
            p in t_lower
            for p in PALABRAS_SALIR
        )
    ):

        MODO_DUENO[
            sender
        ] = False

        enviar_a_messenger(
            sender,
            "Listo, volvi al MODO VENDEDOR. "
            "Ya atiendo normal a los clientes 👍"
        )

        return


    # ================= MODO DUENO =================

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
            + "\n\n"
            + "=== CONVERSACIONES RECIENTES ==="
            + "\n"
            + leer_conversaciones()
        )


        respuesta = preguntar_a_gemini(
            [],
            (
                contexto
                + "\n\nMensaje del dueno: "
                + texto_ia
            ),
            PROMPT_DUENO
        )


    # ================= MODO VENDEDOR =================

    else:

        historial = leer_historial(
            sender
        )


        # Primera consulta a Gemini.
        # Puede responder normalmente o pedir:
        #
        # [CONSULTAR_PRODUCTO: nombre]
        #

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

                # Guardamos el producto real
                # consultado por este cliente.

                ULTIMO_PRODUCTO_CONSULTADO[
                    sender
                ] = datos_producto


                # Ahora Gemini responde usando
                # unicamente los datos reales
                # de Airtable.

                respuesta = (
                    generar_respuesta_con_producto(
                        historial,
                        texto,
                        datos_producto
                    )
                )


            else:

                # Si no existe, borramos cualquier
                # producto anterior para evitar
                # enviar fotos equivocadas.

                ULTIMO_PRODUCTO_CONSULTADO.pop(
                    sender,
                    None
                )

                respuesta = revisar_interes(
                    sender,
                    respuesta
                )


    print(
        ">>> GEMINI "
        f"({'dueno' if en_modo else 'vendedor'}): "
        f"'{respuesta}'"
    )


    # ================= PEDIDOS =================

    if not en_modo:

        respuesta = revisar_pedido(
            sender,
            respuesta
        )


        respuesta = revisar_interes(
            sender,
            respuesta
        )


    # ================= MATERIAL =================

    respuesta, fotos = revisar_fotos(
        sender,
        respuesta
    )


    respuesta, video = revisar_video(
        respuesta
    )


    # ================= ENVIAR =================

    if respuesta:

        enviar_a_messenger(
            sender,
            respuesta
        )


    for url in fotos:

        enviar_foto(
            sender,
            url
        )


    if video:

        enviar_a_messenger(
            sender,
            video
        )


    # ================= GUARDAR =================

    if not en_modo:

        guardar(
            sender,
            "user",
            texto
        )


        guardar(
            sender,
            "model",
            (
                respuesta
                if respuesta
                else
                "(envie material del producto)"
            )
        )


# =================================================
# ================= PRODUCTOS =====================
# =================================================


def extraer_producto_consultado(
    respuesta
):

    """
    Busca:

    [CONSULTAR_PRODUCTO: nombre del producto]
    """

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

    """
    Busca cualquier producto en Airtable
    y devuelve sus datos reales.
    """

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

    """
    Genera una respuesta utilizando
    los datos reales del producto
    encontrado en Airtable.
    """

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
en el catalogo de Airtable.

DATOS REALES DEL PRODUCTO:

{contexto_producto}


Mensaje actual del cliente:

{texto}


Responde usando unicamente
los datos reales del producto.


REGLAS:

- No inventes precio.
- No inventes stock.
- No inventes caracteristicas.
- No digas que solo vendemos la depiladora.
- No digas que vas a consultar al encargado.
- Si pregunta el precio, responde el precio real.
- Si pregunta disponibilidad, responde segun los datos reales.
- Si pide fotos, agrega exactamente [FOTOS].
- Si pide mas fotos, agrega exactamente [MASFOTOS].
- Si pide video y existe una URL real, agrega [VIDEO].
- Si no existe video, no inventes uno.
- Si ya pidio fotos, no preguntes nuevamente si quiere verlas.
- Responde corto, natural y en español paraguayo.
- Mantene el estilo de Fer.

"""


    return preguntar_a_gemini(
        historial,
        instruccion,
        SYSTEM_PROMPT
    )


# =================================================
# ================= FOTOS DINAMICAS ===============
# =================================================


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

                fotos.append(
                    url
                )


    return fotos[
        desde:desde + cantidad
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

            fotos += (
                obtener_fotos_producto(
                    producto,
                    cantidad=3,
                    desde=0
                )
            )


    if "[MASFOTOS]" in respuesta:

        if producto:

            fotos += (
                obtener_fotos_producto(
                    producto,
                    cantidad=3,
                    desde=3
                )
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


def revisar_video(
    respuesta
):

    video = None


    if "[VIDEO]" in respuesta:

        video = VIDEO_URL


        respuesta = (
            respuesta
            .replace(
                "[VIDEO]",
                ""
            )
            .strip()
        )


    return respuesta, video


# =================================================
# ================= PEDIDOS =======================
# =================================================


def revisar_pedido(
    sender,
    respuesta
):

    m = re.search(
        r"\[PEDIDO\](.*?)\[/PEDIDO\]",
        respuesta,
        re.DOTALL
    )


    if m:

        resumen = (
            m.group(
                1
            ).strip()
        )


        avisar_telegram(
            formatear_pedido(
                resumen
            )
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
            r"\[PEDIDO\].*?\[/PEDIDO\]",
            "",
            respuesta,
            flags=re.DOTALL
        ).strip()


    return respuesta


def revisar_interes(
    sender,
    respuesta
):

    m = re.search(
        r"\[INTERES\](.*?)\[/INTERES\]",
        respuesta,
        re.DOTALL
    )


    if m:

        avisar_telegram(
            "👀 INTERES EN OTRO PRODUCTO\n"
            "El cliente pregunto por: "
            + m.group(
                1
            ).strip()
            + f"\n(cliente: {sender})"
        )


        respuesta = re.sub(
            r"\[INTERES\].*?\[/INTERES\]",
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

            clave, valor = (
                parte.split(
                    ":",
                    1
           