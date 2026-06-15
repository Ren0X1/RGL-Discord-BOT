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


def _float(name, default):
    try:
        return float(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


# Probabilidad de reaccionar a un mensaje válido (0.1 = 1 de cada 10 aprox.)
REACT_CHANCE = min(1.0, max(0.0, _float("REACT_CHANCE", 0.1)))

# --- 9) Aviso al owner cuando el bot arranca ---
OWNER_USER_ID = _int("OWNER_USER_ID")

# --- 10) Canales-contador (estadísticas en el nombre del canal de voz) ---
STATS_MEMBERS_CHANNEL_ID = _int("STATS_MEMBERS_CHANNEL_ID")
STATS_VOICE_CHANNEL_ID = _int("STATS_VOICE_CHANNEL_ID")
STATS_MEMBERS_NAME = os.getenv("STATS_MEMBERS_NAME", "👥 Miembros: {count}")
STATS_VOICE_NAME = os.getenv("STATS_VOICE_NAME", "🔊 En voz: {count}")
STATS_COUNT_BOTS = _bool("STATS_COUNT_BOTS", False)
# Discord limita el renombrado de canales (~2 cada 10 min). Mínimo razonable: 300s.
STATS_UPDATE_SECONDS = max(300, _int("STATS_UPDATE_SECONDS", 360))

# --- 11) Auto-sincronizar la plantilla del servidor ---
TEMPLATE_AUTO_SYNC = _bool("TEMPLATE_AUTO_SYNC", False)
TEMPLATE_SYNC_MINUTES = max(10, _int("TEMPLATE_SYNC_MINUTES", 60))

# --- 12) Sistema de tickets ---
TICKET_PANEL_CHANNEL_ID = _int("TICKET_PANEL_CHANNEL_ID")   # canal donde va el mensaje-panel
TICKET_CATEGORY_ID = _int("TICKET_CATEGORY_ID")             # categoría donde se crean los tickets
TICKET_STAFF_ROLE_IDS = _ids("TICKET_STAFF_ROLE_IDS")       # roles que atienden y cierran tickets
TICKET_PANEL_TITLE = os.getenv("TICKET_PANEL_TITLE", "🎫 Soporte")
TICKET_PANEL_TEXT = os.getenv(
    "TICKET_PANEL_TEXT",
    "¿Necesitas ayuda? Pulsa el botón de abajo para abrir un ticket y el staff te atenderá.",
)
TICKET_OPEN_MESSAGE = os.getenv(
    "TICKET_OPEN_MESSAGE",
    "Gracias por abrir un ticket. Explica tu consulta y el staff te atenderá lo antes posible.",
)

# --- General ---
TIMEZONE = os.getenv("TIMEZONE", "Europe/Madrid")

# --- Status del bot (bola amarilla + enlace) ---
STATUS_TEXT = os.getenv("STATUS_TEXT", "loscolegones.com")
STATUS_URL = os.getenv("STATUS_URL", "https://loscolegones.com")

# --- 13) Charla con IA (gratis, p.ej. Groq) en un canal ---
AI_CHANNEL_ID = _int("AI_CHANNEL_ID")
AI_CHANCE = min(1.0, max(0.0, _float("AI_CHANCE", 0.25)))   # 0.25 = 1 de cada 4 mensajes
AI_API_BASE = os.getenv("AI_API_BASE", "https://api.groq.com/openai/v1").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")
AI_MAX_TOKENS = _int("AI_MAX_TOKENS", 150)
AI_COOLDOWN = _int("AI_COOLDOWN", 6)   # segundos mínimos entre respuestas (respeta el límite de la API)
AI_HISTORY = max(0, _int("AI_HISTORY", 20))   # nº de mensajes recientes que se pasan como contexto
AI_MEMORY = _bool("AI_MEMORY", True)   # que la IA guarde sola datos relevantes en ai_saved.json
AI_SUMMARY_CHANNEL_ID = _int("AI_SUMMARY_CHANNEL_ID")   # canal donde postea el resumen diario (vacío = off)
AI_SUMMARY_HOUR = min(23, max(0, _int("AI_SUMMARY_HOUR", 11)))   # hora (0-23) del resumen diario
_AI_PROMPT_DEFECTO = (
    "Eres un colega más de un grupo de Discord de tíos jóvenes y gamers (sobre todo Counter-Strike). "
    "Hablas español de España, coloquial, en minúsculas y de cachondeo, como un mensaje de chat normal.\n"
    "REGLAS DE ESTILO (clave):\n"
    "- Responde SIEMPRE con UN solo mensaje corto: normalmente una frase, dos como mucho. Nada de párrafos ni listas.\n"
    "- NO recapitules ni repitas lo que han dicho. PROHIBIDO empezar con 'parece que', 'veo que', '¡Jajaja!', "
    "'¡Vamos!', '¡Bueno!', '¡Y por último!' ni coletillas de locutor.\n"
    "- NO empieces siempre igual, varía. No te enrolles ni expliques de más: suelta tu comentario y ya.\n"
    "- Escribe como ellos: su jerga, sus motes y sus expresiones, sin hablar fino ni con signos de exclamación dobles.\n"
    "- No hagas rol ni imites a nadie, no narres acciones (nada de asteriscos) y no pongas tu nombre delante.\n"
    "- Fíjate de qué juego o tema están hablando y mete las pullas por ahí.\n"
    "- Vacila y pica con gracia, pero sin insultos graves ni nada ofensivo de verdad. Nunca digas que eres una IA ni un bot.\n"
    "Ejemplos de tu forma de responder (corto y directo, sin recapitular):\n"
    "\"no me apetece counter hoy\" -> \"ya empezamos, seguro que es la novia que no te suelta\"\n"
    "\"jugamos al valorant?\" -> \"valorant? eso pa mariposas illo, counter o nada\"\n"
    "\"me he pillado una play\" -> \"pa jugarla a escondidas de tu novia no?\""
)
AI_SYSTEM_PROMPT = os.getenv("AI_SYSTEM_PROMPT", _AI_PROMPT_DEFECTO)
# Contexto del servidor (vale para TODOS). Predefinido aquí; editable en vivo con /ia_contexto_server.
AI_SERVER_CONTEXT = os.getenv("AI_SERVER_CONTEXT", "")
