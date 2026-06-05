"""
Módulo 5 — Crear eventos del servidor.

Comando:
  /evento nombre:<texto> inicio:<fecha hora> fin:<fecha hora> imagen:<url>
          [channel_id] [descripcion]

Crea un evento programado (Scheduled Event) de tipo externo (con ubicación) y la
portada que le pases por URL.
  - El parámetro channel_id es opcional: si lo pasas, se usa el NOMBRE de ese
    canal como ubicación; si no, la ubicación queda como "Servidor".
  - Las horas se redondean al siguiente múltiplo de 15 minutos (9:51 -> 10:00).
Las fechas se interpretan en la zona horaria configurada (TIMEZONE).

El bot necesita el permiso "Gestionar eventos" (Manage Events).
"""

import datetime
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from cogs.reminders import parse_when, now_utc

log = logging.getLogger("events")

MAX_IMG_BYTES = 8 * 1024 * 1024  # 8 MB, límite de Discord


def ceil_15(dt: datetime.datetime) -> datetime.datetime:
    """Redondea hacia arriba al siguiente múltiplo de 15 minutos.
    Ej: 9:51 -> 10:00, 9:45 -> 9:45 (se queda). Descarta segundos."""
    dt = dt.replace(second=0, microsecond=0)
    resto = dt.minute % 15
    if resto == 0:
        return dt
    return dt + datetime.timedelta(minutes=15 - resto)


async def descargar_imagen(url: str):
    """Descarga la imagen de la URL y devuelve sus bytes, o None si falla."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if not ctype.startswith("image/"):
                    return None
                data = await resp.read()
                if len(data) > MAX_IMG_BYTES:
                    return None
                return data
    except Exception as exc:
        log.warning("No se pudo descargar la imagen: %s", exc)
        return None


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.avisados = set()  # (event_id, "inicio"/"fin") ya anunciados
        self.revisar_eventos.start()

    def cog_unload(self):
        self.revisar_eventos.cancel()

    @app_commands.command(name="evento", description="Crea un evento del servidor con rango de fechas e imagen")
    @app_commands.describe(
        nombre="Nombre del evento",
        inicio="Inicio. Ej: 25/12/2026 18:00 (se redondea al cuarto de hora siguiente)",
        fin="Fin. Ej: 25/12/2026 21:00 (se redondea al cuarto de hora siguiente)",
        imagen="Enlace directo a la imagen de portada (.png/.jpg)",
        channel_id="(Opcional) ID de un canal: su nombre se usa como ubicación. Si lo dejas vacío, pone 'Servidor'",
        descripcion="Descripción del evento (opcional)",
    )
    async def evento(
        self,
        interaction: discord.Interaction,
        nombre: str,
        inicio: str,
        fin: str,
        imagen: str,
        channel_id: str = "",
        descripcion: str = "",
    ):
        if interaction.guild is None:
            await interaction.response.send_message("Esto solo funciona dentro de un servidor.", ephemeral=True)
            return

        # Comprobar permiso del bot
        if not interaction.guild.me.guild_permissions.manage_events:
            await interaction.response.send_message(
                "Me falta el permiso **Gestionar eventos** en este servidor.", ephemeral=True
            )
            return

        # Ubicación: el nombre del canal indicado, o "Servidor" si no se pasa
        ubicacion = "Servidor"
        if channel_id.strip():
            try:
                cid = int(channel_id.strip())
            except ValueError:
                await interaction.response.send_message("El `channel_id` no es un número válido.", ephemeral=True)
                return
            canal = interaction.guild.get_channel(cid)
            if canal is None:
                await interaction.response.send_message("No encuentro ningún canal con ese ID en este servidor.", ephemeral=True)
                return
            ubicacion = canal.name

        # Parsear fechas
        dt_inicio = parse_when(inicio)
        dt_fin = parse_when(fin)
        if dt_inicio is None or dt_fin is None:
            await interaction.response.send_message(
                "No entendí alguna fecha. Usa formato `25/12/2026 18:00`.", ephemeral=True
            )
            return

        # Redondear al siguiente múltiplo de 15 minutos (9:51 -> 10:00)
        dt_inicio = ceil_15(dt_inicio)
        dt_fin = ceil_15(dt_fin)

        if dt_inicio <= now_utc():
            await interaction.response.send_message("El inicio tiene que ser en el futuro.", ephemeral=True)
            return
        if dt_fin <= dt_inicio:
            await interaction.response.send_message("El fin debe ser posterior al inicio.", ephemeral=True)
            return

        # La descarga de imagen puede tardar -> diferimos la respuesta
        await interaction.response.defer(ephemeral=True)

        img_bytes = await descargar_imagen(imagen) if imagen else None

        try:
            evento = await interaction.guild.create_scheduled_event(
                name=nombre[:100],
                description=descripcion[:1000],
                start_time=dt_inicio,
                end_time=dt_fin,
                entity_type=discord.EntityType.external,
                location=ubicacion[:100],
                privacy_level=discord.PrivacyLevel.guild_only,
                image=img_bytes if img_bytes else discord.utils.MISSING,
                reason=f"Evento creado por {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para crear el evento.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Discord rechazó el evento: `{exc}`", ephemeral=True)
            return

        aviso_img = "" if img_bytes else "\n⚠️ No pude usar la imagen (enlace no válido, no es imagen, o pesa más de 8 MB)."
        await interaction.followup.send(
            f"✅ Evento **{evento.name}** creado.\n"
            f"📍 Ubicación: {ubicacion}\n"
            f"🗓️ <t:{int(dt_inicio.timestamp())}:F> → <t:{int(dt_fin.timestamp())}:t>\n"
            f"🔗 {evento.url}{aviso_img}",
            ephemeral=True,
        )
        log.info("Evento creado: %s por %s (ubicación: %s)", evento.name, interaction.user, ubicacion)

    # ---------- aviso antes de empezar / acabar ----------
    @tasks.loop(seconds=60)
    async def revisar_eventos(self):
        canal = self.bot.get_channel(config.EVENT_ANNOUNCE_CHANNEL_ID)
        if canal is None:
            return
        ahora = now_utc()
        margen = datetime.timedelta(minutes=config.EVENT_LEAD_MINUTES)

        for guild in self.bot.guilds:
            for ev in guild.scheduled_events:
                # Aviso de "está a punto de empezar"
                if ev.status in (discord.EventStatus.scheduled,) and ev.start_time:
                    if ahora >= ev.start_time - margen and ahora < ev.start_time:
                        await self._avisar(canal, ev, "inicio")
                # Aviso de "está a punto de acabar"
                if ev.end_time and ev.status in (discord.EventStatus.scheduled, discord.EventStatus.active):
                    if ahora >= ev.end_time - margen and ahora < ev.end_time:
                        await self._avisar(canal, ev, "fin")

    async def _avisar(self, canal, ev, fase):
        clave = (ev.id, fase)
        if clave in self.avisados:
            return
        self.avisados.add(clave)
        if fase == "inicio":
            momento = int(ev.start_time.timestamp())
            texto = f"@everyone ⏰ El evento **{ev.name}** empieza <t:{momento}:R> — {ev.url}"
        else:
            momento = int(ev.end_time.timestamp())
            texto = f"@everyone 🏁 El evento **{ev.name}** termina <t:{momento}:R> — {ev.url}"
        try:
            await canal.send(texto, allowed_mentions=discord.AllowedMentions(everyone=True))
        except discord.HTTPException as exc:
            log.warning("No pude avisar del evento: %s", exc)

    @revisar_eventos.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Events(bot))
