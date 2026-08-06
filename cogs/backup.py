"""
Módulo 26 — Backups automáticos a Google Drive.

Cada BACKUP_INTERVAL_HOURS horas comprime la carpeta data/ (bases de datos y
JSON de la IA) en un .zip con fecha, lo sube a una carpeta de tu Google Drive y
borra los backups viejos dejando solo los BACKUP_KEEP más recientes.

Comandos:
  /backup     -> lanza un backup ahora mismo (staff)
  /backups    -> lista los backups que hay en Drive (staff)

AUTENTICACIÓN: OAuth con TU cuenta de Google (no cuenta de servicio: esas no
tienen espacio propio y Drive rechaza sus subidas). Se autoriza UNA vez con el
script scripts/autorizar_gdrive.py, que guarda un token con refresh en
data/gdrive_token.json; a partir de ahí el bot se renueva solo. Los ficheros los
sube tu usuario, así que ocupan de tu Google One.

Permiso usado: drive.file (mínimo posible). El bot solo ve y gestiona los
ficheros que él mismo crea, por eso se crea su propia carpeta de backups.

Configuración (.env):
  BACKUP_ENABLED=true
  BACKUP_INTERVAL_HOURS=12
  BACKUP_KEEP=10
  BACKUP_INCLUDE_ENV=false            # incluir el .env (lleva tus claves: cuidado)
  GDRIVE_FOLDER_NAME=RGL-Bot-Backups  # carpeta que crea el bot en tu Drive
  GDRIVE_TOKEN=data/gdrive_token.json
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
        self._carpeta_id = None
        if config.BACKUP_ENABLED and self._ruta_token():
            self.backup_automatico.change_interval(hours=config.BACKUP_INTERVAL_HOURS)
            self.backup_automatico.start()

    def cog_unload(self):
        self.backup_automatico.cancel()

    # ---------- Google Drive ----------
    def _ruta_token(self):
        ruta = config.GDRIVE_TOKEN
        if not ruta:
            return None
        if not os.path.isabs(ruta):
            ruta = os.path.join(_RAIZ, ruta)
        return ruta if os.path.exists(ruta) else None

    def _drive(self):
        """Crea (y cachea) el cliente de Drive con tu token OAuth.
        Bloqueante: llamar siempre dentro de asyncio.to_thread."""
        if self._servicio is not None:
            return self._servicio
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        ruta = self._ruta_token()
        creds = Credentials.from_authorized_user_file(ruta, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            else:
                raise RuntimeError("El token de Google no vale. Vuelve a ejecutar "
                                   "scripts/autorizar_gdrive.py")
        self._servicio = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._servicio

    def _carpeta(self):
        """Busca (o crea) la carpeta de backups en tu Drive y devuelve su ID."""
        if self._carpeta_id:
            return self._carpeta_id
        servicio = self._drive()
        nombre = config.GDRIVE_FOLDER_NAME
        res = servicio.files().list(
            q=("mimeType='application/vnd.google-apps.folder' and "
               f"name='{nombre}' and trashed=false"),
            pageSize=1, fields="files(id,name)").execute()
        ficheros = res.get("files", [])
        if ficheros:
            self._carpeta_id = ficheros[0]["id"]
        else:
            carpeta = servicio.files().create(
                body={"name": nombre, "mimeType": "application/vnd.google-apps.folder"},
                fields="id").execute()
            self._carpeta_id = carpeta["id"]
            log.info("Carpeta de backups creada en Drive: %s", nombre)
        return self._carpeta_id

    def _comprimir(self):
        """Crea el zip del contenido de data/ y devuelve su ruta."""
        marca = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        destino = os.path.join(_RAIZ, f"{PREFIJO}{marca}.zip")
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isdir(DATA_DIR):
                for raiz, _dirs, ficheros in os.walk(DATA_DIR):
                    for f in ficheros:
                        if f.startswith(PREFIJO) or f.startswith("gdrive_") or f == "gdrive.json":
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
        meta = {"name": os.path.basename(ruta), "parents": [self._carpeta()]}
        media = MediaFileUpload(ruta, mimetype="application/zip", resumable=False)
        fichero = servicio.files().create(body=meta, media_body=media,
                                          fields="id,name,size,webViewLink").execute()
        return fichero

    def _listar(self):
        servicio = self._drive()
        res = servicio.files().list(
            q=f"'{self._carpeta()}' in parents and name contains '{PREFIJO}' and trashed=false",
            orderBy="createdTime desc", pageSize=50,
            fields="files(id,name,size,createdTime)").execute()
        return res.get("files", [])

    def _rotar(self):
        """Borra los backups que sobren, dejando los BACKUP_KEEP más nuevos."""
        ficheros = self._listar()
        sobran = ficheros[config.BACKUP_KEEP:]
        servicio = self._drive()
        for f in sobran:
            try:
                servicio.files().delete(fileId=f["id"]).execute()
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
        if not self._ruta_token():
            return (f"No encuentro el token de Google (`{config.GDRIVE_TOKEN}`). "
                    "Ejecuta `python3 scripts/autorizar_gdrive.py` para autorizarlo.")
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
