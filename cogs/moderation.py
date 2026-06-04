"""
Módulo 6 — Moderación.

Comando:
  /clear cantidad:<1-1000>

Borra los últimos N mensajes del canal donde se ejecuta (es decir, los que
están por encima). Requiere que tanto quien lo usa como el bot tengan el
permiso "Gestionar mensajes".

Nota de Discord: los mensajes con más de 14 días no se pueden borrar en lote,
así que pueden quedar sin eliminar; la respuesta indica cuántos se borraron de
verdad.
"""

import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("moderation")


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="clear", description="Borra los últimos N mensajes de este canal")
    @app_commands.describe(cantidad="Cuántos mensajes borrar (1-1000)")
    async def clear(self, interaction: discord.Interaction, cantidad: app_commands.Range[int, 1, 1000]):
        if interaction.guild is None:
            await interaction.response.send_message("Esto solo funciona en un servidor.", ephemeral=True)
            return

        # Permiso de quien ejecuta
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "Necesitas el permiso **Gestionar mensajes** para usar esto.", ephemeral=True
            )
            return

        # Permiso del bot en este canal
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            await interaction.response.send_message(
                "Me falta el permiso **Gestionar mensajes** en este canal.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Solo borramos en LOTE los mensajes de menos de 14 días: es lo único
        # que la API de Discord permite eliminar de golpe. Los más antiguos se
        # tendrían que borrar uno a uno (lento y con rate limits 429), así que
        # los saltamos y avisamos.
        limite_14d = discord.utils.utcnow() - datetime.timedelta(days=14)

        def reciente(msg: discord.Message) -> bool:
            return msg.created_at > limite_14d

        try:
            borrados = await interaction.channel.purge(
                limit=cantidad,
                check=reciente,
                bulk=True,
            )
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos suficientes aquí.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Error al borrar: `{exc}`", ephemeral=True)
            return

        nota = ""
        if len(borrados) < cantidad:
            nota = (
                "\n(Se saltaron mensajes de más de 14 días: Discord no permite "
                "borrarlos en lote.)"
            )
        await interaction.followup.send(f"🧹 Borrados **{len(borrados)}** mensaje(s).{nota}", ephemeral=True)
        log.info("/clear: %s borró %d mensajes en #%s", interaction.user, len(borrados), interaction.channel)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
