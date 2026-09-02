"""
Módulo 26 — Estadísticas de Rust.

/rust [usuario|url]   -> stats del jugador + enlace a su perfil de Steam
/rust_vincular <url>  -> vincula tu cuenta de Steam
/rust_desvincular     -> la quita
/rust_comparar        -> compara hasta 4 cuentas

Los datos salen de la **Steam Web API** (gratis), que para Rust (appid 252490)
publica ~150 contadores: combate, puntería, caza, farmeo, construcción y
curiosidades. Hace falta `STEAM_API_KEY` en el .env.

Ojo: Steam solo los sirve si el jugador tiene el perfil **y los detalles del
juego** en público (Perfil -> Editar -> Privacidad -> "Detalles del juego").

Cada juego guarda SU cuenta de Steam (ver cogs/steamutil.py): la primera
vinculación rellena las dos, pero quien juegue a Rust con una cuenta distinta
a la de CS la puede separar con /rust_vincular.
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

# Icono cuadrado de Rust en Steam (32x32), para la cabecera del embed
RUST_ICONO = ("https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images"
              "/apps/252490/820be4782639f9c4b64fa3ca7e6c26a95ae4fd1c.jpg")


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


def _kd_txt(kd):
    """Pinta un K/D ya calculado (en la comparativa viene hecho)."""
    return "—" if kd is None else f"{kd:.2f}"


# Puesto de cada jugador en la comparativa
_MEDALLAS = ("🥇", "🥈", "🥉", "4️⃣")


def _num(v):
    """Número corto. En una columna estrecha '1.234.567' no cabe y Discord lo
    tira a la línea de abajo, así que a partir de 100.000 se abrevia."""
    if v is None:
        return "—"
    v = int(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "M"
    if v >= 100_000:
        return f"{v / 1000:.1f}".replace(".", ",") + "K"
    return su.miles(v)


def _punto(v, neutro=0.0):
    """Discord no pinta texto de colores dentro de un embed, así que el verde/rojo
    lo da un punto delante del dato."""
    if v is None:
        return "⚪"
    if v > neutro:
        return "🟢"
    return "🔴" if v < neutro else "⚪"


def _resumen(s):
    """Los numeros gordos de una cuenta, ya masticados para la comparativa.

    Steam no da agregados: hay que sumar los contadores a mano (madera + piedra
    + metal... para el farmeo, cada bicho para la caza).
    """
    bajas = _g(s, "kill_player") or 0
    muertes = _g(s, "deaths") or 0
    dados = (_g(s, "bullet_hit_player") or 0) + (_g(s, "shotgun_hit_player") or 0)
    disparos = (_g(s, "bullet_fired") or 0) + (_g(s, "shotgun_fired") or 0)
    farmeo = sum(_g(s, *claves) or 0 for claves in (
        ("harvest.wood", "harvested_wood"), ("harvest.stones", "harvested_stones"),
        ("harvest.metal_ore", "acquired_metal.ore"), ("harvest.sulfur_ore",),
        ("harvest.cloth", "harvested_cloth"), ("harvested_leather",)))
    caza = sum(_g(s, c) or 0 for c in ("kill_bear", "kill_wolf", "kill_boar",
                                       "kill_stag", "kill_chicken", "kill_horse"))
    return {
        "bajas": bajas,
        "muertes": muertes,
        "kd": bajas / muertes if muertes else None,
        "punteria": _pct(dados, disparos),
        "headshots": _pct(_g(s, "headshot", "headshots") or 0, dados),
        "farmeo": farmeo or None,
        "caza": caza or None,
        "chatarra": _g(s, "acquired_scrap"),
        "bloques": _g(s, "placed_blocks"),
        "suicidios": _g(s, "death_suicide"),
    }


def _linea(etiqueta, valor, ancho=9):
    """Etiqueta monoespaciada + valor.

    OJO con el ancho: en un campo de 3 columnas de Discord entran unos 15
    caracteres entre etiqueta y valor. Pasarse parte la línea y el dato se cae
    debajo. A lo ancho del embed el margen es de sobra.
    """
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
        tocados = su.vincular(objetivo.id, steam64, "rust")
        extra = ("\nComo no tenías nada puesto en `/cs`, te la he dejado también ahí. "
                 "Si para CS usas otra cuenta, cámbiala con `/cs_vincular`."
                 if "cs" in tocados else
                 "\nLa cuenta de `/cs` se queda como estaba.")
        await interaction.followup.send(
            f"✅ Cuenta de **Rust** vinculada a **{objetivo.display_name}**: `{steam64}`\n"
            f"Ya puedes usar `/rust` sin parámetros.{extra}")

    @app_commands.command(name="rust_desvincular", description="Elimina tu cuenta de Steam vinculada")
    async def rust_desvincular(self, interaction: discord.Interaction):
        if not su.desvincular(interaction.user.id, "rust"):
            await interaction.response.send_message(
                "No tenías ninguna cuenta vinculada para Rust.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🗑️ Cuenta de Rust desvinculada. La de `/cs` sigue donde estaba.", ephemeral=True)

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
            url = su.link_de(interaction.user.id, "rust")
            if not url:
                await interaction.followup.send(
                    "No tienes cuenta vinculada para Rust. Usa `/rust_vincular` con la URL de tu Steam, "
                    "o pásame la URL directamente.")
                return

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
            steam64, _etiqueta, err = await su.resolver_objetivo(session, interaction.guild, url, "rust")
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
        e = discord.Embed(title=nombre, url=enlace, color=COLOR)
        # El logo de Rust en la cabecera; el avatar de Steam sigue en la esquina
        e.set_author(name=f"{config.RUST_EMOJI} Rust".strip(), icon_url=RUST_ICONO)
        if (perfil or {}).get("avatarfull"):
            e.set_thumbnail(url=perfil["avatarfull"])

        # --- cabecera: lo que se mira de un vistazo ---
        kills = _g(s, "kill_player") or 0
        muertes = _g(s, "deaths") or 0
        kd = kills / muertes if muertes else None
        cabecera = [f"⚔️ **{su.miles(kills)}** bajas · ☠️ **{su.miles(muertes)}** muertes · "
                    f"{_punto(kd, 1.0)} K/D **{_kd(kills, muertes)}**"]
        extra = []
        if horas:
            extra.append(f"🕹️ {su.miles(round(horas))} h jugadas")
        if logros:
            extra.append(f"🏆 {logros}/{total_logros} logros" if total_logros
                         else f"🏆 {logros} logros")
        if (perfil or {}).get("loccountrycode"):
            extra.append(f"📍 {perfil['loccountrycode']}")
        if extra:
            cabecera.append(" · ".join(extra))
        e.description = "\n".join(cabecera)

        # --- punteria, arma por arma, con barra (campo a lo ancho) ---
        armas = [
            ("Balas", _g(s, "bullet_hit_player") or 0, _g(s, "bullet_fired") or 0),
            ("Escopeta", _g(s, "shotgun_hit_player") or 0, _g(s, "shotgun_fired") or 0),
            ("Arco", _g(s, "arrow_hit_player") or 0, _g(s, "arrow_fired", "arrows_shot") or 0),
        ]
        punteria = []
        for etiqueta, dados, disparos in armas:
            if not disparos:
                continue
            pc = _pct(dados, disparos)
            punteria.append(f"`{etiqueta:<8}` {su.barra(pc, 50)} **{pc:.1f}%** "
                            f"· {su.miles(dados)}/{su.miles(disparos)}")
        hs = _g(s, "headshot", "headshots") or 0
        if hs:
            acertados = (_g(s, "bullet_hit_player") or 0) + (_g(s, "shotgun_hit_player") or 0)
            punteria.append(f"🎯 **{su.miles(hs)}** headshots"
                            + (f" · {_pct_txt(hs, acertados)} de lo que acierta" if acertados else ""))
        if punteria:
            e.add_field(name="🎯 Puntería", value="\n".join(punteria), inline=False)

        # ---------------------------------------------------------------------
        # Fila de 3 columnas. Van estrechas: etiqueta + valor no pueden pasar de
        # ~15 caracteres o Discord parte la linea. "Como la palma" va la ultima
        # porque su titulo es el mas largo y asi no queda pegado al de al lado.
        # ---------------------------------------------------------------------

        # --- caza ---
        animales = [("🐻 Osos", _g(s, "kill_bear")), ("🐺 Lobos", _g(s, "kill_wolf")),
                    ("🐗 Jabalíes", _g(s, "kill_boar")), ("🦌 Ciervos", _g(s, "kill_stag")),
                    ("🐔 Pollos", _g(s, "kill_chicken")), ("🐴 Caballos", _g(s, "kill_horse"))]
        animales = [(n, v) for n, v in animales if v]
        if animales:
            e.add_field(name="🏹 Caza",
                        value="\n".join(f"{n} **{_num(v)}**" for n, v in animales), inline=True)

        # --- farmeo ---
        recursos = [("Madera", _g(s, "harvest.wood", "harvested_wood")),
                    ("Piedra", _g(s, "harvest.stones", "harvested_stones")),
                    ("Metal", _g(s, "harvest.metal_ore", "acquired_metal.ore")),
                    ("Azufre", _g(s, "harvest.sulfur_ore")),
                    ("Tela", _g(s, "harvest.cloth", "harvested_cloth")),
                    ("Cuero", _g(s, "harvested_leather")),
                    ("Chatarra", _g(s, "acquired_scrap")),
                    ("Combust.", _g(s, "acquired_lowgradefuel"))]
        recursos = [(n, v) for n, v in recursos if v]
        if recursos:
            e.add_field(name="🪓 Farmeo",
                        value="\n".join(_linea(n, _num(v), 8) for n, v in recursos), inline=True)

        # --- como la palma ---
        formas = [("Suicidios", _g(s, "death_suicide")), ("Caídas", _g(s, "death_fall")),
                  ("Lobos", _g(s, "death_wolf")), ("Osos", _g(s, "death_bear")),
                  ("Otros", _g(s, "death_entity", "death_selfinflicted"))]
        formas = [(n, v) for n, v in formas if v]
        heridas = _g(s, "wounded") or 0
        if formas or heridas:
            lineas = [_linea(n, _num(v)) for n, v in formas]
            if heridas:
                lineas.append(_linea("Tumbado", _num(heridas)))
                if _g(s, "wounded_healed"):
                    lineas.append(_linea("Revivido", _num(_g(s, "wounded_healed"))))
            if _g(s, "wounded_assisted"):
                lineas.append(_linea("Revive a", _num(_g(s, "wounded_assisted"))))
            e.add_field(name="💀 Cómo la palma", value="\n".join(lineas), inline=True)

        # --- base y saqueo (se queda solo en su fila: va a lo ancho) ---
        base = [("Bloques", _g(s, "placed_blocks")), ("Mejorados", _g(s, "upgraded_blocks")),
                ("Planos", _g(s, "blueprint_studied")), ("Barriles", _g(s, "destroyed_barrels")),
                ("Granadas", _g(s, "grenades_thrown")), ("Cohetes", _g(s, "rocket_fired"))]
        base = [(n, v) for n, v in base if v]
        if base:
            e.add_field(name="🏠 Base y saqueo",
                        value="\n".join(_linea(n, su.miles(v), 10) for n, v in base), inline=True)

        # --- las tonterias, que son las que dan juego ---
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


    @app_commands.command(name="rust_comparar",
                          description="Compara las stats de Rust de varias cuentas o usuarios")
    @app_commands.describe(jugador1="Usuario (@mención, debe estar vinculado) o URL de Steam",
                           jugador2="Usuario (@mención) o URL de Steam",
                           jugador3="Opcional", jugador4="Opcional")
    async def rust_comparar(self, interaction: discord.Interaction, jugador1: str, jugador2: str,
                            jugador3: str = None, jugador4: str = None):
        await interaction.response.defer(thinking=True, ephemeral=False)
        if not config.STEAM_API_KEY:
            await interaction.followup.send(
                "⚠️ Falta la `STEAM_API_KEY` en el `.env`. Es gratis: "
                "<https://steamcommunity.com/dev/apikey>")
            return

        entradas = [x for x in (jugador1, jugador2, jugador3, jugador4) if x]
        cuentas, errores = [], []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as session:
            total_logros = await self._total_logros_juego(session)
            for texto in entradas:
                steam64, etiqueta, err = await su.resolver_objetivo(session, interaction.guild, texto, "rust")
                if err:
                    errores.append(f"⚠️ {err}")
                    continue
                try:
                    stats, logros, fallo = await self._stats(session, steam64)
                except Exception as exc:
                    log.warning("Steam falló para %s: %s", steam64, exc)
                    errores.append(f"⚠️ No pude consultar a **{etiqueta}**.")
                    continue
                if fallo:
                    errores.append(f"⚠️ **{etiqueta}** — {fallo}")
                    continue
                perfil = await su.perfil_steam(session, steam64)
                horas = await self._horas(session, steam64)
                cuentas.append((stats, logros, horas, perfil, steam64))

        if len(cuentas) < 2:
            await interaction.followup.send(
                ("\n".join(errores) or "No pude comparar.") +
                "\n\nNecesito al menos **dos** cuentas válidas (públicas y con Rust).")
            return
        await interaction.followup.send(
            content="\n".join(errores) if errores else None,
            embed=self._embed_comparativa(cuentas, total_logros))

    # ----------------------------------------------- embed de la comparativa
    def _embed_comparativa(self, cuentas, total_logros):
        """Un campo por jugador, ordenados por K/D, y al final quién gana qué.
        Todo a lo ancho: con 4 nombres largos cualquier reparto en columnas se
        parte."""
        e = discord.Embed(title="⚔️ Comparativa de Rust", color=COLOR)
        e.set_author(name=f"{config.RUST_EMOJI} Rust".strip(), icon_url=RUST_ICONO)

        datos = [(_resumen(s), logros, horas, perfil, steam64)
                 for s, logros, horas, perfil, steam64 in cuentas]

        def _kd(fila):
            v = fila[0]["kd"]
            return v if isinstance(v, (int, float)) else float("-inf")

        for i, (r, logros, horas, perfil, steam64) in enumerate(sorted(datos, key=_kd, reverse=True)):
            nombre = (perfil or {}).get("personaname") or steam64

            titular = [f"{_punto(r['kd'], 1.0)} **K/D {_kd_txt(r['kd'])}**",
                       f"⚔️ **{su.miles(r['bajas'])}** bajas",
                       f"☠️ **{su.miles(r['muertes'])}** muertes"]
            extra = []
            if horas:
                extra.append(f"🕹️ **{su.miles(round(horas))} h**")
            if logros:
                extra.append(f"🏆 **{logros}**" + (f"/{total_logros}" if total_logros else ""))

            lineas = [" · ".join(titular)]
            if extra:
                lineas.append(" · ".join(extra))
            if r["punteria"] is not None:
                lineas.append(f"`Puntería ` {su.barra(r['punteria'], 50)} **{r['punteria']:.1f}%**"
                              + (f" · HS **{r['headshots']:.1f}%**"
                                 if r["headshots"] is not None else ""))
            recuento = " · ".join(x for x in (
                f"🪓 Farmeo **{_num(r['farmeo'])}**" if r["farmeo"] else "",
                f"🏹 Caza **{_num(r['caza'])}**" if r["caza"] else "",
                f"🏠 Bloques **{_num(r['bloques'])}**" if r["bloques"] else "") if x)
            if recuento:
                lineas.append(recuento)

            e.add_field(name=f"{_MEDALLAS[min(i, 3)]} {nombre}",
                        value="\n".join(lineas), inline=False)

        e.add_field(name="🏅 Quién gana qué",
                    value=self._veredicto(datos), inline=False)
        e.set_footer(text="Datos de la Steam Web API")
        return e

    # Apartados del recuento: etiqueta, de donde sale, como se pinta y si gana
    # el numero mas alto o el mas bajo (suicidios: gana el que menos, claro).
    _APARTADOS = (
        ("K/D", lambda r, lo, h: r["kd"], lambda v: f"{v:.2f}", True),
        ("Bajas", lambda r, lo, h: r["bajas"], lambda v: su.miles(v), True),
        ("Puntería", lambda r, lo, h: r["punteria"], lambda v: f"{v:.1f}%", True),
        ("Headshots", lambda r, lo, h: r["headshots"], lambda v: f"{v:.1f}%", True),
        ("Horas", lambda r, lo, h: h, lambda v: f"{su.miles(round(v))} h", True),
        ("Logros", lambda r, lo, h: lo or None, lambda v: str(v), True),
        ("Farmeo", lambda r, lo, h: r["farmeo"], _num, True),
        ("Chatarra", lambda r, lo, h: r["chatarra"], _num, True),
        ("Caza", lambda r, lo, h: r["caza"], _num, True),
        ("Constructor", lambda r, lo, h: r["bloques"], _num, True),
        ("Manazas", lambda r, lo, h: r["suicidios"], lambda v: f"{su.miles(v)} suicidios", False),
    )

    def _veredicto(self, datos):
        lineas, ganadas = [], {}
        for etiqueta, saca, pinta, mas_alto in self._APARTADOS:
            vals = [(saca(r, lo, h), (perfil or {}).get("personaname") or s)
                    for r, lo, h, perfil, s in datos]
            vals = [(v, n) for v, n in vals if isinstance(v, (int, float))]
            if len(vals) < 2:
                continue
            valor, quien = (max if mas_alto else min)(vals, key=lambda x: x[0])
            # "Manazas" es una coña, no cuenta para el recuento de victorias
            if etiqueta != "Manazas":
                ganadas[quien] = ganadas.get(quien, 0) + 1
            lineas.append(f"`{etiqueta:<11}` **{quien}** ({pinta(valor)})")
        if not lineas:
            return "No hay datos suficientes para comparar."
        if ganadas:
            mejor = max(ganadas.items(), key=lambda x: x[1])
            total = sum(1 for e_, _, _, _ in self._APARTADOS if e_ != "Manazas")
            if list(ganadas.values()).count(mejor[1]) == 1:
                lineas.append(f"\n👑 Manda **{mejor[0]}**, {mejor[1]} apartados de {total}.")
            else:
                lineas.append("\n🤝 Empate técnico, no hay un amo claro.")
        return "\n".join(lineas)


async def setup(bot):
    await bot.add_cog(Rust(bot))
