# RGL Discord BOT

Bot de Discord **todo-en-uno** con **panel web de control**, autoalojado en una **Raspberry Pi Zero 2 W**. Incluye moderación, registro de auditoría, recordatorios, eventos, encuestas, sistema de tickets, canales-contador, scrims, y un panel web con tema "hacker" para administrar el bot y la máquina desde el navegador (también en remoto).

---

## 🧰 Tecnologías

| Área | Tecnología |
|------|------------|
| Lenguaje | Python 3.13 |
| Bot | [discord.py](https://discordpy.readthedocs.io/) 2.7 (slash commands, botones, vistas persistentes) |
| Panel web | Flask 3 · waitress (HTTP) · werkzeug TLS (HTTPS) |
| Base de datos | SQLite (recordatorios, encuestas, tickets) |
| Config | python-dotenv (`.env`) |
| Iconos | Pillow (favicon e iconos PWA) |
| Frontend panel | HTML + CSS + JS vanilla (gráficas en `<canvas>`, sin dependencias) |
| Servicios | systemd (`discordbot`, `panel`, `bot-startup`) |
| Despliegue | Git (sincronización desde GitHub) + scripts de arranque/actualización |
| Acceso remoto | Tailscale (VPN WireGuard, sin abrir puertos) |
| Hardware | Raspberry Pi Zero 2 W (Raspberry Pi OS) |

---

## 🤖 Funcionalidades del bot

Cada función vive en su propio *cog* dentro de `cogs/`:

- **Registro de auditoría** (`logs`) — estilo MEE6: mensajes borrados/editados, entradas y salidas, baneos/desbaneos (con el moderador vía audit log), cambios de apodo, roles, avatar y nombre, creación/borrado de canales y movimientos de voz (opcional).
- **Canales de voz temporales** (`tempvoice`) — al entrar a un canal "lobby" se crea un canal de voz propio que se borra al quedarse vacío.
- **Recordatorios** (`reminders`) — `/recordatorio`, `/recordatorios`, `/cancelar_recordatorio`. Avisa por privado en la fecha indicada; persisten en SQLite.
- **Avisos de directos** (`streams`) — anuncia cuando un miembro con cierto rol empieza a emitir en Twitch.
- **Eventos** (`events`) — `/evento` crea eventos del servidor con rango de fechas, imagen de portada y avisos automáticos antes de empezar/terminar.
- **Moderación** (`moderation`) — `/clear` borra en bloque los últimos N mensajes (evita el límite de Discord con mensajes antiguos).
- **Estado** (`stats`) — `/stats` muestra latencia, uptime, CPU, RAM, temperatura y disco de la Pi.
- **Bienvenidas** (`welcome`) — mensaje de bienvenida/despedida y asignación de autorol a los nuevos.
- **Scrims y equipos** (`scrim`) — `/scrim` reparte al azar a la gente de un canal de voz en dos equipos y los **mueve**; `/equipos` solo **anuncia** los equipos sin mover.
- **Auto-reacción** (`autoreact`) — reacciona con un emoji al azar a los mensajes de quien tenga un rol concreto, a ~1 de cada 10 mensajes (configurable con `REACT_CHANCE`). Usa caras por defecto y, si se quiere, los emojis del servidor.
- **Aviso al owner** (`owner_notify`) — manda un DM al dueño cuando el bot arranca (útil para saber que se ha reiniciado tras un corte de luz).
- **Información** (`serverinfo`) — `/serverinfo` (datos del servidor) y `/userinfo` (datos de un usuario).
- **Canales-contador** (`serverstats`) — dos canales de voz bloqueados cuyo nombre muestra el nº de miembros y la gente conectada en voz, actualizándose periódicamente.
- **Auto-sync de plantilla** (`template_sync`) — mantiene al día la plantilla del servidor: si detecta cambios, la sincroniza sola y lo anuncia en el canal de logs.
- **Encuestas** (`polls`) — `/encuesta` con 2–10 opciones y **tiempo límite**. Se vota con botones (un voto por persona, cambiable); al terminar borra el mensaje y publica los resultados con barras y porcentajes. Persisten en SQLite (sobreviven a reinicios).
- **Tickets** (`tickets`) — sistema estilo *Ticket Tool*: panel con botón para abrir, canal privado por ticket dentro de una categoría (solo lo ven el autor y los roles de staff), y cierre con confirmación (solo staff). Botones persistentes.
- **Charla con IA** (`ai_chat`) — en un canal configurable, el bot analiza ~1 de cada 4 mensajes (configurable) y responde con IA **siguiendo el hilo** (se le pasan los últimos mensajes) y hablando **como uno más**, imitando la jerga y el estilo del grupo (sin rol ni imitar a nadie). Usa una API **gratuita** compatible con OpenAI (por defecto **Groq**, sin tarjeta). Sabe que cuando hablan del *BOT* se refieren a ella, conoce el README para resolver dudas de comandos, y parte en varios mensajes las respuestas largas. Memoria en dos capas: **contexto manual** (`ai_context.json`, con `/ia_contexto`, `/ia_contexto_server`, `/ia_contextos`) y **memoria que aprende y consolida sola** (`ai_saved.json`): guarda datos relevantes, motes y expresiones, fusiona duplicados y compacta en cada escritura. Cada usuario guarda `id`, `nombre` y `mote` (autocompletados desde Discord al arrancar). Además: **resumen diario** opcional (la IA postea por la mañana un resumen gracioso del chat del día anterior, vía `AI_SUMMARY_CHANNEL_ID`/`AI_SUMMARY_HOUR`), y todo es **editable desde el panel web** en `/ia` (ver/editar `ai_context.json` y `ai_saved.json` y un interruptor para activar/desactivar la charla al instante).

### Comandos slash

| Comando | Descripción |
|---------|-------------|
| `/recordatorio` | Te aviso por privado en la fecha indicada |
| `/recordatorios` | Lista tus recordatorios pendientes |
| `/cancelar_recordatorio` | Cancela un recordatorio por su número |
| `/evento` | Crea un evento del servidor con fechas e imagen |
| `/clear` | Borra los últimos N mensajes del canal |
| `/stats` | Estado del bot y de la máquina (CPU/RAM/temperatura) |
| `/serverinfo` | Información del servidor |
| `/userinfo` | Información de un usuario |
| `/scrim` | Reparte a los del canal de voz en dos equipos (los mueve) |
| `/equipos` | Anuncia dos equipos al azar (no mueve) |
| `/encuesta` | Crea una encuesta con tiempo límite |
| `/ticket_panel` | Publica el panel para abrir tickets |
| `/ia_contexto` | Define el contexto personal de un usuario para la IA (staff) |
| `/ia_contexto_server` | Define el contexto del servidor para la IA (staff) |
| `/ia_contextos` | Lista los contextos de IA configurados (staff) |

---

## 🖥️ Panel web de control

Panel con tema "hacker" (verde sobre negro, lluvia matrix, scanlines) accesible desde el navegador:

- **Estado del bot** en tiempo real (activo/inactivo) y **telemetría** de la Pi: CPU, RAM, temperatura, disco y uptime.
- **Gráficas históricas** de CPU/RAM/temperatura (~30 min), dibujadas en `<canvas>` sin librerías externas.
- **Visor de logs** del bot en vivo, con auto-refresco cada 5 s y scroll inteligente.
- **Editor del `.env`** desde el navegador, con los secretos (token, contraseñas) enmascarados.
- **Acciones**: iniciar / parar / reiniciar el bot, reiniciar la Pi y lanzar una actualización completa.
- **Seguridad**: login con límite de intentos y bloqueo temporal por IP; **HTTPS local** opcional (certificado autofirmado).
- **App en el móvil**: favicon + manifest + iconos para añadirlo a la pantalla de inicio del iPhone como una app a pantalla completa.

---

## ⚙️ Configuración

Toda la configuración va en un archivo `.env` (ver `.env.example` para la lista completa con comentarios). Bloques principales:

- **Bot**: `DISCORD_TOKEN`, `GUILD_ID`, `OWNER_USER_ID`
- **Logs**: `LOG_CHANNEL_ID`, `LOG_VOICE`, `LOG_BOTS`
- **Voz temporal**: `MAIN_VOICE_CHANNEL_ID`, `TEMP_VOICE_CATEGORY_ID`, `TEMP_VOICE_LIMIT`
- **Directos**: `STREAM_ANNOUNCE_CHANNEL_ID`, `STREAM_ROLE_IDS`
- **Eventos**: `EVENT_ANNOUNCE_CHANNEL_ID`, `EVENT_LEAD_MINUTES`
- **Bienvenidas**: `WELCOME_CHANNEL_ID`, `AUTOROLE_ID`, mensajes
- **Scrims**: `SCRIM_TEAM1_CHANNEL_ID`, `SCRIM_TEAM2_CHANNEL_ID`
- **Auto-reacción**: `REACT_ROLE_ID`, `REACT_EMOJIS`, `REACT_USE_SERVER_EMOJIS`, `REACT_CHANCE`
- **Canales-contador**: `STATS_MEMBERS_CHANNEL_ID`, `STATS_VOICE_CHANNEL_ID`, nombres, `STATS_UPDATE_SECONDS`
- **Plantilla**: `TEMPLATE_AUTO_SYNC`, `TEMPLATE_SYNC_MINUTES`
- **Tickets**: `TICKET_PANEL_CHANNEL_ID`, `TICKET_CATEGORY_ID`, `TICKET_STAFF_ROLE_IDS`, textos
- **Charla con IA**: `AI_CHANNEL_ID`, `AI_CHANCE`, `AI_API_BASE`, `AI_API_KEY`, `AI_MODEL`, `AI_SYSTEM_PROMPT`
- **Panel**: `PANEL_PASSWORD`, `PANEL_PORT`, `PANEL_SECRET_KEY`, `PANEL_SSL_CERT`, `PANEL_SSL_KEY`

---

## 📁 Estructura

```
discord-bot/
├── bot.py                # arranque del bot y carga de cogs
├── config.py             # lee toda la configuración del .env
├── requirements.txt
├── .env.example          # plantilla de configuración
├── ai_context.json       # contexto manual de la IA por servidor/usuario (local, no en git)
├── ai_saved.json         # memoria que la IA guarda sola (local, no en git)
├── startup.sh            # arranque: actualiza, sincroniza con GitHub y reinicia
├── update.sh             # actualización manual completa
├── cogs/                 # cada funcionalidad en su módulo
│   ├── logs.py  tempvoice.py  reminders.py  streams.py  events.py
│   ├── moderation.py  stats.py  welcome.py  scrim.py  autoreact.py
│   ├── owner_notify.py  serverinfo.py  serverstats.py  template_sync.py
│   └── polls.py  tickets.py  ai_chat.py
├── panel/                # panel web
│   ├── app.py            # servidor Flask
│   ├── templates/        # login, dashboard, config (tema hacker)
│   └── static/           # favicon e iconos PWA
└── data/                 # bases de datos SQLite (generado, no en git)
```

---

## 🚀 Despliegue en la Raspberry Pi

El bot y el panel corren como servicios **systemd** y se actualizan solos desde GitHub en cada arranque.

- `discordbot.service` — ejecuta el bot (reinicio automático).
- `panel.service` — ejecuta el panel web (arranca con la Pi).
- `bot-startup.service` — al encender, ejecuta `startup.sh`: `apt update/upgrade`, sincroniza el repo (`git reset --hard origin/main`), instala dependencias y reinicia el bot.

Flujo de trabajo: los cambios se suben a **GitHub** y la Pi se sincroniza sola. Para aplicar a mano:

```bash
bash ~/startup.sh            # sincroniza el repo y reinicia el bot
sudo systemctl restart panel # aplica cambios del panel
```

### Acceso remoto (Tailscale)

Con [Tailscale](https://tailscale.com/) instalado, el panel es accesible desde cualquier sitio **sin abrir puertos del router** y cifrado de extremo a extremo:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4              # IP privada 100.x.y.z para entrar al panel
```

---

> Proyecto personal autoalojado. La configuración sensible (`.env`), las bases de datos y el entorno virtual no se incluyen en el repositorio.
