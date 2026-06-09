"""
Módulo 13 — Información.

  /serverinfo            -> datos del servidor (miembros, canales, roles, etc.)
  /userinfo [usuario]    -> datos de un usuario (o de ti si no indicas a nadie)
"""

import datetime

import discord
from discord import app_commands
from discord.ext import commands


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="serverinfo", description="Información del servidor")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        if g is None:
            await interaction.response.send_message("Esto solo funciona en un servidor.", ephemeral=True)
            return

        humanos = sum(1 for m in g.members if not m.bot)
        bots = sum(1 for m in g.members if m.bot)
        creado = int(g.created_at.timestamp())

        e = discord.Embed(title=f"📊 {g.name}", color=0x5865F2)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name="ID", value=str(g.id), inline=True)
        e.add_field(name="Dueño", value=f"<@{g.owner_id}>", inline=True)
        e.add_field(name="Creado", value=f"<t:{creado}:D>", inline=True)
        e.add_field(name="Miembros", value=f"{g.member_count} ({humanos} 👤 / {bots} 🤖)", inline=True)
        e.add_field(name="Canales", value=f"{len(g.text_channels)} 💬 · {len(g.voice_channels)} 🔊 · {len(g.categories)} 📁", inline=True)
        e.add_field(name="Roles", value=str(len(g.roles)), inline=True)
        e.add_field(name="Emojis", value=str(len(g.emojis)), inline=True)
        e.add_field(name="Boosts", value=f"{g.premium_subscription_count} (nivel {g.premium_tier})", inline=True)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="userinfo", description="Información de un usuario")
    @app_commands.describe(usuario="Usuario a consultar (si lo dejas vacío, te muestra a ti)")
    async def userinfo(self, interaction: discord.Interaction, usuario: discord.Member = None):
        m = usuario or interaction.user
        creado = int(m.created_at.timestamp())
        e = discord.Embed(title=f"👤 {m.display_name}", color=m.color if m.color.value else 0x5865F2)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="Usuario", value=f"{m.mention} (`{m}`)", inline=False)
        e.add_field(name="ID", value=str(m.id), inline=True)
        e.add_field(name="Bot", value="Sí" if m.bot else "No", inline=True)
        e.add_field(name="Cuenta creada", value=f"<t:{creado}:R>", inline=False)
        if getattr(m, "joined_at", None):
            e.add_field(name="Entró al servidor", value=f"<t:{int(m.joined_at.timestamp())}:R>", inline=False)
        roles = [r.mention for r in getattr(m, "roles", []) if r.name != "@everyone"]
        if roles:
            e.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles)[:1024], inline=False)
        await interaction.response.send_message(embed=e)


async def setup(bot):
    await bot.add_cog(Info(bot))
