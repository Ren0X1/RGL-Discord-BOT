"""
Módulo 26 — Backups automáticos a Google Drive.

Cada BACKUP_INTERVAL_HOURS horas comprime la carpeta data/ (bases de datos y
JSON de la IA) en un .zip con fecha, lo sube a una carpeta de tu Google Drive y
borra los backups viejos dejando solo los BACKUP_KEEP más recientes.

Comandos:
  /backup            -> lanza un backup ahora mismo (staff)
  /backups           -> lista los backups que hay en Drive (staff)

Configuración (.env):
  BACKUP_ENABLED=true
  BACKUP_INTERVAL_HOURS=12
  BACKUP_KEEP=10
  BACKUP_INCLUDE_ENV=false          # incluir el .env (lleva tus claves: cuidado)
  GDRIVE_FOLDER_ID=<id de la carpeta de Drive>
  GDRIVE_CREDENTIALS=data/gdrive.json   # clave JSON de la cuenta de servicio

IMPORTANTE: se usa una CUENTA DE SERVICIO de Google Cloud. Hay que compartir la
carpeta de tu Drive con el email de esa cuenta (…@….iam.gserviceaccount.com) con
permiso de Editor; si no, los ficheros irían a la cuota de la cuenta de servicio
(que es 0) y fallaría la subida.
"""

import os
import asyncio
import logging
import zipfile
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger("backup")

_RAIZ = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(_RAIZ, "data")
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
PREFIJO = "rgl-bot-backup-"


class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._servicio = None
        if config.BACKUP_ENABLED and config.GDRIVE_FOLDER_ID and self._ruta_credenciales():
            self.backup_automatico.change_interval(hours=config.BACKUP_INTERVAL_HOURS)
            self.backup_automatico.start()

    def cog_unload(self):
        self.backup_automatico.cancel()

    # ---------- Google Drive ----------
    def _ruta_credenciales(self):
        ruta = config.GDRIVE_CREDENTIALS
        if not ruta:
            return None
        if not os.path.isabs(ruta):
            ruta = os.path.join(_RAIZ, ruta)
        return ruta if os.path.exists(ruta) else None

    def _drive(self):
        """Crea (y cachea) el cliente de Drive. Bloqueante: llamar en un hilo."""
        if self._servicio is not None:
            return self._servicio
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            self._ruta_credenciales(), scopes=SCOPES)
        self._servicio = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._servicio

    def _comprimir(self):
        """Crea el zip del contenido de data/ y devuelve su ruta."""
        marca = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        destino = os.path.join(_RAIZ, f"{PREFIJO}{marca}.zip")
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isdir(DATA_DIR):
                for raiz, _dirs, ficheros in os.walk(DATA_DIR):
                    for f in ficheros:
                        if f.startswith(PREFIJO) or f == os.path.basename(self._ruta_credenciales() or ""):
                            continue
                        completo = os.path.join(raiz, f)
                        z.write(completo, os.path.join("data", os.path.relpath(completo, DATA_DIR)))
            if config.BACKUP_INCLUDE_ENV:
                env = os.path.join(_RAIZ, ".env")
                if os.path.exists(env):
                    z.write(env, ".env")
        return destino

    def _subir(self, ruta):
        from googleapiclient.http import MediaFileUpload
        servicio = self._drive()
        meta = {"name": os.path.basename(ruta), "parents": [config.GDRIVE_FOLDER_ID]}
        media = MediaFileUpload(ruta, mimetype="application/zip", resumable=False)
        fichero = servicio.files().create(body=meta, media_body=media,
                                          fields="id,name,size,webViewLink",
                                          supportsAllDrives=True).execute()
        return fichero

    def _listar(self):
        servicio = self._drive()
        res = servicio.files().list(
            q=f"'{config.GDRIVE_FOLDER_ID}' in parents and name contains '{PREFIJO}' and trashed=false",
            orderBy="createdTime desc", pageSize=50,
            fields="files(id,name,size,createdTime)",
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        return res.get("files", [])

    def _rotar(self):
        """Borra los backups que sobren, dejando los BACKUP_KEEP más nuevos."""
        ficheros = self._listar()
        sobran = ficheros[config.BACKUP_KEEP:]
        servicio = self._drive()
        for f in sobran:
            try:
                servicio.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
            except Exception as exc:
                log.warning("No pude borrar el backup %s: %s", f.get("name"), exc)
        return len(sobran)

    async def _hacer_backup(self):
        """Comprime, sube y rota. Devuelve (fichero_subido, borrados)."""
        ruta = await asyncio.to_thread(self._comprimir)
        try:
            fichero = await asyncio.to_thread(self._subir, ruta)
            borrados = await asyncio.to_thread(self._rotar)
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass
        return fichero, borrados

    # ---------- tarea periódica ----------
    @tasks.loop(hours=12)
    async def backup_automatico(self):
        try:
            fichero, borrados = await self._hacer_backup()
        except Exception as exc:
            log.warning("Fallo en el backup automático: %s", exc)
            await self._avisar_owner(f"⚠️ **El backup ha fallado**: `{exc}`", 0xff4d4d)
            return
        tam = int(fichero.get("size") or 0) / 1024
        log.info("Backup subido a Drive: %s (%.1f KB)", fichero.get("name"), tam)
        await self._avisar_owner(
            f"💾 Backup subido a Drive: **{fichero.get('name')}** ({tam:.1f} KB)"
            + (f"\n🧹 {borrados} backup(s) antiguo(s) borrado(s)." if borrados else ""), 0x2ecc71)

    @backup_automatico.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()

    async def _avisar_owner(self, texto, color):
        if not config.OWNER_USER_ID:
            return
        try:
            owner = self.bot.get_user(config.OWNER_USER_ID) or await self.bot.fetch_user(config.OWNER_USER_ID)
            if owner:
                await owner.send(embed=discord.Embed(description=texto, color=color))
        except discord.HTTPException:
            pass

    # ---------- comandos ----------
    def _comprobar(self, interaction):
        if not interaction.user.guild_permissions.manage_guild:
            return "Necesitas **Gestionar servidor**."
        if not config.GDRIVE_FOLDER_ID:
            return "Falta `GDRIVE_FOLDER_ID` en el `.env`."
        if not self._ruta_credenciales():
            return (f"No encuentro las credenciales de Google (`{config.GDRIVE_CREDENTIALS}`). "
                    "Sube la clave JSON de la cuenta de servicio.")
        return None

    @app_commands.command(name="backup", description="Lanza ahora un backup de los datos del bot a Google Drive")
    async def backup(self, interaction: discord.Interaction):
        error = self._comprobar(interaction)
        if error:
            await interaction.response.send_message(f"⚠️ {error}", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            fichero, borrados = await self._hacer_backup()
        except Exception as exc:
            log.warning("Fallo en /backup: %s", exc)
            await interaction.followup.send(f"⚠️ El backup ha fallado: `{exc}`")
            return
        tam = int(fichero.get("size") or 0) / 1024
        msg = f"✅ Backup subido: **{fichero.get('name')}** ({tam:.1f} KB)"
        if fichero.get("webViewLink"):
            msg += f"\n[Verlo en Drive]({fichero['webViewLink']})"
        if borrados:
            msg += f"\n🧹 {borrados} backup(s) antiguo(s) borrado(s)."
        await interaction.followup.send(msg)

    @app_commands.command(name="backups", description="Lista los backups guardados en Google Drive")
    async def backups(self, interaction: discord.Interaction):
        error = self._comprobar(interaction)
        if error:
            await interaction.response.send_message(f"⚠️ {error}", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            ficheros = await asyncio.to_thread(self._listar)
        except Exception as exc:
            await interaction.followup.send(f"⚠️ No pude listar los backups: `{exc}`")
            return
        if not ficheros:
            await interaction.followup.send("No hay backups todavía. Lanza uno con `/backup`.")
            return
        lineas = []
        for f in ficheros[:15]:
            tam = int(f.get("size") or 0) / 1024
            lineas.append(f"`{f['name']}` · {tam:.1f} KB · {f.get('createdTime', '')[:16].replace('T', ' ')}")
        e = discord.Embed(title="💾 Backups en Google Drive", description="\n".join(lineas), color=0x00ff66)
        e.set_footer(text=f"Se conservan los {config.BACKUP_KEEP} más recientes")
        await interaction.followup.send(embed=e)


async def setup(bot):
    await bot.add_cog(Backup(bot))
