"""
Módulo 18 — Charla con IA (gratis) en un canal, con memoria autoguardada y
autoconsolidada.

- Responde en un canal (AI_CHANNEL_ID) a una fracción de mensajes (AI_CHANCE),
  siguiendo el hilo (últimos AI_HISTORY mensajes) y hablando como uno más.
- Sabe que cuando en el chat hablan del "BOT" se refieren a ella misma.
- Conoce el README del proyecto para resolver dudas sobre comandos.
- Memoria en dos JSON en la raíz (gitignored):
    ai_context.json  -> contexto manual (/ia_contexto, /ia_contexto_server)
    ai_saved.json    -> memoria que la IA aprende y CONSOLIDA sola
  En ambos, cada usuario guarda id + nombre + mote (apodo detectado) + info.
- Tras responder, hace una pasada de aprendizaje que ADEMÁS optimiza el fichero:
  fusiona duplicados, elimina lo trivial/obsoleto y compacta.

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
README_PATH = os.path.join(_RAIZ, "README.md")
MAX_DATOS = 15
README_MAX = 6000
LIMITE_DISCORD = 1990


def _trocear(texto, limite=LIMITE_DISCORD):
    trozos = []
    texto = texto.strip()
    while len(texto) > limite:
        corte = texto.rfind("\n", 0, limite)
        if corte < int(limite * 0.6):
            corte = texto.rfind(" ", 0, limite)
        if corte < int(limite * 0.6):
            corte = limite
        trozos.append(texto[:corte].strip())
        texto = texto[corte:].strip()
    if texto:
        trozos.append(texto)
    return trozos


def _lista_limpia(x):
    return [s.strip() for s in x if isinstance(s, str) and s.strip()][:MAX_DATOS] if isinstance(x, list) else []


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._ultima = 0.0
        self._readme = None
        self._etiquetado = False

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

    def _readme_txt(self):
        if self._readme is None:
            try:
                with open(README_PATH, encoding="utf-8") as f:
                    self._readme = f.read()
            except OSError:
                self._readme = ""
        return self._readme

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

    def _ctx_find_user(self, gid, uid):
        s = self._find_server(self._load(CONTEXT_PATH), gid)
        for u in (s.get("usuarios", []) if s else []):
            if u.get("id") == uid:
                return u
        return None

    def _set_servidor(self, gid, texto):
        d = self._load(CONTEXT_PATH)
        self._ctx_server_obj(d, gid)["contexto"] = texto or ""
        self._save(CONTEXT_PATH, d)

    def _set_usuario(self, gid, uid, nombre, texto):
        d = self._load(CONTEXT_PATH)
        usuarios = self._ctx_server_obj(d, gid)["usuarios"]
        u = next((x for x in usuarios if x.get("id") == uid), None)
        if texto:
            if u is None:
                u = {"id": uid, "nombre": nombre, "mote": "", "contexto": ""}
                usuarios.append(u)
            u["nombre"] = nombre or u.get("nombre", "")
            u["contexto"] = texto
        elif u is not None:
            usuarios.remove(u)
        self._save(CONTEXT_PATH, d)

    def _etiquetar_contexto(self, gid, etiquetas):
        """Actualiza nombre/mote en ai_context para los usuarios que ya tengan ficha."""
        d = self._load(CONTEXT_PATH)
        s = self._find_server(d, gid)
        if not s:
            return
        cambiado = False
        for u in s.get("usuarios", []):
            nm = etiquetas.get(u.get("id"))
            if not nm:
                continue
            nombre, mote = nm
            if nombre and u.get("nombre") != nombre:
                u["nombre"] = nombre
                cambiado = True
            if mote and u.get("mote") != mote:
                u["mote"] = mote
                cambiado = True
        if cambiado:
            self._save(CONTEXT_PATH, d)

    # ---------- memoria autoguardada ----------
    def _saved_server_obj(self, d, gid):
        s = self._find_server(d, gid)
        if s is None:
            s = {"id": gid, "datos": [], "estilo": [], "usuarios": []}
            d["servidores"].append(s)
        s.setdefault("datos", [])
        s.setdefault("estilo", [])
        s.setdefault("usuarios", [])
        return s

    def _saved_server_datos(self, gid):
        s = self._find_server(self._load(SAVED_PATH), gid)
        return s.get("datos", []) if s else []

    def _saved_server_estilo(self, gid):
        s = self._find_server(self._load(SAVED_PATH), gid)
        return s.get("estilo", []) if s else []

    def _saved_find_user(self, gid, uid):
        s = self._find_server(self._load(SAVED_PATH), gid)
        for u in (s.get("usuarios", []) if s else []):
            if u.get("id") == uid:
                return u
        return None

    def _aplicar_consolidado(self, gid, participantes, obj):
        """Sobrescribe (consolida) la memoria del servidor y de los participantes
        presentes con la versión optimizada que devuelve la IA."""
        d = self._load(SAVED_PATH)
        s = self._saved_server_obj(d, gid)
        serv = obj.get("servidor") or {}
        if isinstance(serv, dict):
            if "datos" in serv:
                s["datos"] = _lista_limpia(serv.get("datos"))
            if "estilo" in serv:
                s["estilo"] = _lista_limpia(serv.get("estilo"))
        por_nombre = {n.lower(): i for i, n in participantes}
        nombre_de = dict(participantes and [(i, n) for i, n in participantes])
        etiquetas = {}
        for item in (obj.get("usuarios") or []):
            if not isinstance(item, dict):
                continue
            uid = por_nombre.get((item.get("nombre") or "").strip().lower())
            if not uid:
                continue
            datos = _lista_limpia(item.get("datos"))
            mote = (item.get("mote") or "").strip()
            nombre = nombre_de.get(uid, "")
            u = next((x for x in s["usuarios"] if x.get("id") == uid), None)
            if u is None:
                u = {"id": uid}
                s["usuarios"].append(u)
            u["nombre"] = nombre or u.get("nombre", "")
            u["mote"] = mote or u.get("mote", "")
            u["datos"] = datos
            etiquetas[uid] = (u["nombre"], u["mote"])
        self._save(SAVED_PATH, d)
        if etiquetas:
            self._etiquetar_contexto(gid, etiquetas)

    # ---------- al arrancar: completar nombre/mote desde Discord ----------
    @commands.Cog.listener()
    async def on_ready(self):
        if self._etiquetado:
            return
        self._etiquetado = True
        try:
            await self._completar_etiquetas()
        except Exception as exc:
            log.warning("Fallo completando nombre/mote al arrancar: %s", exc)

    async def _completar_etiquetas(self):
        for path in (CONTEXT_PATH, SAVED_PATH):
            d = self._load(path)
            cambiado = False
            for s in d["servidores"]:
                guild = self.bot.get_guild(s.get("id"))
                if not guild:
                    continue
                for u in s.get("usuarios", []):
                    uid = u.get("id")
                    if not uid:
                        continue
                    falta_nombre = not (u.get("nombre") or "").strip()
                    falta_mote = not (u.get("mote") or "").strip()
                    if not (falta_nombre or falta_mote):
                        continue
                    miembro = guild.get_member(uid)
                    if miembro is None:
                        try:
                            miembro = await guild.fetch_member(uid)
                        except discord.HTTPException:
                            miembro = None
                    if miembro is None:
                        continue
                    if falta_nombre:
                        u["nombre"] = miembro.name
                        cambiado = True
                    if falta_mote and miembro.nick:
                        u["mote"] = miembro.nick
                        cambiado = True
            if cambiado:
                self._save(path, d)
                log.info("Completados nombre/mote en %s", os.path.basename(path))

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
                primero = True
                for tr in _trocear(respuesta):
                    if primero:
                        await message.reply(tr, mention_author=False)
                        primero = False
                    else:
                        await message.channel.send(tr)
        except Exception as exc:
            log.warning("Fallo al responder con IA: %s", exc)
            return

        if config.AI_MEMORY:
            try:
                await self._aprender(message.guild.id, historial, participantes)
            except Exception as exc:
                log.warning("Fallo al aprender/consolidar: %s", exc)

    # ---------- recopilar ----------
    async def _recopilar(self, message):
        historial = []
        async for m in message.channel.history(limit=config.AI_HISTORY or 1):
            historial.append(m)
        historial.reverse()
        participantes, vistos = [], set()
        for m in historial:
            if m.author.bot or m.author.id in vistos:
                continue
            vistos.add(m.author.id)
            participantes.append((m.author.id, m.author.display_name))
        if not participantes:
            participantes = [(message.author.id, message.author.display_name)]
        return historial, participantes

    def _construir_system(self, gid, participantes):
        partes = [config.AI_SYSTEM_PROMPT]
        partes.append(
            "Si en el chat alguien habla del 'BOT', 'el bot' o la IA del servidor, se refieren a "
            "TI. Habla en primera persona como si hablaran de ti.")
        readme = self._readme_txt()
        if readme:
            partes.append(
                "Por si alguien pregunta por un comando o cómo funciona algo del bot, aquí tienes "
                "su documentación (úsala SOLO si preguntan; explícalo con tu estilo, no la copies):\n"
                + readme[:README_MAX])
        # servidor
        serv = []
        sc = self._ctx_servidor(gid)
        if sc:
            serv.append(sc)
        serv += self._saved_server_datos(gid)
        if serv:
            partes.append("Contexto del servidor (vale para todos): " + " · ".join(serv))
        estilo = self._saved_server_estilo(gid)
        if estilo:
            partes.append("Forma de hablar del grupo (imítala, misma jerga y expresiones): " + " · ".join(estilo))
        # gente presente
        lineas = []
        for uid, nombre in participantes:
            cu = self._ctx_find_user(gid, uid)
            su = self._saved_find_user(gid, uid)
            mote = (su or {}).get("mote") or (cu or {}).get("mote") or ""
            info = []
            if cu and cu.get("contexto"):
                info.append(cu["contexto"])
            if su:
                info += su.get("datos", [])
            etiqueta = nombre + (f" (alias '{mote}')" if mote else "")
            if info:
                lineas.append(f"- {etiqueta}: " + " · ".join(info))
            elif mote:
                lineas.append(f"- {etiqueta}")
        if lineas:
            partes.append(
                "Lo que sabes de la gente que está en la conversación (úsalo solo cuando venga a "
                "cuento, sin forzarlo):\n" + "\n".join(lineas))
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

    # ---------- aprender + consolidar ----------
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

        memoria = {
            "servidor": {
                "datos": self._saved_server_datos(gid),
                "estilo": self._saved_server_estilo(gid),
            },
            "usuarios": [],
        }
        for uid, nombre in participantes:
            su = self._saved_find_user(gid, uid)
            memoria["usuarios"].append({
                "nombre": nombre,
                "mote": (su or {}).get("mote", ""),
                "datos": (su or {}).get("datos", []),
            })

        nombres = ", ".join(n for _, n in participantes)
        sys = (
            "Eres el sistema de memoria de un bot de Discord. Te paso la MEMORIA ACTUAL (JSON) y "
            "una CONVERSACIÓN reciente. Devuelve la memoria ACTUALIZADA y OPTIMIZADA en JSON, con "
            "la MISMA estructura. Reglas: añade datos nuevos y relevantes que aparezcan; FUSIONA "
            "duplicados y frases parecidas en una sola; elimina lo trivial, obsoleto o contradictorio; "
            "redacta frases cortas, claras y útiles. Detecta MOTES o apodos con los que se llaman "
            "(campo 'mote'). En 'estilo' guarda expresiones/jerga típicas del grupo. Máximo ~12 datos "
            "por persona y ~12 del servidor. Devuelve SOLO JSON válido, sin texto extra, con la forma: "
            '{"servidor": {"datos": [], "estilo": []}, "usuarios": [{"nombre": "X", "mote": "", "datos": []}]}. '
            f"Usa exactamente estos nombres de usuario: {nombres}."
        )
        user = ("MEMORIA ACTUAL:\n" + json.dumps(memoria, ensure_ascii=False)
                + "\n\nCONVERSACIÓN:\n" + "\n".join(lineas))
        data = await self._api([{"role": "system", "content": sys}, {"role": "user", "content": user}])
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
        if isinstance(obj, dict):
            self._aplicar_consolidado(gid, participantes, obj)

    # ---------- API ----------
    async def _api(self, mensajes):
        headers = {"Authorization": f"Bearer {config.AI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": config.AI_MODEL, "messages": mensajes,
                   "max_tokens": config.AI_MAX_TOKENS, "temperature": 1.0}
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(f"{config.AI_API_BASE}/chat/completions", json=payload, headers=headers) as r:
                if r.status != 200:
                    log.warning("La API de IA respondió %s: %s", r.status, (await r.text())[:200])
                    return None
                return await r.json()

    # ---------- comandos (solo staff) ----------
    def _es_admin(self, interaction):
        return interaction.guild is not None and interaction.user.guild_permissions.manage_guild

    @app_commands.command(name="ia_contexto", description="Define el contexto personal de un usuario para la IA")
    @app_commands.describe(usuario="Usuario", texto="Qué sabe la IA de esa persona (vacío = borrar)")
    async def ia_contexto(self, interaction: discord.Interaction, usuario: discord.Member, texto: str = None):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        self._set_usuario(interaction.guild.id, usuario.id, usuario.display_name, (texto or "").strip())
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
        if sv and sv.get("estilo"):
            lineas.append(f"**🗣️ Estilo**: {', '.join(sv['estilo'])[:150]}")
        for u in (sv.get("usuarios", []) if sv else []):
            etiq = u.get("nombre") or u.get("id")
            if u.get("mote"):
                etiq += f" ('{u['mote']}')"
            if u.get("datos"):
                lineas.append(f"**{etiq}**: {', '.join(u['datos'])[:200]}")
        msg = "\n".join(lineas) if lineas else "No hay contextos ni memoria en este servidor."
        await interaction.response.send_message(msg[:1900], ephemeral=True)


async def setup(bot):
    await bot.add_cog(AIChat(bot))
