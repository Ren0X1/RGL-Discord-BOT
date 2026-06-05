"""
Módulo 8 — Estado del bot y de la máquina.

Comando:
  /stats  -> latencia, uptime, CPU, RAM, temperatura y disco.

Lee la información directamente de /proc y /sys (sin dependencias extra), así
que en la Raspberry funciona sin instalar nada. En otros sistemas, los datos
que no estén disponibles se muestran como "N/D".
"""

import asyncio
import datetime
import shutil

import discord
from discord import app_commands
from discord.ext import commands


def _leer_cpu():
    with open("/proc/stat") as f:
        campos = f.readline().split()[1:]
    nums = list(map(int, campos))
    inactivo = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
    total = sum(nums)
    return inactivo, total


async def cpu_percent():
    try:
        i1, t1 = _leer_cpu()
        await asyncio.sleep(0.5)
        i2, t2 = _leer_cpu()
        dt = t2 - t1
        if dt <= 0:
            return None
        return max(0.0, min(100.0, (1 - (i2 - i1) / dt) * 100))
    except Exception:
        return None


def ram_uso():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for linea in f:
                clave, _, resto = linea.partition(":")
                info[clave] = int(resto.strip().split()[0])  # kB
        total = info["MemTotal"]
        disp = info.get("MemAvailable", info.get("MemFree", 0))
        usado = total - disp
        return usado / 1024, total / 1024  # MB
    except Exception:
        return None, None


def temperatura():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return None


def formato_uptime(delta: datetime.timedelta) -> str:
    seg = int(delta.total_seconds())
    dias, seg = divmod(seg, 86400)
    horas, seg = divmod(seg, 3600)
    mins, seg = divmod(seg, 60)
    partes = []
    if dias:
        partes.append(f"{dias}d")
    if horas:
        partes.append(f"{horas}h")
    if mins:
        partes.append(f"{mins}m")
    partes.append(f"{seg}s")
    return " ".join(partes)


class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.inicio = datetime.datetime.now(datetime.timezone.utc)

    @app_commands.command(name="stats", description="Estado del bot y de la máquina (CPU/RAM/temperatura)")
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        cpu = await cpu_percent()
        ram_usada, ram_total = ram_uso()
        temp = temperatura()
        uptime = datetime.datetime.now(datetime.timezone.utc) - self.inicio
        latencia = self.bot.latency * 1000 if self.bot.latency else None

        try:
            disco = shutil.disk_usage("/")
            disco_txt = f"{disco.used / 1e9:.1f} / {disco.total / 1e9:.1f} GB"
        except Exception:
            disco_txt = "N/D"

        e = discord.Embed(title="📊 Estado del bot", color=0x5865F2, timestamp=datetime.datetime.now(datetime.timezone.utc))
        e.add_field(name="📶 Latencia", value=f"{latencia:.0f} ms" if latencia is not None else "N/D", inline=True)
        e.add_field(name="⏱️ Uptime", value=formato_uptime(uptime), inline=True)
        e.add_field(name="🌐 Servidores", value=str(len(self.bot.guilds)), inline=True)
        e.add_field(name="🖥️ CPU", value=f"{cpu:.0f} %" if cpu is not None else "N/D", inline=True)
        if ram_usada is not None:
            e.add_field(name="🧠 RAM", value=f"{ram_usada:.0f} / {ram_total:.0f} MB", inline=True)
        else:
            e.add_field(name="🧠 RAM", value="N/D", inline=True)
        e.add_field(name="🌡️ Temperatura", value=f"{temp:.1f} °C" if temp is not None else "N/D", inline=True)
        e.add_field(name="💾 Disco", value=disco_txt, inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Stats(bot))
