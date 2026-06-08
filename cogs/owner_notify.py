"""
Módulo 12 — Aviso al owner.

Cuando el bot arranca (o se reinicia, p.ej. tras un corte de luz), envía un
mensaje privado al usuario configurado en OWNER_USER_ID avisando de que está
en línea, con la hora de arranque.
"""

import datetime
import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger("owner_notify")


class OwnerNotify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.avisado = False  # solo una vez por arranque (on_ready puede repetirse)

    @commands.Cog.listener()
    async def on_ready(self):
        if self.avisado or not config.OWNER_USER_ID:
            return
        self.avisado = True
        try:
            user = self.bot.get_user(config.OWNER_USER_ID) or await self.bot.fetch_user(config.OWNER_USER_ID)
        except discord.HTTPException:
            user = None
        if not user:
            return
        ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        try:
            await user.send(f"✅ **{self.bot.user.name}** está en línea. Arrancado <t:{ts}:F> (<t:{ts}:R>).")
            log.info("Aviso de arranque enviado al owner")
        except discord.HTTPException:
            log.warning("No pude enviar el DM de arranque al owner (¿DMs cerrados?)")


async def setup(bot):
    await bot.add_cog(OwnerNotify(bot))
