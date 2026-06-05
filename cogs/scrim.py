"""
Módulo 10 — Scrim (repartir equipos).

Comando:
  /scrim canal_id:<id de canal de voz>

Coge a todos los que estén en ese canal de voz y los reparte al azar entre los
dos canales de equipo configurados (SCRIM_TEAM1_CHANNEL_ID y
SCRIM_TEAM2_CHANNEL_ID). Si son 10, quedan 5 y 5; si son impares, un equipo
tendrá uno más.

Requiere que quien lo use tenga el permiso "Mover miembros" y que el bot
también lo tenga.
"""

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("scrim")


class Scrim(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="scrim", description="Reparte a los del canal de voz en dos equipos al azar")
    @app_commands.describe(canal_id="ID del canal de voz del que coger a la gente")
    async def scrim(self, interaction: discord.Interaction, canal_id: str):
        if interaction.guild is None:
            await interaction.response.send_message("Esto solo funciona en un servidor.", ephemeral=True)
            return

        # Permiso de quien ejecuta
        if not interaction.user.guild_permissions.move_members:
            await interaction.response.send_message(
                "Necesitas el permiso **Mover miembros** para usar esto.", ephemeral=True
            )
            return
        # Permiso del bot
        if not interaction.guild.me.guild_permissions.move_members:
            await interaction.response.send_message(
                "Me falta el permiso **Mover miembros**.", ephemeral=True
            )
            return

        # Canal de origen
        try:
            cid = int(canal_id.strip())
        except ValueError:
            await interaction.response.send_message("El `canal_id` no es un número válido.", ephemeral=True)
            return
        origen = interaction.guild.get_channel(cid)
        if not isinstance(origen, discord.VoiceChannel):
            await interaction.response.send_message("Ese ID no es de un canal de voz.", ephemeral=True)
            return

        # Canales de equipo
        team1 = interaction.guild.get_channel(config.SCRIM_TEAM1_CHANNEL_ID)
        team2 = interaction.guild.get_channel(config.SCRIM_TEAM2_CHANNEL_ID)
        if not isinstance(team1, discord.VoiceChannel) or not isinstance(team2, discord.VoiceChannel):
            await interaction.response.send_message(
                "Los canales de equipo (SCRIM_TEAM1_CHANNEL_ID / SCRIM_TEAM2_CHANNEL_ID) no están bien configurados.",
                ephemeral=True,
            )
            return

        miembros = [m for m in origen.members if not m.bot]
        if not miembros:
            await interaction.response.send_message("No hay nadie en ese canal de voz.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        random.shuffle(miembros)
        corte = (len(miembros) + 1) // 2  # si es impar, el equipo 1 lleva uno más
        equipo1 = miembros[:corte]
        equipo2 = miembros[corte:]

        for m in equipo1:
            try:
                await m.move_to(team1, reason="Scrim: equipo 1")
            except discord.HTTPException:
                pass
        for m in equipo2:
            try:
                await m.move_to(team2, reason="Scrim: equipo 2")
            except discord.HTTPException:
                pass

        lista1 = ", ".join(m.display_name for m in equipo1) or "—"
        lista2 = ", ".join(m.display_name for m in equipo2) or "—"
        e = discord.Embed(title="🎯 Equipos del scrim", color=0x57F287)
        e.add_field(name=f"🟦 {team1.name} ({len(equipo1)})", value=lista1, inline=False)
        e.add_field(name=f"🟥 {team2.name} ({len(equipo2)})", value=lista2, inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)
        log.info("Scrim: %d repartidos por %s", len(miembros), interaction.user)


async def setup(bot):
    await bot.add_cog(Scrim(bot))
