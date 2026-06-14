"""
Módulo 18 — Charla con IA (gratis) en un canal, con memoria autoguardada.

En el canal AI_CHANNEL_ID, el bot analiza una fracción de los mensajes (AI_CHANCE)
y responde con IA siguiendo el hilo (últimos AI_HISTORY mensajes), vacilando como
un miembro más.

El "system prompt" combina: personalidad base (AI_SYSTEM_PROMPT) + contexto manual
(ai_context.json, con /ia_contexto y /ia_contexto_server) + memoria que la propia IA
va guardando (ai_saved.json).

Flujo robusto: PRIMERO responde (llamada normal) y DESPUÉS, en segundo plano, hace
una pasada de "aprendizaje" que extrae datos nuevos y los guarda. Si el aprendizaje
falla, la respuesta no se ve afectada.

API compatible con OpenAI. Por defecto Groq (GRATIS, sin tarjeta): clave en
https://console.groq.com -> AI_API_KEY.
"""

import os
import re
import json
import time
import random
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config

log = logging.getLogger("ai_chat")
_rng = random.SystemRandom()

_RAIZ = os.path.dirname(os.path.dirname(__file__))
CONTEXT_PATH = os.path.join(_RAIZ, "ai_context.json")
SAVED_PATH = os.path.join(_RAIZ, "ai_saved.json")
MAX_DATOS = 25


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._ultima = 0.0

    # ---------- JSON genérico ----------
    def _load(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("servidores"), list):
                return d
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return {"servidores": []}

    def _save(self, path, d):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    def _find_server(self, d, gid):
        for s in d["servidores"]:
            if s.get("id") == gid:
                return s
        return None

    # ---------- contexto manual ----------
    def _ctx_server_obj(self, d, gid):
        s = self._find_server(d, gid)
        if s is None:
            s = {"id": gid, "contexto": "", "usuarios": []}
            d["servidores"].append(s)
        s.setdefault("usuarios", [])
        return s

    def _ctx_servidor(self, gid):
        s = self._find_server(self._load(CONTEXT_PATH), gid)
        if s and s.get("contexto"):
            return s["contexto"]
        return config.AI_SERVER_CONTEXT

    def _ctx_usuario(self, gid, uid):
        s = self._find_server(self._load(CONTEXT_PATH), gid)
        for u in (s.get("usuarios", []) if s else []):
            if u.get("id") == uid:
                return u.get("contexto")
        return None

    def _set_servidor(self, gid, texto):
        d = self._load(CONTEXT_PATH)
        self._ctx_server_obj(d, gid)["contexto"] = texto or ""
        self._save(CONTEXT_PATH, d)

    def _set_usuario(self, gid, uid, texto):
        d = self._load(CONTEXT_PATH)
        usuarios = self._ctx_server_obj(d, gid)["usuarios"]
        existente = next((u for u in usuarios if u.get("id") == uid), None)
        if texto:
            if existente:
                existente["contexto"] = texto
            else:
                usuarios.append({"id": uid, "contexto": texto})
        elif existente:
            usuarios.remove(existente)
        self._save(CONTEXT_PATH, d)

    # ---------- memoria autoguardada ----------
    def _saved_server_obj(self, d, gid):
        s = self._find_server(d, gid)
        if s is None:
            s = {"id": gid, "datos": [], "usuarios": []}
            d["servidores"].append(s)
        s.setdefault("datos", [])
        s.setdefault("usuarios", [])
        return s

    def _saved_server_datos(self, gid):
        s = self._find_server(self._load(SAVED_PATH), gid)
        return s.get("datos", []) if s else []

    def _saved_user_datos(self, gid, uid):
        s = self._find_server(self._load(SAVED_PATH), gid)
        for u in (s.get("usuarios", []) if s else []):
            if u.get("id") == uid:
                return u.get("datos", [])
        return []

    def _saved_add(self, gid, uid, dato):
        dato = (dato or "").strip()
        if not dato:
            return
        d = self._load(SAVED_PATH)
        s = self._saved_server_obj(d, gid)
        if uid == 0:
            datos = s["datos"]
        else:
            u = next((x for x in s["usuarios"] if x.get("id") == uid), None)
            if u is None:
                u = {"id": uid, "datos": []}
                s["usuarios"].append(u)
            datos = u.setdefault("datos", [])
        if not any(dato.lower() == x.lower() for x in datos):
            datos.append(dato)
            del datos[:-MAX_DATOS]
            self._save(SAVED_PATH, d)

    # ---------- escucha ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not config.AI_CHANNEL_ID or message.channel.id != config.AI_CHANNEL_ID:
            return
        if not config.AI_API_KEY or not (message.content or "").strip():
            return
        if _rng.random() > config.AI_CHANCE:
            return
        ahora = time.monotonic()
        if ahora - self._ultima < config.AI_COOLDOWN:
            return
        self._ultima = ahora

        try:
            historial, participantes = await self._recopilar(message)
            async with message.channel.typing():
                respuesta = await self._generar(message.guild.id, historial, participantes)
            if respuesta:
                await message.reply(respuesta[:1900], mention_author=False)
        except Exception as exc:
            log.warning("Fallo al responder con IA: %s", exc)
            return

        # Aprendizaje aparte: nunca debe romper la respuesta
        if config.AI_MEMORY:
            try:
                await self._aprender(message.guild.id, historial, participantes)
            except Exception as exc:
                log.warning("Fallo al aprender: %s", exc)

    # ---------- recopilar conversación ----------
    async def _recopilar(self, message):
        historial = []
        async for m in message.channel.history(limit=config.AI_HISTORY or 1):
            historial.append(m)
        historial.reverse()
        participantes = [(m.author.id, m.author.display_name) for m in historial if not m.author.bot]
        if not participantes:
            participantes = [(message.author.id, message.author.display_name)]
        return historial, participantes

    def _construir_system(self, gid, participantes):
        partes = [config.AI_SYSTEM_PROMPT]
        serv = []
        sc = self._ctx_servidor(gid)
        if sc:
            serv.append(sc)
        serv += self._saved_server_datos(gid)
        if serv:
            partes.append("Contexto del servidor (vale para todos): " + " · ".join(serv))
        lineas, vistos = [], set()
        for uid, nombre in participantes:
            if uid in vistos:
                continue
            vistos.add(uid)
            info = []
            uc = self._ctx_usuario(gid, uid)
            if uc:
                info.append(uc)
            info += self._saved_user_datos(gid, uid)
            if info:
                lineas.append(f"- {nombre}: " + " · ".join(info))
        if lineas:
            partes.append(
                "Lo que sabes de la gente que está en la conversación (úsalo solo cuando "
                "venga a cuento, sin forzarlo):\n" + "\n".join(lineas))
        return "\n\n".join(partes)

    # ---------- responder ----------
    async def _generar(self, gid, historial, participantes):
        mensajes = [{"role": "system", "content": self._construir_system(gid, participantes)}]
        for m in historial:
            contenido = (m.content or "").strip()
            if not contenido:
                continue
            if self.bot.user and m.author.id == self.bot.user.id:
                mensajes.append({"role": "assistant", "content": contenido[:400]})
            else:
                mensajes.append({"role": "user", "content": f"{m.author.display_name}: {contenido[:400]}"})
        data = await self._api(mensajes)
        if not data:
            return None
        try:
            texto = (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            return None
        if not texto:
            return None
        # Quitar un posible "Nombre:" que el modelo haya puesto delante (no queremos que rolee)
        m = re.match(r"^\s*([^\n:]{1,32}):\s*(.+)$", texto, re.S)
        if m:
            nombre = m.group(1).strip().lower()
            conocidos = {n.lower() for _, n in participantes} | {"bot", "yo", "asistente", "ia"}
            if self.bot.user:
                conocidos.add((self.bot.user.display_name or "").lower())
                conocidos.add((self.bot.user.name or "").lower())
            if nombre in conocidos:
                texto = m.group(2).strip()
        return texto or None

    # ---------- aprender (pasada aparte) ----------
    async def _aprender(self, gid, historial, participantes):
        lineas = []
        for m in historial:
            c = (m.content or "").strip()
            if not c:
                continue
            quien = "BOT" if (self.bot.user and m.author.id == self.bot.user.id) else m.author.display_name
            lineas.append(f"{quien}: {c[:300]}")
        if not lineas:
            return
        nombres = ", ".join(sorted({n for _, n in participantes}))
        sys = (
            "Eres un extractor de memoria. A partir de la conversación, identifica datos NUEVOS y "
            "relevantes que merezca la pena recordar sobre el servidor o sobre personas concretas "
            "(gustos, manías, relaciones, cosas que pasan). Responde SOLO con JSON válido, sin nada "
            "más, con esta forma exacta: "
            '{"servidor": ["dato", ...], "usuarios": [{"nombre": "X", "dato": "..."}]}. '
            f"Los nombres válidos de usuario son: {nombres}. Si no hay nada que valga la pena, "
            "devuelve las listas vacías. No incluyas datos triviales, obvios ni inventados."
        )
        mensajes = [{"role": "system", "content": sys}, {"role": "user", "content": "\n".join(lineas)}]
        data = await self._api(mensajes)
        if not data:
            return
        try:
            txt = (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            return
        txt = txt.replace("```json", "").replace("```", "").strip()
        try:
            obj = json.loads(txt)
        except ValueError:
            return
        for dato in (obj.get("servidor") or []):
            if isinstance(dato, str):
                self._saved_add(gid, 0, dato)
        por_nombre = {n.lower(): i for i, n in participantes}
        for item in (obj.get("usuarios") or []):
            if not isinstance(item, dict):
                continue
            uid = por_nombre.get((item.get("nombre") or "").strip().lower())
            dato = (item.get("dato") or "").strip()
            if uid and dato:
                self._saved_add(gid, uid, dato)

    # ---------- llamada a la API ----------
    async def _api(self, mensajes):
        headers = {"Authorization": f"Bearer {config.AI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": config.AI_MODEL,
            "messages": mensajes,
            "max_tokens": config.AI_MAX_TOKENS,
            "temperature": 1.0,
        }
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(f"{config.AI_API_BASE}/chat/completions", json=payload, headers=headers) as r:
                if r.status != 200:
                    log.warning("La API de IA respondió %s: %s", r.status, (await r.text())[:200])
                    return None
                return await r.json()

    # ---------- comandos de contexto (solo staff) ----------
    def _es_admin(self, interaction):
        return interaction.guild is not None and interaction.user.guild_permissions.manage_guild

    @app_commands.command(name="ia_contexto", description="Define el contexto personal de un usuario para la IA")
    @app_commands.describe(usuario="Usuario", texto="Qué sabe la IA de esa persona (vacío = borrar)")
    async def ia_contexto(self, interaction: discord.Interaction, usuario: discord.Member, texto: str = None):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        self._set_usuario(interaction.guild.id, usuario.id, (texto or "").strip())
        if texto and texto.strip():
            await interaction.response.send_message(f"✅ Contexto guardado para {usuario.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"🗑️ Contexto de {usuario.mention} borrado.", ephemeral=True)

    @app_commands.command(name="ia_contexto_server", description="Define el contexto del servidor para la IA (para todos)")
    @app_commands.describe(texto="Contexto general del servidor (vacío = volver al predefinido del .env)")
    async def ia_contexto_server(self, interaction: discord.Interaction, texto: str = None):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        self._set_servidor(interaction.guild.id, (texto or "").strip())
        await interaction.response.send_message("✅ Contexto del servidor actualizado.", ephemeral=True)

    @app_commands.command(name="ia_contextos", description="Lista los contextos y la memoria de IA de este servidor")
    async def ia_contextos(self, interaction: discord.Interaction):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        gid = interaction.guild.id
        s = self._find_server(self._load(CONTEXT_PATH), gid)
        sv = self._find_server(self._load(SAVED_PATH), gid)
        lineas = []
        if s and s.get("contexto"):
            lineas.append(f"**🌐 Servidor (manual)**: {s['contexto'][:120]}")
        if sv and sv.get("datos"):
            lineas.append(f"**🧠 Servidor (recordado)**: {', '.join(sv['datos'])[:200]}")
        for u in (s.get("usuarios", []) if s else []):
            lineas.append(f"**<@{u.get('id')}> (manual)**: {u.get('contexto','')[:120]}")
        for u in (sv.get("usuarios", []) if sv else []):
            if u.get("datos"):
                lineas.append(f"**<@{u.get('id')}> (recordado)**: {', '.join(u['datos'])[:200]}")
        msg = "\n".join(lineas) if lineas else "No hay contextos ni memoria en este servidor."
        await interaction.response.send_message(msg[:1900], ephemeral=True)


async def setup(bot):
    await bot.add_cog(AIChat(bot))
