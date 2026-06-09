"""
Módulo 15 — Auto-sincronizar la plantilla del servidor.

Una plantilla de servidor de Discord guarda una "foto" de la estructura (canales,
roles, ajustes). Cuando cambias algo, la plantilla queda desactualizada y hay que
pulsar "Sincronizar" a mano. Este cog lo hace solo: cada TEMPLATE_SYNC_MINUTES
revisa las plantillas del servidor y, si alguna está desactualizada (is_dirty),
la sincroniza.

Se activa con TEMPLATE_AUTO_SYNC=true en el .env. El bot necesita el permiso
"Gestionar servidor". No crea plantillas: solo mantiene al día las que ya existen.
"""

import datetime
import logging

import discord
from discord.ext import commands, tasks

import config

log = logging.getLogger("template_sync")


class TemplateSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if config.TEMPLATE_AUTO_SYNC:
            self.revisar.change_interval(minutes=config.TEMPLATE_SYNC_MINUTES)
            self.revisar.start()

    def cog_unload(self):
        self.revisar.cancel()

    def _guilds(self):
        if config.GUILD_ID:
            g = self.bot.get_guild(config.GUILD_ID)
            return [g] if g else []
        return list(self.bot.guilds)

    @tasks.loop(minutes=60)
    async def revisar(self):
        for g in self._guilds():
            if not g.me.guild_permissions.manage_guild:
                log.warning("Me falta 'Gestionar servidor' en %s; no puedo sincronizar plantillas.", g.name)
                continue
            try:
                plantillas = await g.templates()
            except discord.HTTPException as exc:
                log.warning("No pude leer las plantillas de %s: %s", g.name, exc)
                continue
            for tpl in plantillas:
                if not tpl.is_dirty:
                    continue
                try:
                    await tpl.sync()
                    log.info("Plantilla '%s' (%s) sincronizada en %s", tpl.name, tpl.code, g.name)
                    await self._avisar(tpl)
                except discord.HTTPException as exc:
                    log.warning("No pude sincronizar la plantilla %s: %s", tpl.code, exc)

    async def _avisar(self, tpl):
        if not config.LOG_CHANNEL_ID:
            return
        ch = self.bot.get_channel(config.LOG_CHANNEL_ID)
        if ch is None:
            return
        e = discord.Embed(
            title="🔄 Plantilla sincronizada",
            description=f"La plantilla **{tpl.name}** se ha actualizado con los últimos cambios del servidor.",
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        e.set_footer(text=f"Código: {tpl.code}")
        try:
            await ch.send(embed=e)
        except discord.HTTPException:
            pass

    @revisar.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(TemplateSync(bot))
