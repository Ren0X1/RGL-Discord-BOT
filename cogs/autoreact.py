"""
Módulo 11 — Auto-reacción por rol.

Cuando un miembro que tiene el rol REACT_ROLE_ID escribe un mensaje en
cualquier canal de texto, el bot añade una reacción con un emoji elegido al
azar. El pool de emojis es la lista REACT_EMOJIS (caras por defecto) más, si
REACT_USE_SERVER_EMOJIS está activo, los emojis propios del servidor.

El bot necesita el permiso "Añadir reacciones".
"""

import logging
import random

import discord
from discord.ext import commands

import config

log = logging.getLogger("autoreact")
_rng = random.SystemRandom()


class AutoReact(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not config.REACT_ROLE_ID or message.guild is None or message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return
        if not any(r.id == config.REACT_ROLE_ID for r in message.author.roles):
            return

        pool = list(config.REACT_EMOJIS)
        if config.REACT_USE_SERVER_EMOJIS and message.guild.emojis:
            pool += list(message.guild.emojis)
        if not pool:
            return

        try:
            await message.add_reaction(_rng.choice(pool))
        except discord.HTTPException:
            log.warning("No pude reaccionar (¿emoji válido? ¿permiso de reacciones?)")


async def setup(bot):
    await bot.add_cog(AutoReact(bot))
