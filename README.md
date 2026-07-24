# Fer Bot — cómo ponerlo a andar (desde el celular)

Esto es un mapa de todo el camino. **No lo hagas solo de corrido** —
vamos paso por paso juntos, y en cada uno te guío con los detalles.
Acá está para que veas el panorama completo.

---

## Los 3 archivos de tu bot
- `main.py` → el bot en sí (todo el código)
- `requirements.txt` → la lista de cosas que el servidor instala
- `README.md` → este mapa

---

## FASE 1 — Cuentas (gratis)
1. Crear una cuenta en **GitHub** (ahí vive el código).
2. Crear una cuenta en **Render** (ahí el código corre 24/7).

## FASE 2 — Subir el código
3. En GitHub, crear un repositorio nuevo.
4. Subir los 3 archivos (se puede desde el navegador del celu).

## FASE 3 — Sacar las llaves 🔑
Cada llave sale de una cuenta tuya. Las vamos sacando de a una:
- **Gemini** → tu API key (ya la tenés).
- **Airtable** → tu API key + el id de la base ZAPPY_BOT.
- **Telegram** → el token de tu bot + tu chat id (ya los tenés).
- **Meta/Facebook** → crear una "app" y sacar el token de tu página.
  (Este es el trámite más largo, pero se hace una sola vez.)

## FASE 4 — Encender el servidor
5. En Render, crear un "Web Service" conectado a tu repo de GitHub.
6. Cargar las llaves como **variables de entorno** (no van en el código).
   Los nombres exactos son:
   ```
   VERIFY_TOKEN     (una palabra que inventás vos, ej: fer123)
   PAGE_TOKEN       (token de tu página de Facebook)
   GEMINI_KEY       (API key de Gemini)
   AIRTABLE_KEY     (API key de Airtable)
   AIRTABLE_BASE    (id de tu base ZAPPY_BOT)
   TELEGRAM_TOKEN   (token de tu bot de Telegram)
   TELEGRAM_CHAT    (tu chat id de Telegram)
   ```
7. En la configuración de Render, poner como comando de arranque:
   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

## FASE 5 — Conectar Messenger
8. En la app de Meta, apuntar el webhook a la dirección que te da Render
   (algo como `https://tu-bot.onrender.com/webhook`) usando el
   `VERIFY_TOKEN` que inventaste.

## FASE 6 — Probar 🎉
9. Escribirle a tu página desde otra cuenta y ver si Fer contesta.

---

### Nota sobre los campos de Airtable
El código asume que tu tabla **Conversaciones** tiene estos campos:
`sender_id`, `rol`, `mensaje`, `creado`.
Si los tuyos se llaman distinto, avisame y ajustamos el código —
es un cambio de dos minutos.
