"""
Módulo 2 — Canales de voz temporales (join-to-create).

Cuando alguien entra al canal "lobby" (MAIN_VOICE_CHANNEL_ID):
  1. Se crea un canal nuevo, p.ej. "Voz-Ren0X", con límite de 10 personas.
  2. Se mueve a esa persona a su nuevo canal.
  3. Cuando el canal temporal se queda vacío, se borra solo.

Al arrancar, limpia canales temporales vacíos que hubieran quedado huérfanos
tras un reinicio.
"""

import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger("tempvoice")


class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # IDs de los canales temporales que ha creado el bot
        self.temp_channels: set[int] = set()

    @commands.Cog.listener()
    async def on_ready(self):
        # Adoptar/limpiar canales que sigan el patrón de nombre tras un reinicio
        prefix = config.TEMP_VOICE_NAME.split("{")[0]
        if not prefix:
            return
        for guild in self.bot.guilds:
            for ch in guild.voice_channels:
                if ch.id == config.MAIN_VOICE_CHANNEL_ID:
                    continue
                if ch.name.startswith(prefix):
                    if len(ch.members) == 0:
                        try:
                            await ch.delete(reason="Limpieza de canal temporal vacío al arrancar")
                        except discord.HTTPException:
                            pass
                    else:
                        self.temp_channels.add(ch.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # 1) Entró al lobby -> crear canal y mover
        if after.channel and after.channel.id == config.MAIN_VOICE_CHANNEL_ID:
            await self._create_for(member, after.channel)

        # 2) Salió de un canal temporal que quedó vacío -> borrar
        if before.channel and before.channel.id in self.temp_channels:
            ch = before.channel
            if len(ch.members) == 0:
                self.temp_channels.discard(ch.id)
                try:
                    await ch.delete(reason="Canal temporal vacío")
                except discord.HTTPException:
                    pass

    async def _create_for(self, member, lobby):
        guild = member.guild
        category = guild.get_channel(config.TEMP_VOICE_CATEGORY_ID) or lobby.category
        name = config.TEMP_VOICE_NAME.format(name=member.display_name)[:100]
        try:
            new_ch = await guild.create_voice_channel(
                name=name,
                category=category,
                user_limit=config.TEMP_VOICE_LIMIT,
                reason=f"Canal temporal para {member}",
            )
            self.temp_channels.add(new_ch.id)
            await member.move_to(new_ch, reason="Movido a su canal temporal")
            log.info("Canal temporal creado: %s para %s", new_ch.name, member)
        except discord.Forbidden:
            log.warning("Sin permisos para crear/mover canales de voz")
        except discord.HTTPException as exc:
            log.warning("Error creando canal temporal: %s", exc)


async def setup(bot):
    await bot.add_cog(TempVoice(bot))
