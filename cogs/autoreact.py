"""
Módulo 11 — Auto-reacción por rol.

Cuando un miembro con el rol REACT_ROLE_ID escribe un mensaje en cualquier canal
de texto, el bot añade una reacción con un emoji al azar. El pool es REACT_EMOJIS
(caras por defecto) más, si REACT_USE_SERVER_EMOJIS está activo, los emojis del
servidor que el bot REALMENTE pueda usar (disponibles y no restringidos por rol).

El bot necesita el permiso "Añadir reacciones" en el canal. Solo reacciona a una
fracción de los mensajes (REACT_CHANCE, por defecto ~1 de cada 10).
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

        # Solo reacciona a una fracción de los mensajes (REACT_CHANCE)
        if _rng.random() > config.REACT_CHANCE:
            return

        # Comprobar permiso de reaccionar en este canal antes de intentarlo
        perms = message.channel.permissions_for(message.guild.me)
        if not perms.add_reactions:
            log.warning("Falta el permiso 'Añadir reacciones' en #%s", message.channel)
            return

        pool = list(config.REACT_EMOJIS)
        if config.REACT_USE_SERVER_EMOJIS:
            # Solo emojis del servidor que el bot pueda usar de verdad
            pool += [e for e in message.guild.emojis if e.available and e.is_usable()]
        if not pool:
            return

        emoji = _rng.choice(pool)
        try:
            await message.add_reaction(emoji)
        except discord.Forbidden:
            log.warning("Sin permiso para reaccionar en #%s", message.channel)
        except discord.HTTPException as exc:
            log.warning("No pude reaccionar con %r: %s", str(emoji), exc)


async def setup(bot):
    await bot.add_cog(AutoReact(bot))
