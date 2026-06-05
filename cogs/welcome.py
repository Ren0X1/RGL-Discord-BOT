"""
Módulo 9 — Bienvenida, despedida y autorol.

Al entrar un miembro:
  - Se le asigna el rol configurado en AUTOROLE_ID (si está puesto).
  - Se publica un mensaje de bienvenida (visible para todos) en
    WELCOME_CHANNEL_ID, mencionando al usuario.
Al salir un miembro:
  - Se publica un mensaje de despedida en el mismo canal.

Los textos se configuran con WELCOME_MESSAGE y GOODBYE_MESSAGE, y admiten los
comodines {user} y {server}.

El bot necesita el permiso "Gestionar roles" para el autorol, y su rol debe
estar por encima del rol que asigna.
"""

import logging

import discord
from discord.ext import commands

import config

log = logging.getLogger("welcome")


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def canal(self):
        return self.bot.get_channel(config.WELCOME_CHANNEL_ID)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Autorol
        if config.AUTOROLE_ID:
            rol = member.guild.get_role(config.AUTOROLE_ID)
            if rol:
                try:
                    await member.add_roles(rol, reason="Autorol de bienvenida")
                except discord.Forbidden:
                    log.warning("Sin permisos para asignar el autorol (¿rol del bot por debajo?)")
                except discord.HTTPException as exc:
                    log.warning("Error asignando autorol: %s", exc)

        # Mensaje de bienvenida
        ch = self.canal
        if ch:
            texto = config.WELCOME_MESSAGE.format(user=member.mention, server=member.guild.name)
            try:
                await ch.send(texto, allowed_mentions=discord.AllowedMentions(users=True, everyone=False, roles=False))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        ch = self.canal
        if ch:
            texto = config.GOODBYE_MESSAGE.format(user=f"**{member.display_name}**", server=member.guild.name)
            try:
                await ch.send(texto, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Welcome(bot))
