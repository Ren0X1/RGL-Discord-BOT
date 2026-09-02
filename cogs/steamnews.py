"""
Módulo 27 — Noticias oficiales de Steam.

Vigila los juegos de `STEAM_NEWS_JUEGOS` y publica en `STEAM_NEWS_CHANNEL_ID`
lo que los desarrolladores anuncian en la pestaña de novedades de Steam
(parches, devblogs, eventos), pingando al rol de cada juego.

Reparto del canal:
  - El canal principal se deja libre para el panel de reaction roles.
  - Cada juego tiene **su propio hilo** ("📰 Counter-Strike 2", "📰 Rust") y
    todas sus noticias van ahí dentro, así no se llena el canal de hilos.

Los datos salen de la Steam Web API (`ISteamNews/GetNewsForApp`), que es
pública y no necesita clave. Se piden solo los anuncios oficiales
(`steam_community_announcements`, `feed_type == 1`): el feed trae además
noticias de PC Gamer, PCGamesN o SteamDB, que aquí no pintan nada.

El contenido viene en el BBCode de Steam ([p], [list], [h2], [img]...) y
`_a_markdown()` lo traduce a lo que entiende Discord.

Estado en `data/steam_news.json`: por cada appid, la última noticia publicada
y el hilo que le toca. La **primera vuelta no publica nada**: solo apunta por
dónde va cada juego, para no soltar de golpe el histórico entero.

Configuración en `.env.avisos` (ver `.env.avisos.example`).
"""

import os
import re
import json
import html
import asyncio
import logging
import datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger("steamnews")

_DIR_DATOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ESTADO_PATH = os.path.join(_DIR_DATOS, "steam_news.json")

API = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
FEED_OFICIAL = "steam_community_announcements"

# Cuánto se pide y cuánto se enseña
NOTICIAS_POR_CONSULTA = 10
MAX_DESCRIPCION = 1400          # el tope de Discord es 4096, pero un tocho no lo lee nadie
DIAS_ARCHIVADO = 10080          # 7 días, el máximo de auto-archivado de un hilo

_COLOR = 0x1B2838               # el azul oscuro de Steam


# --------------------------------------------------------------- BBCode
_IMG_RE = re.compile(r"\[img\s+src=[\"']?([^\"'\]\s]+)", re.I)
_YT_RE = re.compile(r"\[previewyoutube=[\"']?([\w-]+)", re.I)

# Apartan los corchetes literales de Steam mientras se limpia el BBCode. Van en
# la zona de uso privado de Unicode, así que no chocan con ningún texto real.
_MARCA_ABRE = "\ue000"
_MARCA_CIERRA = "\ue001"

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


def _a_markdown(texto):
    """El BBCode de Steam -> markdown de Discord, recortado."""
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
        texto = texto[:corte if corte > MAX_DESCRIPCION // 2 else MAX_DESCRIPCION]
        texto = texto.rstrip() + " […]"
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


class SteamNews(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._estado = self._cargar()
        self._lock = asyncio.Lock()
        if config.STEAM_NEWS_ENABLED and config.STEAM_NEWS_CHANNEL_ID and config.STEAM_NEWS_JUEGOS:
            self.comprobar.change_interval(minutes=config.STEAM_NEWS_INTERVAL)
            self.comprobar.start()
        else:
            log.info("Noticias de Steam apagadas (faltan canal, juegos o STEAM_NEWS_ENABLED).")

    def cog_unload(self):
        self.comprobar.cancel()

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
        self._estado.setdefault(clave, {})["hilo"] = hilo.id
        return hilo

    # ------------------------------------------------------------- embed
    def _embed(self, noticia, juego):
        crudo = noticia.get("contents") or ""
        e = discord.Embed(
            title=(noticia.get("title") or "Sin título")[:256],
            url=_enlace(juego["appid"], noticia.get("gid")),
            description=_a_markdown(crudo) or "*(sin texto, mira el enlace)*",
            color=_COLOR,
            timestamp=datetime.datetime.fromtimestamp(
                noticia.get("date") or 0, datetime.timezone.utc))
        e.set_author(
            name=juego["nombre"],
            url=f"https://store.steampowered.com/news/app/{juego['appid']}",
            icon_url=("https://cdn.cloudflare.steamstatic.com/steam/apps/"
                      f"{juego['appid']}/capsule_231x87.jpg"))
        imagen = _imagen(crudo)
        if imagen:
            e.set_image(url=imagen)
        video = _youtube(crudo)
        if video:
            e.add_field(name="🎬 Vídeo", value=video, inline=False)
        autor = noticia.get("author")
        e.set_footer(text=f"Noticias de Steam · {autor}" if autor else "Noticias de Steam")
        return e

    async def _publicar(self, canal, juego, noticia):
        hilo = await self._hilo(canal, juego)
        if hilo is None:
            return False
        rol = f"<@&{juego['rol']}> " if juego["rol"] else ""
        try:
            await hilo.send(
                content=f"{rol}**{juego['nombre']}** · {noticia.get('title') or 'Novedades'}",
                embed=self._embed(noticia, juego),
                allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False))
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
        publicadas = 0
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            for juego in config.STEAM_NEWS_JUEGOS:
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

    # ---------------------------------------------------------- comandos
    @app_commands.command(name="noticias",
                          description="Solo staff: busca noticias de Steam ahora mismo")
    @app_commands.describe(forzar="Publica la última noticia aunque ya se hubiera publicado")
    async def noticias(self, interaction: discord.Interaction, forzar: bool = False):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Esto es cosa del staff.", ephemeral=True)
            return
        if not (config.STEAM_NEWS_CHANNEL_ID and config.STEAM_NEWS_JUEGOS):
            await interaction.response.send_message(
                "Las noticias de Steam no están configuradas: mira `STEAM_NEWS_CHANNEL_ID` "
                "y `STEAM_NEWS_JUEGOS` en el `.env.avisos`.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        async with self._lock:
            n = await self._vuelta(forzar=forzar)
        juegos = ", ".join(j["nombre"] for j in config.STEAM_NEWS_JUEGOS)
        await interaction.followup.send(
            f"Listo. Publicadas **{n}** noticias en <#{config.STEAM_NEWS_CHANNEL_ID}>.\n"
            f"Juegos vigilados: {juegos}."
            + ("" if n else "\nSi esperabas alguna, prueba con `forzar: True`."))


async def setup(bot):
    await bot.add_cog(SteamNews(bot))
