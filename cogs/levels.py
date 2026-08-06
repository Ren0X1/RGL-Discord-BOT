"""
Módulo 24 — Niveles y XP.

Da XP por participar en el chat (con anti-spam por cooldown), sube de nivel y
avisa. Comandos:
  /rank [usuario]     -> tu tarjeta de nivel (o la de otro)
  /leaderboard        -> top 10 del servidor
  /xp_dar             -> staff: da o quita XP a alguien
  /xp_reset           -> staff: resetea a alguien o a todo el servidor

Config (config.py / .env):
  LEVELS_ENABLED, LEVELS_XP_MIN, LEVELS_XP_MAX, LEVELS_COOLDOWN,
  LEVELS_ANNOUNCE_CHANNEL_ID (vacío = responde en el mismo canal),
  LEVELS_IGNORED_CHANNELS

La curva de nivel es la clásica: para el nivel N hacen falta 5*N² + 50*N + 100 XP
acumulados por nivel (estilo MEE6), así que cada nivel cuesta un poco más.
"""

import os
import time
import random
import sqlite3
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("levels")
_rng = random.SystemRandom()

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "levels.db")


def _xp_para_nivel(n):
    """XP total necesaria para alcanzar el nivel n."""
    total = 0
    for i in range(n):
        total += 5 * (i ** 2) + 50 * i + 100
    return total


def _nivel_de_xp(xp):
    n = 0
    while xp >= _xp_para_nivel(n + 1):
        n += 1
        if n > 500:
            break
    return n


def _barra(actual, objetivo, ancho=18):
    if objetivo <= 0:
        return "▰" * ancho
    lleno = max(0, min(ancho, round(ancho * actual / objetivo)))
    return "▰" * lleno + "▱" * (ancho - lleno)


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._ultimo = {}     # (gid, uid) -> monotonic del último XP
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS niveles (
                   guild_id INTEGER NOT NULL,
                   user_id  INTEGER NOT NULL,
                   xp       INTEGER NOT NULL DEFAULT 0,
                   mensajes INTEGER NOT NULL DEFAULT 0,
                   PRIMARY KEY (guild_id, user_id)
               )""")
        self.db.commit()

    def cog_unload(self):
        try:
            self.db.close()
        except Exception:
            pass

    # ---------- datos ----------
    def _get(self, gid, uid):
        cur = self.db.execute("SELECT xp, mensajes FROM niveles WHERE guild_id=? AND user_id=?", (gid, uid))
        fila = cur.fetchone()
        return (fila[0], fila[1]) if fila else (0, 0)

    def _set(self, gid, uid, xp, mensajes):
        self.db.execute(
            "INSERT INTO niveles (guild_id, user_id, xp, mensajes) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=excluded.xp, mensajes=excluded.mensajes",
            (gid, uid, max(0, xp), mensajes))
        self.db.commit()

    def _top(self, gid, limite=10):
        cur = self.db.execute(
            "SELECT user_id, xp, mensajes FROM niveles WHERE guild_id=? ORDER BY xp DESC LIMIT ?",
            (gid, limite))
        return cur.fetchall()

    def _posicion(self, gid, uid):
        cur = self.db.execute(
            "SELECT COUNT(*)+1 FROM niveles WHERE guild_id=? AND xp > "
            "(SELECT xp FROM niveles WHERE guild_id=? AND user_id=?)", (gid, gid, uid))
        fila = cur.fetchone()
        return fila[0] if fila else 1

    # ---------- ganar XP ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not config.LEVELS_ENABLED or message.author.bot or message.guild is None:
            return
        if not (message.content or "").strip():
            return
        if message.channel.id in config.LEVELS_IGNORED_CHANNELS:
            return
        gid, uid = message.guild.id, message.author.id
        ahora = time.monotonic()
        if ahora - self._ultimo.get((gid, uid), 0) < config.LEVELS_COOLDOWN:
            return
        self._ultimo[(gid, uid)] = ahora

        xp, mensajes = self._get(gid, uid)
        nivel_antes = _nivel_de_xp(xp)
        xp += _rng.randint(config.LEVELS_XP_MIN, config.LEVELS_XP_MAX)
        self._set(gid, uid, xp, mensajes + 1)
        nivel_ahora = _nivel_de_xp(xp)
        if nivel_ahora > nivel_antes:
            await self._anunciar_subida(message, nivel_ahora)

    async def _anunciar_subida(self, message, nivel):
        canal = message.channel
        if config.LEVELS_ANNOUNCE_CHANNEL_ID:
            canal = message.guild.get_channel(config.LEVELS_ANNOUNCE_CHANNEL_ID) or canal
        try:
            await canal.send(f"🎉 {message.author.mention} ha subido al **nivel {nivel}**.")
        except discord.HTTPException:
            pass

    # ---------- comandos ----------
    @app_commands.command(name="rank", description="Tu nivel y XP (o el de otra persona)")
    @app_commands.describe(usuario="De quién ver el nivel (vacío = tú)")
    async def rank(self, interaction: discord.Interaction, usuario: discord.Member = None):
        objetivo = usuario or interaction.user
        gid = interaction.guild.id
        xp, mensajes = self._get(gid, objetivo.id)
        if xp <= 0 and mensajes <= 0:
            await interaction.response.send_message(
                f"**{objetivo.display_name}** todavía no tiene XP. ¡A hablar!")
            return
        nivel = _nivel_de_xp(xp)
        base = _xp_para_nivel(nivel)
        siguiente = _xp_para_nivel(nivel + 1)
        actual, objetivo_xp = xp - base, siguiente - base
        pos = self._posicion(gid, objetivo.id)

        e = discord.Embed(title=f"🏅 Nivel de {objetivo.display_name}", color=0x00ff66)
        e.add_field(name="Nivel", value=f"**{nivel}**", inline=True)
        e.add_field(name="Puesto", value=f"#{pos}", inline=True)
        e.add_field(name="Mensajes", value=str(mensajes), inline=True)
        e.add_field(name=f"Progreso · {actual}/{objetivo_xp} XP",
                    value=f"{_barra(actual, objetivo_xp)}\nXP total: **{xp}**", inline=False)
        e.set_thumbnail(url=objetivo.display_avatar.url)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="Top 10 de niveles del servidor")
    async def leaderboard(self, interaction: discord.Interaction):
        filas = self._top(interaction.guild.id, 10)
        if not filas:
            await interaction.response.send_message("Todavía no hay nadie con XP.")
            return
        medallas = {1: "🥇", 2: "🥈", 3: "🥉"}
        lineas = []
        for i, (uid, xp, mensajes) in enumerate(filas, 1):
            miembro = interaction.guild.get_member(uid)
            nombre = miembro.display_name if miembro else f"<@{uid}>"
            lineas.append(f"{medallas.get(i, f'`{i}.`')} **{nombre}** — nivel {_nivel_de_xp(xp)} · {xp} XP")
        e = discord.Embed(title="🏆 Ranking del servidor", description="\n".join(lineas), color=0xffb000)
        e.set_footer(text="Se gana XP hablando en el chat")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="xp_dar", description="Staff: da (o quita con negativo) XP a alguien")
    @app_commands.describe(usuario="A quién", cantidad="XP a sumar (usa negativo para restar)")
    async def xp_dar(self, interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        gid = interaction.guild.id
        xp, mensajes = self._get(gid, usuario.id)
        nuevo = max(0, xp + cantidad)
        self._set(gid, usuario.id, nuevo, mensajes)
        await interaction.response.send_message(
            f"✅ {usuario.mention}: {xp} → **{nuevo} XP** (nivel {_nivel_de_xp(nuevo)}).", ephemeral=True)

    @app_commands.command(name="xp_reset", description="Staff: resetea el XP de alguien o de todo el servidor")
    @app_commands.describe(usuario="A quién resetear", todo="True = resetea a TODO el servidor")
    async def xp_reset(self, interaction: discord.Interaction, usuario: discord.Member = None, todo: bool = False):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        gid = interaction.guild.id
        if todo:
            self.db.execute("DELETE FROM niveles WHERE guild_id=?", (gid,))
            self.db.commit()
            await interaction.response.send_message("🧹 XP reseteado en todo el servidor.", ephemeral=True)
        elif usuario:
            self.db.execute("DELETE FROM niveles WHERE guild_id=? AND user_id=?", (gid, usuario.id))
            self.db.commit()
            await interaction.response.send_message(f"🧹 XP de {usuario.mention} reseteado.", ephemeral=True)
        else:
            await interaction.response.send_message("Dime a quién resetear o marca `todo`.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Levels(bot))
