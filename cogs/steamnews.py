"""
Módulo 27 — Noticias oficiales de Steam.

Vigila los juegos configurados y publica en `STEAM_NEWS_CHANNEL_ID` lo que los
desarrolladores anuncian en la pestaña de novedades de Steam (parches, devblogs,
eventos), pingando al rol de cada juego.

Reparto del canal:
  - El canal principal se deja libre para el panel de reaction roles.
  - Cada juego tiene **su propio hilo** ("📰 Counter-Strike 2", "📰 Rust") y
    todas sus noticias van ahí dentro, así no se llena el canal de hilos.

De dónde salen los juegos (dos sitios, se fusionan por appid):
  - `STEAM_NEWS_JUEGOS` del `.env.avisos` (los de toda la vida).
  - `data/steam_juegos.json`, que mantiene `/noticias_juego` desde Discord.
    Si un appid está en los dos manda el del comando, que es lo último tocado.

Los datos salen de la Steam Web API (`ISteamNews/GetNewsForApp`), que es
pública y no necesita clave. Se piden solo los anuncios oficiales
(`steam_community_announcements`, `feed_type == 1`): el feed trae además
noticias de PC Gamer, PCGamesN o SteamDB, que aquí no pintan nada.

El contenido viene en el BBCode de Steam ([p], [list], [h2], [img]...) y
`_a_markdown()` lo traduce a lo que entiende Discord.

**Ancho de los embeds**: Discord estrecha el embed hasta el texto más largo
salvo que lleve imagen, y entonces lo estira al ancho máximo. Como no todas las
noticias traen foto, las que no la llevan van con un PNG transparente de
1024x2 px (`_espaciador()`): no se ve, pero fuerza el ancho máximo. Más ancho =
menos líneas = menos scroll.

**Hilos vivos**: Discord archiva un hilo si nadie habla en él (7 días como
mucho). Cada día a `STEAM_NEWS_KEEPALIVE_HOUR` el bot pasa por cada hilo, lo
desarchiva si hacía falta, suelta un mensaje y lo borra al momento: cuenta como
actividad y no queda rastro.

Estado en `data/steam_news.json`: por cada appid, la última noticia publicada
y el hilo que le toca. La **primera vuelta no publica nada**: solo apunta por
dónde va cada juego, para no soltar de golpe el histórico entero.

Configuración en `.env.avisos` (ver `.env.avisos.example`).
"""

import io
import os
import re
import json
import html
import base64
import asyncio
import logging
import datetime
from datetime import time as dtime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from cogs import reactionroles as rr

log = logging.getLogger("steamnews")

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(config.TIMEZONE)
except Exception:                       # sistema sin tzdata: se tira de UTC
    _TZ = datetime.timezone.utc

_DIR_DATOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ESTADO_PATH = os.path.join(_DIR_DATOS, "steam_news.json")
JUEGOS_PATH = os.path.join(_DIR_DATOS, "steam_juegos.json")

API = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
API_TIENDA = "https://store.steampowered.com/api/appdetails"
FEED_OFICIAL = "steam_community_announcements"

# Cuánto se pide y cuánto se enseña
NOTICIAS_POR_CONSULTA = 10
MAX_DESCRIPCION = 2200          # el tope de Discord es 4096, pero un tocho no lo lee nadie
DIAS_ARCHIVADO = 10080          # 7 días, el máximo de auto-archivado de un hilo
TEXTO_KEEPALIVE = "."           # se borra al segundo, no lo ve nadie

_COLOR = 0x1B2838               # el azul oscuro de Steam

# PNG transparente de 1024x2 px (88 bytes). Va como adjunto en las noticias que
# no traen imagen: Discord estira el embed hasta el ancho de la imagen, así que
# el embed sale al máximo y el "espaciador" queda como una línea invisible.
_ESPACIADOR_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAABAAAAAACCAYAAADGmq6bAAAAH0lEQVR42u3BAQ0AAADCoPdPbQ43"
    "oAAAAAAAAACAfwMgAgABNk63HgAAAABJRU5ErkJggg=="
)
_ESPACIADOR_NOMBRE = "ancho.png"


def _espaciador():
    """Un `discord.File` nuevo con el PNG invisible que ensancha el embed."""
    return discord.File(io.BytesIO(base64.b64decode(_ESPACIADOR_B64)),
                        filename=_ESPACIADOR_NOMBRE)


# --------------------------------------------------------------- BBCode
_IMG_RE = re.compile(r"\[img\s+src=[\"']?([^\"'\]\s]+)", re.I)
_YT_RE = re.compile(r"\[previewyoutube=[\"']?([\w-]+)", re.I)

# Apartan los corchetes literales de Steam mientras se limpia el BBCode. Van en
# la zona de uso privado de Unicode, así que no chocan con ningún texto real.
_MARCA_ABRE = ""
_MARCA_CIERRA = ""

# (patrón, reemplazo) en orden; se aplican sobre el texto crudo de Steam
_REGLAS = (
    # Los parches de CS2 vienen como [*][p]texto[/p][/*]: si no se juntan aquí,
    # la viñeta y su texto acaban en líneas distintas.
    (r"\[\*\]\s*\[p\]", "\n- "),
    (r"\[/p\]\s*\[/\*\]", "\n"),
    (r"\[/?p\]", "\n"),
    (r"\[h[1-6]\]", "\n## "),
    (r"\[/h[1-6]\]", "\n"),
    (r"\[/?b\]", "**"),
    (r"\[/?i\]", "*"),
    (r"\[/?u\]", "__"),
    (r"\[/?strike\]", "~~"),
    (r"\[/?noparse\]", ""),
    (r"\[url=([^\]]+)\](.+?)\[/url\]", r"[\2](\1)"),
    (r"\[\*\]", "\n- "),
    (r"\[/?list[^\]]*\]", "\n"),
    (r"\[/?olist\]", "\n"),
    (r"\[/?\*\]", ""),
    (r"\[quote[^\]]*\]", "\n> "),
    (r"\[/quote\]", "\n"),
    (r"\[/?code\]", "```"),
    (r"\[hr\]\[/hr\]", "\n---\n"),
    (r"\[previewyoutube=[^\]]*\]\[/previewyoutube\]", ""),
    (r"\[img[^\]]*\]", ""),
    (r"\[/img\]", ""),
    (r"\[/?table[^\]]*\]|\[/?tr\]|\[/?th\]|\[/?td\]", " "),
    (r"\[[^\]\n]{0,60}\]", ""),      # lo que quede de BBCode, fuera
)
_REGLAS = tuple((re.compile(p, re.I | re.S), r) for p, r in _REGLAS)


def _a_markdown(texto, url=None):
    """El BBCode de Steam -> markdown de Discord, recortado.

    Si hay que cortar se remata con un enlace a la noticia entera (`url`).
    """
    if not texto:
        return ""
    # Steam escapa los corchetes literales de los parches (los patch notes de
    # CS2 empiezan por "\[ MAP SCRIPTING ]"). Se apartan para que la limpieza
    # de BBCode no se los coma y se devuelven justo después.
    texto = texto.replace(r"\[", _MARCA_ABRE).replace(r"\]", _MARCA_CIERRA)
    for patron, sustituto in _REGLAS:
        texto = patron.sub(sustituto, texto)
    texto = texto.replace(_MARCA_ABRE, "[").replace(_MARCA_CIERRA, "]")
    texto = html.unescape(texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if len(texto) > MAX_DESCRIPCION:
        # cortar por el último salto de línea para no partir una frase
        corte = texto.rfind("\n", 0, MAX_DESCRIPCION)
        texto = texto[:corte if corte > MAX_DESCRIPCION // 2 else MAX_DESCRIPCION].rstrip()
        texto += (f"…\n\n**[Seguir leyendo en Steam]({url})**" if url else " […]")
    return texto


def _imagen(texto):
    """La primera imagen del cuerpo, para la cabecera del embed."""
    m = _IMG_RE.search(texto or "")
    if m:
        url = m.group(1).replace("{STEAM_CLAN_IMAGE}",
                                 "https://clan.cloudflare.steamstatic.com/images")
        if url.startswith("http"):
            return url
    return None


def _youtube(texto):
    m = _YT_RE.search(texto or "")
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


def _enlace(appid, gid):
    """La URL bonita de la noticia (la que trae la API es un redirect de akamai)."""
    return f"https://store.steampowered.com/news/app/{appid}/view/{gid}"


def _capsula(appid):
    """El icono del juego en Steam, para la cabecera de los embeds."""
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/capsule_231x87.jpg"


class SteamNews(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._estado = self._cargar()
        self._juegos = self._cargar_juegos()
        self._lock = asyncio.Lock()
        # Se arranca aunque todavía no haya juegos: con /noticias_juego se
        # añaden en caliente, sin reiniciar el bot.
        if config.STEAM_NEWS_ENABLED and config.STEAM_NEWS_CHANNEL_ID:
            self.comprobar.change_interval(minutes=config.STEAM_NEWS_INTERVAL)
            self.comprobar.start()
            if config.STEAM_NEWS_KEEPALIVE:
                self.mantener_hilos.start()
        else:
            log.info("Noticias de Steam apagadas (faltan canal o STEAM_NEWS_ENABLED).")

    def cog_unload(self):
        self.comprobar.cancel()
        self.mantener_hilos.cancel()

    # ------------------------------------------------------------ estado
    def _cargar(self):
        try:
            with open(ESTADO_PATH, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _guardar(self):
        os.makedirs(_DIR_DATOS, exist_ok=True)
        try:
            with open(ESTADO_PATH, "w", encoding="utf-8") as f:
                json.dump(self._estado, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            log.warning("No pude guardar %s: %s", ESTADO_PATH, exc)

    # -------------------------------------------------- juegos vigilados
    def _cargar_juegos(self):
        """Los juegos añadidos a mano con `/noticias_juego`."""
        try:
            with open(JUEGOS_PATH, encoding="utf-8") as f:
                datos = json.load(f)
        except (OSError, ValueError):
            return []
        juegos = []
        for j in datos if isinstance(datos, list) else []:
            try:
                appid = int(j["appid"])
            except (KeyError, TypeError, ValueError):
                continue
            juegos.append({
                "appid": appid,
                "rol": int(j.get("rol") or 0),
                "nombre": str(j.get("nombre") or f"App {appid}"),
                "emoji": str(j.get("emoji") or "📰"),
                "rol_auto": bool(j.get("rol_auto")),
            })
        return juegos

    def _guardar_juegos(self):
        os.makedirs(_DIR_DATOS, exist_ok=True)
        try:
            with open(JUEGOS_PATH, "w", encoding="utf-8") as f:
                json.dump(self._juegos, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            log.warning("No pude guardar %s: %s", JUEGOS_PATH, exc)

    def juegos(self):
        """Los del `.env.avisos` + los del comando (estos mandan si coinciden)."""
        fusion = {j["appid"]: dict(j) for j in config.STEAM_NEWS_JUEGOS}
        for j in self._juegos:
            fusion[j["appid"]] = dict(j)
        return list(fusion.values())

    def _juego(self, appid):
        for j in self.juegos():
            if j["appid"] == appid:
                return j
        return None

    def _fijar_juego(self, juego):
        """Guarda el juego en data/steam_juegos.json (manda sobre el .env.avisos)."""
        self._juegos = ([j for j in self._juegos if j["appid"] != juego["appid"]]
                        + [dict(juego)])
        self._guardar_juegos()

    # ------------------------------------------ rol y panel de cada juego
    def _nombre_rol(self, juego):
        return config.STEAM_NEWS_ROL_FORMATO.format(
            emoji=juego["emoji"], nombre=juego["nombre"], appid=juego["appid"])[:100]

    async def _asegurar_rol(self, guild, juego):
        """El rol de noticias del juego, creándolo si no lo hay. None si no se puede.

        El rol se clona de STEAM_NEWS_ROL_PLANTILLA (permisos, si destaca y si se
        puede mencionar) y coge un color de la paleta STEAM_NEWS_ROL_COLORES; el
        nombre sale de STEAM_NEWS_ROL_FORMATO, así que lleva el emoji del juego.
        """
        rol = guild.get_role(juego.get("rol") or 0)
        deseado = self._nombre_rol(juego)
        if rol is not None:
            # Si el rol lo creamos nosotros y luego cambian el emoji o el nombre
            # del juego, el rol se renombra solo. Los puestos a mano no se tocan.
            if juego.get("rol_auto") and rol.name != deseado:
                try:
                    await rol.edit(name=deseado, reason="Cambió el nombre del juego")
                except (discord.Forbidden, discord.HTTPException) as exc:
                    log.info("No pude renombrar el rol de %s: %s", juego["nombre"], exc)
            return rol
        if not config.STEAM_NEWS_ROL_AUTO:
            return None

        plantilla = guild.get_role(config.STEAM_NEWS_ROL_PLANTILLA or 0)
        paleta = config.STEAM_NEWS_ROL_COLORES
        usados = sum(1 for j in self.juegos() if j.get("rol_auto"))
        datos = {"name": deseado, "colour": discord.Colour(paleta[usados % len(paleta)]),
                 "mentionable": True, "hoist": False,
                 "permissions": discord.Permissions.none(),
                 "reason": "Rol de noticias de " + juego["nombre"]}
        if plantilla is not None:
            datos.update(permissions=plantilla.permissions, hoist=plantilla.hoist,
                         mentionable=plantilla.mentionable)
        try:
            rol = await guild.create_role(**datos)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("No pude crear el rol de %s: %s", juego["nombre"], exc)
            return None
        if plantilla is not None:       # que quede pegado a los de su familia
            try:
                await rol.edit(position=max(1, plantilla.position))
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.info("No pude colocar el rol de %s: %s", juego["nombre"], exc)
        juego["rol"], juego["rol_auto"] = rol.id, True
        self._fijar_juego(juego)
        log.info("Rol %s creado para %s", rol.id, juego["nombre"])
        return rol

    async def _sincronizar_panel(self, guild, forzar=False, limpiar=False):
        """Roles que falten + panel al día + republicado. Devuelve (creados, mensaje)."""
        if guild is None or not config.STEAM_NEWS_PANEL:
            return 0, None
        cog = self.bot.get_cog("ReactionRoles")
        if cog is None:
            log.warning("El cog de reaction roles no está cargado, no toco el panel.")
            return 0, None

        creados, cambios, vivos = 0, False, set()
        for juego in sorted(self.juegos(), key=lambda j: j["nombre"].lower()):
            tenia = bool(juego.get("rol"))
            rol = await self._asegurar_rol(guild, juego)
            if rol is None:
                continue
            if not tenia:
                creados += 1
            vivos.add(rol.id)
            if rr.asegurar_rol(guild.id, config.STEAM_NEWS_PANEL, rol.id,
                               juego["emoji"], juego["nombre"], auto=True):
                cambios = True

        # Los que metimos nosotros y ya no corresponden a ningún juego, fuera.
        panel = rr.obtener_panel(guild.id, config.STEAM_NEWS_PANEL) or {}
        for entrada in list(panel.get("roles", [])):
            if entrada.get("auto") and entrada["id"] not in vivos:
                if rr.quitar_rol(guild.id, config.STEAM_NEWS_PANEL, entrada["id"]):
                    cambios = True

        msg = None
        if cambios or creados or forzar:
            canal = guild.get_channel(config.STEAM_NEWS_PANEL_CANAL_ID)
            msg = await cog.publicar_panel(guild, config.STEAM_NEWS_PANEL, canal,
                                           limpiar=limpiar)
        return creados, msg

    # --------------------------------------------------------------- API
    async def _noticias(self, session, appid):
        """Anuncios oficiales del juego, del más nuevo al más viejo."""
        params = {"appid": appid, "count": NOTICIAS_POR_CONSULTA, "maxlength": 0,
                  "format": "json", "feeds": FEED_OFICIAL}
        async with session.get(API, params=params) as r:
            if r.status != 200:
                log.warning("Steam respondió %s pidiendo noticias de %s", r.status, appid)
                return []
            datos = await r.json()
        items = (datos.get("appnews") or {}).get("newsitems") or []
        # El parámetro feeds no siempre filtra: se comprueba también aquí
        oficiales = [n for n in items
                     if n.get("feed_type") == 1 or n.get("feedname") == FEED_OFICIAL]
        return sorted(oficiales, key=lambda n: n.get("date") or 0, reverse=True)

    async def _nombre_en_steam(self, session, appid):
        """El nombre del juego según la tienda. None si el App ID no existe."""
        params = {"appids": appid, "filters": "basic", "l": "spanish"}
        try:
            async with session.get(API_TIENDA, params=params) as r:
                if r.status != 200:
                    log.info("La tienda respondió %s para el appid %s", r.status, appid)
                    return None
                datos = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            log.info("No pude consultar la tienda para %s: %s", appid, exc)
            return None
        ficha = (datos or {}).get(str(appid)) or {}
        if not ficha.get("success"):
            return None
        return ((ficha.get("data") or {}).get("name") or "").strip() or None

    # -------------------------------------------------------------- hilo
    async def _hilo(self, canal, juego):
        """El hilo de ese juego, buscándolo o creándolo. None si no se puede."""
        clave = str(juego["appid"])
        guardado = self._estado.get(clave, {})
        nombre = f"{juego['emoji']} {juego['nombre']}"

        hilo = None
        if guardado.get("hilo"):
            hilo = canal.get_thread(guardado["hilo"])
            if hilo is None:                      # puede estar archivado
                try:
                    obj = await self.bot.fetch_channel(guardado["hilo"])
                    hilo = obj if isinstance(obj, discord.Thread) else None
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                    log.info("El hilo guardado de %s ya no vale (%s), creo otro", nombre, exc)
                    hilo = None
        if hilo is None:                          # ¿existe ya uno con ese nombre?
            hilo = discord.utils.get(canal.threads, name=nombre)
        if hilo is None:
            try:
                hilo = await canal.create_thread(
                    name=nombre, type=discord.ChannelType.public_thread,
                    auto_archive_duration=DIAS_ARCHIVADO,
                    reason="Hilo de noticias de Steam")
                log.info("Hilo creado para %s (%s)", nombre, hilo.id)
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning("No pude crear el hilo de %s: %s", nombre, exc)
                return None
        if hilo.archived:
            try:
                await hilo.edit(archived=False)
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning("No pude desarchivar el hilo de %s: %s", nombre, exc)
                return None
        elif hilo.name != nombre:
            # le han cambiado el nombre o el emoji con /noticias_juego
            try:
                await hilo.edit(name=nombre)
                log.info("Hilo %s renombrado a %s", hilo.id, nombre)
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.info("No pude renombrar el hilo de %s: %s", nombre, exc)
        self._estado.setdefault(clave, {})["hilo"] = hilo.id
        return hilo

    # ------------------------------------------------------------- embed
    def _embed(self, noticia, juego):
        """El embed de una noticia y, si hace falta, el adjunto que lo ensancha."""
        crudo = noticia.get("contents") or ""
        url = _enlace(juego["appid"], noticia.get("gid"))
        e = discord.Embed(
            title=(noticia.get("title") or "Sin título")[:256],
            url=url,
            description=_a_markdown(crudo, url) or "*(sin texto, mira el enlace)*",
            color=_COLOR,
            timestamp=datetime.datetime.fromtimestamp(
                noticia.get("date") or 0, datetime.timezone.utc))
        e.set_author(
            name=juego["nombre"],
            url=f"https://store.steampowered.com/news/app/{juego['appid']}",
            icon_url=_capsula(juego["appid"]))
        video = _youtube(crudo)
        if video:
            e.add_field(name="🎬 Vídeo", value=video, inline=False)
        autor = noticia.get("author")
        e.set_footer(text=f"Noticias de Steam · {autor}" if autor else "Noticias de Steam")

        # La imagen es lo que decide el ancho del embed: si la noticia trae una,
        # esa; si no, el espaciador invisible, para que salga igual de ancho.
        imagen = _imagen(crudo)
        if imagen:
            e.set_image(url=imagen)
            return e, None
        e.set_image(url=f"attachment://{_ESPACIADOR_NOMBRE}")
        return e, _espaciador()

    # ---------------------------------------------- presentación del hilo
    async def _presentar(self, canal, juego):
        """Crea el hilo de un juego y suelta dentro el mensaje de estreno.

        Se hace **una sola vez por juego** (queda apuntado en el estado). Sirve
        para dos cosas: que el hilo exista desde el minuto uno aunque el juego
        no haya sacado nada todavía, y para comprobar de un vistazo que el rol
        configurado es el que toca. El rol se enseña pero NO se pinga: aún no
        lo tiene nadie, que el panel de reaction roles se pone después.
        """
        clave = str(juego["appid"])
        if self._estado.get(clave, {}).get("presentado"):
            return False
        hilo = await self._hilo(canal, juego)
        if hilo is None:
            return False

        rol = f"<@&{juego['rol']}>" if juego["rol"] else "*(ninguno configurado)*"
        e = discord.Embed(
            title=f"{juego['emoji']} Noticias de {juego['nombre']}",
            url=f"https://store.steampowered.com/news/app/{juego['appid']}",
            description=("Aquí van a caer las novedades que publiquen los "
                         f"desarrolladores de **{juego['nombre']}** en Steam: parches, "
                         "devblogs y eventos.\n\nCoge el rol en el canal para que te "
                         "avise cuando salga algo."),
            color=_COLOR)
        e.set_thumbnail(url=_capsula(juego["appid"]))
        e.add_field(name="🔔 Avisa a", value=rol, inline=True)
        e.add_field(name="🆔 App ID", value=str(juego["appid"]), inline=True)
        e.add_field(name="⏱️ Comprueba cada",
                    value=f"{config.STEAM_NEWS_INTERVAL} min", inline=True)
        e.set_image(url=f"attachment://{_ESPACIADOR_NOMBRE}")   # a ancho máximo
        e.set_footer(text="Mensaje de estreno del hilo · solo sale una vez")

        try:
            await hilo.send(embed=e, file=_espaciador(),
                            allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("No pude presentar el hilo de %s: %s", juego["nombre"], exc)
            return False
        self._estado.setdefault(clave, {})["presentado"] = True
        self._guardar()
        log.info("Hilo de %s estrenado en %s", juego["nombre"], hilo.id)
        return True

    async def _publicar(self, canal, juego, noticia):
        hilo = await self._hilo(canal, juego)
        if hilo is None:
            return False
        rol = f"<@&{juego['rol']}> " if juego["rol"] else ""
        embed, adjunto = self._embed(noticia, juego)
        extra = {"file": adjunto} if adjunto else {}
        try:
            await hilo.send(
                content=f"{rol}**{juego['nombre']}** · {noticia.get('title') or 'Novedades'}",
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False),
                **extra)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("No pude publicar la noticia %s de %s: %s",
                        noticia.get("gid"), juego["nombre"], exc)
            return False
        return True

    # -------------------------------------------------------------- loop
    @tasks.loop(minutes=20)
    async def comprobar(self):
        async with self._lock:
            await self._vuelta()

    async def _vuelta(self, forzar=False):
        """Mira los juegos y publica lo nuevo. Devuelve cuántas ha publicado."""
        canal = self.bot.get_channel(config.STEAM_NEWS_CHANNEL_ID)
        if canal is None:
            log.warning("No encuentro el canal de noticias %s", config.STEAM_NEWS_CHANNEL_ID)
            return 0
        juegos = self.juegos()
        publicadas = 0
        # Los hilos que falten se crean y se estrenan antes de nada: así están
        # ahí desde el primer momento, y al añadir un juego nuevo aparece su
        # hilo en la siguiente vuelta sin esperar a que saquen parche.
        for juego in juegos:
            if await self._presentar(canal, juego):
                await asyncio.sleep(2)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            for juego in juegos:
                clave = str(juego["appid"])
                guardado = self._estado.setdefault(clave, {})
                try:
                    noticias = await self._noticias(session, juego["appid"])
                except Exception as exc:
                    log.warning("Fallo pidiendo noticias de %s: %s", juego["nombre"], exc)
                    continue
                if not noticias:
                    log.info("Sin anuncios oficiales para %s", juego["nombre"])
                    continue

                ultima = guardado.get("date") or 0
                if not ultima and not forzar:
                    # Primera vez: apuntar por dónde va y callarse, que si no
                    # suelta el histórico entero de golpe.
                    guardado.update(date=noticias[0].get("date") or 0,
                                    gid=noticias[0].get("gid"))
                    self._guardar()
                    log.info("Primera vuelta de %s: me quedo en '%s' sin publicar",
                             juego["nombre"], noticias[0].get("title"))
                    continue

                nuevas = [n for n in noticias
                          if (n.get("date") or 0) > ultima and n.get("gid") != guardado.get("gid")]
                if forzar and not nuevas:
                    nuevas = noticias[:1]      # /noticias forzar: la última, aunque ya se viera
                # de la más vieja a la más nueva, para que queden en orden en el hilo
                nuevas = list(reversed(nuevas[:config.STEAM_NEWS_MAX]))
                for noticia in nuevas:
                    if await self._publicar(canal, juego, noticia):
                        publicadas += 1
                        guardado.update(date=noticia.get("date") or 0, gid=noticia.get("gid"))
                        self._guardar()
                        await asyncio.sleep(2)   # sin prisa, que Discord no se queje
        return publicadas

    @comprobar.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------- mantener los hilos vivos
    @tasks.loop(time=dtime(hour=config.STEAM_NEWS_KEEPALIVE_HOUR, tzinfo=_TZ))
    async def mantener_hilos(self):
        async with self._lock:
            n = await self._keepalive()
        log.info("Keep-alive de noticias: %s hilos remozados", n)

    async def _keepalive(self):
        """Un mensaje en cada hilo, y borrado al momento, para que no se archiven.

        Discord archiva un hilo tras `auto_archive_duration` sin actividad, y el
        máximo son 7 días. Un mensaje —aunque se borre justo después— cuenta
        como actividad y reinicia la cuenta. De paso `_hilo()` desarchiva el que
        ya se hubiera cerrado.
        """
        canal = self.bot.get_channel(config.STEAM_NEWS_CHANNEL_ID)
        if canal is None:
            log.warning("Keep-alive: no encuentro el canal %s", config.STEAM_NEWS_CHANNEL_ID)
            return 0
        vivos = 0
        for juego in self.juegos():
            hilo = await self._hilo(canal, juego)
            if hilo is None:
                continue
            try:
                msg = await hilo.send(TEXTO_KEEPALIVE,
                                      allowed_mentions=discord.AllowedMentions.none())
                await asyncio.sleep(1)
                await msg.delete()
                vivos += 1
            except (discord.Forbidden, discord.HTTPException) as exc:
                log.warning("Keep-alive: fallo con el hilo de %s: %s", juego["nombre"], exc)
            await asyncio.sleep(1)
        self._guardar()
        return vivos

    @mantener_hilos.before_loop
    async def _antes_keepalive(self):
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------- comandos
    @staticmethod
    def _staff(interaction):
        return interaction.user.guild_permissions.manage_guild

    @app_commands.command(name="noticias",
                          description="Solo staff: busca noticias de Steam ahora mismo")
    @app_commands.describe(
        forzar="Publica la última noticia aunque ya se hubiera publicado",
        mantener="Pasa por los hilos para que no se archiven (prueba del keep-alive)")
    async def noticias(self, interaction: discord.Interaction,
                       forzar: bool = False, mantener: bool = False):
        if not self._staff(interaction):
            await interaction.response.send_message("Esto es cosa del staff.", ephemeral=True)
            return
        juegos = self.juegos()
        if not (config.STEAM_NEWS_CHANNEL_ID and juegos):
            await interaction.response.send_message(
                "Las noticias de Steam no están configuradas: mira `STEAM_NEWS_CHANNEL_ID` "
                "en el `.env.avisos` y añade juegos con `/noticias_juego`.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._lock:
            n = await self._vuelta(forzar=forzar)
            vivos = await self._keepalive() if mantener else 0
        nombres = ", ".join(j["nombre"] for j in juegos)
        extra = f"\nHilos remozados: **{vivos}**." if mantener else ""
        await interaction.followup.send(
            f"Listo. Publicadas **{n}** noticias en <#{config.STEAM_NEWS_CHANNEL_ID}>.\n"
            f"Juegos vigilados: {nombres}.{extra}"
            + ("" if n else "\nSi esperabas alguna, prueba con `forzar: True`."))

    @app_commands.command(
        name="noticias_juego",
        description="Solo staff: añade (o actualiza) un juego de Steam en las noticias")
    @app_commands.describe(
        appid="App ID del juego en Steam: store.steampowered.com/app/730 -> 730",
        rol="Rol al que pingar con cada noticia de este juego",
        nombre="Nombre a mostrar (por defecto, el que tenga en Steam)",
        emoji="Emoji del hilo (por defecto 📰)")
    async def noticias_juego(self, interaction: discord.Interaction, appid: int,
                             rol: discord.Role = None, nombre: str = None,
                             emoji: str = None):
        if not self._staff(interaction):
            await interaction.response.send_message("Esto es cosa del staff.", ephemeral=True)
            return
        if appid <= 0:
            await interaction.response.send_message(
                "El App ID es el número de la URL de la tienda: "
                "`store.steampowered.com/app/730/` → **730**.", ephemeral=True)
            return
        if not config.STEAM_NEWS_CHANNEL_ID:
            await interaction.response.send_message(
                "Falta `STEAM_NEWS_CHANNEL_ID` en el `.env.avisos`: sin canal no hay hilos.",
                ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            en_steam = await self._nombre_en_steam(session, appid)
            if en_steam is None and not nombre:
                await interaction.followup.send(
                    f"No encuentro el App ID **{appid}** en la tienda de Steam. Comprueba el "
                    "número o, si estás seguro de que es ese, vuélvelo a lanzar poniendo "
                    "el parámetro `nombre`.")
                return
            try:
                noticias = await self._noticias(session, appid)
            except Exception as exc:
                log.warning("Fallo pidiendo noticias de %s al añadirlo: %s", appid, exc)
                noticias = []

        ya_estaba = self._juego(appid)
        juego = {
            "appid": appid,
            "rol": rol.id if rol else (ya_estaba or {}).get("rol", 0),
            "nombre": (nombre or en_steam or (ya_estaba or {}).get("nombre")
                       or f"App {appid}").strip()[:80],
            "emoji": (emoji or (ya_estaba or {}).get("emoji") or "📰").strip()[:32],
        }
        self._juegos = [j for j in self._juegos if j["appid"] != appid] + [juego]
        self._guardar_juegos()

        # Se apunta por dónde va el feed sin publicar el histórico, igual que en
        # la primera vuelta de cualquier juego.
        guardado = self._estado.setdefault(str(appid), {})
        if noticias and not guardado.get("date"):
            guardado.update(date=noticias[0].get("date") or 0, gid=noticias[0].get("gid"))
        self._guardar()

        # Rol + panel de roles antes de estrenar el hilo, para que el mensaje de
        # presentación ya enseñe el rol bueno.
        creados, panel_msg = await self._sincronizar_panel(interaction.guild)
        juego = self._juego(appid) or juego

        canal = self.bot.get_channel(config.STEAM_NEWS_CHANNEL_ID)
        hilo = None
        if canal is not None:
            await self._presentar(canal, juego)          # crea el hilo y lo estrena
            hilo = await self._hilo(canal, juego)
            self._guardar()

        e = discord.Embed(
            title=f"{juego['emoji']} {juego['nombre']}",
            url=f"https://store.steampowered.com/app/{appid}",
            description=("Juego **actualizado**." if ya_estaba
                         else "Juego **añadido** a las noticias de Steam."),
            color=_COLOR)
        e.set_thumbnail(url=_capsula(appid))
        e.add_field(name="🆔 App ID", value=str(appid), inline=True)
        e.add_field(name="🔔 Avisa a",
                    value=f"<@&{juego['rol']}>" if juego["rol"] else "*nadie*", inline=True)
        e.add_field(name="🧵 Hilo",
                    value=hilo.mention if hilo else "*(no he podido crearlo)*", inline=True)
        e.add_field(
            name="📰 Anuncios oficiales",
            value=(f"{len(noticias)} en el feed · se publicará la próxima que saquen"
                   if noticias else "ninguno todavía; se publicará lo que saquen"),
            inline=False)
        if config.STEAM_NEWS_PANEL:
            e.add_field(
                name="🎛️ Panel de roles",
                value=((f"Rol **creado** y panel `{config.STEAM_NEWS_PANEL}` actualizado"
                        if creados else f"Panel `{config.STEAM_NEWS_PANEL}` actualizado")
                       + (f" · {panel_msg.jump_url}" if panel_msg else
                          " · *(no pude republicarlo, mira los logs)*")),
                inline=False)
        e.set_footer(text="Guardado en data/steam_juegos.json · no hace falta reiniciar el bot")
        await interaction.followup.send(embed=e,
                                        allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="noticias_borrar",
                          description="Solo staff: deja de vigilar un juego de Steam")
    @app_commands.describe(appid="App ID del juego que se deja de vigilar",
                           borrar_hilo="Borra también el hilo con todas sus noticias",
                           borrar_rol="Borra también el rol, si lo creó el bot")
    async def noticias_borrar(self, interaction: discord.Interaction, appid: int,
                              borrar_hilo: bool = False, borrar_rol: bool = False):
        if not self._staff(interaction):
            await interaction.response.send_message("Esto es cosa del staff.", ephemeral=True)
            return
        juego = self._juego(appid)
        if juego is None:
            await interaction.response.send_message(
                f"No estoy vigilando el App ID **{appid}**. Míralos con `/noticias_lista`.",
                ephemeral=True)
            return
        if not any(j["appid"] == appid for j in self._juegos):
            await interaction.response.send_message(
                f"**{juego['nombre']}** viene de `STEAM_NEWS_JUEGOS` (el `.env.avisos`), "
                "así que hay que quitarlo de ahí y reiniciar el bot.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)

        self._juegos = [j for j in self._juegos if j["appid"] != appid]
        self._guardar_juegos()
        guardado = self._estado.pop(str(appid), {})
        self._guardar()

        nota = ""
        if guardado.get("hilo") and borrar_hilo:
            try:
                hilo = await self.bot.fetch_channel(guardado["hilo"])
                await hilo.delete()
                nota = " El hilo también se ha borrado."
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                log.info("No pude borrar el hilo de %s: %s", juego["nombre"], exc)
                nota = " El hilo no he podido borrarlo, bórralo a mano."
        elif guardado.get("hilo"):
            nota = " El hilo se queda con lo que ya se publicó."

        # Fuera del panel de roles, y el rol también si lo creamos nosotros.
        if juego.get("rol") and juego.get("rol_auto") and borrar_rol:
            rol = interaction.guild.get_role(juego["rol"])
            if rol is not None:
                try:
                    await rol.delete(reason="Juego quitado de las noticias")
                    nota += " El rol también."
                except (discord.Forbidden, discord.HTTPException) as exc:
                    log.info("No pude borrar el rol de %s: %s", juego["nombre"], exc)
                    nota += " El rol no he podido borrarlo."
        _, panel_msg = await self._sincronizar_panel(interaction.guild, forzar=True)
        if config.STEAM_NEWS_PANEL and panel_msg:
            nota += f" Panel `{config.STEAM_NEWS_PANEL}` actualizado."

        await interaction.followup.send(
            f"Dejo de vigilar **{juego['nombre']}** (`{appid}`).{nota}")

    @app_commands.command(
        name="noticias_panel",
        description="Solo staff: rehace el panel de roles con todos los juegos vigilados")
    @app_commands.describe(
        limpiar="Borra los mensajes del bot en el canal y publica el panel de cero")
    async def noticias_panel(self, interaction: discord.Interaction, limpiar: bool = False):
        if not self._staff(interaction):
            await interaction.response.send_message("Esto es cosa del staff.", ephemeral=True)
            return
        if not config.STEAM_NEWS_PANEL:
            await interaction.response.send_message(
                "Falta `STEAM_NEWS_PANEL` en el `.env.avisos`: ahí va el nombre del "
                "panel de `/roles_crear` que quieres que se mantenga solo.", ephemeral=True)
            return
        if rr.obtener_panel(interaction.guild.id, config.STEAM_NEWS_PANEL) is None:
            await interaction.response.send_message(
                f"No existe el panel `{config.STEAM_NEWS_PANEL}`. Créalo antes con "
                f"`/roles_crear {config.STEAM_NEWS_PANEL}`.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        creados, msg = await self._sincronizar_panel(interaction.guild, forzar=True,
                                                     limpiar=limpiar)
        juegos = self.juegos()
        if msg is None:
            await interaction.followup.send(
                "No he podido publicar el panel. Comprueba `STEAM_NEWS_PANEL_CANAL_ID` "
                "y que tengo permisos ahí.")
            return
        await interaction.followup.send(
            f"✅ Panel `{config.STEAM_NEWS_PANEL}` al día con **{len(juegos)}** juegos "
            f"(roles creados: **{creados}**).\n{msg.jump_url}")

    @app_commands.command(name="noticias_lista",
                          description="Solo staff: juegos vigilados en las noticias de Steam")
    async def noticias_lista(self, interaction: discord.Interaction):
        if not self._staff(interaction):
            await interaction.response.send_message("Esto es cosa del staff.", ephemeral=True)
            return
        juegos = self.juegos()
        if not juegos:
            await interaction.response.send_message(
                "No vigilo ningún juego todavía. Añade uno con `/noticias_juego appid:730`.",
                ephemeral=True)
            return
        propios = {j["appid"] for j in self._juegos}
        e = discord.Embed(
            title="📰 Juegos vigilados en Steam",
            description=(f"Canal: <#{config.STEAM_NEWS_CHANNEL_ID}> · "
                         f"cada **{config.STEAM_NEWS_INTERVAL} min**"),
            color=_COLOR)
        for juego in sorted(juegos, key=lambda j: j["nombre"].lower())[:24]:
            guardado = self._estado.get(str(juego["appid"]), {})
            lineas = [
                f"🆔 `{juego['appid']}` · {'comando' if juego['appid'] in propios else '.env'}",
                "🔔 " + (f"<@&{juego['rol']}>" if juego["rol"] else "*sin rol*"),
                "🧵 " + (f"<#{guardado['hilo']}>" if guardado.get("hilo") else "*sin hilo*"),
            ]
            if guardado.get("date"):
                lineas.append(f"🕒 <t:{int(guardado['date'])}:R>")
            e.add_field(name=f"{juego['emoji']} {juego['nombre']}"[:256],
                        value="\n".join(lineas), inline=True)
        e.set_footer(
            text=(f"Los hilos se remozan cada día a las "
                  f"{config.STEAM_NEWS_KEEPALIVE_HOUR:02d}:00 ({config.TIMEZONE})")
            if config.STEAM_NEWS_KEEPALIVE
            else "Keep-alive de hilos desactivado (STEAM_NEWS_KEEPALIVE)")
        await interaction.response.send_message(
            embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @noticias_borrar.autocomplete("appid")
    async def _auto_appid(self, interaction: discord.Interaction, actual: str):
        """Sugiere los juegos que ya se vigilan al escribir el App ID."""
        opciones = []
        for juego in self.juegos():
            if actual and actual not in str(juego["appid"]) \
                    and actual.lower() not in juego["nombre"].lower():
                continue
            etiqueta = f"{juego['emoji']} {juego['nombre']} ({juego['appid']})"
            opciones.append(app_commands.Choice(name=etiqueta[:100], value=juego["appid"]))
        return opciones[:25]


async def setup(bot):
    await bot.add_cog(SteamNews(bot))
