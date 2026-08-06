"""
Módulo 23 — Estadísticas de Counter-Strike.

/cs <url_perfil_steam>  -> saca stats del jugador usando la API pública de Leetify
(https://api-public.cs-prod.leetify.com, GET /v3/profile?steam64_id=...) y añade
enlaces a su perfil de Leetify y de csstats.gg.

Acepta la URL de Steam en cualquiera de estas formas:
  - https://steamcommunity.com/profiles/7656119XXXXXXXXXX
  - https://steamcommunity.com/id/<nombre>     (requiere STEAM_API_KEY para resolverlo)
  - directamente el SteamID64 (17 dígitos)

LEETIFY_API_KEY es opcional (más límite). STEAM_API_KEY solo hace falta para las
URLs con nombre personalizado (/id/...).
"""

import os
import re
import json
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("csstats")

LEETIFY_BASE = "https://api-public.cs-prod.leetify.com"
LINKS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cs_links.json")
_MENCION_RE = re.compile(r"^<@!?(\d+)>$")
_STEAM64_RE = re.compile(r"(7656\d{13})")
_VANITY_RE = re.compile(r"steamcommunity\.com/id/([^/?#\s]+)", re.I)

# Rangos clásicos de CS (Competitivo y Wingman usan esta escala 1-18)
_RANGOS_CS = {
    1: "Silver I", 2: "Silver II", 3: "Silver III", 4: "Silver IV",
    5: "Silver Elite", 6: "Silver Elite Master", 7: "Gold Nova I",
    8: "Gold Nova II", 9: "Gold Nova III", 10: "Gold Nova Master",
    11: "Master Guardian I", 12: "Master Guardian II", 13: "Master Guardian Elite",
    14: "Distinguished Master Guardian", 15: "Legendary Eagle",
    16: "Legendary Eagle Master", 17: "Supreme Master First Class",
    18: "The Global Elite",
}


def _rango_cs(n):
    if n is None:
        return None
    return _RANGOS_CS.get(n, f"rango {n}")


_RESULTADO = {"win": "✅", "won": "✅", "loss": "❌", "lose": "❌", "lost": "❌",
              "tie": "🟰", "draw": "🟰"}


def _emoji_resultado(o):
    return _RESULTADO.get((o or "").lower(), "❔")


def _pct(x):
    if x is None:
        return "—"
    return f"{x * 100:.0f}%" if x <= 1 else f"{x:.0f}%"


def _num(x, dec=1, suf=""):
    return "—" if x is None else f"{x:.{dec}f}{suf}"


class CSStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _resolver_steam64(self, session, url):
        url = (url or "").strip()
        v = _VANITY_RE.search(url)
        if v:
            vanity = v.group(1)
            if not config.STEAM_API_KEY:
                return None, ("Esa URL usa nombre personalizado (`/id/...`). Necesito una `STEAM_API_KEY` "
                              "para resolverla, o pásame la URL con `/profiles/<número>`.")
            api = ("https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
                   f"?key={config.STEAM_API_KEY}&vanityurl={vanity}")
            try:
                async with session.get(api) as r:
                    data = (await r.json()).get("response", {})
                if data.get("success") == 1 and data.get("steamid"):
                    return data["steamid"], None
                return None, "No pude resolver ese nombre de Steam."
            except Exception as exc:
                log.warning("Vanity resolve falló: %s", exc)
                return None, "Error consultando la API de Steam."
        m = _STEAM64_RE.search(url)
        if m:
            return m.group(1), None
        return None, "No reconozco esa URL de Steam. Pásame el enlace al perfil (`/profiles/...` o `/id/...`)."

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

    # ---------- vinculaciones ----------
    def _links(self):
        try:
            with open(LINKS_PATH, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _guardar_links(self, d):
        os.makedirs(os.path.dirname(LINKS_PATH), exist_ok=True)
        with open(LINKS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    def _link_de(self, uid):
        return self._links().get(str(uid))

    async def _resolver_objetivo(self, session, guild, texto):
        """Devuelve (steam64, etiqueta, error). Acepta mención/ID de Discord (requiere
        perfil vinculado) o una URL/SteamID64."""
        texto = (texto or "").strip()
        m = _MENCION_RE.match(texto)
        uid = None
        if m:
            uid = int(m.group(1))
        elif texto.isdigit() and len(texto) < 17:
            uid = int(texto)
        if uid is not None:
            sid = self._link_de(uid)
            miembro = guild.get_member(uid) if guild else None
            nombre = miembro.display_name if miembro else f"<@{uid}>"
            if not sid:
                return None, nombre, (f"**{nombre}** no tiene perfil vinculado. "
                                      f"Que use `/cs_vincular` con la URL de su Steam.")
            return sid, nombre, None
        sid, err = await self._resolver_steam64(session, texto)
        return sid, texto, err

    @app_commands.command(name="cs_vincular", description="Vincula tu perfil de Steam para usar /cs sin pegar la URL")
    @app_commands.describe(url="URL de tu perfil de Steam (o el SteamID64)",
                           usuario="Solo staff: vincular el perfil de otra persona")
    async def cs_vincular(self, interaction: discord.Interaction, url: str, usuario: discord.Member = None):
        await interaction.response.defer(thinking=True, ephemeral=True)
        objetivo = interaction.user
        if usuario and usuario.id != interaction.user.id:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.followup.send("Solo el staff puede vincular a otra persona.")
                return
            objetivo = usuario
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            steam64, err = await self._resolver_steam64(session, url)
        if err:
            await interaction.followup.send(f"⚠️ {err}")
            return
        d = self._links()
        d[str(objetivo.id)] = steam64
        self._guardar_links(d)
        await interaction.followup.send(
            f"✅ Perfil vinculado a **{objetivo.display_name}**: `{steam64}`\n"
            f"Ya puedes usar `/cs` sin parámetros.")

    @app_commands.command(name="cs_desvincular", description="Elimina tu perfil de Steam vinculado")
    async def cs_desvincular(self, interaction: discord.Interaction):
        d = self._links()
        if d.pop(str(interaction.user.id), None) is None:
            await interaction.response.send_message("No tenías ningún perfil vinculado.", ephemeral=True)
            return
        self._guardar_links(d)
        await interaction.response.send_message("🗑️ Perfil desvinculado.", ephemeral=True)

    @app_commands.command(name="cs_comparar", description="Compara las stats de CS de varios perfiles o usuarios")
    @app_commands.describe(jugador1="Usuario (@mención, debe estar vinculado) o URL de Steam",
                           jugador2="Usuario (@mención) o URL de Steam",
                           jugador3="Opcional", jugador4="Opcional")
    async def cs_comparar(self, interaction: discord.Interaction, jugador1: str, jugador2: str,
                          jugador3: str = None, jugador4: str = None):
        await interaction.response.defer(thinking=True, ephemeral=False)
        entradas = [x for x in (jugador1, jugador2, jugador3, jugador4) if x]
        perfiles, errores = [], []
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for texto in entradas:
                steam64, etiqueta, err = await self._resolver_objetivo(session, interaction.guild, texto)
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

    def _embed_comparativa(self, perfiles):
        e = discord.Embed(title="⚔️ Comparativa de Counter-Strike", color=0xF84982)
        for prof, steam64 in perfiles:
            ranks = prof.get("ranks") or {}
            rating = prof.get("rating") or {}
            stats = prof.get("stats") or {}
            partes = []
            if ranks.get("faceit") is not None:
                elo = f" · {ranks['faceit_elo']} ELO" if ranks.get("faceit_elo") else ""
                partes.append(f"FACEIT Nivel {ranks['faceit']}{elo}")
            if ranks.get("premier") is not None:
                partes.append(f"Premier {ranks['premier']} ELO")
            comp = ranks.get("competitive") or []
            if comp:
                mejor = max(comp, key=lambda c: c.get("rank") or 0)
                partes.append(f"Competitivo {_rango_cs(mejor.get('rank'))}")
            wr = prof.get("winrate")
            if wr is not None:
                partes.append(f"Winrate {(wr * 100 if wr <= 1 else wr):.0f}%")
            partes.append(f"Aim {_num(rating.get('aim'))} · HS {_pct(stats.get('accuracy_head'))} · "
                          f"Reacción {_num(stats.get('reaction_time_ms'), 0, ' ms')}")
            e.add_field(name=f"🎮 {prof.get('name') or steam64}",
                        value="\n".join(partes) or "—", inline=False)
        # veredicto rápido por rating de aim
        mejores = [(p.get("rating", {}).get("aim"), p.get("name") or s) for p, s in perfiles]
        mejores = [(v, n) for v, n in mejores if isinstance(v, (int, float))]
        if len(mejores) >= 2:
            ganador = max(mejores)[1]
            e.set_footer(text=f"Mejor aim: {ganador}")
        return e

    @app_commands.command(name="cs", description="Estadísticas de Counter-Strike de un perfil de Steam (Leetify)")
    @app_commands.describe(url="URL de Steam o @usuario (vacío = tu perfil vinculado)")
    async def cs(self, interaction: discord.Interaction, url: str = None):
        await interaction.response.defer(thinking=True, ephemeral=False)   # visible para todos
        if not url:
            propio = self._link_de(interaction.user.id)
            if not propio:
                await interaction.followup.send(
                    "No tienes perfil vinculado. Usa `/cs_vincular` con la URL de tu Steam, "
                    "o pásame la URL directamente.")
                return
            url = propio
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            steam64, _etiqueta, err = await self._resolver_objetivo(session, interaction.guild, url)
            if err:
                await interaction.followup.send(f"⚠️ {err}")
                return
            try:
                prof, status = await self._leetify(session, steam64)
            except Exception as exc:
                log.warning("Leetify falló: %s", exc)
                await interaction.followup.send("⚠️ No pude conectar con Leetify, prueba más tarde.")
                return

        if status == 404 or not prof:
            await interaction.followup.send(
                f"No encuentro stats de ese perfil en Leetify. ¿Tiene cuenta y partidas?\n"
                f"https://csstats.gg/player/{steam64}")
            return
        if status != 200:
            await interaction.followup.send(f"⚠️ Leetify respondió un error ({status}). Prueba más tarde.")
            return
        if prof.get("privacy_mode") and str(prof.get("privacy_mode")).lower() not in ("public", "0", "false"):
            # perfil oculto: aun así damos enlaces
            await interaction.followup.send(
                f"El perfil de **{prof.get('name') or steam64}** está oculto en Leetify.\n"
                f"https://csstats.gg/player/{steam64}")
            return

        await interaction.followup.send(embed=self._embed(prof, steam64))

    def _embed(self, prof, steam64):
        nombre = prof.get("name") or "Jugador"
        ranks = prof.get("ranks") or {}
        rating = prof.get("rating") or {}
        stats = prof.get("stats") or {}
        leetify_url = f"https://leetify.com/app/profile/{steam64}"

        e = discord.Embed(title=f"📊 {nombre}", url=leetify_url, color=0xF84982)

        # rangos: cada modo en su propia línea
        lineas_rango = []
        if ranks.get("faceit") is not None:
            elo = f" · {ranks['faceit_elo']} ELO" if ranks.get("faceit_elo") else ""
            lineas_rango.append(f"**FACEIT:** Nivel {ranks['faceit']}{elo}")
        if ranks.get("premier") is not None:
            lineas_rango.append(f"**Premier:** {ranks['premier']} ELO")
        if ranks.get("wingman") is not None:
            lineas_rango.append(f"**Wingman:** {_rango_cs(ranks['wingman'])}")
        comp = ranks.get("competitive") or []
        if comp:
            mejor = max(comp, key=lambda c: c.get("rank") or 0)
            lineas_rango.append(f"**Competitivo:** {_rango_cs(mejor.get('rank'))} ({mejor.get('map_name')})")
        e.add_field(name="🎖️ Rangos", value="\n".join(lineas_rango) or "Sin rangos", inline=False)

        # leetify rating
        e.add_field(name="⭐ Leetify rating",
                    value=(f"Aim {_num(rating.get('aim'))} · Posic. {_num(rating.get('positioning'))} · "
                           f"Util. {_num(rating.get('utility'))} · Clutch {_num(rating.get('clutch'))} · "
                           f"Apertura {_num(rating.get('opening'))}"),
                    inline=False)

        # puntería
        e.add_field(name="🎯 Puntería",
                    value=(f"HS {_pct(stats.get('accuracy_head'))} · "
                           f"Preaim {_num(stats.get('preaim'), 1, '°')} · "
                           f"Reacción {_num(stats.get('reaction_time_ms'), 0, ' ms')} · "
                           f"Spray {_pct(stats.get('spray_accuracy'))}"),
                    inline=False)

        # winrate
        wr = prof.get("winrate")
        tot = prof.get("total_matches")
        if wr is not None:
            wr_pct = wr * 100 if wr <= 1 else wr
            e.add_field(name="📈 Winrate", value=f"{wr_pct:.0f}%" + (f" en {tot} partidas" if tot else ""), inline=True)

        # bans
        bans = prof.get("bans") or []
        if bans:
            e.add_field(name="🚨 Bans", value=", ".join(b.get("platform", "?") for b in bans), inline=True)

        # últimas partidas
        recientes = prof.get("recent_matches") or []
        if recientes:
            lineas = []
            for m in recientes[:4]:
                sc = m.get("score") or []
                marcador = f"{sc[0]}-{sc[1]}" if len(sc) == 2 else ""
                lr = m.get("leetify_rating")
                lr_txt = f" · LR {lr*100:+.1f}" if isinstance(lr, (int, float)) else ""
                mapa = (m.get("map_name") or "?").replace("de_", "")
                lineas.append(f"{_emoji_resultado(m.get('outcome'))} `{mapa:8}` {marcador}{lr_txt}")
            e.add_field(name="🕹️ Últimas partidas", value="\n".join(lineas), inline=False)

        e.add_field(name="🔗 Enlaces",
                    value=f"[Ver en Leetify]({leetify_url}) · [csstats.gg](https://csstats.gg/player/{steam64})",
                    inline=False)
        e.set_footer(text="Datos de Leetify")
        return e


async def setup(bot):
    await bot.add_cog(CSStats(bot))
