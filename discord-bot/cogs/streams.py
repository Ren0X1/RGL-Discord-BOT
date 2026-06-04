"""
Módulo 4 — Aviso de directos.

Cuando un miembro que tiene alguno de los roles configurados (STREAM_ROLE_IDS)
empieza a transmitir (estado de "streaming" de Twitch/YouTube, que sí expone
una URL pública), el bot publica en el canal configurado un aviso con la
mención (@everyone por defecto) y el enlace del directo.

Nota: el "Go Live" / compartir pantalla dentro de un canal de voz NO tiene
enlace público, por eso no se puede anunciar con link.
"""

import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger("streams")


def streaming_activity(member: discord.Member):
    """Devuelve la actividad de streaming (con URL) si la hay, o None."""
    for act in member.activities:
        if isinstance(act, discord.Streaming) and act.url:
            return act
        if getattr(act, "type", None) == discord.ActivityType.streaming and getattr(act, "url", None):
            return act
    return None


def tiene_rol(member: discord.Member):
    if not config.STREAM_ROLE_IDS:
        return True  # si no se configuran roles, avisa de cualquiera
    member_role_ids = {r.id for r in member.roles}
    return any(rid in member_role_ids for rid in config.STREAM_ROLE_IDS)


class Streams(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.live: set[int] = set()  # IDs de quienes ya anunciamos

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return

        act = streaming_activity(after)

        # Empezó a transmitir
        if act and after.id not in self.live:
            if tiene_rol(after):
                self.live.add(after.id)
                await self._announce(after, act)

        # Dejó de transmitir
        elif not act and after.id in self.live:
            self.live.discard(after.id)

    async def _announce(self, member: discord.Member, act):
        channel = self.bot.get_channel(config.STREAM_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            return
        titulo = act.name or "directo"
        e = discord.Embed(
            title=f"🔴 {member.display_name} está en directo",
            description=f"**{titulo}**\n{act.url}",
            color=0x9146FF,
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Ver ahora", value=f"[Abrir directo]({act.url})", inline=False)
        try:
            await channel.send(
                content=f"{config.STREAM_MENTION} {member.mention} {act.url}",
                embed=e,
                allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=True),
            )
            log.info("Anunciado directo de %s: %s", member, act.url)
        except discord.Forbidden:
            log.warning("Sin permisos para anunciar en el canal de streams")
        except discord.HTTPException as exc:
            log.warning("Error anunciando directo: %s", exc)


async def setup(bot):
    await bot.add_cog(Streams(bot))
