# RGL Discord BOT — contexto del proyecto

Bot de Discord (Python / discord.py 2.7) + panel web Flask, autoalojado en una
Raspberry Pi Zero 2 W. Servidor privado de colegas ("la man cave"): gamers de
Counter-Strike y Rust, humor de cachondeo entre amigos.

- **Repo**: https://github.com/Ren0X1/RGL-Discord-BOT (rama `main`)
- **Versión actual**: 1.2.0.f0
- **Autor**: Ren0X1 (renox) — responder siempre **en español**, directo y sin florituras.

> Este fichero es el manual del proyecto y **entra en los backups automáticos**
> (ver *Backups*). Mantenerlo al día: si se toca la estructura, los módulos, el
> despliegue o los servicios, se actualiza aquí.

---

## Entorno

| | |
|---|---|
| Máquina | Raspberry Pi Zero 2 W, Debian 13 (trixie), aarch64, Python 3.13 |
| Recursos | ~415 MB RAM + 414 MB swap, 4 cores |
| Carpeta del bot | `/home/renox/discord-bot` (venv propio en `venv/`) |
| Usuario | `renox` · host `RnxZeroPI` · IP LAN `192.168.100.75` |
| Servicios systemd | `discordbot`, `panel`, `bot-startup` |
| Acceso remoto | Tailscale (nunca `tailscale funnel`) |
| Servidor Discord | ID `673322136298979328` |

### Acceso desde Windows
No hay `sshpass`, pero sí **plink** (PuTTY). Hace falta fijar la host key y, como
no hay tty, `sudo` se alimenta por stdin:

```bash
"/c/Program Files/PuTTY/plink" -batch -ssh renox@192.168.100.75 -pw <contraseña> \
  -hostkey "SHA256:6QLdPo7bY5s6iD3pZZdFe7X0fXtQ6sYmS/fKjSx0oXM" \
  "echo '<contraseña>' | sudo -S <comando>"
```

### Despliegue
El flujo es: **cambios → GitHub → la Pi se sincroniza**. GitHub es la fuente de verdad.

```bash
sudo bash /home/renox/discord-bot/startup.sh   # apt + git reset --hard origin/main + pip + restart
sudo systemctl restart panel                   # si se tocó el panel
```

> ⚠️ El script está en `~/discord-bot/startup.sh`, **no** en `~/startup.sh`.

`startup.sh` corre como root pero hace el `git` con `sudo -u renox`. Si algún
fichero del repo se queda de root, el fetch falla con
`insufficient permission for adding an object to repository database .git/objects`
y —ojo— **el script sigue adelante y arranca el bot con el código viejo**, así que
parece que ha ido bien. Se arregla y se comprueba con:

```bash
sudo chown -R renox:renox /home/renox/discord-bot
cd ~/discord-bot && cat VERSION && git log --oneline -1   # siempre verificar
```

### Logs
```bash
sudo journalctl -u discordbot -f      # el bot
sudo journalctl -u panel -f           # el panel
sudo journalctl -u bot-startup -b     # el arranque de la Pi (script startup.sh)
```

---

## Servicios systemd (arranque automático tras un reinicio)

Los tres units viven en `/etc/systemd/system/` (fuera del repo, por eso **van
dentro del backup**). Si hay que rehacer la Pi desde cero, se crean así:

### 1) `discordbot.service` — el bot
```ini
[Unit]
Description=Bot de Discord
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=renox
WorkingDirectory=/home/renox/discord-bot
ExecStart=/home/renox/discord-bot/venv/bin/python /home/renox/discord-bot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2) `panel.service` — el panel web
```ini
[Unit]
Description=Panel web de control del bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=renox
WorkingDirectory=/home/renox/discord-bot
ExecStart=/home/renox/discord-bot/venv/bin/python /home/renox/discord-bot/panel/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3) `bot-startup.service` — actualizar y arrancar al encender
`oneshot` + `RemainAfterExit`: corre una vez por arranque. `TimeoutStartSec=0`
porque un `apt upgrade` en la Zero 2 W puede tardar lo suyo.
```ini
[Unit]
Description=Actualizar sistema y bot, y arrancarlo al inicio
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash /home/renox/discord-bot/startup.sh
RemainAfterExit=yes
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

### Instalarlos
```bash
sudo nano /etc/systemd/system/discordbot.service     # pegar el contenido de arriba
sudo systemctl daemon-reload
sudo systemctl enable --now discordbot panel bot-startup
sudo systemctl status discordbot                     # comprobar
```

`enable` es lo que hace que arranquen solos tras un reinicio; `--now` además los
lanza en el momento. Después de editar un unit: `daemon-reload` + `restart`.

---

## Estructura

```
discord-bot/
├── bot.py                # MiBot(commands.Bot), tupla COGS, sync de slash commands al GUILD_ID
├── config.py             # TODA la config, leída de .env y .env.avisos
├── VERSION               # versión actual, la actualiza el workflow
├── CHANGELOG.md          # el workflow saca de aquí las notas de cada release
├── CLAUDE.md             # este fichero (va al backup)
├── requirements.txt
├── startup.sh            # actualiza la Pi y arranca el bot (lo llama bot-startup.service)
├── update.sh             # actualización manual (no lo llama nadie automáticamente)
├── .github/workflows/release.yml
├── cogs/                 # 27 cogs + steamutil (ver abajo)
├── panel/
│   ├── app.py            # Flask + waitress (HTTP) / werkzeug (HTTPS)
│   ├── templates/        # login, dashboard, config, ia
│   └── static/           # iconos PWA
├── scripts/autorizar_gdrive.py
├── data/                 # TODO el estado (gitignored)
└── certs/                # certificados del panel (HTTPS opcional)
```

### Los dos ficheros de configuración
| Fichero | Qué lleva |
|---|---|
| `.env` | Token, IDs de canales, IA, niveles, tickets, backups, claves de API… |
| `.env.avisos` | Solo lo que el bot **vigila**: repos de GitHub y juegos de Steam |

Se separaron porque las listas de repos y juegos crecen y ensuciaban el `.env`.
`config.py` carga los dos (`load_dotenv()` + `load_dotenv(.env.avisos)`); si el
segundo no existe, esas funciones simplemente quedan apagadas. Las plantillas son
`.env.example` y `.env.avisos.example`, que **sí** van a git; los reales, no.

### `data/` — estado persistente (nada de esto va a git)
`ai_context.json`, `ai_saved.json`, `ai_state.json`, `steam_links.json`,
`steam_news.json`, `levels.db`, `polls.db`, `reminders.db`, `tickets.db`,
`reaction_roles.json`, `releases_state.json`,
`gdrive_token.json`, `gdrive_client.json`

---

## Módulos (`cogs/`)

| Cog | Qué hace |
|---|---|
| `ai_chat` | Charla con IA (Groq). El módulo más complejo, ver sección propia. |
| `automod` | Anti-invitaciones externas y anti-spam/flood, con timeout opcional. |
| `autoreact` | Reacciones con caritas aleatorias a los mensajes de un rol. |
| `backup` | Backups a Google Drive (OAuth). `/backup`, `/backups`. Ver sección propia. |
| `botinfo` | `/bot` (versión, uptime, latencia, host) + resumen del sistema al arrancar. |
| `csstats` | `/cs`, `/cs_vincular`, `/cs_desvincular`, `/cs_comparar` (API de Leetify). |
| `events` | `/evento` con imagen y avisos con antelación. |
| `health` | Vigila temperatura/RAM/disco y avisa por DM al owner. |
| `levels` | XP por participar, `/rank`, `/leaderboard`, `/xp_dar`, `/xp_reset`. |
| `logs` | Registro de auditoría estilo MEE6. |
| `moderation` | `/clear`. |
| `owner_notify` | DM al owner cuando arranca el bot. |
| `polls` | `/encuesta` con botones persistentes. |
| `reactionroles` | Paneles de roles por botón, configurables por comando. |
| `releases` | Anuncia nuevas releases de repos de GitHub. Config en `.env.avisos`. |
| `reminders` | `/recordatorio`, `/recordatorios`, `/cancelar_recordatorio`. |
| `rust` | `/rust`, `/rust_vincular`, `/rust_desvincular`, `/rust_comparar` (Steam Web API). |
| `scrim` | `/scrim` reparte equipos, `/equipos` los anuncia. |
| `serverinfo` | `/serverinfo`, `/userinfo`. |
| `serverstats` | Canales de voz como contadores de miembros. |
| `stats` | `/stats` (telemetría de la Pi). Exporta `temperatura()`, `ram_uso()`, `cpu_percent()`, `formato_uptime()` — **reutilizadas por `health` y `botinfo`**. |
| `steamnews` | Noticias oficiales de Steam en hilos, por juego. Ver sección propia. |
| `streams` | Avisos de directos de Twitch. |
| `template_sync` | Sincroniza la plantilla del servidor. **En silencio**: no escribe en el canal de log. |
| `tempvoice` | Canales de voz temporales. |
| `tickets` | Tickets estilo Ticket Tool. |
| `welcome` | Bienvenidas/despedidas + autorol. |

`cogs/steamutil.py` **no es un cog** (no va en la tupla `COGS`): son las ayudas
de Steam que comparten `csstats` y `rust`.

---

## Stats de juegos (`csstats`, `rust`, `steamutil`)

### Vinculación: una cuenta de Steam **por juego**
`data/steam_links.json` guarda `{"<id de discord>": {"cs": "7656…", "rust": "7656…"}}`.
Hay quien usa una cuenta para CS y otra para Rust, así que **no** se comparten.

- La **primera** vinculación de alguien rellena los dos juegos (lo normal es
  tener una sola cuenta); a partir de ahí cada comando toca solo el suyo.
- Los formatos antiguos (un SteamID suelto por usuario, y el aún más viejo
  `data/cs_links.json`) se migran solos copiando el ID a los dos juegos, para
  no desvincular a nadie al actualizar.
- `su.link_de(uid, juego)`, `su.vincular(uid, steam64, juego)`,
  `su.desvincular(uid, juego)`, `su.resolver_objetivo(session, guild, texto, juego)`.

### Maquetado de los embeds (importante)
Los campos `inline` de Discord se reparten en filas de **hasta 3**. Medido sobre
capturas reales:

| Columnas en la fila | Ancho útil | Presupuesto |
|---|---|---|
| 3 | ~125 px | **etiqueta + valor ≤ 15 caracteres** |
| 2 | ~187 px | ≤ 24 caracteres |
| 1 (a lo ancho) | ~380 px | de sobra |

Pasarse **no** corta el texto: lo tira a la línea de abajo, y el dato queda
suelto debajo de su etiqueta. Por eso las etiquetas van cortas y los números
grandes se abrevian (`462,5K`). Si se añade una métrica, contar los caracteres.

- **Colores**: Discord no pinta texto de color dentro de un embed, así que el
  verde/rojo va como **punto delante del dato** (`🟢` / `🔴` / `⚪`).
- **Resultados de partida**: ✅ ganada, ❌ perdida, 🟰 empate.
- **Logos**: el icono cuadrado del juego en Steam va en el `author` del embed
  (`CS_ICONO`, `RUST_ICONO`); el avatar de Steam sigue en el `thumbnail`.
  Opcionalmente `CS_EMOJI` / `RUST_EMOJI` en el `.env` añaden un emoji propio
  del servidor junto al nombre del juego.

---

## `steamnews` — noticias oficiales de Steam

Publica en `STEAM_NEWS_CHANNEL_ID` lo que los desarrolladores anuncian en la
pestaña de novedades de Steam (parches, devblogs, eventos).

- **Un hilo por juego** dentro del canal (`📰 Counter-Strike 2`, `📰 Rust`), no un
  hilo por noticia: así el canal principal se queda libre para el panel de
  reaction roles con el que la peña se asigna los roles de noticias.
- Cada noticia **pinga al rol** de su juego dentro del hilo.
- Fuente: `ISteamNews/GetNewsForApp` (pública, sin clave). Se filtra a
  `feed_type == 1` / `steam_community_announcements`: el feed trae además
  noticias de PC Gamer, PCGamesN y SteamDB, que aquí no pintan nada.
- El contenido viene en el BBCode de Steam y `_a_markdown()` lo traduce.
- Estado en `data/steam_news.json` (última noticia y el hilo de cada appid).
  **La primera vuelta no publica**: solo apunta por dónde va cada juego, para no
  soltar el histórico entero de golpe.
- `/noticias` (staff) fuerza una comprobación; `/noticias forzar:True` republica
  la última aunque ya se hubiera visto (para probar).

Config en `.env.avisos`: `STEAM_NEWS_JUEGOS=appid:ID_DEL_ROL:Nombre[:emoji]`
separados por comas.

---

## `ai_chat` — el módulo delicado

Charla en `AI_CHANNEL_ID` usando **Groq** (API compatible con OpenAI, gratis).

### Comportamiento
- Responde a una fracción de mensajes (`AI_CHANCE`, ~25%) con cooldown.
- **Si le mencionan o responden a un mensaje suyo, responde SIEMPRE** (sin probabilidad).
- Divide la respuesta en **varios mensajes de Discord** (por saltos de línea), no en un `\n`.
- Inyecta el README **solo** si detecta una pregunta sobre comandos/el bot.
- Sabe que cuando hablan del "BOT" se refieren a ella.

### Memoria (dos capas)
- `data/ai_context.json` — **manual**, lo edita el staff (`/ia_contexto`, `/ia_contexto_server`).
  Estructura por usuario: `{id, nombre, mote, contexto}`.
- `data/ai_saved.json` — **aprendida**, la IA la mantiene sola. Cada dato es
  `{texto, veces, ult}`: `veces` se refuerza al repetirse y ordena la prioridad.

Funcionamiento:
- `_capturar()` se lanza **cada 5 mensajes** (`APRENDER_CADA`), aunque el bot no responda.
  Es **aditivo**: añade y refuerza, nunca reescribe lo aprendido.
- Los usuarios se mapean **por número** (`[1] Ren0X`, `[2] DaN1`), no por nombre.
- `consolidar_memoria()` corre a diario (5:00) y fusiona duplicados.
- Al arrancar completa `nombre`/`mote` que falten, consultándolos en Discord.
- Comandos de control: `/ia_memoria`, `/ia_olvidar`, `/ia_reset`, `/ia_aprender` (fuerza y diagnostica).

### Persona
Colega más del grupo: gracioso, vacilón, español coloquial. **Prohibido** hacer de
presentador o recapitular ("me parece que X está…", "Y, por último…") y **nunca**
romper el personaje hablando de que es un bot o de que lo programan.
Definida en `_AI_PROMPT_DEFECTO` (config.py) y **sobreescribible con `AI_SYSTEM_PROMPT`
en el `.env`** — si el usuario reporta que la persona no cambia, revisar esa variable primero.

### Modelos de razonamiento (importante)
`openai/gpt-oss-120b` **razona antes de responder**. Si el presupuesto de tokens es
corto se lo gasta pensando y devuelve `content` vacío → el bot se queda mudo.
Por eso `_api()` detecta estos modelos (`_es_razonador()`) y les manda
`reasoning_effort=low`, `reasoning_format=hidden` y `max_completion_tokens` amplio.
Los modelos normales siguen usando `max_tokens`.

---

## Versionado y releases

Formato propio: **`MAJOR.FEATURE.MINOR.fFIX`** (ej. `1.2.3.f1`).

El workflow `.github/workflows/release.yml` corre en cada push a `main`, decide el
salto **por número de líneas cambiadas desde la última tag** (ignorando `VERSION` y
`CHANGELOG.md`), actualiza `VERSION`, **crea la tag y publica la release** con un ZIP.

| Líneas cambiadas | Sube |
|---|---|
| ≥ 1200 | MAJOR |
| ≥ 250 | FEATURE |
| ≥ 50 | MINOR |
| < 50 | FIX |

Atajos: un commit con `major:` o `BREAKING CHANGE` fuerza MAJOR; desde
**Actions → Run workflow** se puede escribir la versión exacta.

Las notas de cada release salen de la sección correspondiente del `CHANGELOG.md`,
así que **al añadir una versión hay que crear su apartado `## [x.y.z.fN]`**.
Se calcula con:
```bash
git diff --numstat <ultima-tag> -- . ':(exclude)VERSION' ':(exclude)CHANGELOG.md' \
  | awk '{a+=$1;b+=$2} END {print a+b}'
```

---

## Backups (Google Drive)

OAuth **con la cuenta del usuario**, NO cuenta de servicio (las cuentas de servicio
no tienen cuota de Drive y la subida falla con `storageQuotaExceeded`).

- Autorización: `scripts/autorizar_gdrive.py` (una vez) → `data/gdrive_token.json`.
- La app de OAuth debe estar **PUBLICADA** en Google Cloud; en modo "Prueba" el
  refresh token caduca a los 7 días (`invalid_grant`).
- El cog crea su carpeta `RGL-Bot-Backups` en Drive (scope `drive.file`).
- Rota por **cantidad** (`BACKUP_KEEP`), no por días.

### Qué entra en el zip
Todo lo necesario para levantar el bot en una máquina limpia:

| Ruta en el zip | Qué es |
|---|---|
| `data/` | bases de datos y JSON (memoria de la IA, niveles, tickets, vinculaciones…) |
| `.env`, `.env.avisos`, `.env.example`… | **toda** la configuración (si `BACKUP_INCLUDE_ENV`) |
| `CLAUDE.md` | este manual, que documenta hasta cómo rehacer los servicios |
| `systemd/*.service` | los tres units, que viven en `/etc/systemd/system` |

Lo único que **no** se guarda son las credenciales de Drive
(`data/gdrive_token.json`, `data/gdrive_client.json`): se vuelven a autorizar con
el script y no interesa tenerlas dentro del propio backup.

---

## Convenciones del proyecto

- **Todo el código y los comentarios, en español.**
- Un cog por funcionalidad; registrarlo en la tupla `COGS` de `bot.py`.
- Config nueva → `config.py` (leída del `.env`) **y** a `.env.example`. Si es una
  lista de cosas a vigilar, va a `.env.avisos` / `.env.avisos.example`.
  Excepción: valores internos que el usuario no debe tocar → constante en el cog
  (ej. `APRENDER_CADA = 5`).
- Ficheros de estado siempre en `data/`, y añadidos al `.gitignore`.
- Los comandos de staff se comprueban con `manage_guild` (o `manage_roles`) y responden `ephemeral=True`.
  Los comandos de cara a la peña (`/cs`, `/rust`, `/bot`, `/rank`) son **públicos**.
- Persistencia: SQLite para datos que crecen (niveles, tickets, encuestas),
  JSON para configuración y memoria.
- Antes de entregar: `py_compile` + cargar TODOS los cogs para comprobar que no se rompe nada.

---

## Errores ya cometidos (no repetir)

1. **Meter el README en cada mensaje de la IA** → tono robótico de asistente. Solo bajo demanda.
2. **Reescribir la memoria entera en cada captura** → perdía datos. Debe ser aditiva.
3. **Mapear usuarios por nombre** en la memoria → fallaba en silencio. Usar índices.
4. **Guardar solo si había cambios** → el fichero `ai_saved.json` nunca se creaba.
5. **`return` mudos sin log** → fallos invisibles. Loguear siempre los caminos de error.
6. **Ordenar tags con `--sort=-creatordate`** → devolvía la tag más vieja. Ordenar por versión.
7. **`.bak` de credenciales dentro del repo** → GitHub bloqueó el push por secretos.
8. **Presupuesto de tokens corto con modelo de razonamiento** → respuestas vacías.
9. Al copiar despliegues: usar `cp -r origen/. destino/` (con el punto) o se pierden
   `.github`, `.gitignore` y `.env.example`.
10. **Una sola cuenta de Steam para CS y Rust** → `/rust_vincular` pisaba la de CS.
    Cada juego guarda la suya.
11. **Etiquetas largas en columnas de 3** → el valor se cae a la línea de abajo.
    Contar caracteres (ver *Maquetado de los embeds*).
12. **Meter la config de todo en un solo `.env`** → ilegible. Lo que se vigila
    (repos, juegos) va en `.env.avisos`.
13. **Dar por bueno un despliegue porque `startup.sh` dice "Hecho"** → si el
    `git fetch` falla por permisos, el script continúa y reinicia con el código
    de antes. Comprobar siempre `cat VERSION` en la Pi al terminar.

---

## Ideas pendientes

- Recordatorios recurrentes.
- Transcripts al cerrar tickets.
- Sistema de avisos (`/warn`, `/warnings`).
- Alertas de salud ampliadas (autoreinicio / healthcheck).
- Anuncios de GitHub para commits, PRs e issues (ahora solo releases).
- Más juegos en `steamnews` (basta con añadirlos a `STEAM_NEWS_JUEGOS`).
