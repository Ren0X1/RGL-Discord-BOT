"""
Módulo 1 — Registro de acciones del servidor (estilo MEE6).

Cubre:
  - Mensajes eliminados y editados
  - Entradas y salidas de miembros
  - Baneos y desbaneos (con el moderador, vía audit log)
  - Cambios de apodo y de roles
  - Cambios de avatar y de nombre de usuario
  - Creación y borrado de canales
  - Entradas/salidas/movimientos de voz (opcional)

Requiere que el bot tenga el permiso "Ver registro de auditoría" para saber
quién realizó baneos/desbaneos.
"""

import datetime

import discord
from discord.ext import commands

import config

RED = 0xED4245
YELLOW = 0xFEE75C
GREEN = 0x57F287
BLURPLE = 0x5865F2
GRAY = 0x99AAB5


def now():
    return datetime.datetime.now(datetime.timezone.utc)


class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- utilidades ----------
    @property
    def channel(self):
        return self.bot.get_channel(config.LOG_CHANNEL_ID)

    async def send(self, embed):
        ch = self.channel
        if ch is None:
            return
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    def _skip(self, user):
        return user.bot and not config.LOG_BOTS

    async def _actor(self, guild, action, target_id):
        """Busca en el audit log quién hizo la acción sobre target_id."""
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                if entry.target and entry.target.id == target_id:
                    return entry.user, entry.reason
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None, None

    # ---------- mensajes ----------
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or self._skip(message.author):
            return
        e = discord.Embed(title="🗑️ Mensaje eliminado", color=RED, timestamp=now())
        e.add_field(name="Autor", value=f"{message.author.mention} (`{message.author}`)", inline=False)
        e.add_field(name="Canal", value=message.channel.mention, inline=False)
        if message.content:
            e.add_field(name="Contenido", value=message.content[:1024], inline=False)
        if message.attachments:
            e.add_field(name="Adjuntos", value="\n".join(a.url for a in message.attachments)[:1024], inline=False)
        e.set_footer(text=f"ID usuario: {message.author.id}")
        await self.send(e)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or self._skip(before.author) or before.content == after.content:
            return
        e = discord.Embed(title="✏️ Mensaje editado", color=YELLOW, timestamp=now())
        e.add_field(name="Autor", value=f"{before.author.mention} (`{before.author}`)", inline=False)
        e.add_field(name="Canal", value=before.channel.mention, inline=False)
        e.add_field(name="Antes", value=(before.content or "—")[:1024], inline=False)
        e.add_field(name="Después", value=(after.content or "—")[:1024], inline=False)
        e.add_field(name="Saltar", value=f"[Ir al mensaje]({after.jump_url})", inline=False)
        e.set_footer(text=f"ID usuario: {before.author.id}")
        await self.send(e)

    # ---------- miembros ----------
    @commands.Cog.listener()
    async def on_member_join(self, member):
        e = discord.Embed(title="📥 Miembro entró", color=GREEN, timestamp=now())
        e.add_field(name="Usuario", value=f"{member.mention} (`{member}`)", inline=False)
        created = int(member.created_at.timestamp())
        e.add_field(name="Cuenta creada", value=f"<t:{created}:R>", inline=False)
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"ID usuario: {member.id}")
        await self.send(e)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        e = discord.Embed(title="📤 Miembro salió", color=GRAY, timestamp=now())
        e.add_field(name="Usuario", value=f"{member.mention} (`{member}`)", inline=False)
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        if roles:
            e.add_field(name="Roles que tenía", value=" ".join(roles)[:1024], inline=False)
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=f"ID usuario: {member.id}")
        await self.send(e)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        mod, reason = await self._actor(guild, discord.AuditLogAction.ban, user.id)
        e = discord.Embed(title="🔨 Usuario baneado", color=RED, timestamp=now())
        e.add_field(name="Usuario", value=f"`{user}`", inline=False)
        if mod:
            e.add_field(name="Moderador", value=f"{mod.mention} (`{mod}`)", inline=False)
        if reason:
            e.add_field(name="Razón", value=reason[:1024], inline=False)
        e.set_footer(text=f"ID usuario: {user.id}")
        await self.send(e)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        mod, reason = await self._actor(guild, discord.AuditLogAction.unban, user.id)
        e = discord.Embed(title="♻️ Usuario desbaneado", color=GREEN, timestamp=now())
        e.add_field(name="Usuario", value=f"`{user}`", inline=False)
        if mod:
            e.add_field(name="Moderador", value=f"{mod.mention} (`{mod}`)", inline=False)
        e.set_footer(text=f"ID usuario: {user.id}")
        await self.send(e)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Apodo
        if before.nick != after.nick:
            e = discord.Embed(title="📝 Apodo cambiado", color=BLURPLE, timestamp=now())
            e.add_field(name="Usuario", value=f"{after.mention} (`{after}`)", inline=False)
            e.add_field(name="Antes", value=before.nick or "—", inline=True)
            e.add_field(name="Después", value=after.nick or "—", inline=True)
            e.set_footer(text=f"ID usuario: {after.id}")
            await self.send(e)

        # Roles
        if before.roles != after.roles:
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            if added or removed:
                e = discord.Embed(title="🎭 Roles actualizados", color=BLURPLE, timestamp=now())
                e.add_field(name="Usuario", value=f"{after.mention} (`{after}`)", inline=False)
                if added:
                    e.add_field(name="Añadidos", value=" ".join(added)[:1024], inline=False)
                if removed:
                    e.add_field(name="Quitados", value=" ".join(removed)[:1024], inline=False)
                e.set_footer(text=f"ID usuario: {after.id}")
                await self.send(e)

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        """Cambios globales del usuario: avatar y nombre. Solo logueamos si
        comparte el servidor donde está el canal de logs."""
        guild = self.channel.guild if self.channel else None
        if guild is None or guild.get_member(after.id) is None:
            return

        if before.avatar != after.avatar:
            e = discord.Embed(title="🖼️ Foto de perfil cambiada", color=BLURPLE, timestamp=now())
            e.add_field(name="Usuario", value=f"{after.mention} (`{after}`)", inline=False)
            if before.avatar:
                e.add_field(name="Anterior", value=f"[ver]({before.avatar.url})", inline=True)
            e.set_thumbnail(url=after.display_avatar.url)
            e.set_footer(text=f"ID usuario: {after.id}")
            await self.send(e)

        if before.name != after.name or before.global_name != after.global_name:
            e = discord.Embed(title="🔤 Nombre cambiado", color=BLURPLE, timestamp=now())
            e.add_field(name="Antes", value=f"`{before}` / {before.global_name or '—'}", inline=False)
            e.add_field(name="Después", value=f"`{after}` / {after.global_name or '—'}", inline=False)
            e.set_footer(text=f"ID usuario: {after.id}")
            await self.send(e)

    # ---------- canales ----------
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        e = discord.Embed(title="➕ Canal creado", color=GREEN, timestamp=now())
        e.add_field(name="Canal", value=f"{channel.name} (`{channel.id}`)", inline=False)
        e.add_field(name="Tipo", value=str(channel.type), inline=True)
        await self.send(e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        e = discord.Embed(title="➖ Canal eliminado", color=RED, timestamp=now())
        e.add_field(name="Canal", value=f"{channel.name} (`{channel.id}`)", inline=False)
        e.add_field(name="Tipo", value=str(channel.type), inline=True)
        await self.send(e)

    # ---------- voz ----------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not config.LOG_VOICE or self._skip(member):
            return
        if before.channel == after.channel:
            return
        if before.channel is None:
            title, color, detail = "🔊 Entró a voz", GREEN, after.channel.mention
        elif after.channel is None:
            title, color, detail = "🔇 Salió de voz", GRAY, before.channel.mention
        else:
            title, color, detail = "↔️ Cambió de voz", BLURPLE, f"{before.channel.mention} → {after.channel.mention}"
        e = discord.Embed(title=title, color=color, timestamp=now())
        e.add_field(name="Usuario", value=f"{member.mention} (`{member}`)", inline=False)
        e.add_field(name="Canal", value=detail, inline=False)
        e.set_footer(text=f"ID usuario: {member.id}")
        await self.send(e)


async def setup(bot):
    await bot.add_cog(Logs(bot))
