"""
Módulo 22 — Estado del propio bot.

/bot -> uptime, latencia, versión (último commit de git), nº de servidores y
comandos, versiones de Python/discord.py y un vistazo al host (CPU/RAM/temp).
"""

import os
import sys
import platform
import datetime
import subprocess

import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs.stats import cpu_percent, ram_uso, temperatura, formato_uptime

_RAIZ = os.path.dirname(os.path.dirname(__file__))


def _version_git():
    try:
        out = subprocess.run(
            ["git", "-C", _RAIZ, "log", "-1", "--format=%h · %s · %cd", "--date=short"],
            capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "N/D (sin git)"


class BotInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.inicio = datetime.datetime.now(datetime.timezone.utc)

    @app_commands.command(name="bot", description="Estado del bot: versión, uptime, latencia y host")
    async def estado_bot(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        cpu = await cpu_percent()
        usada, total = ram_uso()
        temp = temperatura()
        uptime = formato_uptime(datetime.datetime.now(datetime.timezone.utc) - self.inicio)
        n_cmds = len(self.bot.tree.get_commands(guild=discord.Object(id=config.GUILD_ID))) if config.GUILD_ID else len(self.bot.tree.get_commands())

        e = discord.Embed(title="🤖 Estado del bot", color=0x00ff66,
                          timestamp=datetime.datetime.now(datetime.timezone.utc))
        e.add_field(name="🟢 Estado", value="En línea", inline=True)
        e.add_field(name="📡 Latencia", value=f"{self.bot.latency * 1000:.0f} ms", inline=True)
        e.add_field(name="⏱️ Uptime", value=uptime, inline=True)
        e.add_field(name="🏷️ Versión", value=_version_git(), inline=False)
        e.add_field(name="🧩 Módulos", value=str(len(self.bot.cogs)), inline=True)
        e.add_field(name="⌨️ Comandos", value=str(n_cmds), inline=True)
        e.add_field(name="🌐 Servidores", value=str(len(self.bot.guilds)), inline=True)
        host = []
        if cpu is not None:
            host.append(f"CPU {cpu:.0f}%")
        if usada is not None and total:
            host.append(f"RAM {usada/total*100:.0f}%")
        if temp is not None:
            host.append(f"{temp:.0f} °C")
        if host:
            e.add_field(name="🖥️ Host", value=" · ".join(host), inline=False)
        e.set_footer(text=f"Python {platform.python_version()} · discord.py {discord.__version__}")
        if self.bot.user and self.bot.user.display_avatar:
            e.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=e)


async def setup(bot):
    await bot.add_cog(BotInfo(bot))
