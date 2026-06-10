"""
Bot de Discord con 4 módulos:
  - logs        -> registro de acciones del servidor (estilo MEE6)
  - tempvoice   -> canales de voz temporales (join-to-create)
  - reminders   -> recordatorios por DM con /recordatorio
  - streams     -> aviso cuando alguien con cierto rol empieza a transmitir
"""

import asyncio
import logging

import discord
from discord.ext import commands

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# --- Intents (permisos de eventos que recibe el bot) ---
intents = discord.Intents.default()
intents.members = True          # entrar/salir, cambios de miembro
intents.presences = True        # detección de streaming
intents.message_content = True  # leer contenido para los logs
intents.voice_states = True     # canales de voz temporales
intents.guilds = True

COGS = (
    "cogs.logs",
    "cogs.tempvoice",
    "cogs.reminders",
    "cogs.streams",
    "cogs.events",
    "cogs.moderation",
    "cogs.stats",
    "cogs.welcome",
    "cogs.scrim",
    "cogs.autoreact",
    "cogs.owner_notify",
    "cogs.serverinfo",
    "cogs.serverstats",
    "cogs.template_sync",
    "cogs.polls",
    "cogs.tickets",
)


class MiBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info("Módulo cargado: %s", ext)
            except Exception:
                log.exception("Error cargando %s", ext)

        # Sincronizar slash commands.
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            # 1) Registrar los comandos en el servidor (aparecen al instante)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            # 2) Borrar los comandos GLOBALES antiguos para que no salgan
            #    duplicados/obsoletos en las sugerencias.
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            log.info("Comandos sincronizados en el servidor %s y limpiados los globales antiguos", config.GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Slash commands sincronizados globalmente (%d). Pueden tardar en propagarse.", len(synced))

    async def on_ready(self):
        log.info("Conectado como %s (ID %s)", self.user, self.user.id)
        log.info("En %d servidor(es)", len(self.guilds))
        # Bola amarilla (idle) + actividad "Transmitiendo" con el enlace
        activity = discord.Streaming(name=config.STATUS_TEXT, url=config.STATUS_URL)
        await self.change_presence(status=discord.Status.idle, activity=activity)


def main():
    if not config.TOKEN:
        raise SystemExit("Falta DISCORD_TOKEN en el archivo .env")
    bot = MiBot()
    bot.run(config.TOKEN)


if __name__ == "__main__":
    main()
