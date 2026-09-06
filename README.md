# 🤖 RGL Discord BOT

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white) ![discord.py](https://img.shields.io/badge/discord.py-2.7-5865F2?style=flat-square&logo=discord&logoColor=white) ![Flask](https://img.shields.io/badge/Flask-3.1-000000?style=flat-square&logo=flask&logoColor=white) ![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite&logoColor=white) ![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-Zero%202%20W-A22846?style=flat-square&logo=raspberrypi&logoColor=white) ![Google Drive](https://img.shields.io/badge/Google%20Drive-backups-4285F4?style=flat-square&logo=googledrive&logoColor=white) ![Tailscale](https://img.shields.io/badge/Tailscale-remote%20access-242424?style=flat-square&logo=tailscale&logoColor=white)

**All-in-one Discord bot with a web control panel**, self-hosted on a **Raspberry Pi Zero 2 W**. It runs a whole private gaming server: moderation and audit logs, reminders, events, polls, tickets, XP levels, counter channels, scrims, CS2 and Rust stats, Steam news, an AI that chats like one of the group, and automatic backups to Google Drive — plus a hacker-themed web panel to manage the bot **and the machine** from any browser, remotely included.

---

## 🧰 Tech stack

| Area | Technology |
|------|------------|
| Language | Python 3.13 |
| Bot | [discord.py](https://discordpy.readthedocs.io/) 2.7 (slash commands, buttons, persistent views) |
| Web panel | Flask 3 · waitress (HTTP) · werkzeug TLS (HTTPS) |
| Database | SQLite (levels, reminders, polls, tickets) |
| State | JSON files under `data/` (AI memory, Steam links, news, reaction roles) |
| Config | python-dotenv — `.env` + `.env.avisos` |
| Panel frontend | Vanilla HTML + CSS + JS (charts drawn on `<canvas>`, zero dependencies) |
| AI | Any OpenAI-compatible API — [Groq](https://groq.com/) by default (free, no card) |
| Backups | Google Drive API (OAuth, user account) |
| Services | systemd — `discordbot`, `panel`, `bot-startup` |
| Deployment | Git (the Pi syncs itself from GitHub) + startup/update scripts |
| Remote access | Tailscale (WireGuard VPN, no ports opened) |
| Hardware | Raspberry Pi Zero 2 W (Raspberry Pi OS) |

---

## 🎮 What the bot does

Every feature lives in its own *cog* inside `cogs/`:

- 📋 **Audit log** (`logs`) — MEE6 style: deleted and edited messages, joins and leaves, bans/unbans (with the moderator, via audit log), nickname, role, avatar and username changes, channel creation/deletion and voice moves (optional).
- 🔊 **Temporary voice channels** (`tempvoice`) — joining a "lobby" channel creates your own voice channel, which is deleted when the last person leaves.
- ⏰ **Reminders** (`reminders`) — `/recordatorio`, `/recordatorios`, `/cancelar_recordatorio`. Pings you by DM on the date you set; stored in SQLite.
- 📺 **Stream alerts** (`streams`) — announces when a member with a given role goes live on Twitch.
- 📅 **Events** (`events`) — `/evento` creates server events with a date range, a cover image and automatic reminders before they start and end.
- 🛡️ **Moderation** (`moderation`) — `/clear` bulk-deletes the last N messages (works around Discord's limit on old messages).
- 📊 **Machine stats** (`stats`) — `/stats` shows latency, uptime, CPU, RAM, temperature and disk of the Pi.
- 👋 **Welcome** (`welcome`) — welcome/goodbye messages and an auto-role for new members.
- ⚔️ **Scrims and teams** (`scrim`) — `/scrim` randomly splits the people in a voice channel into two teams and **moves them**; `/equipos` only **announces** the teams.
- 😂 **Auto-react** (`autoreact`) — reacts with a random emoji to messages from anyone with a given role, on ~1 in 10 messages (`REACT_CHANCE`). Uses default faces or your own server emojis.
- 📬 **Owner notice** (`owner_notify`) — DMs the owner when the bot starts, so you know it came back after a power cut.
- ℹ️ **Server info** (`serverinfo`) — `/serverinfo` and `/userinfo`.
- 🔢 **Counter channels** (`serverstats`) — two locked voice channels whose names show the member count and how many people are in voice, refreshed periodically.
- 🧩 **Template auto-sync** (`template_sync`) — keeps the server template up to date, syncing it on its own when it detects changes.
- 🗳️ **Polls** (`polls`) — `/encuesta` with 2–10 options and a **deadline**. Voting is done with buttons (one vote each, changeable); when time is up it deletes the message and posts the results with bars and percentages. Persisted in SQLite, so they survive restarts.
- 🎫 **Tickets** (`tickets`) — *Ticket Tool* style: a panel with a button to open one, a private channel per ticket inside a category (visible only to the author and staff roles) and closing with confirmation. Persistent buttons.
- 🚀 **GitHub release alerts** (`releases`) — watches one or more repos (`GITHUB_RELEASES_REPOS`, `owner/repo`) and announces every new release in `GITHUB_RELEASES_CHANNEL_ID` with an embed and a configurable ping. On first boot it memorises the current version without posting, so it never spams the history.
- 📰 **Steam news** (`steamnews`) — publishes what developers announce on Steam (patches, devblogs, events), **one thread per game** inside a single channel, pinging that game's role. Games are added on the fly with `/noticias_juego <appid>`; a daily keep-alive keeps the threads from being archived.
- 🩺 **Health alerts** (`health`) — watches temperature, RAM and disk on the Pi and **DMs the owner** when a threshold is crossed, plus a recovery notice.
- 🚫 **Automod** (`automod`) — deletes **invites to other servers** and stops **spam/flood** (`AUTOMOD_SPAM_COUNT` messages in `AUTOMOD_SPAM_SECONDS`), with optional timeout. Staff and `AUTOMOD_EXEMPT_ROLES` are exempt.
- 🏷️ **Bot info** (`botinfo`) — `/bot`: uptime, latency, version (latest git commit), number of servers and commands, and a peek at the host.
- 🔫 **Counter-Strike stats** (`csstats`) — `/cs [@user|url]`: **Leetify rating**, ranks (Premier, FACEIT, Wingman, Renown and per-map competitive), the three skills with bars (aim/positioning/utility), round impact (clutches, opening duels, CT vs T), fine mechanics (headshots, spray, counter-strafing, preaim, reaction time), trades, utility usage and the **form of the last 10 matches**. Data from the public **Leetify API**. Also `/cs_vincular`, `/cs_desvincular` and `/cs_comparar` (up to 4 profiles).
- 🪓 **Rust stats** (`rust`) — `/rust [@user|url]`: Steam profile link, K/D, hours played, achievements, per-weapon accuracy with bars, how you die, hunting, farming, building and trivia (notes played, metres on horseback, time irradiated…). Straight from the **Steam Web API** (free, needs `STEAM_API_KEY`), which exposes ~150 in-game counters. Also `/rust_vincular`, `/rust_desvincular` and `/rust_comparar`.
- 🎚️ **Levels and XP** (`levels`) — XP for taking part, `/rank` with a progress bar, `/leaderboard` top 10 and the staff commands `/xp_dar` and `/xp_reset`.
- 🔘 **Button roles** (`reactionroles`) — panels configured by command with persistent buttons: `/roles_crear`, `/roles_add`, `/roles_publicar`…
- 💾 **Backups** (`backup`) — zips `data/`, every `.env*`, the project manual and the systemd units and uploads them to **Google Drive** on a schedule, keeping the last N. `/backup`, `/backups`.
- 🧠 **AI chat** (`ai_chat`) — in a dedicated channel the bot reads ~1 in 4 messages (configurable) and replies **following the thread**, talking **like one more of the group** instead of an assistant. Uses a **free** OpenAI-compatible API (Groq by default). It knows that when people say *the BOT* they mean her, reads the README to answer questions about commands, and splits long replies into several messages. Two-layer memory: **manual context** (`ai_context.json`, via `/ia_contexto`, `/ia_contexto_server`, `/ia_contextos`) and a **memory it builds and consolidates on its own** (`ai_saved.json`): it saves relevant facts, nicknames and catchphrases, merges duplicates and compacts on every write. It can also post a **daily summary** of the previous day's chat, and everything is editable from the web panel at `/ia`.

> 🔗 Steam accounts are linked **per game**: `/cs_vincular` and `/rust_vincular` keep their own account, because plenty of people play CS on one and Rust on another.

### ⌨️ Slash commands

| Command | What it does |
|---------|--------------|
| `/bot` · `/stats` | Bot status (uptime, latency, version) and Pi telemetry |
| `/serverinfo` · `/userinfo` | Server and user information |
| `/recordatorio` · `/recordatorios` · `/cancelar_recordatorio` | Personal reminders by DM |
| `/evento` | Creates a server event with dates and a cover image |
| `/encuesta` | Poll with buttons and a deadline |
| `/scrim` · `/equipos` | Random teams, moving people or just announcing them |
| `/rank` · `/leaderboard` | Your level and the server top 10 |
| `/cs` · `/cs_comparar` · `/cs_vincular` · `/cs_desvincular` | Counter-Strike 2 stats |
| `/rust` · `/rust_comparar` · `/rust_vincular` · `/rust_desvincular` | Rust stats |
| `/clear` | Bulk-deletes the last N messages *(staff)* |
| `/ticket_panel` | Publishes the ticket panel *(staff)* |
| `/roles_crear` · `/roles_add` · `/roles_publicar` | Button role panels *(staff)* |
| `/noticias` · `/noticias_juego` · `/noticias_borrar` · `/noticias_lista` | Steam news and the games it watches *(staff)* |
| `/backup` · `/backups` | Manual backup and the list of stored ones *(staff)* |
| `/ia_contexto` · `/ia_memoria` · `/ia_olvidar` · `/ia_reset` | AI memory and context *(staff)* |

---

## 🖥️ Web control panel

Hacker-themed panel (green on black, matrix rain, scanlines) you open in a browser:

- 📈 **Live bot status** and Pi **telemetry**: CPU, RAM, temperature, disk and uptime.
- 📉 **History charts** for CPU/RAM/temperature (~30 min), drawn on `<canvas>` with no external libraries.
- 📜 **Live log viewer**, auto-refreshing every 5 s with smart scrolling.
- ✏️ **`.env` editor** from the browser, with secrets (token, passwords) masked.
- 🧠 **AI page** (`/ia`): read and edit `ai_context.json` and `ai_saved.json`, and a switch to turn the chat on or off instantly.
- 🎛️ **Actions**: start / stop / restart the bot, reboot the Pi and run a full update.
- 🔒 **Security**: login with attempt limits and temporary per-IP lockout; optional **local HTTPS** (self-signed certificate).
- 📱 **Phone app**: favicon + manifest + icons, so you can add it to your iPhone home screen as a full-screen app.

---

## ⚙️ Configuration

Everything is read from two files (see `.env.example` and `.env.avisos.example` for the full annotated list):

**`.env`** — the bot itself:

- 🤖 **Bot**: `DISCORD_TOKEN`, `GUILD_ID`, `OWNER_USER_ID`, `TIMEZONE`
- 📋 **Logs**: `LOG_CHANNEL_ID`, `LOG_VOICE`, `LOG_BOTS`
- 🔊 **Temp voice**: `MAIN_VOICE_CHANNEL_ID`, `TEMP_VOICE_CATEGORY_ID`, `TEMP_VOICE_LIMIT`
- 📺 **Streams**: `STREAM_ANNOUNCE_CHANNEL_ID`, `STREAM_ROLE_IDS`
- 📅 **Events**: `EVENT_ANNOUNCE_CHANNEL_ID`, `EVENT_LEAD_MINUTES`
- 👋 **Welcome**: `WELCOME_CHANNEL_ID`, `AUTOROLE_ID`, messages
- ⚔️ **Scrims**: `SCRIM_TEAM1_CHANNEL_ID`, `SCRIM_TEAM2_CHANNEL_ID`
- 🔢 **Counter channels**: `STATS_MEMBERS_CHANNEL_ID`, `STATS_VOICE_CHANNEL_ID`, `STATS_UPDATE_SECONDS`
- 🎫 **Tickets**: `TICKET_PANEL_CHANNEL_ID`, `TICKET_CATEGORY_ID`, `TICKET_STAFF_ROLE_IDS`
- 🎮 **Game stats**: `STEAM_API_KEY`, `LEETIFY_API_KEY`, `CS_EMOJI`, `RUST_EMOJI`
- 🧠 **AI**: `AI_CHANNEL_ID`, `AI_CHANCE`, `AI_API_BASE`, `AI_API_KEY`, `AI_MODEL`, `AI_SYSTEM_PROMPT`
- 💾 **Backups**: `BACKUP_ENABLED`, `BACKUP_KEEP`, `BACKUP_INCLUDE_ENV`
- 🖥️ **Panel**: `PANEL_PASSWORD`, `PANEL_PORT`, `PANEL_SECRET_KEY`, `PANEL_SSL_CERT`, `PANEL_SSL_KEY`

**`.env.avisos`** — only the things the bot watches, kept apart because these lists grow:

- 🚀 `GITHUB_RELEASES_REPOS`, `GITHUB_RELEASES_CHANNEL_ID`, `GITHUB_RELEASES_INTERVAL`
- 📰 `STEAM_NEWS_CHANNEL_ID`, `STEAM_NEWS_JUEGOS`, `STEAM_NEWS_INTERVAL`, `STEAM_NEWS_KEEPALIVE_HOUR`

---

## 📁 Layout

```
discord-bot/
├── bot.py                # boots the bot and loads the cogs
├── config.py             # reads every setting from .env / .env.avisos
├── VERSION               # current version, bumped by the release workflow
├── CHANGELOG.md          # release notes are taken from here
├── requirements.txt
├── .env.example          # configuration template
├── .env.avisos.example   # template for what the bot watches
├── startup.sh            # on boot: updates the Pi, syncs with GitHub, restarts the bot
├── update.sh             # manual full update
├── cogs/                 # one module per feature (27 of them)
├── panel/                # web panel
│   ├── app.py            # Flask server
│   ├── templates/        # login, dashboard, config, ai
│   └── static/           # favicon and PWA icons
├── scripts/              # helpers (Google Drive authorisation)
└── data/                 # all persistent state (git-ignored)
```

---

## 🚀 Deployment on the Raspberry Pi

The bot and the panel run as **systemd** services and update themselves from GitHub on every boot.

- `discordbot.service` — runs the bot (auto-restart).
- `panel.service` — runs the web panel.
- `bot-startup.service` — on boot runs `startup.sh`: `apt update/upgrade`, syncs the repo (`git reset --hard origin/main`), installs dependencies and restarts the bot.

The workflow is: **changes → GitHub → the Pi syncs itself**. To apply them by hand:

```bash
sudo bash /home/renox/discord-bot/startup.sh   # sync the repo and restart the bot
sudo systemctl restart panel                   # apply panel changes
cat ~/discord-bot/VERSION                      # always check what actually got deployed
```

### 🔐 Remote access (Tailscale)

With [Tailscale](https://tailscale.com/) installed, the panel is reachable from anywhere **without opening a single router port**, end-to-end encrypted:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4              # private 100.x.y.z address to reach the panel
```

---

> 🔒 Personal self-hosted project. Sensitive configuration (`.env`), databases and the virtual environment are **not** part of this repository.
