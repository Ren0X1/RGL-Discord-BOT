"""
Módulo 25 — Roles por botón (reaction roles).

Se configura TODO por comandos y se guarda en data/reaction_roles.json:
  /roles_crear <nombre> [titulo] [descripcion]  -> crea un panel vacío
  /roles_add <panel> <rol> [emoji] [etiqueta]   -> añade un rol al panel
  /roles_quitar <panel> <rol>                   -> quita un rol del panel
  /roles_listar                                 -> lista los paneles y sus roles
  /roles_publicar <panel> [canal]               -> publica el panel con sus botones
  /roles_borrar <panel>                         -> borra el panel

Los botones son persistentes (custom_id "rr:<rol_id>"), así que siguen
funcionando después de reiniciar el bot. Al pulsar: si no tienes el rol te lo
pone, y si lo tienes te lo quita.

Cada panel recuerda dónde se publicó (canal y mensaje), así que republicarlo
EDITA el mensaje de siempre en vez de soltar otro debajo: el panel no se mueve
de sitio y la peña no pierde los botones. Si el mensaje ya no existe, se limpian
los mensajes que el bot tuviera sueltos en ese canal y se publica uno nuevo.

Otros cogs pueden mantener un panel solos: `steamnews` usa `asegurar_rol()` y
`republicar()` para meter en el panel el rol de cada juego que se añade.
"""

import os
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("reactionroles")

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reaction_roles.json")
_COLORES = [discord.ButtonStyle.primary, discord.ButtonStyle.success,
            discord.ButtonStyle.secondary, discord.ButtonStyle.danger]


def _cargar():
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar(d):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _paneles(gid):
    return _cargar().get(str(gid), {})


def obtener_panel(gid, nombre):
    """El panel tal cual está guardado, o None. Para que lo usen otros cogs."""
    return _paneles(gid).get((nombre or "").lower())


def asegurar_rol(gid, panel, rol_id, emoji=None, etiqueta=None, auto=False):
    """Mete un rol en un panel si no estaba. Devuelve True si ha cambiado algo.

    No pisa lo que ya hubiera: si el rol ya está, se respeta el emoji y la
    etiqueta que le pusieran a mano.
    """
    d = _cargar()
    p = d.get(str(gid), {}).get(panel.lower())
    if p is None:
        return False
    if any(r["id"] == rol_id for r in p.get("roles", [])):
        return False
    if len(p.get("roles", [])) >= 25:
        log.warning("El panel %s ya tiene 25 roles, no cabe %s", panel, rol_id)
        return False
    entrada = {"id": rol_id, "emoji": (emoji or "").strip() or None,
               "etiqueta": (etiqueta or "rol")[:80]}
    if auto:
        entrada["auto"] = True      # lo puso un cog, se puede quitar solo
    p.setdefault("roles", []).append(entrada)
    _guardar(d)
    return True


def quitar_rol(gid, panel, rol_id, solo_auto=True):
    """Saca un rol del panel. Con solo_auto, no toca los que se pusieron a mano."""
    d = _cargar()
    p = d.get(str(gid), {}).get(panel.lower())
    if p is None:
        return False
    quedan = [r for r in p.get("roles", [])
              if r["id"] != rol_id or (solo_auto and not r.get("auto"))]
    if len(quedan) == len(p.get("roles", [])):
        return False
    p["roles"] = quedan
    _guardar(d)
    return True


class BotonRol(discord.ui.DynamicItem[discord.ui.Button], template=r"rr:(?P<rol>\d+)"):
    """Botón persistente que da/quita un rol."""

    def __init__(self, rol_id, etiqueta, emoji=None, estilo=discord.ButtonStyle.primary):
        self.rol_id = rol_id
        super().__init__(discord.ui.Button(label=etiqueta[:80], emoji=emoji, style=estilo,
                                           custom_id=f"rr:{rol_id}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["rol"]), item.label or "rol", item.emoji, item.style)

    async def callback(self, interaction: discord.Interaction):
        rol = interaction.guild.get_role(self.rol_id)
        if rol is None:
            await interaction.response.send_message("Ese rol ya no existe.", ephemeral=True)
            return
        try:
            if rol in interaction.user.roles:
                await interaction.user.remove_roles(rol, reason="Roles por botón")
                await interaction.response.send_message(f"➖ Te he quitado {rol.mention}.", ephemeral=True)
            else:
                await interaction.user.add_roles(rol, reason="Roles por botón")
                await interaction.response.send_message(f"➕ Te he dado {rol.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "No puedo gestionar ese rol (¿está por encima del mío?).", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("No he podido cambiar el rol, prueba otra vez.", ephemeral=True)


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_dynamic_items(BotonRol)

    def _es_admin(self, interaction):
        return interaction.guild is not None and interaction.user.guild_permissions.manage_roles

    def _panel(self, gid, nombre):
        return _paneles(gid).get(nombre.lower())

    def _set_panel(self, gid, nombre, panel):
        d = _cargar()
        d.setdefault(str(gid), {})[nombre.lower()] = panel
        _guardar(d)

    # ---------- construir y publicar ----------
    def _vista(self, p):
        vista = discord.ui.View(timeout=None)
        for i, r in enumerate(p.get("roles", [])):
            vista.add_item(BotonRol(r["id"], r.get("etiqueta") or "rol",
                                    r.get("emoji"), _COLORES[i % len(_COLORES)]))
        return vista

    def _embed(self, p):
        return discord.Embed(title=p.get("titulo") or "Elige tus roles",
                             description=p.get("descripcion") or "", color=0x5865F2)

    async def publicar_panel(self, guild, nombre, canal=None, limpiar=False):
        """Publica o actualiza un panel. Devuelve el mensaje, o None si no pudo.

        Si el panel ya se publicó y el mensaje sigue vivo, se EDITA: así no se
        mueve de sitio ni se llena el canal de paneles viejos. Si no está (o se
        pide `limpiar`), se borran los mensajes que el bot tenga sueltos en ese
        canal y se publica uno nuevo.
        """
        p = self._panel(guild.id, nombre)
        if not p or not p.get("roles"):
            return None
        destino = canal
        if destino is None and p.get("canal_id"):
            destino = guild.get_channel(p["canal_id"])
        if destino is None:
            return None

        emb, vista = self._embed(p), self._vista(p)
        mismo_canal = p.get("canal_id") == destino.id
        if not limpiar and mismo_canal and p.get("mensaje_id"):
            try:
                msg = await destino.fetch_message(p["mensaje_id"])
                await msg.edit(embed=emb, view=vista)
                return msg
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                log.info("El mensaje del panel %s ya no vale (%s), publico otro", nombre, exc)

        # Limpieza: fuera los mensajes que el bot tenga por ahí en ese canal, que
        # son paneles viejos. Los de otra gente no se tocan.
        try:
            async for msg in destino.history(limit=100):
                if msg.author.id == self.bot.user.id:
                    await msg.delete()
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.info("No pude limpiar %s: %s", destino, exc)

        try:
            msg = await destino.send(embed=emb, view=vista)
        except discord.HTTPException as exc:
            log.warning("No pude publicar el panel %s: %s", nombre, exc)
            return None
        p["canal_id"], p["mensaje_id"] = destino.id, msg.id
        self._set_panel(guild.id, nombre, p)
        return msg

    # ---------- comandos ----------
    @app_commands.command(name="roles_crear", description="Crea un panel de roles por botón")
    @app_commands.describe(nombre="Nombre corto del panel (para referirte a él)",
                           titulo="Título que verá la gente", descripcion="Texto del panel")
    async def roles_crear(self, interaction: discord.Interaction, nombre: str,
                          titulo: str = None, descripcion: str = None):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar roles**.", ephemeral=True)
            return
        gid = interaction.guild.id
        if self._panel(gid, nombre):
            await interaction.response.send_message(f"Ya existe un panel llamado `{nombre}`.", ephemeral=True)
            return
        self._set_panel(gid, nombre, {"titulo": titulo or "Elige tus roles",
                                      "descripcion": descripcion or "Pulsa un botón para ponerte o quitarte el rol.",
                                      "roles": []})
        await interaction.response.send_message(
            f"✅ Panel `{nombre}` creado. Añade roles con `/roles_add {nombre} <rol>` y publícalo con "
            f"`/roles_publicar {nombre}`.", ephemeral=True)

    @app_commands.command(name="roles_add", description="Añade un rol a un panel")
    @app_commands.describe(panel="Nombre del panel", rol="Rol a añadir",
                           emoji="Emoji del botón (opcional)", etiqueta="Texto del botón (opcional)")
    async def roles_add(self, interaction: discord.Interaction, panel: str, rol: discord.Role,
                        emoji: str = None, etiqueta: str = None):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar roles**.", ephemeral=True)
            return
        gid = interaction.guild.id
        p = self._panel(gid, panel)
        if not p:
            await interaction.response.send_message(f"No existe el panel `{panel}`.", ephemeral=True)
            return
        if len(p["roles"]) >= 25:
            await interaction.response.send_message("Un panel admite como mucho 25 roles.", ephemeral=True)
            return
        if any(r["id"] == rol.id for r in p["roles"]):
            await interaction.response.send_message(f"{rol.mention} ya está en el panel.", ephemeral=True)
            return
        if rol >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"No puedo gestionar {rol.mention}: está por encima de mi rol.", ephemeral=True)
            return
        p["roles"].append({"id": rol.id, "emoji": (emoji or "").strip() or None,
                           "etiqueta": (etiqueta or rol.name)[:80]})
        self._set_panel(gid, panel, p)
        await interaction.response.send_message(
            f"✅ {rol.mention} añadido a `{panel}` ({len(p['roles'])} roles). "
            f"Republica con `/roles_publicar {panel}`.", ephemeral=True)

    @app_commands.command(name="roles_quitar", description="Quita un rol de un panel")
    @app_commands.describe(panel="Nombre del panel", rol="Rol a quitar")
    async def roles_quitar(self, interaction: discord.Interaction, panel: str, rol: discord.Role):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar roles**.", ephemeral=True)
            return
        gid = interaction.guild.id
        p = self._panel(gid, panel)
        if not p:
            await interaction.response.send_message(f"No existe el panel `{panel}`.", ephemeral=True)
            return
        antes = len(p["roles"])
        p["roles"] = [r for r in p["roles"] if r["id"] != rol.id]
        if len(p["roles"]) == antes:
            await interaction.response.send_message(f"{rol.mention} no estaba en el panel.", ephemeral=True)
            return
        self._set_panel(gid, panel, p)
        await interaction.response.send_message(
            f"🗑️ {rol.mention} quitado de `{panel}`. Republica con `/roles_publicar {panel}`.", ephemeral=True)

    @app_commands.command(name="roles_listar", description="Lista los paneles de roles y sus roles")
    async def roles_listar(self, interaction: discord.Interaction):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar roles**.", ephemeral=True)
            return
        paneles = _paneles(interaction.guild.id)
        if not paneles:
            await interaction.response.send_message(
                "No hay paneles. Crea uno con `/roles_crear`.", ephemeral=True)
            return
        lineas = []
        for nombre, p in paneles.items():
            roles = ", ".join(f"<@&{r['id']}>" for r in p.get("roles", [])) or "_sin roles_"
            lineas.append(f"**`{nombre}`** — {p.get('titulo', '')}\n{roles}")
        await interaction.response.send_message("\n\n".join(lineas)[:1900], ephemeral=True)

    @app_commands.command(name="roles_publicar", description="Publica un panel con sus botones")
    @app_commands.describe(panel="Nombre del panel", canal="Dónde publicarlo (vacío = aquí)",
                           limpiar="Borra los mensajes del bot en el canal y publica uno nuevo")
    async def roles_publicar(self, interaction: discord.Interaction, panel: str,
                             canal: discord.TextChannel = None, limpiar: bool = False):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar roles**.", ephemeral=True)
            return
        gid = interaction.guild.id
        p = self._panel(gid, panel)
        if not p:
            await interaction.response.send_message(f"No existe el panel `{panel}`.", ephemeral=True)
            return
        if not p.get("roles"):
            await interaction.response.send_message(
                f"El panel `{panel}` no tiene roles. Añádelos con `/roles_add {panel} <rol>`.", ephemeral=True)
            return
        destino = canal or interaction.channel
        await interaction.response.defer(ephemeral=True, thinking=True)
        msg = await self.publicar_panel(interaction.guild, panel, destino, limpiar=limpiar)
        if msg is None:
            await interaction.followup.send("No pude publicarlo, mira los logs.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Panel `{panel}` {'republicado' if limpiar else 'actualizado'} en "
            f"{destino.mention}. {msg.jump_url}", ephemeral=True)

    @app_commands.command(name="roles_borrar", description="Borra un panel de roles")
    @app_commands.describe(panel="Nombre del panel")
    async def roles_borrar(self, interaction: discord.Interaction, panel: str):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar roles**.", ephemeral=True)
            return
        d = _cargar()
        paneles = d.get(str(interaction.guild.id), {})
        if paneles.pop(panel.lower(), None) is None:
            await interaction.response.send_message(f"No existe el panel `{panel}`.", ephemeral=True)
            return
        _guardar(d)
        await interaction.response.send_message(
            f"🗑️ Panel `{panel}` borrado (los mensajes ya publicados hay que borrarlos a mano).", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
