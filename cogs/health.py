"""
Módulo 20 — Alertas de salud de la máquina.

Cada HEALTH_INTERVAL minutos mira temperatura, RAM y disco. Si alguna métrica
supera su umbral (HEALTH_TEMP_MAX / HEALTH_RAM_MAX / HEALTH_DISK_MAX), avisa por
DM al owner (OWNER_USER_ID). Avisa UNA vez al cruzar el umbral y otra cuando se
recupera, para no spamear. Solo se activa si hay OWNER_USER_ID configurado.
"""

import shutil
import logging

import discord
from discord.ext import commands, tasks

import config
from cogs.stats import temperatura, ram_uso

log = logging.getLogger("health")


class Health(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._alarma = {"temp": False, "ram": False, "disk": False}
        if config.OWNER_USER_ID:
            self.vigilar.change_interval(minutes=config.HEALTH_INTERVAL)
            self.vigilar.start()

    def cog_unload(self):
        self.vigilar.cancel()

    def _disco_pct(self):
        try:
            u = shutil.disk_usage("/")
            return u.used / u.total * 100, u
        except Exception:
            return None, None

    async def _dm(self, texto, color):
        try:
            owner = self.bot.get_user(config.OWNER_USER_ID) or await self.bot.fetch_user(config.OWNER_USER_ID)
            if owner:
                await owner.send(embed=discord.Embed(description=texto, color=color))
        except discord.HTTPException as exc:
            log.warning("No pude avisar al owner: %s", exc)

    async def _check(self, clave, valor, umbral, fmt_sup, fmt_ok):
        if valor is None:
            return
        if valor >= umbral and not self._alarma[clave]:
            self._alarma[clave] = True
            await self._dm(fmt_sup, 0xff4d4d)
        elif valor < umbral and self._alarma[clave]:
            self._alarma[clave] = False
            await self._dm(fmt_ok, 0x2ecc71)

    @tasks.loop(minutes=5)
    async def vigilar(self):
        temp = temperatura()
        usada, total = ram_uso()
        ram_pct = (usada / total * 100) if (usada is not None and total) else None
        disk_pct, du = self._disco_pct()

        await self._check("temp", temp, config.HEALTH_TEMP_MAX,
                          f"🌡️ **Temperatura alta**: {temp:.1f} °C (límite {config.HEALTH_TEMP_MAX:.0f} °C).",
                          f"✅ Temperatura normalizada: {temp:.1f} °C." if temp is not None else "✅ Temperatura normalizada.")
        await self._check("ram", ram_pct, config.HEALTH_RAM_MAX,
                          (f"🧠 **RAM alta**: {ram_pct:.0f}% usada" + (f" ({usada:.0f}/{total:.0f} MB)" if usada else "")
                           + f" (límite {config.HEALTH_RAM_MAX:.0f}%).") if ram_pct is not None else "",
                          f"✅ RAM normalizada: {ram_pct:.0f}%." if ram_pct is not None else "✅ RAM normalizada.")
        await self._check("disk", disk_pct, config.HEALTH_DISK_MAX,
                          (f"💾 **Disco casi lleno**: {disk_pct:.0f}% usado"
                           + (f" ({du.used/2**30:.1f}/{du.total/2**30:.1f} GB)" if du else "")
                           + f" (límite {config.HEALTH_DISK_MAX:.0f}%).") if disk_pct is not None else "",
                          f"✅ Disco con espacio de nuevo: {disk_pct:.0f}% usado." if disk_pct is not None else "✅ Disco recuperado.")

    @vigilar.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Health(bot))
