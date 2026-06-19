"""
Módulo 21 — Automod (anti-invitaciones y anti-spam).

- Anti-invitaciones: borra mensajes con invitaciones a OTROS servidores de Discord
  (deja pasar las del propio servidor) de quien no esté exento.
- Anti-spam: si alguien manda AUTOMOD_SPAM_COUNT mensajes en AUTOMOD_SPAM_SECONDS,
  borra esa ráfaga y (opcional) lo aísla AUTOMOD_TIMEOUT_SECONDS.

Se libran: staff con "Gestionar mensajes", roles de AUTOMOD_EXEMPT_ROLES, el owner
y el propio bot. Las acciones se registran en AUTOMOD_LOG_CHANNEL_ID (o LOG_CHANNEL_ID).
"""

import re
import time
import logging
import datetime
from collections import defaultdict, deque

import discord
from discord.ext import commands

import config

log = logging.getLogger("automod")

_INVITE_RE = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite|discord\.me)/([a-zA-Z0-9\-]+)", re.I)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._recientes = defaultdict(lambda: deque(maxlen=20))   # (gid,uid) -> deque de (ts, message)

    def _log_channel(self, guild):
        cid = config.AUTOMOD_LOG_CHANNEL_ID or config.LOG_CHANNEL_ID
        return guild.get_channel(cid) if cid else None

    def _exento(self, member):
        if member.bot or member.id == config.OWNER_USER_ID:
            return True
        perms = getattr(member, "guild_permissions", None)
        if perms and (perms.manage_messages or perms.administrator):
            return True
        if config.AUTOMOD_EXEMPT_ROLES and any(r.id in config.AUTOMOD_EXEMPT_ROLES for r in getattr(member, "roles", [])):
            return True
        return False

    async def _registrar(self, guild, texto):
        canal = self._log_channel(guild)
        if canal:
            try:
                await canal.send(embed=discord.Embed(description=texto, color=0xffb000,
                                                     timestamp=datetime.datetime.now(datetime.timezone.utc)))
            except discord.HTTPException:
                pass

    async def _invitacion_externa(self, message):
        for code in _INVITE_RE.findall(message.content):
            try:
                inv = await self.bot.fetch_invite(code, with_counts=False)
            except discord.NotFound:
                return True   # inválida/caducada: la tratamos como externa
            except discord.HTTPException:
                return True
            if inv.guild is None or inv.guild.id != message.guild.id:
                return True
        return False

    async def _anti_invite(self, message):
        if not config.AUTOMOD_ANTIINVITE or "/" not in message.content:
            return False
        if not _INVITE_RE.search(message.content):
            return False
        if not await self._invitacion_externa(message):
            return False
        try:
            await message.delete()
        except discord.HTTPException:
            return False
        try:
            await message.channel.send(
                f"{message.author.mention} aquí no se ponen invitaciones a otros servidores.",
                delete_after=8)
        except discord.HTTPException:
            pass
        await self._registrar(message.guild,
                              f"🔗 Invitación externa borrada de {message.author.mention} en {message.channel.mention}.")
        return True

    async def _anti_spam(self, message):
        if not config.AUTOMOD_ANTISPAM:
            return False
        clave = (message.guild.id, message.author.id)
        cola = self._recientes[clave]
        ahora = time.monotonic()
        cola.append((ahora, message))
        recientes = [(t, m) for t, m in cola if ahora - t <= config.AUTOMOD_SPAM_SECONDS]
        if len(recientes) < config.AUTOMOD_SPAM_COUNT:
            return False
        cola.clear()
        msgs = [m for _, m in recientes]
        try:
            await message.channel.delete_messages(msgs)
        except (discord.HTTPException, discord.ClientException):
            for m in msgs:
                try:
                    await m.delete()
                except discord.HTTPException:
                    pass
        aislado = ""
        if config.AUTOMOD_TIMEOUT_SECONDS > 0 and isinstance(message.author, discord.Member):
            try:
                await message.author.timeout(
                    datetime.timedelta(seconds=config.AUTOMOD_TIMEOUT_SECONDS),
                    reason="Automod: spam")
                aislado = f" y aislado {config.AUTOMOD_TIMEOUT_SECONDS}s"
            except discord.HTTPException:
                pass
        try:
            await message.channel.send(f"{message.author.mention} frena con el spam.", delete_after=8)
        except discord.HTTPException:
            pass
        await self._registrar(message.guild,
                              f"🚫 Spam de {message.author.mention} en {message.channel.mention}: "
                              f"{len(msgs)} mensajes borrados{aislado}.")
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or not isinstance(message.author, discord.Member):
            return
        if self._exento(message.author):
            return
        try:
            if await self._anti_invite(message):
                return
            await self._anti_spam(message)
        except Exception as exc:
            log.warning("Fallo en automod: %s", exc)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
