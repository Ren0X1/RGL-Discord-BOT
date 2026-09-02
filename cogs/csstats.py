"""
Módulo 23 — Estadísticas de Counter-Strike.

/cs [usuario|url]     -> stats del jugador (API pública de Leetify)
/cs_vincular <url>    -> vincula tu cuenta de Steam
/cs_desvincular       -> la quita
/cs_comparar          -> compara hasta 4 perfiles

Datos de https://api-public.cs-prod.leetify.com (GET /v3/profile?steam64_id=...),
que publica rangos (Premier, FACEIT, Wingman, Renown, competitivo por mapa),
el Leetify rating, 21 métricas de juego y las últimas 100 partidas.

La resolución de perfiles y la vinculación viven en cogs/steamutil.py. Cada
juego guarda SU cuenta de Steam: la primera vinculación rellena las dos, pero
quien use una cuenta para CS y otra para Rust las puede separar.

LEETIFY_API_KEY es opcional (más límite). STEAM_API_KEY se usa para las URLs
con nombre personalizado (/id/...) y para sacar el avatar del jugador.
"""

import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs import steamutil as su

log = logging.getLogger("csstats")

LEETIFY_BASE = "https://api-public.cs-prod.leetify.com"

# Rangos clásicos de CS (competitivo y wingman usan esta escala 1-18)
_RANGOS_CS = {
    1: "Silver I", 2: "Silver II", 3: "Silver III", 4: "Silver IV",
    5: "Silver Elite", 6: "Silver Elite Master", 7: "Gold Nova I",
    8: "Gold Nova II", 9: "Gold Nova III", 10: "Gold Nova Master",
    11: "Master Guardian I", 12: "Master Guardian II", 13: "Master Guardian Elite",
    14: "Distinguished Master Guardian", 15: "Legendary Eagle",
    16: "Legendary Eagle Master", 17: "Supreme Master First Class",
    18: "The Global Elite",
}

# De dónde viene cada partida
_FUENTES = {"faceit": "FACEIT", "matchmaking": "Premier", "premier": "Premier",
            "esea": "ESEA", "esportal": "Esportal", "renown": "Renown"}

# Cómo acabó cada partida. Nada de cuadraditos de color: de un vistazo no se
# distinguen, y en el móvil menos.
_RESULTADOS = {"win": "✅", "won": "✅", "loss": "❌", "lose": "❌", "lost": "❌",
               "tie": "🟰", "draw": "🟰"}

# Icono cuadrado de CS2 en Steam (32x32), para la cabecera del embed
CS_ICONO = ("https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images"
            "/apps/730/8dbc71957312bbd3baea65848b545be9eae2a355.jpg")


def _rango_cs(n):
    return None if n is None else _RANGOS_CS.get(n, f"rango {n}")


def _resultado(outcome):
    return _RESULTADOS.get((outcome or "").lower(), "❔")


def _punto(v, neutro=0.0):
    """Discord no pinta texto de colores dentro de un embed, así que el verde/rojo
    lo da un punto delante del dato: verde si va por encima, rojo si por debajo."""
    if v is None:
        return "⚪"
    if v > neutro:
        return "🟢"
    return "🔴" if v < neutro else "⚪"


# Puesto de cada jugador en la comparativa
_MEDALLAS = ("🥇", "🥈", "🥉", "4️⃣")


def _fila(etiqueta, valor, ancho=9):
    """Etiqueta monoespaciada + valor.

    OJO con el ancho: en un campo de 3 columnas de Discord entran unos 15
    caracteres entre etiqueta y valor. Pasarse parte la línea y el dato se cae
    debajo. A media anchura (2 columnas) el margen sube a ~24.
    """
    return f"`{etiqueta:<{ancho}}` **{valor}**"


def _p(x, dec=1):
    """Valores que YA vienen en 0-100 (accuracy_head, spray_accuracy...)."""
    return "—" if x is None else f"{x:.{dec}f}%"


def _n(x, dec=1, suf=""):
    return "—" if x is None else f"{x:.{dec}f}{suf}"


def _r(x, dec=2):
    """Ratios por ronda (clutch, opening, ct/t_leetify): se enseñan x100 y con signo,
    que es como los pinta Leetify."""
    return "—" if x is None else f"{x * 100:+.{dec}f}"


def _color(lr):
    """El color del embed dice de un vistazo cómo va el jugador."""
    if lr is None:
        return 0xF84982        # rosa Leetify
    if lr >= 5:
        return 0x43B581        # verde
    if lr >= 1:
        return 0x3498DB        # azul
    if lr >= -1:
        return 0xF84982
    return 0xE74C3C            # rojo


class CSStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _leetify(self, session, steam64):
        headers = {"Accept": "application/json", "User-Agent": "RGL-Discord-BOT"}
        if config.LEETIFY_API_KEY:
            headers["Authorization"] = f"Bearer {config.LEETIFY_API_KEY}"
        url = f"{LEETIFY_BASE}/v3/profile?steam64_id={steam64}"
        async with session.get(url, headers=headers) as r:
            if r.status == 404:
                return None, 404
            if r.status != 200:
                return None, r.status
            return await r.json(), 200

    # --------------------------------------------------------- comandos
    @app_commands.command(name="cs_vincular",
                          description="Vincula tu perfil de Steam para usar /cs sin pegar la URL")
    @app_commands.describe(url="URL de tu perfil de Steam (o el SteamID64)",
                           usuario="Solo staff: vincular el perfil de otra persona")
    async def cs_vincular(self, interaction: discord.Interaction, url: str,
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
        tocados = su.vincular(objetivo.id, steam64, "cs")
        extra = ("\nComo no tenías nada puesto en `/rust`, te la he dejado también ahí. "
                 "Si para Rust usas otra cuenta, cámbiala con `/rust_vincular`."
                 if "rust" in tocados else
                 "\nLa cuenta de `/rust` se queda como estaba.")
        await interaction.followup.send(
            f"✅ Cuenta de **Counter-Strike** vinculada a **{objetivo.display_name}**: "
            f"`{steam64}`\nYa puedes usar `/cs` sin parámetros.{extra}")

    @app_commands.command(name="cs_desvincular", description="Elimina tu perfil de Steam vinculado")
    async def cs_desvincular(self, interaction: discord.Interaction):
        if not su.desvincular(interaction.user.id, "cs"):
            await interaction.response.send_message(
                "No tenías ninguna cuenta vinculada para Counter-Strike.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🗑️ Cuenta de Counter-Strike desvinculada. La de `/rust` sigue donde estaba.",
            ephemeral=True)

    @app_commands.command(name="cs", description="Estadísticas de Counter-Strike de un perfil de Steam (Leetify)")
    @app_commands.describe(url="URL de Steam o @usuario (vacío = tu perfil vinculado)")
    async def cs(self, interaction: discord.Interaction, url: str = None):
        await interaction.response.defer(thinking=True, ephemeral=False)   # visible para todos
        if not url:
            url = su.link_de(interaction.user.id, "cs")
            if not url:
                await interaction.followup.send(
                    "No tienes cuenta vinculada para CS. Usa `/cs_vincular` con la URL de tu Steam, "
                    "o pásame la URL directamente.")
                return

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            steam64, _etiqueta, err = await su.resolver_objetivo(session, interaction.guild, url, "cs")
            if err:
                await interaction.followup.send(f"⚠️ {err}")
                return
            try:
                prof, status = await self._leetify(session, steam64)
            except Exception as exc:
                log.warning("Leetify falló: %s", exc)
                await interaction.followup.send("⚠️ No pude conectar con Leetify, prueba más tarde.")
                return
            perfil_steam = await su.perfil_steam(session, steam64)

        if status == 404 or not prof:
            await interaction.followup.send(
                f"No encuentro stats de ese perfil en Leetify. ¿Tiene cuenta y partidas?\n"
                f"https://csstats.gg/player/{steam64}")
            return
        if status != 200:
            await interaction.followup.send(f"⚠️ Leetify respondió un error ({status}). Prueba más tarde.")
            return
        if prof.get("privacy_mode") and str(prof.get("privacy_mode")).lower() not in ("public", "0", "false"):
            await interaction.followup.send(
                f"El perfil de **{prof.get('name') or steam64}** está oculto en Leetify.\n"
                f"https://csstats.gg/player/{steam64}")
            return

        await interaction.followup.send(
            embed=self._embed(prof, steam64, perfil_steam, interaction.guild))

    @app_commands.command(name="cs_comparar", description="Compara las stats de CS de varios perfiles o usuarios")
    @app_commands.describe(jugador1="Usuario (@mención, debe estar vinculado) o URL de Steam",
                           jugador2="Usuario (@mención) o URL de Steam",
                           jugador3="Opcional", jugador4="Opcional")
    async def cs_comparar(self, interaction: discord.Interaction, jugador1: str, jugador2: str,
                          jugador3: str = None, jugador4: str = None):
        await interaction.response.defer(thinking=True, ephemeral=False)
        entradas = [x for x in (jugador1, jugador2, jugador3, jugador4) if x]
        perfiles, errores = [], []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            for texto in entradas:
                steam64, etiqueta, err = await su.resolver_objetivo(session, interaction.guild, texto, "cs")
                if err:
                    errores.append(f"⚠️ {err}")
                    continue
                try:
                    prof, status = await self._leetify(session, steam64)
                except Exception as exc:
                    log.warning("Leetify falló: %s", exc)
                    errores.append(f"⚠️ No pude consultar a **{etiqueta}**.")
                    continue
                if status != 200 or not prof:
                    errores.append(f"⚠️ Sin stats en Leetify para **{etiqueta}**.")
                    continue
                perfiles.append((prof, steam64))
        if len(perfiles) < 2:
            await interaction.followup.send(
                ("\n".join(errores) or "No pude comparar.") +
                "\n\nNecesito al menos **dos** perfiles válidos.")
            return
        await interaction.followup.send(
            content="\n".join(errores) if errores else None,
            embed=self._embed_comparativa(perfiles))

    # ------------------------------------------------------------ embed
    def _embed(self, prof, steam64, perfil_steam, guild):
        nombre = prof.get("name") or (perfil_steam or {}).get("personaname") or "Jugador"
        ranks = prof.get("ranks") or {}
        rating = prof.get("rating") or {}
        stats = prof.get("stats") or {}
        leetify_url = f"https://leetify.com/app/profile/{steam64}"
        lr = ranks.get("leetify")

        e = discord.Embed(title=nombre, url=leetify_url, color=_color(lr))
        # El logo de CS2 en la cabecera; el avatar de Steam sigue en la esquina
        e.set_author(name=f"{config.CS_EMOJI} Counter-Strike 2".strip(), icon_url=CS_ICONO)
        if (perfil_steam or {}).get("avatarfull"):
            e.set_thumbnail(url=perfil_steam["avatarfull"])

        # --- cabecera: el rating global y el balance ---
        cabecera = []
        if lr is not None:
            cabecera.append(f"{_punto(lr)} **Leetify rating {lr:+.2f}**")
        wr, tot = prof.get("winrate"), prof.get("total_matches")
        if wr is not None:
            cabecera.append(f"🏆 **{wr * 100:.0f}%** de victorias"
                            + (f" en {su.miles(tot)} partidas" if tot else ""))
        if cabecera:
            e.description = " · ".join(cabecera)

        # --- rangos, uno por linea (campo a lo ancho: aqui si caben etiquetas largas) ---
        lineas = []
        if ranks.get("premier") is not None:
            lineas.append(f"`Premier    ` **{su.miles(ranks['premier'])}** ELO")
        if ranks.get("faceit") is not None:
            elo = f" · {su.miles(ranks['faceit_elo'])} ELO" if ranks.get("faceit_elo") else ""
            lineas.append(f"`FACEIT     ` **Nivel {ranks['faceit']}**{elo}")
        if ranks.get("renown") is not None:
            lineas.append(f"`Renown     ` **{su.miles(ranks['renown'])}**")
        if ranks.get("wingman") is not None:
            lineas.append(f"`Wingman    ` **{_rango_cs(ranks['wingman'])}**")
        comp = [c for c in (ranks.get("competitive") or []) if c.get("rank")]
        if comp:
            mejor = max(comp, key=lambda c: c.get("rank") or 0)
            mapa = (mejor.get("map_name") or "").replace("de_", "").replace("cs_", "")
            lineas.append(f"`Competitivo` **{_rango_cs(mejor.get('rank'))}** ({mapa})")
        e.add_field(name="🎖️ Rangos", value="\n".join(lineas) or "Sin rangos", inline=False)

        # --- las tres habilidades base, con barra (van de 0 a 100) ---
        habilidades = [("Puntería", rating.get("aim")), ("Posición", rating.get("positioning")),
                       ("Utilidad", rating.get("utility"))]
        barras = [f"`{n:<9}` {su.barra(v)} **{_n(v, 0)}**" for n, v in habilidades if v is not None]
        if barras:
            e.add_field(name="⭐ Habilidades", value="\n".join(barras), inline=False)

        # ---------------------------------------------------------------------
        # Fila de 3 columnas. Cada columna es estrecha (~125 px): etiqueta + valor
        # no pueden pasar de ~15 caracteres o Discord parte la linea y el dato
        # se cae debajo de su etiqueta.
        # ---------------------------------------------------------------------

        # --- mecanica fina ---
        mecanica = []
        if stats.get("accuracy_head") is not None:
            mecanica.append(_fila("Headshots", _p(stats["accuracy_head"])))
        if stats.get("accuracy_enemy_spotted") is not None:
            mecanica.append(_fila("Avistando", _p(stats["accuracy_enemy_spotted"])))
        if stats.get("spray_accuracy") is not None:
            mecanica.append(_fila("Spray", _p(stats["spray_accuracy"])))
        if stats.get("counter_strafing_good_shots_ratio") is not None:
            mecanica.append(_fila("C-strafe", _p(stats["counter_strafing_good_shots_ratio"])))
        if stats.get("preaim") is not None:
            mecanica.append(_fila("Preaim", _n(stats["preaim"], 1, "°")))
        if stats.get("reaction_time_ms") is not None:
            mecanica.append(_fila("Reacción", _n(stats["reaction_time_ms"], 0, "ms")))
        if mecanica:
            e.add_field(name="🎯 Mecánica", value="\n".join(mecanica), inline=True)

        # --- duelos de apertura, CT y T por separado ---
        duelos = []
        if stats.get("ct_opening_duel_success_percentage") is not None:
            duelos.append(_fila("Gana CT", _p(stats["ct_opening_duel_success_percentage"], 0)))
        if stats.get("t_opening_duel_success_percentage") is not None:
            duelos.append(_fila("Gana T", _p(stats["t_opening_duel_success_percentage"], 0)))
        if stats.get("ct_opening_aggression_success_rate") is not None:
            duelos.append(_fila("Agres. CT", _p(stats["ct_opening_aggression_success_rate"], 0)))
        if stats.get("t_opening_aggression_success_rate") is not None:
            duelos.append(_fila("Agres. T", _p(stats["t_opening_aggression_success_rate"], 0)))
        if duelos:
            e.add_field(name="⚔️ Aperturas", value="\n".join(duelos), inline=True)

        # --- trades: cuanto venga y cuanto le vengan ---
        trades = []
        if stats.get("trade_kills_success_percentage") is not None:
            trades.append(_fila("Yo vengo", _p(stats["trade_kills_success_percentage"], 0), 10))
        if stats.get("traded_deaths_success_percentage") is not None:
            trades.append(_fila("Me vengan", _p(stats["traded_deaths_success_percentage"], 0), 10))
        if stats.get("trade_kill_opportunities_per_round") is not None:
            trades.append(_fila("Ocas/ronda",
                                _n(stats["trade_kill_opportunities_per_round"], 2), 10))
        if trades:
            e.add_field(name="🤝 Trades", value="\n".join(trades), inline=True)

        # ---------------------------------------------------------------------
        # Fila de 2 columnas: al quedar solo dos campos Discord les da media
        # anchura (~187 px), asi que aqui si caben el punto de color y las
        # etiquetas largas.
        # ---------------------------------------------------------------------

        # --- impacto por ronda (ratios, se pintan x100 como en Leetify) ---
        # Aqui lo que canta es el signo, asi que en vez de etiqueta monoespaciada
        # va el punto de color: verde si suma, rojo si resta.
        impacto = []
        for etiqueta, clave in (("Clutch", "clutch"), ("Apertura", "opening"),
                                ("Como CT", "ct_leetify"), ("Como T", "t_leetify")):
            v = rating.get(clave)
            if v is not None:
                impacto.append(f"{_punto(v)} {etiqueta} **{_r(v)}**")
        if impacto:
            e.add_field(name="💥 Por ronda", value="\n".join(impacto), inline=True)

        # --- utilidad: flashes y granadas ---
        util = []
        if stats.get("flashbang_thrown") is not None:
            util.append(_fila("Flashes", f"{_n(stats['flashbang_thrown'], 1)}/partida", 11))
        if stats.get("flashbang_hit_foe_per_flashbang") is not None:
            util.append(_fila("Ciega rival",
                              f"{_n(stats['flashbang_hit_foe_per_flashbang'], 2)}"
                              f" ({_n(stats.get('flashbang_hit_foe_avg_duration'), 1, 's')})", 11))
        if stats.get("flashbang_hit_friend_per_flashbang") is not None:
            util.append(_fila("Ciega amigo", _n(stats["flashbang_hit_friend_per_flashbang"], 2), 11))
        if stats.get("flashbang_leading_to_kill") is not None:
            util.append(_fila("Flash→baja", _p(stats["flashbang_leading_to_kill"], 0), 11))
        if stats.get("he_foes_damage_avg") is not None:
            util.append(_fila("Daño HE", _n(stats["he_foes_damage_avg"], 0), 11))
            util.append(_fila("A colegas", _n(stats.get("he_friends_damage_avg"), 0), 11))
        if stats.get("utility_on_death_avg") is not None:
            util.append(_fila("Sin usar", f"{_n(stats['utility_on_death_avg'], 0)}$/muerte", 11))
        if util:
            e.add_field(name="💣 Utilidad", value="\n".join(util), inline=True)

        # --- forma reciente ---
        recientes = prof.get("recent_matches") or []
        if recientes:
            forma = "".join(_resultado(m.get("outcome")) for m in recientes[:10])
            ganadas = sum(1 for m in recientes[:10] if (m.get("outcome") or "").lower() in ("win", "won"))
            lrs = [m.get("leetify_rating") for m in recientes[:10]
                   if isinstance(m.get("leetify_rating"), (int, float))]
            media = sum(lrs) / len(lrs) * 100 if lrs else None
            resumen = f"{forma}  **{ganadas}-{min(10, len(recientes)) - ganadas}**"
            if media is not None:
                resumen += f" · {_punto(media)} LR **{media:+.2f}**"
            lineas = [resumen, ""]
            for m in recientes[:5]:
                sc = m.get("score") or []
                marcador = f"{sc[0]}-{sc[1]}" if len(sc) == 2 else ""
                lr_m = m.get("leetify_rating")
                lr_txt = (f" · {_punto(lr_m)} **{lr_m * 100:+.2f}**"
                          if isinstance(lr_m, (int, float)) else "")
                mapa = (m.get("map_name") or "?").replace("de_", "").replace("cs_", "")
                fuente = _FUENTES.get((m.get("data_source") or "").lower(), "")
                lineas.append(f"{_resultado(m.get('outcome'))} `{mapa:<9}` `{marcador:>5}`{lr_txt}"
                              + (f" · {fuente}" if fuente else ""))
            e.add_field(name="🕹️ Últimas partidas", value="\n".join(lineas), inline=False)

        # --- con quien juega, si estan en el server ---
        companeros = []
        for t in (prof.get("recent_teammates") or [])[:10]:
            uid = su.discord_de(t.get("steam64_id"))
            if uid and guild and guild.get_member(uid):
                companeros.append(f"<@{uid}> ({t.get('recent_matches_count', 0)})")
        if companeros:
            e.add_field(name="👥 Ha jugado con", value=" · ".join(companeros[:6]), inline=False)

        # --- bans ---
        bans = prof.get("bans") or []
        if bans:
            e.add_field(name="🚨 Bans",
                        value=", ".join(str(b.get("platform", "?")) for b in bans), inline=False)

        e.add_field(name="🔗 Enlaces",
                    value=f"[Leetify]({leetify_url}) · [csstats.gg](https://csstats.gg/player/{steam64}) · "
                          f"[Steam](https://steamcommunity.com/profiles/{steam64})",
                    inline=False)
        e.set_footer(text="Datos de Leetify")
        return e

    def _embed_comparativa(self, perfiles):
        """Un campo por jugador, ordenados por Leetify rating, y al final quien
        gana cada apartado. Todos los campos van a lo ancho: con 4 jugadores y
        nombres largos cualquier reparto en columnas se parte."""
        e = discord.Embed(title="⚔️ Comparativa de Counter-Strike", color=0xF84982)
        e.set_author(name=f"{config.CS_EMOJI} Counter-Strike 2".strip(), icon_url=CS_ICONO)

        def _lr(par):
            v = (par[0].get("ranks") or {}).get("leetify")
            return v if isinstance(v, (int, float)) else float("-inf")

        orden = sorted(perfiles, key=_lr, reverse=True)

        for i, (prof, steam64) in enumerate(orden):
            ranks = prof.get("ranks") or {}
            rating = prof.get("rating") or {}
            stats = prof.get("stats") or {}
            nombre = prof.get("name") or steam64

            # primera linea: el titular, con el punto de color del rating
            titular = []
            lr = ranks.get("leetify")
            if lr is not None:
                titular.append(f"{_punto(lr)} **Rating {lr:+.2f}**")
            wr, tot = prof.get("winrate"), prof.get("total_matches")
            if wr is not None:
                titular.append(f"🏆 **{wr * 100:.0f}%**"
                               + (f" de {su.miles(tot)}" if tot else ""))
            if ranks.get("premier") is not None:
                titular.append(f"Premier **{su.miles(ranks['premier'])}**")
            elif ranks.get("faceit") is not None:
                titular.append(f"FACEIT **{ranks['faceit']}**")

            lineas = [" · ".join(titular) or "Sin rangos"]
            for etiqueta, v in (("Puntería", rating.get("aim")),
                                ("Posición", rating.get("positioning")),
                                ("Utilidad", rating.get("utility"))):
                lineas.append(f"`{etiqueta:<9}` {su.barra(v)} **{_n(v, 0)}**")

            # mecanica y impacto, en dos lineas apretadas
            mecanica = " · ".join(x for x in (
                f"HS **{_p(stats['accuracy_head'])}**" if stats.get("accuracy_head") is not None else "",
                f"Reacción **{_n(stats.get('reaction_time_ms'), 0, 'ms')}**"
                if stats.get("reaction_time_ms") is not None else "",
                f"Preaim **{_n(stats.get('preaim'), 1, '°')}**"
                if stats.get("preaim") is not None else "") if x)
            if mecanica:
                lineas.append(mecanica)
            impacto = " · ".join(f"{_punto(v)} {n} **{_r(v)}**" for n, v in
                                     (("Clutch", rating.get("clutch")),
                                      ("Apertura", rating.get("opening")))
                                     if v is not None)
            if impacto:
                lineas.append(impacto)

            e.add_field(name=f"{_MEDALLAS[min(i, 3)]} {nombre}",
                        value="\n".join(lineas), inline=False)

        # --- quien gana cada cosa ---
        e.add_field(name="🏅 Quién gana qué", value=self._veredicto(perfiles), inline=False)
        e.set_footer(text="Datos de Leetify")
        return e

    # Apartados del recuento: etiqueta, de donde sale, como se pinta y si gana
    # el numero mas alto o el mas bajo (reaccion y preaim: cuanto menos, mejor).
    _APARTADOS = (
        ("Rating", lambda p: (p.get("ranks") or {}).get("leetify"), lambda v: f"{v:+.2f}", True),
        ("Winrate", lambda p: p.get("winrate"), lambda v: f"{v * 100:.0f}%", True),
        ("Puntería", lambda p: (p.get("rating") or {}).get("aim"), lambda v: f"{v:.0f}", True),
        ("Posición", lambda p: (p.get("rating") or {}).get("positioning"), lambda v: f"{v:.0f}", True),
        ("Utilidad", lambda p: (p.get("rating") or {}).get("utility"), lambda v: f"{v:.0f}", True),
        ("Headshots", lambda p: (p.get("stats") or {}).get("accuracy_head"), lambda v: f"{v:.1f}%", True),
        ("Reacción", lambda p: (p.get("stats") or {}).get("reaction_time_ms"), lambda v: f"{v:.0f}ms", False),
        ("Preaim", lambda p: (p.get("stats") or {}).get("preaim"), lambda v: f"{v:.1f}°", False),
        ("Clutch", lambda p: (p.get("rating") or {}).get("clutch"), lambda v: f"{v * 100:+.2f}", True),
        ("Aperturas", lambda p: (p.get("rating") or {}).get("opening"), lambda v: f"{v * 100:+.2f}", True),
    )

    def _veredicto(self, perfiles):
        lineas, ganadas = [], {}
        for etiqueta, saca, pinta, mas_alto in self._APARTADOS:
            vals = [(saca(prof), prof.get("name") or s) for prof, s in perfiles]
            vals = [(v, n) for v, n in vals if isinstance(v, (int, float))]
            if len(vals) < 2:
                continue
            valor, quien = (max if mas_alto else min)(vals, key=lambda x: x[0])
            ganadas[quien] = ganadas.get(quien, 0) + 1
            lineas.append(f"`{etiqueta:<9}` **{quien}** ({pinta(valor)})")
        if not lineas:
            return "No hay datos suficientes para comparar."
        mejor = max(ganadas.items(), key=lambda x: x[1])
        if list(ganadas.values()).count(mejor[1]) == 1:
            lineas.append(f"\n👑 Manda **{mejor[0]}**, {mejor[1]} de {len(lineas)} apartados.")
        else:
            lineas.append("\n🤝 Empate técnico, no hay un amo claro.")
        return "\n".join(lineas)


async def setup(bot):
    await bot.add_cog(CSStats(bot))
