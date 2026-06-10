"""
Módulo 16 — Encuestas con tiempo límite.

  /encuesta pregunta:<...> duracion:<30s|10m|2h|1d> opcion1:<...> opcion2:<...> [opcion3..opcion10]

- Mínimo 2 opciones, máximo 10.
- Se vota con BOTONES (un voto por persona; se puede cambiar mientras esté abierta).
- Cuando se acaba el tiempo, el bot borra el mensaje de la encuesta y publica
  los resultados en el mismo canal.

Las encuestas se guardan en SQLite (data/polls.db) y los botones son persistentes
(DynamicItem), así que sobreviven a reinicios de la Pi: si el bot se reinicia con
una encuesta abierta, sigue contando votos y la cierra igualmente al terminar.
"""

import os
import re
import json
import time
import secrets
import sqlite3
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger("polls")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "polls.db")
NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
MIN_SEG = 10
MAX_SEG = 7 * 24 * 3600  # 7 días


def parse_duracion(texto):
    """'30s', '10m', '2h', '1d' o un número suelto (minutos). Devuelve segundos o None."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", (texto or "").lower())
    if not m:
        return None
    n = int(m.group(1))
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 60}[m.group(2)]
    return n * mult


def barra(pct):
    llenos = round(pct / 10)
    return "█" * llenos + "░" * (10 - llenos)


# ---------- botón persistente ----------
class BotonVoto(discord.ui.DynamicItem[discord.ui.Button],
                template=r"poll:(?P<pid>[0-9a-f]+):(?P<idx>[0-9]+)"):
    def __init__(self, pid: str, idx: int, label: str = "·"):
        self.pid = pid
        self.idx = idx
        super().__init__(
            discord.ui.Button(label=label[:80], custom_id=f"poll:{pid}:{idx}",
                              style=discord.ButtonStyle.secondary)
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["pid"], int(match["idx"]))

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Polls")
        if cog:
            await cog.registrar_voto(interaction, self.pid, self.idx)


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS polls (
                   poll_id TEXT PRIMARY KEY,
                   guild_id INTEGER, channel_id INTEGER, message_id INTEGER,
                   author_id INTEGER, question TEXT, options TEXT,
                   end_ts INTEGER, closed INTEGER DEFAULT 0
               )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS votes (
                   poll_id TEXT, user_id INTEGER, option_idx INTEGER,
                   PRIMARY KEY (poll_id, user_id)
               )"""
        )
        self.db.commit()
        self.bot.add_dynamic_items(BotonVoto)  # botones persistentes tras reinicio
        self.cerrar_expiradas.start()

    def cog_unload(self):
        self.cerrar_expiradas.cancel()
        self.db.close()

    # ---------- crear ----------
    @app_commands.command(name="encuesta", description="Crea una encuesta con tiempo límite")
    @app_commands.describe(
        pregunta="La pregunta de la encuesta",
        duracion="Tiempo límite: 30s, 10m, 2h, 1d (un número solo = minutos)",
        opcion1="Opción 1", opcion2="Opción 2", opcion3="Opción 3", opcion4="Opción 4",
        opcion5="Opción 5", opcion6="Opción 6", opcion7="Opción 7", opcion8="Opción 8",
        opcion9="Opción 9", opcion10="Opción 10",
    )
    async def encuesta(self, interaction: discord.Interaction, pregunta: str, duracion: str,
                       opcion1: str, opcion2: str, opcion3: str = None, opcion4: str = None,
                       opcion5: str = None, opcion6: str = None, opcion7: str = None,
                       opcion8: str = None, opcion9: str = None, opcion10: str = None):
        opciones = [o for o in (opcion1, opcion2, opcion3, opcion4, opcion5,
                                opcion6, opcion7, opcion8, opcion9, opcion10) if o]
        # (2 mínimo garantizado por opcion1/opcion2 obligatorias; 10 máximo por la lista)

        segundos = parse_duracion(duracion)
        if segundos is None:
            await interaction.response.send_message(
                "Duración no válida. Usa por ejemplo `30s`, `10m`, `2h` o `1d`.", ephemeral=True)
            return
        if segundos < MIN_SEG:
            await interaction.response.send_message("La duración mínima es 10 segundos.", ephemeral=True)
            return
        if segundos > MAX_SEG:
            await interaction.response.send_message("La duración máxima es 7 días.", ephemeral=True)
            return

        end_ts = int(time.time()) + segundos
        pid = secrets.token_hex(5)

        desc = "\n".join(f"{NUM[i]} {opt}" for i, opt in enumerate(opciones))
        emb = discord.Embed(title=f"📊 {pregunta}", description=desc, color=0x5865F2)
        emb.add_field(name="\u200b", value=f"⏰ Termina <t:{end_ts}:R>", inline=False)
        emb.set_footer(text="Un voto por persona · puedes cambiarlo hasta que termine")

        view = discord.ui.View(timeout=None)
        for i, opt in enumerate(opciones):
            view.add_item(BotonVoto(pid, i, label=f"{i + 1}"))

        await interaction.response.send_message(embed=emb, view=view)
        msg = await interaction.original_response()

        self.db.execute(
            "INSERT INTO polls VALUES (?,?,?,?,?,?,?,?,0)",
            (pid, interaction.guild_id, interaction.channel_id, msg.id,
             interaction.user.id, pregunta, json.dumps(opciones), end_ts),
        )
        self.db.commit()
        log.info("Encuesta %s creada por %s (%d opciones, %ds)", pid, interaction.user, len(opciones), segundos)

    # ---------- votar ----------
    async def registrar_voto(self, interaction: discord.Interaction, pid: str, idx: int):
        fila = self.db.execute(
            "SELECT options, end_ts, closed FROM polls WHERE poll_id=?", (pid,)).fetchone()
        if not fila:
            await interaction.response.send_message("Esta encuesta ya no existe.", ephemeral=True)
            return
        opciones, end_ts, closed = json.loads(fila[0]), fila[1], fila[2]
        if closed or end_ts <= int(time.time()):
            await interaction.response.send_message("⏰ Esta encuesta ya ha terminado.", ephemeral=True)
            return
        self.db.execute("INSERT OR REPLACE INTO votes VALUES (?,?,?)",
                        (pid, interaction.user.id, idx))
        self.db.commit()
        await interaction.response.send_message(
            f"✅ Has votado: **{opciones[idx]}**", ephemeral=True)

    # ---------- cerrar ----------
    @tasks.loop(seconds=15)
    async def cerrar_expiradas(self):
        ahora = int(time.time())
        filas = self.db.execute(
            "SELECT poll_id, channel_id, message_id, question, options FROM polls "
            "WHERE closed=0 AND end_ts<=?", (ahora,)).fetchall()
        for pid, channel_id, message_id, question, options_json in filas:
            await self._cerrar(pid, channel_id, message_id, question, json.loads(options_json))

    async def _cerrar(self, pid, channel_id, message_id, question, opciones):
        # contar votos
        conteo = [0] * len(opciones)
        for idx, c in self.db.execute(
                "SELECT option_idx, COUNT(*) FROM votes WHERE poll_id=? GROUP BY option_idx", (pid,)):
            if 0 <= idx < len(conteo):
                conteo[idx] = c
        total = sum(conteo)
        maximo = max(conteo) if total else 0

        lineas = []
        for i, opt in enumerate(opciones):
            pct = (conteo[i] / total * 100) if total else 0
            corona = "🏆 " if total and conteo[i] == maximo else ""
            lineas.append(f"{corona}{NUM[i]} **{opt}**\n`{barra(pct)}` {conteo[i]} · {pct:.0f}%")

        emb = discord.Embed(
            title=f"📊 Resultados: {question}",
            description="\n\n".join(lineas),
            color=0x57F287 if total else 0x99AAB5,
        )
        emb.set_footer(text=f"Total de votos: {total}")

        ch = self.bot.get_channel(channel_id)
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                ch = None
        if ch is not None:
            # borrar el mensaje original de la encuesta (lo envió el bot, puede borrarlo)
            try:
                original = await ch.fetch_message(message_id)
                await original.delete()
            except discord.HTTPException:
                pass
            try:
                await ch.send(embed=emb)
            except discord.HTTPException:
                pass

        self.db.execute("UPDATE polls SET closed=1 WHERE poll_id=?", (pid,))
        self.db.commit()
        log.info("Encuesta %s cerrada (%d votos)", pid, total)

    @cerrar_expiradas.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Polls(bot))
