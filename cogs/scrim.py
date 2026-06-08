"""
Módulo 10 — Scrim y equipos.

  /scrim   canal_id:<id de canal de voz>
      Coge a los del canal de voz y los MUEVE al azar a los dos canales de
      equipo configurados (SCRIM_TEAM1_CHANNEL_ID / SCRIM_TEAM2_CHANNEL_ID).

  /equipos canal_id:<id de canal de voz>
      Igual de aleatorio, pero SOLO anuncia los equipos en un mensaje (no mueve
      a nadie). Útil cuando no queréis cambiar a la gente de canal.

/scrim requiere permiso "Mover miembros". /equipos lo puede usar cualquiera.
"""

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("scrim")
_rng = random.SystemRandom()


def repartir(miembros):
    """Baraja y parte en dos. Si es impar, el equipo 1 lleva uno más."""
    m = list(miembros)
    _rng.shuffle(m)
    corte = (len(m) + 1) // 2
    return m[:corte], m[corte:]


class Scrim(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _voz(self, guild, canal_id):
        try:
            cid = int(str(canal_id).strip())
        except ValueError:
            return None, "El `canal_id` no es un número válido."
        canal = guild.get_channel(cid)
        if not isinstance(canal, discord.VoiceChannel):
            return None, "Ese ID no es de un canal de voz."
        return canal, None

    @app_commands.command(name="scrim", description="Reparte a los del canal de voz en dos equipos (los mueve)")
    @app_commands.describe(canal_id="ID del canal de voz del que coger a la gente")
    async def scrim(self, interaction: discord.Interaction, canal_id: str):
        if interaction.guild is None:
            await interaction.response.send_message("Esto solo funciona en un servidor.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.move_members:
            await interaction.response.send_message("Necesitas el permiso **Mover miembros**.", ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.move_members:
            await interaction.response.send_message("Me falta el permiso **Mover miembros**.", ephemeral=True)
            return

        origen, err = self._voz(interaction.guild, canal_id)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        team1 = interaction.guild.get_channel(config.SCRIM_TEAM1_CHANNEL_ID)
        team2 = interaction.guild.get_channel(config.SCRIM_TEAM2_CHANNEL_ID)
        if not isinstance(team1, discord.VoiceChannel) or not isinstance(team2, discord.VoiceChannel):
            await interaction.response.send_message(
                "Los canales de equipo no están bien configurados (SCRIM_TEAM1_CHANNEL_ID / SCRIM_TEAM2_CHANNEL_ID).",
                ephemeral=True,
            )
            return

        miembros = [m for m in origen.members if not m.bot]
        if not miembros:
            await interaction.response.send_message("No hay nadie en ese canal de voz.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        e1, e2 = repartir(miembros)
        for m in e1:
            try:
                await m.move_to(team1, reason="Scrim: equipo 1")
            except discord.HTTPException:
                pass
        for m in e2:
            try:
                await m.move_to(team2, reason="Scrim: equipo 2")
            except discord.HTTPException:
                pass

        emb = discord.Embed(title="🎯 Equipos del scrim", color=0x57F287)
        emb.add_field(name=f"🟦 {team1.name} ({len(e1)})", value=", ".join(x.display_name for x in e1) or "—", inline=False)
        emb.add_field(name=f"🟥 {team2.name} ({len(e2)})", value=", ".join(x.display_name for x in e2) or "—", inline=False)
        await interaction.followup.send(embed=emb, ephemeral=True)
        log.info("Scrim: %d repartidos por %s", len(miembros), interaction.user)

    @app_commands.command(name="equipos", description="Anuncia dos equipos al azar con los del canal de voz (no mueve)")
    @app_commands.describe(canal_id="ID del canal de voz del que coger a la gente")
    async def equipos(self, interaction: discord.Interaction, canal_id: str):
        if interaction.guild is None:
            await interaction.response.send_message("Esto solo funciona en un servidor.", ephemeral=True)
            return

        origen, err = self._voz(interaction.guild, canal_id)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        miembros = [m for m in origen.members if not m.bot]
        if not miembros:
            await interaction.response.send_message("No hay nadie en ese canal de voz.", ephemeral=True)
            return

        e1, e2 = repartir(miembros)
        emb = discord.Embed(title="🎲 Equipos al azar", description=f"Canal: {origen.mention}", color=0x5865F2)
        emb.add_field(name=f"🟦 Equipo 1 ({len(e1)})", value=", ".join(x.display_name for x in e1) or "—", inline=False)
        emb.add_field(name=f"🟥 Equipo 2 ({len(e2)})", value=", ".join(x.display_name for x in e2) or "—", inline=False)
        await interaction.response.send_message(embed=emb)  # público: lo ven todos
        log.info("Equipos anunciados: %d por %s", len(miembros), interaction.user)


async def setup(bot):
    await bot.add_cog(Scrim(bot))
