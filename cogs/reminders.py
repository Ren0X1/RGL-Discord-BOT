"""
Módulo 3 — Recordatorios por mensaje privado.

Comandos:
  /recordatorio  cuando: <30m | 2h | 3d | 25/12/2026 09:00>  mensaje: <texto>
  /recordatorios          -> lista tus recordatorios pendientes
  /cancelar_recordatorio  id: <número>

Los recordatorios se guardan en SQLite (data/reminders.db) para que sobrevivan
a los reinicios del bot. Un bucle revisa cada 30s los que ya vencieron y te
escribe por privado.
"""

import datetime
import os
import re
import sqlite3
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger("reminders")


class _CET(datetime.tzinfo):
    """Respaldo CET/CEST (UTC+1 / UTC+2) con las reglas de cambio de hora de la
    UE, por si en el sistema no está disponible 'tzdata'. Cubre Madrid y el
    resto de la Europa central."""

    def _last_sunday(self, year, month):
        d = datetime.date(year, month, 31)  # marzo y octubre tienen 31 días
        return d - datetime.timedelta(days=(d.weekday() - 6) % 7)

    def _is_dst(self, dt):
        if dt is None:
            return False
        year = dt.year
        inicio = datetime.datetime(year, 3, self._last_sunday(year, 3).day, 2, 0)
        fin = datetime.datetime(year, 10, self._last_sunday(year, 10).day, 3, 0)
        naive = dt.replace(tzinfo=None)
        return inicio <= naive < fin

    def utcoffset(self, dt):
        return datetime.timedelta(hours=2 if self._is_dst(dt) else 1)

    def dst(self, dt):
        return datetime.timedelta(hours=1 if self._is_dst(dt) else 0)

    def tzname(self, dt):
        return "CEST" if self._is_dst(dt) else "CET"


_CET_ZONES = {
    "Europe/Madrid", "Europe/Paris", "Europe/Berlin", "Europe/Rome",
    "Europe/Brussels", "Europe/Amsterdam", "Europe/Vienna", "Europe/Lisbon",
}

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(config.TIMEZONE)
except Exception:
    if config.TIMEZONE in _CET_ZONES:
        log.warning(
            "No se encontró 'tzdata'; uso un cálculo CET/CEST de respaldo para %s. "
            "Recomendado instalar: pip install tzdata",
            config.TIMEZONE,
        )
        TZ = _CET()
    else:
        log.warning(
            "No se encontró 'tzdata' ni respaldo para '%s'; uso UTC. "
            "Instala con: pip install tzdata",
            config.TIMEZONE,
        )
        TZ = datetime.timezone.utc

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reminders.db")

REL_RE = re.compile(r"^\s*(\d+)\s*(m|min|h|hora|horas|d|dia|dias|día|días|s|seg|segundos)\s*$", re.I)
ABS_FORMATS = ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y %H:%M")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_when(text: str):
    """Devuelve un datetime aware en UTC, o None si no se entiende."""
    text = text.strip()

    m = REL_RE.match(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("s"):
            delta = datetime.timedelta(seconds=n)
        elif unit.startswith("m"):
            delta = datetime.timedelta(minutes=n)
        elif unit.startswith("h"):
            delta = datetime.timedelta(hours=n)
        else:  # d
            delta = datetime.timedelta(days=n)
        return now_utc() + delta

    for fmt in ABS_FORMATS:
        try:
            naive = datetime.datetime.strptime(text, fmt)
            local = naive.replace(tzinfo=TZ)
            return local.astimezone(datetime.timezone.utc)
        except ValueError:
            continue
    return None


class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id INTEGER NOT NULL,
                   remind_at TEXT NOT NULL,
                   message TEXT NOT NULL,
                   created TEXT NOT NULL
               )"""
        )
        self.db.commit()
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()
        self.db.close()

    # ---------- comandos ----------
    @app_commands.command(name="recordatorio", description="Te aviso por privado en la fecha indicada")
    @app_commands.describe(
        cuando="Ej: 30m · 2h · 3d · 25/12/2026 09:00",
        mensaje="Lo que quieres que te recuerde",
    )
    async def recordatorio(self, interaction: discord.Interaction, cuando: str, mensaje: str):
        dt = parse_when(cuando)
        if dt is None:
            await interaction.response.send_message(
                "No entendí la fecha. Usa `30m`, `2h`, `3d` o `25/12/2026 09:00`.",
                ephemeral=True,
            )
            return
        if dt <= now_utc():
            await interaction.response.send_message("Esa fecha ya pasó 🙂", ephemeral=True)
            return

        self.db.execute(
            "INSERT INTO reminders (user_id, remind_at, message, created) VALUES (?, ?, ?, ?)",
            (interaction.user.id, dt.isoformat(), mensaje, now_utc().isoformat()),
        )
        self.db.commit()
        await interaction.response.send_message(
            f"✅ Listo. Te lo recordaré <t:{int(dt.timestamp())}:R> (<t:{int(dt.timestamp())}:f>).",
            ephemeral=True,
        )

    @app_commands.command(name="recordatorios", description="Lista tus recordatorios pendientes")
    async def recordatorios(self, interaction: discord.Interaction):
        rows = self.db.execute(
            "SELECT id, remind_at, message FROM reminders WHERE user_id = ? ORDER BY remind_at",
            (interaction.user.id,),
        ).fetchall()
        if not rows:
            await interaction.response.send_message("No tienes recordatorios pendientes.", ephemeral=True)
            return
        lines = []
        for rid, remind_at, msg in rows:
            ts = int(datetime.datetime.fromisoformat(remind_at).timestamp())
            lines.append(f"`#{rid}` <t:{ts}:R> — {msg[:80]}")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @app_commands.command(name="cancelar_recordatorio", description="Cancela un recordatorio por su número")
    @app_commands.describe(id="Número del recordatorio (lo ves en /recordatorios)")
    async def cancelar_recordatorio(self, interaction: discord.Interaction, id: int):
        cur = self.db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (id, interaction.user.id),
        )
        self.db.commit()
        if cur.rowcount:
            await interaction.response.send_message(f"🗑️ Recordatorio `#{id}` cancelado.", ephemeral=True)
        else:
            await interaction.response.send_message("No encontré ese recordatorio tuyo.", ephemeral=True)

    # ---------- bucle ----------
    @tasks.loop(seconds=30)
    async def check_reminders(self):
        ahora = now_utc().isoformat()
        rows = self.db.execute(
            "SELECT id, user_id, message FROM reminders WHERE remind_at <= ?",
            (ahora,),
        ).fetchall()
        for rid, user_id, message in rows:
            user = self.bot.get_user(user_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(user_id)
                except discord.HTTPException:
                    user = None
            if user:
                e = discord.Embed(
                    title="⏰ Recordatorio",
                    description=message,
                    color=0x5865F2,
                    timestamp=now_utc(),
                )
                try:
                    await user.send(embed=e)
                except discord.HTTPException:
                    pass  # DMs cerrados; lo borramos igual para no reintentar siempre
            self.db.execute("DELETE FROM reminders WHERE id = ?", (rid,))
        if rows:
            self.db.commit()

    @check_reminders.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Reminders(bot))
