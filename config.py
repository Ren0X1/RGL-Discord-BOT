"""
Toda la configuración se lee del archivo .env (copia .env.example a .env).
Así no escribes tokens ni IDs dentro del código.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _int(name, default=0):
    v = os.getenv(name, "").strip()
    return int(v) if v.lstrip("-").isdigit() else default


def _ids(name):
    raw = os.getenv(name, "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()]


def _bool(name, default=True):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "si", "sí")


# --- Token del bot (secreto) ---
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# Servidor principal: si lo pones, los comandos / aparecen al instante.
GUILD_ID = _int("GUILD_ID")

# --- 1) Logs ---
LOG_CHANNEL_ID = _int("LOG_CHANNEL_ID")
LOG_VOICE = _bool("LOG_VOICE", True)       # registrar entradas/salidas de voz
LOG_BOTS = _bool("LOG_BOTS", False)        # registrar acciones de otros bots

# --- 2) Canales de voz temporales ---
MAIN_VOICE_CHANNEL_ID = _int("MAIN_VOICE_CHANNEL_ID")   # canal "lobby" al que se entra
TEMP_VOICE_CATEGORY_ID = _int("TEMP_VOICE_CATEGORY_ID")  # opcional; si no, usa la del lobby
TEMP_VOICE_LIMIT = _int("TEMP_VOICE_LIMIT", 10)
TEMP_VOICE_NAME = os.getenv("TEMP_VOICE_NAME", "Voz-{name}")

# --- 4) Streams ---
STREAM_ANNOUNCE_CHANNEL_ID = _int("STREAM_ANNOUNCE_CHANNEL_ID")
STREAM_ROLE_IDS = _ids("STREAM_ROLE_IDS")   # solo avisa si el usuario tiene alguno de estos roles
STREAM_MENTION = os.getenv("STREAM_MENTION", "@everyone")

# --- 5) Eventos: aviso @everyone antes de empezar/acabar ---
EVENT_ANNOUNCE_CHANNEL_ID = _int("EVENT_ANNOUNCE_CHANNEL_ID")
EVENT_LEAD_MINUTES = _int("EVENT_LEAD_MINUTES", 10)   # minutos de antelación del aviso

# --- 6) Bienvenida / despedida + autorol ---
WELCOME_CHANNEL_ID = _int("WELCOME_CHANNEL_ID")
WELCOME_MESSAGE = os.getenv("WELCOME_MESSAGE", "¡Bienvenido/a {user} a {server}! 🎉")
GOODBYE_MESSAGE = os.getenv("GOODBYE_MESSAGE", "{user} ha salido del servidor. 👋")
AUTOROLE_ID = _int("AUTOROLE_ID")   # rol que se asigna a cada nuevo miembro

# --- 7) Scrim (repartir equipos de voz) ---
SCRIM_TEAM1_CHANNEL_ID = _int("SCRIM_TEAM1_CHANNEL_ID")
SCRIM_TEAM2_CHANNEL_ID = _int("SCRIM_TEAM2_CHANNEL_ID")

# --- 8) Auto-reacción: reacciona a los mensajes de quien tenga este rol ---
REACT_ROLE_ID = _int("REACT_ROLE_ID")

_FACES_POR_DEFECTO = (
    "😀 😃 😄 😁 😆 😅 😂 🤣 🥲 😊 😇 🙂 🙃 😉 😌 😍 🥰 😘 😗 😙 😚 😋 😛 😝 😜 "
    "🤪 🤨 🧐 🤓 😎 🥸 🤩 🥳 😏 😒 😞 😔 😟 😕 🙁 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 "
    "🤬 🤯 😳 🥵 🥶 😱 😨 😰 😥 😓 🤗 🤔 🤭 🤫 🤥 😶 😐 😑 😬 🙄 😯 😦 😧 😮 😲 "
    "🥱 😴 🤤 😪 😵 🤐 🥴 🤢 🤮 🤧 😷 🤒 🤕 🤑 🤠 😈 👿 💀 💩 🤡 👹 👺 👻 👽 🤖"
).split()


def _emojis(name, default):
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    partes = [p for p in raw.replace(",", " ").split() if p]
    return partes or default


REACT_EMOJIS = _emojis("REACT_EMOJIS", _FACES_POR_DEFECTO)
REACT_USE_SERVER_EMOJIS = _bool("REACT_USE_SERVER_EMOJIS", True)

# --- 9) Aviso al owner cuando el bot arranca ---
OWNER_USER_ID = _int("OWNER_USER_ID")

# --- General ---
TIMEZONE = os.getenv("TIMEZONE", "Europe/Madrid")

# --- Status del bot (bola amarilla + enlace) ---
STATUS_TEXT = os.getenv("STATUS_TEXT", "loscolegones.com")
STATUS_URL = os.getenv("STATUS_URL", "https://loscolegones.com")
