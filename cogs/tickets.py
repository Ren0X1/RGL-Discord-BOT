"""
Módulo 17 — Sistema de tickets (estilo Ticket Tool).

Flujo:
  1) Pones un mensaje-panel en un canal con /ticket_panel. Ese mensaje lleva un
     botón "Abrir ticket".
  2) Cuando alguien lo pulsa, se crea un canal de texto dentro de la categoría
     TICKET_CATEGORY_ID, privado: solo lo ven y escriben el que lo abrió y los
     roles de staff (TICKET_STAFF_ROLE_IDS).
  3) Solo el staff puede cerrar el ticket (botón 🔒), con confirmación. Al cerrar
     se borra el canal.

Config (.env):
  TICKET_PANEL_CHANNEL_ID   canal donde va el panel
  TICKET_CATEGORY_ID        categoría donde se crean los tickets
  TICKET_STAFF_ROLE_IDS     roles que atienden/cierran (separados por coma o espacio)
  TICKET_PANEL_TITLE / TICKET_PANEL_TEXT / TICKET_OPEN_MESSAGE  textos (opcionales)

El bot necesita "Gestionar canales" (crear/borrar) y un rol suficientemente alto.
"""

import re
import asyncio
import datetime
import logging
import os
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("tickets")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tickets.db")


def _slug(nombre):
    s = re.sub(r"[^a-z0-9]+", "-", (nombre or "").lower()).strip("-")
    return s[:90] or "user"


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------- vistas persistentes ----------
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir ticket", emoji="🎫",
                       style=discord.ButtonStyle.primary, custom_id="ticket:abrir")
    async def abrir(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.abrir_ticket(interaction)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Cerrar", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="ticket:cerrar")
    async def cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.pedir_cierre(interaction)


class ConfirmarView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Confirmar cierre", style=discord.ButtonStyle.danger)
    async def si(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🔒 Cerrando el ticket…", view=None)
        await self.cog.cerrar_ticket(interaction.channel)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cierre cancelado.", view=None)


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS tickets (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   guild_id INTEGER, channel_id INTEGER, opener_id INTEGER,
                   created TEXT, open INTEGER DEFAULT 1
               )"""
        )
        self.db.commit()
        # vistas persistentes (los botones funcionan tras reiniciar)
        self.bot.add_view(PanelView())
        self.bot.add_view(TicketView())

    def cog_unload(self):
        self.db.close()

    # ---------- utilidades ----------
    def es_staff(self, member):
        if isinstance(member, discord.Member) and member.guild_permissions.administrator:
            return True
        return any(r.id in config.TICKET_STAFF_ROLE_IDS for r in getattr(member, "roles", []))

    def _ticket_abierto(self, guild, opener_id):
        """Devuelve el canal del ticket abierto del usuario, o None. Limpia los que ya no existan."""
        canal = None
        for (cid,) in self.db.execute(
                "SELECT channel_id FROM tickets WHERE guild_id=? AND opener_id=? AND open=1",
                (guild.id, opener_id)).fetchall():
            ch = guild.get_channel(cid)
            if ch:
                canal = ch
            else:
                self.db.execute("UPDATE tickets SET open=0 WHERE channel_id=?", (cid,))
        self.db.commit()
        return canal

    # ---------- panel ----------
    @app_commands.command(name="ticket_panel", description="Publica el panel para abrir tickets")
    async def ticket_panel(self, interaction: discord.Interaction):
        if interaction.guild is None or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Necesitas el permiso **Gestionar servidor**.", ephemeral=True)
            return
        canal = interaction.guild.get_channel(config.TICKET_PANEL_CHANNEL_ID) or interaction.channel
        emb = discord.Embed(title=config.TICKET_PANEL_TITLE, description=config.TICKET_PANEL_TEXT, color=0x5865F2)
        try:
            await canal.send(embed=emb, view=PanelView())
        except discord.HTTPException:
            await interaction.response.send_message("No pude enviar el panel a ese canal.", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Panel publicado en {canal.mention}.", ephemeral=True)

    # ---------- abrir ----------
    async def abrir_ticket(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return
        category = guild.get_channel(config.TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "El sistema de tickets no está configurado (falta la categoría).", ephemeral=True)
            return

        existente = self._ticket_abierto(guild, interaction.user.id)
        if existente:
            await interaction.response.send_message(
                f"Ya tienes un ticket abierto: {existente.mention}", ephemeral=True)
            return

        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_channels=True),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True),
        }
        roles_staff = []
        for rid in config.TICKET_STAFF_ROLE_IDS:
            role = guild.get_role(rid)
            if role:
                ow[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)
                roles_staff.append(role)

        nombre = f"ticket-{_slug(interaction.user.name)}"
        try:
            canal = await guild.create_text_channel(
                nombre, category=category, overwrites=ow,
                topic=f"Ticket de {interaction.user} ({interaction.user.id})",
                reason=f"Ticket abierto por {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "No pude crear el canal: me falta **Gestionar canales** o mi rol está demasiado bajo.",
                ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.response.send_message("Hubo un error creando el ticket.", ephemeral=True)
            return

        self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, opener_id, created, open) VALUES (?,?,?,?,1)",
            (guild.id, canal.id, interaction.user.id, _now_iso()))
        self.db.commit()

        menciones = interaction.user.mention
        if roles_staff:
            menciones += " " + " ".join(r.mention for r in roles_staff)
        emb = discord.Embed(
            title=f"Ticket de {interaction.user.display_name}",
            description=config.TICKET_OPEN_MESSAGE, color=0x5865F2)
        emb.set_footer(text="El staff te atenderá aquí. Cierre con el botón 🔒 (solo staff).")
        try:
            await canal.send(content=menciones, embed=emb, view=TicketView())
        except discord.HTTPException:
            pass
        await interaction.response.send_message(f"✅ Ticket creado: {canal.mention}", ephemeral=True)
        log.info("Ticket abierto por %s -> #%s", interaction.user, canal.name)

    # ---------- cerrar ----------
    async def pedir_cierre(self, interaction: discord.Interaction):
        if not self.es_staff(interaction.user):
            await interaction.response.send_message(
                "Solo el staff puede cerrar este ticket.", ephemeral=True)
            return
        await interaction.response.send_message(
            "¿Seguro que quieres cerrar este ticket? Se **borrará** el canal.",
            view=ConfirmarView(self), ephemeral=True)

    async def cerrar_ticket(self, channel):
        self.db.execute("UPDATE tickets SET open=0 WHERE channel_id=?", (channel.id,))
        self.db.commit()
        await asyncio.sleep(2)
        try:
            await channel.delete(reason="Ticket cerrado")
            log.info("Ticket #%s cerrado y borrado", channel.name)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Tickets(bot))
