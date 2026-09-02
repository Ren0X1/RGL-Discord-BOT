"""
Módulo 26 — Estadísticas de Rust.

/rust [usuario|url]   -> stats del jugador + enlace a su perfil de Steam
/rust_vincular <url>  -> vincula tu cuenta de Steam
/rust_desvincular     -> la quita

Los datos salen de la **Steam Web API** (gratis), que para Rust (appid 252490)
publica ~150 contadores: combate, puntería, caza, farmeo, construcción y
curiosidades. Hace falta `STEAM_API_KEY` en el .env.

Ojo: Steam solo los sirve si el jugador tiene el perfil **y los detalles del
juego** en público (Perfil -> Editar -> Privacidad -> "Detalles del juego").

La vinculación se comparte con /cs: quien ya tenga el Steam vinculado allí no
tiene que volver a hacerlo (ver cogs/steamutil.py).
"""

import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs import steamutil as su

log = logging.getLogger("rust")

APPID = 252490
STEAM_API = su.STEAM_API
COLOR = 0xCD412B   # el naranja-óxido de Rust


def _g(s, *nombres):
    """Suma los contadores que existan. Rust arrastra claves duplicadas de
    versiones distintas (harvest.wood y harvested_wood), así que se suman."""
    total, encontrado = 0, False
    for n in nombres:
        if n in s:
            total += s[n] or 0
            encontrado = True
    return total if encontrado else None


def _pct(a, b):
    """a/b en porcentaje. Devuelve el número, no el texto."""
    if not b:
        return None
    return (a or 0) / b * 100


def _pct_txt(a, b):
    v = _pct(a, b)
    return "—" if v is None else f"{v:.1f}%"


def _kd(kills, muertes):
    if not muertes:
        return f"{kills}.00" if kills else "—"
    return f"{kills / muertes:.2f}"


def _linea(etiqueta, valor, ancho=12):
    return f"`{etiqueta:<{ancho}}` **{valor}**"


class Rust(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._total_logros = None   # se cachea en el primer /rust

    # -------------------------------------------------------------- API
    async def _stats(self, session, steam64):
        """Devuelve (stats, nº_logros, error)."""
        url = (f"{STEAM_API}/ISteamUserStats/GetUserStatsForGame/v2/"
               f"?appid={APPID}&key={config.STEAM_API_KEY}&steamid={steam64}")
        async with session.get(url) as r:
            if r.status == 400:
                # Steam contesta 400 tanto si no tiene el juego como si lo tiene en
                # privado. Preguntamos por su lista de juegos para saber cual es.
                return None, 0, await self._porque_400(session, steam64)
            if r.status != 200:
                return None, 0, f"Steam respondió un error ({r.status}). Prueba más tarde."
            ps = (await r.json()).get("playerstats") or {}
        stats = {x["name"]: x["value"] for x in ps.get("stats") or []}
        logros = sum(1 for a in ps.get("achievements") or [] if a.get("achieved") == 1)
        if not stats:
            return None, logros, "Esa cuenta no tiene ninguna estadística de Rust todavía."
        return stats, logros, None

    async def _porque_400(self, session, steam64):
        """Explica el 400 de Steam: no tiene Rust, o lo tiene pero oculto.

        GetOwnedGames distingue los dos casos: si devuelve la lista de juegos y
        Rust no esta, es que no lo tiene; si no devuelve nada, es privacidad.
        """
        privado = ("Steam no me deja ver esas stats: tiene la **privacidad** de por medio.\n"
                   "Se arregla en Steam → Editar perfil → Privacidad → *Detalles del juego: Público*.")
        url = (f"{STEAM_API}/IPlayerService/GetOwnedGames/v1/?key={config.STEAM_API_KEY}"
               f"&steamid={steam64}&appids_filter[0]={APPID}&format=json")
        try:
            async with session.get(url) as r:
                if r.status != 200:
                    return privado
                respuesta = (await r.json()).get("response") or {}
        except Exception as exc:
            log.debug("GetOwnedGames falló al diagnosticar: %s", exc)
            return privado
        if not respuesta:
            return privado                      # la lista de juegos esta oculta
        if not respuesta.get("games"):
            return "esa cuenta **no tiene Rust**. 🤷"
        return privado                          # lo tiene, pero con las stats ocultas

    async def _horas(self, session, steam64):
        """Horas jugadas a Rust. None si el perfil no lo publica."""
        url = (f"{STEAM_API}/IPlayerService/GetOwnedGames/v1/?key={config.STEAM_API_KEY}"
               f"&steamid={steam64}&appids_filter[0]={APPID}&format=json")
        try:
            async with session.get(url) as r:
                if r.status != 200:
                    return None
                juegos = (await r.json()).get("response", {}).get("games") or []
            return (juegos[0].get("playtime_forever") or 0) / 60 if juegos else None
        except Exception as exc:
            log.debug("GetOwnedGames falló: %s", exc)
            return None

    async def _total_logros_juego(self, session):
        """Cuántos logros tiene Rust en total (para el 'X/Y'). Se cachea."""
        if self._total_logros is not None:
            return self._total_logros
        url = f"{STEAM_API}/ISteamUserStats/GetSchemaForGame/v2/?key={config.STEAM_API_KEY}&appid={APPID}"
        try:
            async with session.get(url) as r:
                d = await r.json() if r.status == 200 else {}
            logros = d.get("game", {}).get("availableGameStats", {}).get("achievements") or []
            self._total_logros = len(logros) or None
        except Exception as exc:
            log.debug("GetSchemaForGame falló: %s", exc)
            self._total_logros = None
        return self._total_logros

    # --------------------------------------------------------- comandos
    @app_commands.command(name="rust_vincular",
                          description="Vincula tu cuenta de Steam para usar /rust sin pegar la URL")
    @app_commands.describe(url="URL de tu perfil de Steam (o el SteamID64)",
                           usuario="Solo staff: vincular la cuenta de otra persona")
    async def rust_vincular(self, interaction: discord.Interaction, url: str,
                            usuario: discord.Member = None):
        await interaction.response.defer(thinking=True, ephemeral=True)
        objetivo = interaction.user
        if usuario and usuario.id != interaction.user.id:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.followup.send("Solo el staff puede vincular a otra persona.")
                return
            objetivo = usuario
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            steam64, err = await su.resolver_steam64(session, url)
        if err:
            await interaction.followup.send(f"⚠️ {err}")
            return
        su.vincular(objetivo.id, steam64)
        await interaction.followup.send(
            f"✅ Cuenta de Steam vinculada a **{objetivo.display_name}**: `{steam64}`\n"
            f"Ya puedes usar `/rust` sin parámetros — y te vale también para `/cs`.")

    @app_commands.command(name="rust_desvincular", description="Elimina tu cuenta de Steam vinculada")
    async def rust_desvincular(self, interaction: discord.Interaction):
        if not su.desvincular(interaction.user.id):
            await interaction.response.send_message("No tenías ninguna cuenta vinculada.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🗑️ Cuenta desvinculada (deja de valer también para `/cs`).", ephemeral=True)

    @app_commands.command(name="rust", description="Estadísticas de Rust de una cuenta de Steam")
    @app_commands.describe(url="URL de Steam o @usuario (vacío = tu cuenta vinculada)")
    async def rust(self, interaction: discord.Interaction, url: str = None):
        await interaction.response.defer(thinking=True, ephemeral=False)
        if not config.STEAM_API_KEY:
            await interaction.followup.send(
                "⚠️ Falta la `STEAM_API_KEY` en el `.env`. Es gratis: "
                "<https://steamcommunity.com/dev/apikey>")
            return
        if not url:
            url = su.link_de(interaction.user.id)
            if not url:
                await interaction.followup.send(
                    "No tienes cuenta vinculada. Usa `/rust_vincular` con la URL de tu Steam, "
                    "o pásame la URL directamente.")
                return

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            steam64, _etiqueta, err = await su.resolver_objetivo(session, interaction.guild, url)
            if err:
                await interaction.followup.send(f"⚠️ {err}")
                return
            perfil = await su.perfil_steam(session, steam64)
            try:
                stats, logros, err = await self._stats(session, steam64)
            except Exception as exc:
                log.warning("Steam falló para %s: %s", steam64, exc)
                await interaction.followup.send("⚠️ No pude conectar con Steam, prueba más tarde.")
                return
            horas = await self._horas(session, steam64) if not err else None
            total_logros = await self._total_logros_juego(session) if not err else None

        enlace = (perfil or {}).get("profileurl") or f"https://steamcommunity.com/profiles/{steam64}"
        if err:
            nombre = (perfil or {}).get("personaname") or steam64
            await interaction.followup.send(f"⚠️ **{nombre}** — {err}\n🔗 {enlace}")
            return

        await interaction.followup.send(
            embed=self._embed(stats, logros, total_logros, horas, perfil, steam64, enlace))

    # ------------------------------------------------------------ embed
    def _embed(self, s, logros, total_logros, horas, perfil, steam64, enlace):
        nombre = (perfil or {}).get("personaname") or "Jugador"
        e = discord.Embed(title=f"🔫 {nombre}", url=enlace, color=COLOR)
        if (perfil or {}).get("avatarfull"):
            e.set_thumbnail(url=perfil["avatarfull"])

        # --- cabecera: lo que se mira de un vistazo ---
        kills = _g(s, "kill_player") or 0
        muertes = _g(s, "deaths") or 0
        cabecera = [f"⚔️ **{su.miles(kills)}** bajas · ☠️ **{su.miles(muertes)}** muertes · "
                    f"📊 K/D **{_kd(kills, muertes)}**"]
        extra = []
        if horas:
            extra.append(f"🕹️ {su.miles(round(horas))} h jugadas")
        if logros:
            extra.append(f"🏆 {logros}/{total_logros} logros" if total_logros else f"🏆 {logros} logros")
        if (perfil or {}).get("loccountrycode"):
            extra.append(f"📍 {perfil['loccountrycode']}")
        if extra:
            cabecera.append(" · ".join(extra))
        e.description = "\n".join(cabecera)

        # --- puntería, arma por arma, con barra ---
        armas = [
            ("Balas", _g(s, "bullet_hit_player") or 0, _g(s, "bullet_fired") or 0),
            ("Escopeta", _g(s, "shotgun_hit_player") or 0, _g(s, "shotgun_fired") or 0),
            ("Arco", _g(s, "arrow_hit_player") or 0, _g(s, "arrow_fired", "arrows_shot") or 0),
        ]
        punteria = []
        for etiqueta, dados, disparos in armas:
            if not disparos:
                continue
            p = _pct(dados, disparos)
            punteria.append(f"`{etiqueta:<9}` {su.barra(p, 50)} **{p:.1f}%** "
                            f"· {su.miles(dados)}/{su.miles(disparos)}")
        hs = _g(s, "headshot", "headshots") or 0
        if hs:
            acertados = (_g(s, "bullet_hit_player") or 0) + (_g(s, "shotgun_hit_player") or 0)
            punteria.append(f"🎯 **{su.miles(hs)}** headshots"
                            + (f" · {_pct_txt(hs, acertados)} de lo que acierta" if acertados else ""))
        if punteria:
            e.add_field(name="🎯 Puntería", value="\n".join(punteria), inline=False)

        # --- cómo la palma ---
        formas = [("Suicidios", _g(s, "death_suicide")), ("Caídas", _g(s, "death_fall")),
                  ("Lobos", _g(s, "death_wolf")), ("Osos", _g(s, "death_bear")),
                  ("Otros", _g(s, "death_entity", "death_selfinflicted"))]
        formas = [(n, v) for n, v in formas if v]
        heridas = _g(s, "wounded") or 0
        if formas or heridas:
            lineas = [_linea(n, su.miles(v), 10) for n, v in formas]
            if heridas:
                lineas.append(_linea("Tumbado", su.miles(heridas), 10))
                if _g(s, "wounded_healed"):
                    lineas.append(_linea("Revivido", su.miles(_g(s, "wounded_healed")), 10))
            if _g(s, "wounded_assisted"):
                lineas.append(_linea("Ha revivido", su.miles(_g(s, "wounded_assisted")), 10))
            e.add_field(name="💀 Cómo la palma", value="\n".join(lineas), inline=True)

        # --- caza ---
        animales = [("🐻 Osos", _g(s, "kill_bear")), ("🐺 Lobos", _g(s, "kill_wolf")),
                    ("🐗 Jabalíes", _g(s, "kill_boar")), ("🦌 Ciervos", _g(s, "kill_stag")),
                    ("🐔 Pollos", _g(s, "kill_chicken")), ("🐴 Caballos", _g(s, "kill_horse"))]
        animales = [(n, v) for n, v in animales if v]
        if animales:
            e.add_field(name="🏹 Caza",
                        value="\n".join(f"{n} **{su.miles(v)}**" for n, v in animales), inline=True)

        # --- farmeo ---
        recursos = [("Madera", _g(s, "harvest.wood", "harvested_wood")),
                    ("Piedra", _g(s, "harvest.stones", "harvested_stones")),
                    ("Metal", _g(s, "harvest.metal_ore", "acquired_metal.ore")),
                    ("Azufre", _g(s, "harvest.sulfur_ore")),
                    ("Tela", _g(s, "harvest.cloth", "harvested_cloth")),
                    ("Cuero", _g(s, "harvested_leather")),
                    ("Chatarra", _g(s, "acquired_scrap")),
                    ("Combustible", _g(s, "acquired_lowgradefuel"))]
        recursos = [(n, v) for n, v in recursos if v]
        if recursos:
            e.add_field(name="🪓 Farmeo",
                        value="\n".join(_linea(n, su.miles(v)) for n, v in recursos), inline=True)

        # --- base y saqueo ---
        base = [("Bloques", _g(s, "placed_blocks")), ("Mejorados", _g(s, "upgraded_blocks")),
                ("Planos", _g(s, "blueprint_studied")), ("Barriles", _g(s, "destroyed_barrels")),
                ("Granadas", _g(s, "grenades_thrown")), ("Cohetes", _g(s, "rocket_fired"))]
        base = [(n, v) for n, v in base if v]
        if base:
            e.add_field(name="🏠 Base y saqueo",
                        value="\n".join(_linea(n, su.miles(v), 10) for n, v in base), inline=True)

        # --- las tonterías, que son las que dan juego ---
        curiosas = []
        if _g(s, "InstrumentNotesPlayed"):
            curiosas.append(f"🎸 **{su.miles(_g(s, 'InstrumentNotesPlayed'))}** notas tocadas")
        metros = _g(s, "horse_distance_ridden")
        if metros:
            recorrido = f"{metros / 1000:.1f} km" if metros >= 1000 else f"{su.miles(metros)} m"
            curiosas.append(f"🐴 **{recorrido}** a caballo")
        if _g(s, "seconds_speaking"):
            curiosas.append(f"🎤 **{su.duracion(_g(s, 'seconds_speaking'))}** hablando")
        if _g(s, "radiation_exposure_duration"):
            curiosas.append(f"☢️ **{su.duracion(_g(s, 'radiation_exposure_duration'))}** irradiado")
        if _g(s, "cold_exposure_duration"):
            curiosas.append(f"🥶 **{su.duracion(_g(s, 'cold_exposure_duration'))}** pasando frío")
        if _g(s, "comfort_duration"):
            curiosas.append(f"🛋️ **{su.duracion(_g(s, 'comfort_duration'))}** a gustito")
        if _g(s, "cargoship_bridge_visits"):
            curiosas.append(f"🚢 **{su.miles(_g(s, 'cargoship_bridge_visits'))}** subidas al Cargo")
        if curiosas:
            e.add_field(name="🎪 Curiosidades", value="\n".join(curiosas[:6]), inline=False)

        e.add_field(name="🔗 Enlaces",
                    value=f"[Perfil de Steam]({enlace}) · "
                          f"[Stats en Steam]({enlace.rstrip('/')}/stats/{APPID}/)",
                    inline=False)
        e.set_footer(text="Datos de la Steam Web API")
        return e


async def setup(bot):
    await bot.add_cog(Rust(bot))
