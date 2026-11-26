"""
Módulo 26 — Backups automáticos a Google Drive.

Cada BACKUP_INTERVAL_HOURS horas comprime en un .zip con fecha todo lo que hace
falta para levantar el bot en una máquina limpia, lo sube a una carpeta de tu
Google Drive y borra los backups viejos dejando solo los BACKUP_KEEP recientes.

Qué entra en el zip:
  data/            bases de datos y JSON (memoria de la IA, niveles, tickets...)
  .env, .env.*     TODA la configuración, incluido .env.avisos  (BACKUP_INCLUDE_ENV)
  CLAUDE.md        el manual del proyecto, que documenta hasta los servicios
  zerodesk/        .env, estado y telemetría del panel ZeroDesk (BACKUP_ZERODESK_DIR)
  systemd/*.service  los units de systemd, que viven fuera del repo
  MANIFIESTO.txt   versión, commit, Python y paquetes exactos para reconstruir

Las bases SQLite se copian con la API de backup de SQLite (foto consistente
aunque el bot esté escribiendo en modo WAL), no copiando el fichero a pelo.

Lo único que NO se guarda son las credenciales de Google Drive
(data/gdrive_token.json y data/gdrive_client.json): si se pierden se vuelven a
autorizar con scripts/autorizar_gdrive.py, y no interesa tenerlas dando vueltas
dentro del propio backup.

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
import json
import time
import asyncio
import logging
import platform
import sqlite3
import zipfile
import datetime
import tempfile
import subprocess
import importlib.metadata

import aiohttp

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from cogs import httputil

log = logging.getLogger("backup")

_RAIZ = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(_RAIZ, "data")
TOKEN_URI = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
PREFIJO = "rgl-bot-backup-"

# Documentación del proyecto que va dentro del backup. Está en git, pero un
# backup tiene que servir por sí solo aunque el repo no esté a mano.
DOCS = ("CLAUDE.md",)

# Los units de systemd viven fuera del repo (/etc/systemd/system) y sin ellos
# el bot no arranca solo tras un reinicio, así que se guardan también.
SYSTEMD_DIR = "/etc/systemd/system"
SERVICIOS = ("discordbot.service", "bot-startup.service", "recarga-web.service")

# De ZeroDesk se guarda la configuración y el estado, no el código (está en su repo).
ZERODESK_FICHEROS = (".env", "estado.json", "eventos.json", "telemetria.db")



def _excluido(nombre):
    """Lo que no va al zip: credenciales de Drive, restos de SQLite (el .db ya
    se copia consistente), temporales y zips de backups anteriores."""
    return (nombre.startswith(PREFIJO) or nombre.startswith("gdrive_") or nombre == "gdrive.json"
            or nombre.endswith(("-wal", "-shm", "-journal", ".tmp")))


def _meter_sqlite(z, completo, nombre):
    """Copia una base SQLite con su API de backup, no el fichero a pelo.

    Las bases van en modo WAL: parte de lo último escrito puede estar todavía
    en el -wal, y copiar solo el .db daría una base vieja o incoherente. La API
    de backup saca una foto consistente aunque el bot esté escribiendo."""
    with tempfile.TemporaryDirectory() as tmp:
        copia = os.path.join(tmp, "copia.db")
        origen = sqlite3.connect(f"file:{completo}?mode=ro", uri=True)
        try:
            dest = sqlite3.connect(copia)
            try:
                origen.backup(dest)
            finally:
                dest.close()
        finally:
            origen.close()
        z.write(copia, nombre)


def _manifiesto(incluidos):
    """Texto con lo necesario para reconstruir el entorno: versión del bot,
    commit, Python y paquetes exactos (como un pip freeze)."""
    def leer(ruta):
        try:
            with open(ruta, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return "?"

    commit = "?"
    try:
        r = subprocess.run(["git", "-C", _RAIZ, "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        commit = r.stdout.strip() or "?"
    except (OSError, subprocess.SubprocessError):
        pass
    paquetes = sorted(f"{d.metadata['Name']}=={d.version}"
                      for d in importlib.metadata.distributions() if d.metadata["Name"])
    lineas = [
        "Backup del RGL Discord BOT",
        f"Fecha:   {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Máquina: {platform.node()} ({platform.machine()})",
        f"Versión: {leer(os.path.join(_RAIZ, 'VERSION'))}  ·  commit {commit}",
        f"Python:  {platform.python_version()}",
        "",
        "Restaurar: clonar el repo en esa versión, copiar data/ y los .env a su",
        "sitio, los systemd/*.service a /etc/systemd/system y zerodesk/ a",
        "~/ZeroDesk/panel. Credenciales de Drive: scripts/autorizar_gdrive.py.",
        "La clave SSH de la Pi al PC (~/.ssh/id_ed25519_pc) NO va: se regenera",
        "con el instalar.sh de ZeroDesk.",
        "",
        "Contenido:",
        *(f"  {n}" for n in incluidos),
        "",
        "Paquetes del venv (pip install -r de esta lista para clavar versiones):",
        *(f"  {p}" for p in paquetes),
    ]
    return "\n".join(lineas) + "\n"


def _leer_bytes(ruta):
    with open(ruta, "rb") as f:
        return f.read()


def _leer_expiry(texto):
    """Pasa el 'expiry' de google-auth (ISO en UTC, con o sin Z) a epoch."""
    if not texto:
        return None
    try:
        dt = datetime.datetime.fromisoformat(texto.rstrip("Z"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.timestamp()


class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._acceso = None      # token de acceso en memoria
        self._caduca = 0.0
        self._carpeta_id = None
        if config.BACKUP_ENABLED and self._ruta_token():
            self.backup_automatico.change_interval(hours=config.BACKUP_INTERVAL_HOURS)
            self.backup_automatico.start()

    def cog_unload(self):
        self.backup_automatico.cancel()

    # ---------- Google Drive (API REST, sin google-api-python-client) ----------
    # Antes se usaba googleapiclient, que al importarse carga el documento de
    # descubrimiento de Drive y se queda con unos cuantos MB para siempre. Para
    # cuatro llamadas (listar, crear, subir y borrar) basta con la API REST y la
    # sesión HTTP compartida del bot.
    def _ruta_token(self):
        ruta = config.GDRIVE_TOKEN
        if not ruta:
            return None
        if not os.path.isabs(ruta):
            ruta = os.path.join(_RAIZ, ruta)
        return ruta if os.path.exists(ruta) else None

    async def _token(self, session):
        """Token de acceso válido; lo renueva con el refresh token si caducó.

        El fichero es el que escribe scripts/autorizar_gdrive.py (formato de
        google-auth): token, refresh_token, client_id, client_secret, expiry…"""
        if self._acceso and time.time() < self._caduca - 60:
            return self._acceso
        ruta = self._ruta_token()
        if not ruta:
            raise RuntimeError("No encuentro el token de Google. Ejecuta scripts/autorizar_gdrive.py")
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)

        caduca = _leer_expiry(datos.get("expiry"))
        if datos.get("token") and caduca and time.time() < caduca - 60:
            self._acceso, self._caduca = datos["token"], caduca
            return self._acceso

        if not datos.get("refresh_token"):
            raise RuntimeError("El token de Google no tiene refresh_token. Vuelve a ejecutar "
                               "scripts/autorizar_gdrive.py")
        async with session.post(datos.get("token_uri") or TOKEN_URI, data={
            "client_id": datos.get("client_id", ""),
            "client_secret": datos.get("client_secret", ""),
            "refresh_token": datos["refresh_token"],
            "grant_type": "refresh_token",
        }) as r:
            cuerpo = await r.json(content_type=None)
            if r.status != 200:
                # invalid_grant = token revocado o app de OAuth en modo "Prueba"
                raise RuntimeError(f"Google no renovó el token ({r.status}: "
                                   f"{cuerpo.get('error', cuerpo)}). Vuelve a ejecutar "
                                   "scripts/autorizar_gdrive.py")
        self._acceso = cuerpo["access_token"]
        self._caduca = time.time() + int(cuerpo.get("expires_in", 3600))
        datos["token"] = self._acceso
        datos["expiry"] = datetime.datetime.fromtimestamp(
            self._caduca, datetime.UTC).replace(tzinfo=None).isoformat() + "Z"
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f)
        os.replace(tmp, ruta)
        return self._acceso

    async def _api(self, session, metodo, url, **kw):
        """Llamada autenticada a Drive. Lanza RuntimeError con el motivo si falla."""
        cabeceras = kw.pop("headers", {})
        cabeceras["Authorization"] = f"Bearer {await self._token(session)}"
        async with session.request(metodo, url, headers=cabeceras, **kw) as r:
            if r.status >= 400:
                raise RuntimeError(f"Drive respondió {r.status}: {(await r.text())[:200]}")
            if r.status == 204:
                return {}
            return await r.json(content_type=None)

    async def _carpeta(self, session):
        """Busca (o crea) la carpeta de backups en tu Drive y devuelve su ID."""
        if self._carpeta_id:
            return self._carpeta_id
        nombre = config.GDRIVE_FOLDER_NAME.replace("'", "\\'")
        res = await self._api(session, "GET", DRIVE_API, params={
            "q": ("mimeType='application/vnd.google-apps.folder' and "
                  f"name='{nombre}' and trashed=false"),
            "pageSize": "1", "fields": "files(id,name)"})
        ficheros = res.get("files", [])
        if ficheros:
            self._carpeta_id = ficheros[0]["id"]
        else:
            carpeta = await self._api(session, "POST", DRIVE_API, params={"fields": "id"}, json={
                "name": config.GDRIVE_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder"})
            self._carpeta_id = carpeta["id"]
            log.info("Carpeta de backups creada en Drive: %s", config.GDRIVE_FOLDER_NAME)
        return self._carpeta_id

    def _comprimir(self):
        """Crea el zip (data/, configuración, ZeroDesk, units y manifiesto) y
        devuelve su ruta. Bloqueante: se llama dentro de asyncio.to_thread."""
        marca = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        destino = os.path.join(_RAIZ, f"{PREFIJO}{marca}.zip")
        incluidos = []
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            def meter(completo, nombre):
                try:
                    if nombre.endswith(".db"):
                        _meter_sqlite(z, completo, nombre)
                    else:
                        z.write(completo, nombre)
                    incluidos.append(nombre)
                except OSError as exc:
                    log.warning("No pude meter %s en el backup: %s", nombre, exc)

            if os.path.isdir(DATA_DIR):
                for raiz, _dirs, ficheros in os.walk(DATA_DIR):
                    for f in sorted(ficheros):
                        if _excluido(f):
                            continue
                        completo = os.path.join(raiz, f)
                        meter(completo, os.path.join("data", os.path.relpath(completo, DATA_DIR)))

            if config.BACKUP_INCLUDE_ENV:
                # todos los .env* de la raíz (.env, .env.avisos, .env.example...),
                # al mismo nivel que data/
                for f in sorted(os.listdir(_RAIZ)):
                    if f.startswith(".env") and not f.endswith((".swp", ".swo", "~")):
                        completo = os.path.join(_RAIZ, f)
                        if os.path.isfile(completo):
                            meter(completo, f)

            for f in DOCS:
                completo = os.path.join(_RAIZ, f)
                if os.path.isfile(completo):
                    meter(completo, f)

            # ZeroDesk (el panel de la Pi, que también controla el bot) vive en
            # otra carpeta y no tenía backup propio: su .env, su estado y su
            # histórico de telemetría.
            zd = config.BACKUP_ZERODESK_DIR
            if zd and os.path.isdir(zd):
                for f in ZERODESK_FICHEROS:
                    if f.startswith(".env") and not config.BACKUP_INCLUDE_ENV:
                        continue
                    completo = os.path.join(zd, f)
                    if os.path.isfile(completo):
                        meter(completo, os.path.join("zerodesk", f))

            # Los .service solo existen en la Pi; en Windows o si no se pueden
            # leer, simplemente no van (el resto del backup sigue valiendo).
            for f in SERVICIOS:
                completo = os.path.join(SYSTEMD_DIR, f)
                if os.path.isfile(completo):
                    meter(completo, os.path.join("systemd", f))

            z.writestr("MANIFIESTO.txt", _manifiesto(incluidos))
        return destino

    async def _subir(self, session, ruta):
        meta = {"name": os.path.basename(ruta), "parents": [await self._carpeta(session)]}
        contenido = await asyncio.to_thread(_leer_bytes, ruta)
        with aiohttp.MultipartWriter("related") as mp:
            mp.append_json(meta)
            mp.append(contenido, {"Content-Type": "application/zip"})
            return await self._api(session, "POST", DRIVE_UPLOAD, data=mp, params={
                "uploadType": "multipart", "fields": "id,name,size,webViewLink"})

    async def _listar(self, session):
        res = await self._api(session, "GET", DRIVE_API, params={
            "q": f"'{await self._carpeta(session)}' in parents and name contains '{PREFIJO}' "
                 "and trashed=false",
            "orderBy": "createdTime desc", "pageSize": "50",
            "fields": "files(id,name,size,createdTime)"})
        return res.get("files", [])

    async def _rotar(self, session):
        """Borra los backups que sobren, dejando los BACKUP_KEEP más nuevos."""
        sobran = (await self._listar(session))[config.BACKUP_KEEP:]
        for f in sobran:
            try:
                await self._api(session, "DELETE", f"{DRIVE_API}/{f['id']}")
            except Exception as exc:
                log.warning("No pude borrar el backup %s: %s", f.get("name"), exc)
        return len(sobran)

    async def _hacer_backup(self):
        """Comprime, sube y rota. Devuelve (fichero_subido, borrados)."""
        ruta = await asyncio.to_thread(self._comprimir)
        try:
            async with httputil.sesion(180) as session:
                fichero = await self._subir(session, ruta)
                borrados = await self._rotar(session)
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
            async with httputil.sesion(30) as session:
                ficheros = await self._listar(session)
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
