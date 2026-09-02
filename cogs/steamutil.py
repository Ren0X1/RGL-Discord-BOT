"""
Ayudas compartidas de Steam — las usan /cs (csstats) y /rust.

Qué hace:
  - Resolver cualquier forma de perfil de Steam a SteamID64.
  - Guardar los perfiles vinculados a cada usuario de Discord.
  - Consultar el perfil público de Steam (nombre, avatar, país, antigüedad).

Los perfiles vinculados viven en `data/steam_links.json` y los COMPARTEN /cs y
/rust: la peña vincula su Steam una vez y le vale para los dos juegos. Si aún
existe el antiguo `data/cs_links.json` se migra solo la primera vez.

Esto NO es un cog: no se registra en la tupla COGS de bot.py.
"""

import os
import re
import json
import logging

import config

log = logging.getLogger("steamutil")

_DIR_DATOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
LINKS_PATH = os.path.join(_DIR_DATOS, "steam_links.json")
LINKS_PATH_VIEJO = os.path.join(_DIR_DATOS, "cs_links.json")   # formato anterior, solo CS

STEAM_API = "https://api.steampowered.com"

_MENCION_RE = re.compile(r"^<@!?(\d+)>$")
_STEAM64_RE = re.compile(r"(7656\d{13})")
_VANITY_RE = re.compile(r"steamcommunity\.com/id/([^/?#\s]+)", re.I)


# ---------------------------------------------------------------- formateo
def miles(n):
    """12345 -> '12.345' (separador de miles a la española)."""
    if n is None:
        return "—"
    return f"{int(n):,}".replace(",", ".")


def duracion(segundos):
    """9876 -> '2 h 44 min'. Para los contadores de tiempo de Rust."""
    if not segundos:
        return "—"
    segundos = int(segundos)
    h, m = segundos // 3600, (segundos % 3600) // 60
    if h:
        return f"{miles(h)} h {m} min"
    if m:
        return f"{m} min"
    return f"{segundos} s"


def barra(valor, maximo=100, celdas=10):
    """Barra de progreso con bloques: barra(77) -> '████████░░'."""
    if valor is None:
        return "░" * celdas
    llenas = max(0, min(celdas, round((valor / maximo) * celdas)))
    return "█" * llenas + "░" * (celdas - llenas)


# ---------------------------------------------------- perfiles vinculados
def _migrar_si_hace_falta():
    """La primera vez, copia las vinculaciones del fichero antiguo de CS."""
    if os.path.exists(LINKS_PATH) or not os.path.exists(LINKS_PATH_VIEJO):
        return
    try:
        with open(LINKS_PATH_VIEJO, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d:
            guardar_links(d)
            log.info("Migradas %d vinculaciones de cs_links.json a steam_links.json", len(d))
    except (OSError, ValueError) as exc:
        log.warning("No pude migrar cs_links.json: %s", exc)


def links():
    _migrar_si_hace_falta()
    try:
        with open(LINKS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_links(d):
    os.makedirs(_DIR_DATOS, exist_ok=True)
    with open(LINKS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def link_de(uid):
    return links().get(str(uid))


def vincular(uid, steam64):
    d = links()
    d[str(uid)] = steam64
    guardar_links(d)


def desvincular(uid):
    d = links()
    if d.pop(str(uid), None) is None:
        return False
    guardar_links(d)
    return True


def discord_de(steam64):
    """SteamID64 -> ID de Discord vinculado (o None). Para listar compañeros."""
    for uid, sid in links().items():
        if sid == steam64:
            try:
                return int(uid)
            except ValueError:
                return None
    return None


# ------------------------------------------------------- resolver perfiles
async def resolver_steam64(session, texto):
    """Devuelve (steam64, error). Acepta /profiles/<id>, /id/<nombre> o el ID suelto."""
    texto = (texto or "").strip()
    v = _VANITY_RE.search(texto)
    if v:
        vanity = v.group(1)
        if not config.STEAM_API_KEY:
            return None, ("Esa URL usa nombre personalizado (`/id/...`). Necesito una `STEAM_API_KEY` "
                          "para resolverla, o pásame la URL con `/profiles/<número>`.")
        url = (f"{STEAM_API}/ISteamUser/ResolveVanityURL/v1/"
               f"?key={config.STEAM_API_KEY}&vanityurl={vanity}")
        try:
            async with session.get(url) as r:
                data = (await r.json()).get("response", {})
            if data.get("success") == 1 and data.get("steamid"):
                return data["steamid"], None
            return None, "No pude resolver ese nombre de Steam."
        except Exception as exc:
            log.warning("Vanity resolve falló: %s", exc)
            return None, "Error consultando la API de Steam."
    m = _STEAM64_RE.search(texto)
    if m:
        return m.group(1), None
    return None, "No reconozco esa URL de Steam. Pásame el enlace al perfil (`/profiles/...` o `/id/...`)."


async def resolver_objetivo(session, guild, texto):
    """Devuelve (steam64, etiqueta, error).

    Acepta una @mención o un ID de Discord (hace falta perfil vinculado), o
    directamente una URL de Steam / SteamID64.
    """
    texto = (texto or "").strip()
    m = _MENCION_RE.match(texto)
    uid = None
    if m:
        uid = int(m.group(1))
    elif texto.isdigit() and len(texto) < 17:
        uid = int(texto)
    if uid is not None:
        sid = link_de(uid)
        miembro = guild.get_member(uid) if guild else None
        nombre = miembro.display_name if miembro else f"<@{uid}>"
        if not sid:
            return None, nombre, (f"**{nombre}** no tiene perfil vinculado. "
                                  f"Que use `/cs_vincular` (o `/rust_vincular`) con la URL de su Steam.")
        return sid, nombre, None
    sid, err = await resolver_steam64(session, texto)
    return sid, texto, err


# -------------------------------------------------------- perfil de Steam
async def perfil_steam(session, steam64):
    """Nombre, avatar y demás del perfil público. None si no hay clave o falla."""
    if not config.STEAM_API_KEY:
        return None
    url = f"{STEAM_API}/ISteamUser/GetPlayerSummaries/v2/?key={config.STEAM_API_KEY}&steamids={steam64}"
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            jugadores = (await r.json()).get("response", {}).get("players", [])
        return jugadores[0] if jugadores else None
    except Exception as exc:
        log.warning("GetPlayerSummaries falló: %s", exc)
        return None
