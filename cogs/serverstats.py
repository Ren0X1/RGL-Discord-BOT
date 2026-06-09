"""
Módulo 14 — Canales-contador (estadísticas en el nombre del canal de voz).

Mantiene dos canales de voz cuyo nombre muestra:
  - el número de miembros del servidor (STATS_MEMBERS_CHANNEL_ID)
  - el número de gente actualmente en voz (STATS_VOICE_CHANNEL_ID)

Los nombres se configuran con STATS_MEMBERS_NAME / STATS_VOICE_NAME (con {count}).
Además bloquea esos canales para que NADIE pueda entrar (deniega Conectar a
@everyone).

IMPORTANTE: Discord limita el renombrado de canales (~2 cada 10 min). Por eso
solo se actualizan cada STATS_UPDATE_SECONDS (mínimo 300) y únicamente cuando el
número cambia. El "en voz" es, por tanto, aproximado a unos minutos.

El bot necesita "Gestionar canales" (renombrar) y poder editar permisos del canal.
Tú creas los dos canales de voz, los colocas arriba del todo y pones sus IDs en
el .env.
"""

import logging

import discord
from discord.ext import commands, tasks

import config

log = logging.getLogger("serverstats")


class ServerStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.actualizar.change_interval(seconds=config.STATS_UPDATE_SECONDS)
        self.actualizar.start()

    def cog_unload(self):
        self.actualizar.cancel()

    @tasks.loop(seconds=360)
    async def actualizar(self):
        ch_m = self.bot.get_channel(config.STATS_MEMBERS_CHANNEL_ID)
        ch_v = self.bot.get_channel(config.STATS_VOICE_CHANNEL_ID)
        if ch_m is None and ch_v is None:
            return
        guild = (ch_m or ch_v).guild

        # Contar miembros
        if config.STATS_COUNT_BOTS:
            total = guild.member_count or 0
        else:
            total = sum(1 for m in guild.members if not m.bot)

        # Contar gente en voz (excluyendo los propios canales-contador)
        ids_stats = {config.STATS_MEMBERS_CHANNEL_ID, config.STATS_VOICE_CHANNEL_ID}
        en_voz = 0
        for vc in guild.voice_channels:
            if vc.id in ids_stats:
                continue
            en_voz += sum(1 for m in vc.members if config.STATS_COUNT_BOTS or not m.bot)

        await self._preparar(ch_m, config.STATS_MEMBERS_NAME.format(count=total))
        await self._preparar(ch_v, config.STATS_VOICE_NAME.format(count=en_voz))

    async def _preparar(self, ch, nombre):
        if ch is None:
            return
        # Bloquear: nadie puede conectarse
        try:
            ow = ch.overwrites_for(ch.guild.default_role)
            if ow.connect is not False:
                await ch.set_permissions(ch.guild.default_role, connect=False,
                                         reason="Canal-contador (solo lectura)")
        except discord.HTTPException:
            pass
        # Renombrar solo si cambió (ahorra rate limit)
        nombre = nombre[:100]
        if ch.name != nombre:
            try:
                await ch.edit(name=nombre, reason="Actualizar estadística")
            except discord.HTTPException as exc:
                log.warning("No pude renombrar %s: %s", ch.id, exc)

    @actualizar.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ServerStats(bot))
