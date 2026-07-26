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

PRODUCTOS: La informacion de cada producto debe salir del catalogo de Airtable. Para la Depiladora IPL, si la conversacion ya tiene los datos del producto, podes usar la informacion conocida; para cualquier otro producto, primero consulta Airtable con [CONSULTAR_PRODUCTO].

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
[PEDIDO] Producto: <producto> | Precio: <precio real en Gs> | Nombre: <nombre> | Ciudad: <ciudad> | Tel: <telefono> | Direccion: <direccion> [/PEDIDO]
Usa el NOMBRE y el PRECIO REAL del producto que el cliente compro (el que consultaste en el catalogo). Solo cuando el pedido esta cerrado. El cliente no la vera.

CATALOGO DE PRODUCTOS (IMPORTANTE): Airtable es la fuente principal de verdad de los productos.
Fer puede vender y responder sobre CUALQUIER producto que exista en la tabla Catalogo_Espejo.
Nunca digas que solo vendes la depiladora IPL.

Si el cliente menciona un producto del catalogo o pregunta por su precio, disponibilidad, caracteristicas, fotos, video o cualquier dato:
1. Usa UNICAMENTE esta etiqueta, sin agregar texto en esa respuesta:
[CONSULTAR_PRODUCTO: nombre del producto]
2. El sistema consulta Airtable y despues vos respondes usando los datos reales.
3. Nunca inventes precio, stock, caracteristicas ni disponibilidad.

Si el producto NO existe en Airtable, recien entonces avisa al encargado usando:
[INTERES] <lo que pidio el cliente> [/INTERES]
El codigo avisa al dueno. El cliente no ve la etiqueta.

DISPONIBILIDAD: si preguntan "hay stock?", "tenes disponible?" o "todavia queda?", tambien usa:
[CONSULTAR_PRODUCTO: nombre del producto]
El sistema consulta el producto completo y te devuelve el dato real.

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
        respuesta = revisar_producto(respuesta, historial)
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
    producto = d.get("producto", "Producto")
    precio = d.get("precio", "-")
    return (
        "🛍️  NUEVO PEDIDO — Guaranístore\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤  Nombre:     {d.get('nombre', '-')}\n"
        f"📍  Ciudad:     {d.get('ciudad', '-')}\n"
        f"📞  Teléfono:   {d.get('tel', '-')}\n"
        f"🏠  Dirección:  {d.get('direccion', '-')}\n"
        "━━━━━━━━━━━━━━━\n"
        f"💜  Producto:   {producto}\n"
        f"💰  Total:      {precio} (contra entrega)\n"
        f"🕒  {hora} hs"
    )


def guardar_pedido(resumen):
    d = _parsear(resumen)
    hora = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA_PEDIDOS}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}", "Content-Type": "application/json"}
    cuerpo = {"fields": {
        "Producto":  d.get("producto", ""),
        "Nombre":    d.get("nombre", ""),
        "Ciudad":    d.get("ciudad", ""),
        "Telefono":  d.get("tel", ""),
        "Direccion": d.get("direccion", ""),
        "Total":     d.get("precio", ""),
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


# ================= HERRAMIENTA DEL AGENTE: consultar_producto =================
def _normalizar_texto(valor):
    """Convierte cualquier valor de Airtable en texto comparable."""
    if valor is None:
        return ""
    if isinstance(valor, list):
        return " ".join(_normalizar_texto(v) for v in valor)
    if isinstance(valor, dict):
        return " ".join(_normalizar_texto(v) for v in valor.values())
    return str(valor).strip()


def _encontrar_producto_en_catalogo(producto):
    """Busca un producto en Catalogo_Espejo y devuelve sus campos reales."""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA_CATALOGO}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    registros = []
    offset = None

    # Lee hasta 1000 registros, incluyendo paginacion de Airtable.
    for _ in range(10):
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code != 200:
            print(">>> AIRTABLE (catalogo) error:", r.status_code, r.text)
            return None, "No pude consultar el catalogo en este momento."
        data = r.json()
        registros.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break

    consulta = _normalizar_texto(producto).lower()
    palabras = [w for w in re.findall(r"[a-záéíóúñ0-9]+", consulta) if len(w) > 2]

    # Campos que normalmente identifican el producto.
    campos_identidad = {
        "producto_id", "nombre", "producto", "nombre_producto", "titulo",
        "title", "name", "sku", "codigo", "categoria"
    }

    mejor = None
    mejor_puntaje = 0

    for registro in registros:
        campos = registro.get("fields", {})
        identidad = " ".join(
            _normalizar_texto(valor).lower()
            for nombre, valor in campos.items()
            if nombre.lower().strip() in campos_identidad
        )

        # Fallback: si no hay campos de identidad reconocibles, usa producto_id.
        if not identidad:
            identidad = _normalizar_texto(campos.get("producto_id", "")).lower()

        if not identidad:
            continue

        puntaje = 0
        if consulta and consulta in identidad:
            puntaje += 100
        puntaje += sum(1 for palabra in palabras if palabra in identidad) * 10

        if puntaje > mejor_puntaje:
            mejor = campos
            mejor_puntaje = puntaje

    if mejor is None:
        ids = []
        for registro in registros:
            pid = registro.get("fields", {}).get("producto_id")
            if pid:
                ids.append(str(pid))
        return None, f"No encontré '{producto}' en el catálogo. Productos registrados: {', '.join(ids)}"

    return mejor, None


def consultar_producto(producto):
    """Devuelve los datos reales del producto desde Airtable."""
    campos, error = _encontrar_producto_en_catalogo(producto)
    if error:
        return error

    producto_id = campos.get("producto_id", producto)
    datos = []
    for nombre, valor in campos.items():
        if valor in (None, "", [], {}):
            continue
        # No mandamos URLs largas como texto al modelo; las herramientas de fotos/video ya existen.
        if nombre.lower() in {"url_foto_1", "url_foto_2", "url_foto_3", "url_video", "link_venta"}:
            continue
        datos.append(f"{nombre}: {_normalizar_texto(valor)}")

    resultado = f"Producto encontrado: {producto_id}. Datos reales del catálogo:\n" + "\n".join(datos)
    print(f">>> PRODUCTO AIRTABLE '{producto}': {resultado}")
    return resultado


# Si Gemini pidio [CONSULTAR_PRODUCTO: x], consulta el producto completo y re-arma la respuesta.
def revisar_producto(respuesta, historial):
    m = re.search(r"\[CONSULTAR_PRODUCTO:\s*(.*?)\]", respuesta, re.IGNORECASE | re.DOTALL)
    if not m:
        return respuesta

    producto = m.group(1).strip()
    dato = consultar_producto(producto)
    print(f">>> PRODUCTO '{producto}': consulta completada")

    refuerzo = (
        f"[DATO REAL DEL CATALOGO] El cliente pregunto por '{producto}'.\n"
        f"{dato}\n\n"
        "Respondele al cliente de forma natural, breve y calida usando solamente los datos reales del catalogo. "
        "Si el producto fue encontrado, tratalo como un producto de la tienda y no digas que solo vendes la depiladora. "
        "Si el catalogo indica disponibilidad o stock, informa eso. Si incluye precio, informa el precio real. "
        "No menciones etiquetas, herramientas, Airtable ni sistemas."
    )
    final = preguntar_a_gemini(historial, refuerzo, SYSTEM_PROMPT)
    return re.sub(r"\[CONSULTAR_PRODUCTO:.*?\]", "", final, flags=re.IGNORECASE | re.DOTALL).strip()


# ================= HERRAMIENTA DEL AGENTE: consultar_stock =================
# Lee el stock REAL del catalogo. Esta es la 1ra "herramienta" de verdad de Fer.
def consultar_stock(producto):
    # Compatibilidad con la etiqueta antigua. La consulta real ahora usa el catalogo completo.
    return consultar_producto(producto)


# Si Gemini pidio [CONSULTAR_STOCK: x], consulta el dato real y re-arma la respuesta
def revisar_stock(respuesta, historial):
    m = re.search(r"\[CONSULTAR_STOCK:\s*(.*?)\]", respuesta)
    if not m:
        return respuesta
    producto = m.group(1).strip()
    dato = consultar_stock(producto)
    print(f">>> STOCK '{producto}': {dato}")
    refuerzo = (
        f"[DATO REAL DEL CATALOGO] El cliente pregunto por la disponibilidad de '{producto}'. "
        f"Resultado real del catalogo: {dato} "
        "Respondele al cliente de forma natural y calida con ese dato. "
        "No menciones etiquetas, herramientas ni sistemas."
    )
    final = preguntar_a_gemini(historial, refuerzo, SYSTEM_PROMPT)
    return re.sub(r"\[CONSULTAR_STOCK:.*?\]", "", final).strip()


# ================= MEMORIA (Airtable) =================
def leer_historial(sender):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{TABLA}"
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    params = {"filterByFormula": f"{{contact_id}}='{sender}'", "maxRecords": 100}
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
    return historial[-20:]   # los ultimos 20 mensajes (los mas recientes de la charla)


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


# ================= WHATSAPP (via CallMeBot) =================
def formatear_pedido_whatsapp(resumen):
    d = _parsear(resumen)
    hora = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    producto = d.get("producto", "Producto")
    precio = d.get("precio", "-")
    return (
        "🛍️ *PEDIDO para cargar en Zappy*\n\n"
        f"📦 {producto} — {precio} (contra entrega)\n\n"
        f"👤 Cliente: {d.get('nombre', '-')}\n"
        f"📍 Ciudad: {d.get('ciudad', '-')}\n"
        f"📞 Tel: {d.get('tel', '-')}\n"
        f"🏠 Direccion: {d.get('direccion', '-')}\n"
        f"🕒 {hora} hs"
    )


def enviar_whatsapp(texto):
    if not (WHATSAPP_DESTINO and CALLMEBOT_APIKEY):
        print(">>> WhatsApp no configurado (falta WHATSAPP_DESTINO o CALLMEBOT_APIKEY)")
        return
    url = "https://api.callmebot.com/whatsapp.php"
    params = {"phone": WHATSAPP_DESTINO, "text": texto, "apikey": CALLMEBOT_APIKEY}
    try:
        r = requests.get(url, params=params, timeout=15)
        print(">>> WHATSAPP:", r.status_code, r.text[:150])
    except Exception as e:
        print(">>> WHATSAPP error:", e)


@app.get("/")
def inicio():
    return {"estado": "Fer esta prendido y esperando mensajes"}
