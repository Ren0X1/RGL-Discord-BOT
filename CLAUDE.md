# RGL Discord BOT — contexto del proyecto

Bot de Discord (Python / discord.py 2.7) + panel web Flask, autoalojado en una
Raspberry Pi Zero 2 W. Servidor privado de colegas ("la man cave"): gamers de
Counter-Strike, humor de cachondeo entre amigos.

- **Repo**: https://github.com/Ren0X1/RGL-Discord-BOT (rama `main`)
- **Versión actual**: 0.27.0.f4
- **Autor**: Ren0X1 (renox) — responder siempre **en español**, directo y sin florituras.

---

## Entorno

| | |
|---|---|
| Máquina | Raspberry Pi Zero 2 W, Debian, Python 3.13 |
| Carpeta del bot | `/home/renox/discord-bot` |
| Usuario | `renox` · host `RnxZeroPI` |
| Servicios systemd | `discordbot`, `panel`, `bot-startup` |
| Acceso remoto | Tailscale (nunca `tailscale funnel`) |
| Servidor Discord | ID `673322136298979328` |

### Despliegue
El flujo es: **cambios → GitHub → la Pi se sincroniza**. GitHub es la fuente de verdad.

```bash
bash ~/startup.sh              # apt update + git reset --hard origin/main + pip + restart bot
sudo systemctl restart panel   # si se tocó el panel
```

### Logs
```bash
sudo journalctl -u discordbot -f      # el bot
sudo journalctl -u panel -f           # el panel
sudo journalctl -u bot-startup -b     # el arranque de la Pi (script startup.sh)
```

---

## Estructura

```
discord-bot/
├── bot.py                # MiBot(commands.Bot), tupla COGS, sync de slash commands al GUILD_ID
├── config.py             # TODA la config, leída del .env con helpers _int/_ids/_bool/_float/_emojis
├── VERSION               # versión actual, la actualiza el workflow
├── CHANGELOG.md          # el workflow saca de aquí las notas de cada release
├── requirements.txt
├── startup.sh            # actualiza la Pi y arranca el bot (lo llama bot-startup.service)
├── update.sh             # actualización manual (no lo llama nadie automáticamente)
├── .github/workflows/release.yml
├── cogs/                 # 25 módulos (ver abajo)
├── panel/
│   ├── app.py            # Flask + waitress (HTTP) / werkzeug (HTTPS)
│   ├── templates/        # login, dashboard, config, ia
│   └── static/           # iconos PWA
├── scripts/autorizar_gdrive.py
├── data/                 # TODO el estado (gitignored)
└── certs/                # certificados del panel (HTTPS opcional)
```

### `data/` — estado persistente (nada de esto va a git)
`ai_context.json`, `ai_saved.json`, `ai_state.json`, `cs_links.json`,
`levels.db`, `polls.db`, `reminders.db`, `tickets.db`,
`reaction_roles.json`, `releases_state.json`,
`gdrive_token.json`, `gdrive_client.json`

---

## Módulos (`cogs/`)

| Cog | Qué hace |
|---|---|
| `ai_chat` | Charla con IA (Groq). El módulo más complejo, ver sección propia. |
| `automod` | Anti-invitaciones externas y anti-spam/flood, con timeout opcional. |
| `autoreact` | Reacciones con caritas aleatorias a los mensajes de un rol. |
| `backup` | Backups de `data/` + `.env*` a Google Drive (OAuth). `/backup`, `/backups`. |
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
| `releases` | Anuncia nuevas releases de repos de GitHub con `@everyone`. |
| `reminders` | `/recordatorio`, `/recordatorios`, `/cancelar_recordatorio`. |
| `scrim` | `/scrim` reparte equipos, `/equipos` los anuncia. |
| `serverinfo` | `/serverinfo`, `/userinfo`. |
| `serverstats` | Canales de voz como contadores de miembros. |
| `stats` | `/stats` (telemetría de la Pi). Exporta `temperatura()`, `ram_uso()`, `cpu_percent()`, `formato_uptime()` — **reutilizadas por `health` y `botinfo`**. |
| `streams` | Avisos de directos de Twitch. |
| `template_sync` | Sincroniza la plantilla del servidor. **En silencio**: no escribe en el canal de log. |
| `tempvoice` | Canales de voz temporales. |
| `tickets` | Tickets estilo Ticket Tool. |
| `welcome` | Bienvenidas/despedidas + autorol. |

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
salto **por número de líneas cambiadas** (ignorando `VERSION` y `CHANGELOG.md`),
actualiza `VERSION`, **crea la tag y publica la release** con un ZIP.

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

---

## Backups (Google Drive)

OAuth **con la cuenta del usuario**, NO cuenta de servicio (las cuentas de servicio
no tienen cuota de Drive y la subida falla con `storageQuotaExceeded`).

- Autorización: `scripts/autorizar_gdrive.py` (una vez) → `data/gdrive_token.json`.
- La app de OAuth debe estar **PUBLICADA** en Google Cloud; en modo "Prueba" el
  refresh token caduca a los 7 días (`invalid_grant`).
- El cog crea su carpeta `RGL-Bot-Backups` en Drive (scope `drive.file`).
- Comprime `data/` + los `.env*` (al mismo nivel que `data/`), **nunca** las credenciales.
- Rota por **cantidad** (`BACKUP_KEEP`), no por días.

---

## Convenciones del proyecto

- **Todo el código y los comentarios, en español.**
- Un cog por funcionalidad; registrarlo en la tupla `COGS` de `bot.py`.
- Toda la config nueva va a `config.py` (leída del `.env`) **y** a `.env.example`.
  Excepción: valores internos que el usuario no debe tocar → constante en el cog
  (ej. `APRENDER_CADA = 5`).
- Ficheros de estado siempre en `data/`, y añadidos al `.gitignore`.
- Los comandos de staff se comprueban con `manage_guild` (o `manage_roles`) y responden `ephemeral=True`.
  Los comandos de cara a la peña (`/cs`, `/bot`, `/rank`) son **públicos**.
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

---

## Ideas pendientes

- Comparativa automática de CS entre todos los vinculados.
- Recordatorios recurrentes.
- Transcripts al cerrar tickets.
- Sistema de avisos (`/warn`, `/warnings`).
- Alertas de salud ampliadas (autoreinicio / healthcheck).
- Anuncios de GitHub para commits, PRs e issues (ahora solo releases).
