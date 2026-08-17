"""
Módulo 18 — Charla con IA (gratis) en un canal, con memoria autoguardada y
autoconsolidada.

- Responde en AI_CHANNEL_ID a una fracción de mensajes (AI_CHANCE), siguiendo el
  hilo (últimos AI_HISTORY mensajes) y hablando como uno más del grupo.
- Si le MENCIONAN o RESPONDEN a un mensaje suyo, contesta SIEMPRE (sin chance).
- Respuestas largas o con varias frases -> se mandan como VARIOS mensajes de
  Discord (no como un \\n dentro de uno).
- Sabe que cuando hablan del "BOT" se refieren a ella. Conoce el README, pero solo
  lo usa cuando alguien pregunta por un comando o por cómo funciona el bot.
- Memoria en dos JSON (gitignored): ai_context.json (manual) y ai_saved.json (que
  la IA aprende y CONSOLIDA sola: fusiona duplicados, quita lo viejo, compacta).
  En ambos cada usuario guarda id + nombre + mote.
- Resumen diario opcional (AI_SUMMARY_CHANNEL_ID / AI_SUMMARY_HOUR).
- Interruptor en vivo desde el panel mediante ai_state.json ({"enabled": bool}).

API compatible con OpenAI. Por defecto Groq (GRATIS): clave en
https://console.groq.com -> AI_API_KEY.
"""

import os
import re
import json
import time
import random
import asyncio
import logging
import unicodedata
from datetime import time as dtime, datetime, timedelta, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger("ai_chat")
_rng = random.SystemRandom()

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(getattr(config, "TIMEZONE", "Europe/Madrid"))
except Exception:
    _TZ = timezone.utc

_RAIZ = os.path.dirname(os.path.dirname(__file__))
_DATA = os.path.join(_RAIZ, "data")
CONTEXT_PATH = os.path.join(_DATA, "ai_context.json")
SAVED_PATH = os.path.join(_DATA, "ai_saved.json")
README_PATH = os.path.join(_RAIZ, "README.md")
STATE_PATH = os.path.join(_DATA, "ai_state.json")
MAX_DATOS = 18            # tope duro de datos por persona/servidor
OBJETIVO_DATOS = 10       # a cuántos comprime la consolidación
UMBRAL_CONSOLIDA = 14     # a partir de aquí, la tarea diaria fusiona
APRENDER_CADA = 5         # cada cuántos mensajes captura contexto (aunque no responda)
MIN_TOKENS_RAZONADOR = 1500   # presupuesto mínimo para modelos que "razonan" antes de responder
README_MAX = 6000
LIMITE_DISCORD = 1990

_CLAVES_BOT = (
    "comando", "comandos", "cómo funciona", "como funciona", "qué haces", "que haces",
    "para qué sirve", "para que sirve", "qué eres", "que eres", "cómo te", "como te",
    "qué puedes", "que puedes", "función", "funcion", "ayuda", "help",
)


def _trocear(texto, limite=LIMITE_DISCORD):
    """Parte un texto largo en trozos <= limite respetando espacios."""
    trozos = []
    texto = texto.strip()
    while len(texto) > limite:
        corte = texto.rfind(" ", 0, limite)
        if corte < int(limite * 0.6):
            corte = limite
        trozos.append(texto[:corte].strip())
        texto = texto[corte:].strip()
    if texto:
        trozos.append(texto)
    return trozos


def _dividir(texto):
    """Cada línea no vacía es un mensaje aparte de Discord; trocea las muy largas."""
    salida = []
    for linea in (texto or "").split("\n"):
        linea = linea.strip()
        if linea:
            salida.extend(_trocear(linea))
    return salida[:5]   # tope de seguridad: máximo 5 mensajes seguidos


def _es_razonador(modelo):
    """Modelos que consumen tokens razonando antes de escribir la respuesta."""
    m = (modelo or "").lower()
    return "gpt-oss" in m or "qwen3" in m or "o1" in m or "deepseek-r1" in m or "reason" in m


def _hoy():
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def _clave(texto):
    """Normaliza un texto para comparar duplicados (sin tildes ni puntuación)."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _norm_lista(lista):
    """Migra a [{texto,veces,ult}] desde textos sueltos (formato viejo) o dicts."""
    out = []
    for x in (lista or []):
        if isinstance(x, str):
            t = x.strip()
            if t:
                out.append({"texto": t, "veces": 1, "ult": _hoy()})
        elif isinstance(x, dict):
            t = (x.get("texto") or "").strip()
            if t:
                out.append({"texto": t, "veces": int(x.get("veces", 1) or 1),
                            "ult": x.get("ult") or _hoy()})
    return out


def _ordenar(lista):
    return sorted(lista, key=lambda d: (int(d.get("veces", 1) or 1), d.get("ult", "")), reverse=True)


def _top_textos(lista, n=None):
    orden = _ordenar(_norm_lista(lista))
    return [d["texto"] for d in (orden[:n] if n else orden)]


def _reforzar(lista, texto):
    """Añade un dato o, si ya existe uno equivalente, lo refuerza (veces++)."""
    t = (texto or "").strip()
    k = _clave(t)
    if len(k) < 3:
        return
    for it in lista:
        if _clave(it.get("texto", "")) == k:
            it["veces"] = int(it.get("veces", 1) or 1) + 1
            it["ult"] = _hoy()
            return
    lista.append({"texto": t, "veces": 1, "ult": _hoy()})


def _podar(lista, tope=MAX_DATOS):
    return _ordenar(_norm_lista(lista))[:tope]


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._ultima = 0.0
        self._readme = None
        self._etiquetado = False
        self._contador = {}        # gid -> mensajes desde el último aprendizaje
        self._modelo_avisado = False   # para no repetir el aviso de modelo caído
        self._aprendiendo = False
        if config.AI_SUMMARY_CHANNEL_ID and config.AI_API_KEY:
            self.resumen_diario.start()
        if config.AI_MEMORY and config.AI_API_KEY:
            self.consolidar_memoria.start()

    def cog_unload(self):
        self.resumen_diario.cancel()
        self.consolidar_memoria.cancel()

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
        os.makedirs(os.path.dirname(path), exist_ok=True)
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

    def _activo(self):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return bool(json.load(f).get("enabled", True))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return True

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
    def _saved_load(self):
        """Carga ai_saved.json migrando datos/estilo al formato {texto,veces,ult}."""
        d = self._load(SAVED_PATH)
        for s in d["servidores"]:
            s["datos"] = _norm_lista(s.get("datos"))
            s["estilo"] = _norm_lista(s.get("estilo"))
            for u in s.get("usuarios", []):
                u["datos"] = _norm_lista(u.get("datos"))
        return d

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
        s = self._find_server(self._saved_load(), gid)
        return s.get("datos", []) if s else []

    def _saved_server_estilo(self, gid):
        s = self._find_server(self._saved_load(), gid)
        return s.get("estilo", []) if s else []

    def _saved_find_user(self, gid, uid):
        s = self._find_server(self._saved_load(), gid)
        for u in (s.get("usuarios", []) if s else []):
            if u.get("id") == uid:
                return u
        return None

    async def _fusionar(self, lista, quien=""):
        """Pide a la IA fusionar/compactar una lista de {texto,veces} a ~OBJETIVO_DATOS."""
        entradas = _ordenar(_norm_lista(lista))
        if len(entradas) <= OBJETIVO_DATOS:
            return None
        payload = [{"texto": e["texto"], "veces": e.get("veces", 1)} for e in entradas]
        sys = (
            "Recibes una lista JSON de datos memorizados sobre " + (quien or "un servidor") + ", cada uno "
            "con 'veces' (cuántas veces se ha visto). FUSIONA los que digan lo mismo o casi lo mismo en UNO "
            "solo (el más completo y corto) SUMANDO sus 'veces'; elimina lo trivial, obsoleto o "
            "contradictorio; prioriza lo de más 'veces'. Deja como MUCHO " + str(OBJETIVO_DATOS) + " datos. "
            'Devuelve SOLO JSON: {"datos":[{"texto":"","veces":N}]}.'
        )
        data = await self._api([{"role": "system", "content": sys},
                                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        if not data:
            return None
        try:
            txt = (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            return None
        txt = txt.replace("```json", "").replace("```", "").strip()
        try:
            obj = json.loads(txt)
        except ValueError:
            return None
        bruto = obj.get("datos") if isinstance(obj, dict) else obj
        salida = []
        for it in (bruto or []):
            if isinstance(it, dict) and (it.get("texto") or "").strip():
                salida.append({"texto": it["texto"].strip(),
                               "veces": int(it.get("veces", 1) or 1), "ult": _hoy()})
            elif isinstance(it, str) and it.strip():
                salida.append({"texto": it.strip(), "veces": 1, "ult": _hoy()})
        return _podar(salida, OBJETIVO_DATOS) if salida else None

    # ---------- al arrancar: completar nombre/mote desde Discord ----------
    @commands.Cog.listener()
    async def on_ready(self):
        if self._etiquetado:
            return
        self._etiquetado = True
        try:
            await self._completar_etiquetas()
        except Exception as exc:
            log.warning("Fallo completando nombre/mote: %s", exc)

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
    def _es_directo(self, message):
        if not self.bot.user:
            return False
        if self.bot.user in message.mentions:
            return True
        ref = getattr(message, "reference", None)
        res = getattr(ref, "resolved", None) if ref else None
        if isinstance(res, discord.Message) and res.author.id == self.bot.user.id:
            return True
        return False

    def _pregunta_del_bot(self, texto):
        t = (texto or "").lower()
        if re.search(r"/[a-záéíóúñ_]{2,}", t):
            return True
        menciona = "bot" in t or " ia " in f" {t} "
        if "?" in t and (menciona or any(k in t for k in _CLAVES_BOT)):
            return True
        return menciona and any(k in t for k in _CLAVES_BOT)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not config.AI_CHANNEL_ID or message.channel.id != config.AI_CHANNEL_ID:
            return
        if not config.AI_API_KEY or not (message.content or "").strip():
            return
        if not self._activo():
            return

        gid = message.guild.id

        # --- aprendizaje por nº de mensajes (aunque el bot no responda) ---
        if config.AI_MEMORY:
            self._contador[gid] = self._contador.get(gid, 0) + 1
            if self._contador[gid] >= APRENDER_CADA and not self._aprendiendo:
                self._contador[gid] = 0
                log.info("Lanzando captura de memoria (cada %d mensajes)", APRENDER_CADA)
                asyncio.create_task(self._aprender_seguro(message))

        directo = self._es_directo(message)
        if not directo:
            if _rng.random() > config.AI_CHANCE:
                return
            ahora = time.monotonic()
            if ahora - self._ultima < config.AI_COOLDOWN:
                return
        self._ultima = time.monotonic()

        incluir_readme = self._pregunta_del_bot(message.content)
        try:
            historial, participantes = await self._recopilar(message)
            async with message.channel.typing():
                respuesta = await self._generar(gid, historial, participantes, incluir_readme)
            if respuesta:
                primero = True
                for tr in _dividir(respuesta):
                    if primero:
                        await message.reply(tr, mention_author=False)
                        primero = False
                    else:
                        await message.channel.send(tr)
        except Exception as exc:
            log.warning("Fallo al responder con IA: %s", exc)
            return

    async def _aprender_seguro(self, message):
        self._aprendiendo = True
        try:
            historial, participantes = await self._recopilar(message)
            await self._capturar(message.guild.id, historial, participantes)
        except Exception as exc:
            log.warning("Fallo al aprender: %s", exc)
        finally:
            self._aprendiendo = False

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

    def _construir_system(self, gid, participantes, incluir_readme=False):
        partes = [config.AI_SYSTEM_PROMPT]
        partes.append(
            "Si en el chat alguien habla del 'BOT', 'el bot' o la IA del servidor, se refieren a TI: "
            "respóndeles en primera persona, no en tercera.")
        if incluir_readme and self._readme_txt():
            partes.append(
                "Parece que preguntan por un comando o por cómo funciona el bot. Aquí tienes su "
                "documentación; explícalo con tu estilo y en corto, sin copiarla:\n" + self._readme_txt()[:README_MAX])
        serv = []
        sc = self._ctx_servidor(gid)
        if sc:
            serv.append(sc)
        serv += _top_textos(self._saved_server_datos(gid), 12)
        if serv:
            partes.append("Contexto del servidor (vale para todos): " + " · ".join(serv))
        estilo = _top_textos(self._saved_server_estilo(gid), 10)
        if estilo:
            partes.append("Expresiones/jerga del grupo (úsalas para sonar como ellos): " + " · ".join(estilo))
        lineas = []
        for uid, nombre in participantes:
            cu = self._ctx_find_user(gid, uid)
            su = self._saved_find_user(gid, uid)
            mote = (su or {}).get("mote") or (cu or {}).get("mote") or ""
            info = []
            if cu and cu.get("contexto"):
                info.append(cu["contexto"])
            if su:
                info += _top_textos(su.get("datos"), 12)
            etiqueta = nombre + (f" (alias '{mote}')" if mote else "")
            if info:
                lineas.append(f"- {etiqueta}: " + " · ".join(info))
            elif mote:
                lineas.append(f"- {etiqueta}")
        if lineas:
            partes.append(
                "Lo que sabes de la gente presente (úsalo solo cuando venga a cuento para un buen "
                "zasca, sin forzarlo):\n" + "\n".join(lineas))
        return "\n\n".join(partes)

    # ---------- responder ----------
    async def _generar(self, gid, historial, participantes, incluir_readme=False):
        mensajes = [{"role": "system", "content": self._construir_system(gid, participantes, incluir_readme)}]
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
            msg = data["choices"][0]["message"]
            texto = (msg.get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            return None
        # los modelos de razonamiento a veces cuelan tokens de control
        texto = re.sub(r"<\|[a-z_]+\|>", "", texto).strip()
        if not texto:
            fin = (data.get("choices") or [{}])[0].get("finish_reason")
            log.warning("La IA devolvió una respuesta vacía (finish_reason=%s). "
                        "Si es un modelo de razonamiento, sube AI_MAX_TOKENS.", fin)
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

    # ---------- capturar (aditivo, mapeo por número) ----------
    async def _capturar(self, gid, historial, participantes):
        lineas = []
        for m in historial:
            c = (m.content or "").strip()
            if not c:
                continue
            quien = "BOT" if (self.bot.user and m.author.id == self.bot.user.id) else m.author.display_name
            lineas.append(f"{quien}: {c[:300]}")
        if len(lineas) < 2:
            log.info("Captura cancelada: solo %d mensajes con texto", len(lineas))
            return

        vistos, orden = set(), []
        for uid, nombre in participantes:
            if uid not in vistos:
                vistos.add(uid)
                orden.append((uid, nombre))

        d = self._saved_load()
        s = self._saved_server_obj(d, gid)
        conocido_serv = _top_textos(s.get("datos"), 12)
        fichas = []
        for i, (uid, nombre) in enumerate(orden, 1):
            u = next((x for x in s["usuarios"] if x.get("id") == uid), None)
            ya = _top_textos((u or {}).get("datos"), 10)
            fichas.append(f"[{i}] {nombre}" + (f" (ya sabes: {'; '.join(ya)})" if ya else ""))

        sys = (
            "Eres el sistema de memoria de un bot de Discord. Lee la CONVERSACIÓN y extrae SOLO hechos "
            "NUEVOS, concretos y claramente dichos sobre estas personas o sobre el servidor (gustos, manías, "
            "relaciones, curro, juegos, cosas que pasan). NO repitas ni reformules lo que ya se sabe. NO "
            "inventes. Frases muy cortas. Identifica a cada persona por su NÚMERO [n]. Detecta motes/apodos. "
            "En 'estilo' guarda expresiones o jerga típicas del grupo que aparezcan. Devuelve SOLO JSON con "
            'la forma: {"servidor":[], "estilo":[], "usuarios":[{"n":1, "mote":"", "datos":[]}]}. '
            "Si no hay nada nuevo, devuelve listas vacías.\n\nPERSONAS:\n" + "\n".join(fichas)
            + (("\n\nYA SABES DEL SERVIDOR: " + "; ".join(conocido_serv)) if conocido_serv else "")
        )
        data = await self._api([{"role": "system", "content": sys},
                                {"role": "user", "content": "CONVERSACIÓN:\n" + "\n".join(lineas)}])
        if not data:
            log.warning("Captura: la API no devolvió nada")
            return
        try:
            txt = (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            log.warning("Captura: respuesta de la API con formato raro: %s", str(data)[:200])
            return
        txt = txt.replace("```json", "").replace("```", "").strip()
        # el modelo a veces mete texto alrededor del JSON: nos quedamos con el bloque
        if not txt.startswith("{"):
            ini, fin = txt.find("{"), txt.rfind("}")
            if ini != -1 and fin > ini:
                txt = txt[ini:fin + 1]
        try:
            obj = json.loads(txt)
        except ValueError:
            log.warning("Captura: el modelo no devolvió JSON válido: %s", txt[:200])
            return
        if not isinstance(obj, dict):
            log.warning("Captura: JSON inesperado (%s)", type(obj).__name__)
            return

        cambios = False
        etiquetas = {}
        for t in (obj.get("servidor") or []):
            if isinstance(t, str) and t.strip():
                _reforzar(s["datos"], t)
                cambios = True
        for t in (obj.get("estilo") or []):
            if isinstance(t, str) and t.strip():
                _reforzar(s["estilo"], t)
                cambios = True
        for item in (obj.get("usuarios") or []):
            if not isinstance(item, dict):
                continue
            try:
                n = int(item.get("n"))
            except (TypeError, ValueError):
                continue
            if not (1 <= n <= len(orden)):
                continue
            uid, nombre = orden[n - 1]
            u = next((x for x in s["usuarios"] if x.get("id") == uid), None)
            if u is None:
                u = {"id": uid, "nombre": nombre, "mote": "", "datos": []}
                s["usuarios"].append(u)
            u.setdefault("datos", [])
            u["nombre"] = nombre or u.get("nombre", "")
            mote = (item.get("mote") or "").strip()
            if mote:
                u["mote"] = mote
            for t in (item.get("datos") or []):
                if isinstance(t, str) and t.strip():
                    _reforzar(u["datos"], t)
                    cambios = True
            u["datos"] = _podar(u["datos"])
            etiquetas[uid] = (u["nombre"], u.get("mote", ""))

        s["datos"] = _podar(s["datos"])
        s["estilo"] = _podar(s["estilo"])
        # guardamos siempre: así el fichero existe desde la primera captura, aunque
        # esta vez el modelo no haya encontrado nada nuevo que apuntar
        self._save(SAVED_PATH, d)
        if etiquetas:
            self._etiquetar_contexto(gid, etiquetas)
        log.info("Captura completada: %s (%d personas en memoria)",
                 "con datos nuevos" if cambios else "sin datos nuevos", len(s["usuarios"]))
        return cambios

    # ---------- consolidación diaria (fusiona duplicados/parecidos) ----------
    @tasks.loop(time=dtime(hour=5, tzinfo=_TZ))
    async def consolidar_memoria(self):
        if not config.AI_API_KEY:
            return
        d = self._saved_load()
        cambios = False
        for s in d["servidores"]:
            if len(s.get("datos", [])) > UMBRAL_CONSOLIDA:
                nuevo = await self._fusionar(s["datos"])
                if nuevo is not None:
                    s["datos"] = nuevo
                    cambios = True
            if len(s.get("estilo", [])) > UMBRAL_CONSOLIDA:
                nuevo = await self._fusionar(s["estilo"])
                if nuevo is not None:
                    s["estilo"] = nuevo
                    cambios = True
            for u in s.get("usuarios", []):
                if len(u.get("datos", [])) > UMBRAL_CONSOLIDA:
                    nuevo = await self._fusionar(u["datos"], quien=u.get("nombre", ""))
                    if nuevo is not None:
                        u["datos"] = nuevo
                        cambios = True
        if cambios:
            self._save(SAVED_PATH, d)
            log.info("Memoria de IA consolidada")

    @consolidar_memoria.before_loop
    async def _antes_consolidar(self):
        await self.bot.wait_until_ready()

    # ---------- resumen diario (#7) ----------
    @tasks.loop(time=dtime(hour=config.AI_SUMMARY_HOUR, tzinfo=_TZ))
    async def resumen_diario(self):
        cid = config.AI_SUMMARY_CHANNEL_ID
        canal = self.bot.get_channel(cid) if cid else None
        if canal is None or not config.AI_API_KEY:
            return
        desde = datetime.now(_TZ) - timedelta(days=1)
        lineas = []
        try:
            async for m in canal.history(limit=400, after=desde, oldest_first=True):
                if m.author.bot:
                    continue
                c = (m.content or "").strip()
                if c:
                    lineas.append(f"{m.author.display_name}: {c[:200]}")
        except discord.HTTPException:
            return
        if len(lineas) < 5:
            return
        sys = (config.AI_SYSTEM_PROMPT + "\n\nAhora haz un RESUMEN gracioso y breve (4-6 frases, una por "
               "línea) de lo que se habló ayer en el chat, en plan colega y con algún zasca a quien "
               "proceda. No saludes ni te despidas, ve al grano.")
        data = await self._api([{"role": "system", "content": sys},
                                {"role": "user", "content": "\n".join(lineas[-250:])}])
        if not data:
            return
        try:
            texto = (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            return
        for tr in _dividir(texto):
            await canal.send(tr)

    @resumen_diario.before_loop
    async def _antes_resumen(self):
        await self.bot.wait_until_ready()

    # ---------- API ----------
    async def _api(self, mensajes):
        headers = {"Authorization": f"Bearer {config.AI_API_KEY}", "Content-Type": "application/json"}
        modelo = config.AI_MODEL or ""
        payload = {"model": modelo, "messages": mensajes, "temperature": 1.0}

        if _es_razonador(modelo):
            # Los modelos de razonamiento (gpt-oss, qwen3...) gastan tokens "pensando"
            # ANTES de escribir la respuesta. Con un presupuesto corto se quedaban sin
            # tokens y devolvían content vacío (el bot no respondía). Por eso:
            #  - reasoning_effort bajo: piensan poco, que esto es cachondeo, no álgebra
            #  - reasoning_format hidden: no queremos ver su chapa, solo la respuesta
            #  - presupuesto ampliado: el razonamiento no se come la respuesta
            payload["reasoning_effort"] = "low"
            payload["reasoning_format"] = "hidden"
            payload["max_completion_tokens"] = max(config.AI_MAX_TOKENS, MIN_TOKENS_RAZONADOR)
        else:
            payload["max_tokens"] = config.AI_MAX_TOKENS
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(f"{config.AI_API_BASE}/chat/completions", json=payload, headers=headers) as r:
                if r.status != 200:
                    cuerpo = (await r.text())[:300]
                    log.warning("La API de IA respondió %s: %s", r.status, cuerpo)
                    # el modelo ya no existe / sin acceso: avisar al owner UNA vez
                    if r.status in (400, 404) and ("model_not_found" in cuerpo
                                                   or "decommissioned" in cuerpo
                                                   or "does not exist" in cuerpo):
                        await self._avisar_modelo_caido(cuerpo)
                    return None
                return await r.json()

    async def _avisar_modelo_caido(self, detalle):
        if self._modelo_avisado or not config.OWNER_USER_ID:
            return
        self._modelo_avisado = True
        texto = (f"⚠️ **El modelo de IA `{config.AI_MODEL}` ya no está disponible.**\n"
                 "La charla con IA está caída hasta que lo cambies.\n\n"
                 "Pon otro modelo en `AI_MODEL` del `.env` y reinicia el bot. "
                 "Mira los disponibles en https://console.groq.com/docs/models\n"
                 f"```{detalle[:300]}```")
        try:
            owner = self.bot.get_user(config.OWNER_USER_ID) or await self.bot.fetch_user(config.OWNER_USER_ID)
            if owner:
                await owner.send(embed=discord.Embed(description=texto, color=0xff4d4d))
        except discord.HTTPException:
            pass

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
        sv = self._find_server(self._saved_load(), gid)
        lineas = []
        if s and s.get("contexto"):
            lineas.append(f"**🌐 Servidor (manual)**: {s['contexto'][:120]}")
        if sv and sv.get("datos"):
            lineas.append(f"**🧠 Servidor (recordado)**: {', '.join(_top_textos(sv['datos'], 12))[:200]}")
        if sv and sv.get("estilo"):
            lineas.append(f"**🗣️ Estilo**: {', '.join(_top_textos(sv['estilo'], 10))[:150]}")
        for u in (sv.get("usuarios", []) if sv else []):
            etiq = u.get("nombre") or u.get("id")
            if u.get("mote"):
                etiq += f" ('{u['mote']}')"
            if u.get("datos"):
                lineas.append(f"**{etiq}**: {', '.join(_top_textos(u['datos'], 12))[:200]}")
        msg = "\n".join(lineas) if lineas else "No hay contextos ni memoria en este servidor."
        await interaction.response.send_message(msg[:1900], ephemeral=True)


    @app_commands.command(name="ia_aprender",
                          description="Fuerza ahora una captura de memoria y dice qué ha pasado")
    async def ia_aprender(self, interaction: discord.Interaction):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not config.AI_API_KEY:
            await interaction.followup.send("⚠️ Falta `AI_API_KEY` en el `.env`.")
            return
        canal = self.bot.get_channel(config.AI_CHANNEL_ID) if config.AI_CHANNEL_ID else None
        if canal is None:
            await interaction.followup.send(
                f"⚠️ No encuentro el canal de IA (`AI_CHANNEL_ID={config.AI_CHANNEL_ID}`).")
            return
        historial = []
        async for m in canal.history(limit=config.AI_HISTORY or 20):
            historial.append(m)
        historial.reverse()
        participantes, vistos = [], set()
        for m in historial:
            if m.author.bot or m.author.id in vistos:
                continue
            vistos.add(m.author.id)
            participantes.append((m.author.id, m.author.display_name))
        if not participantes:
            await interaction.followup.send(
                f"⚠️ No hay mensajes de personas en {canal.mention} para aprender.")
            return
        try:
            cambios = await self._capturar(interaction.guild.id, historial, participantes)
        except Exception as exc:
            log.warning("Fallo en /ia_aprender: %s", exc)
            await interaction.followup.send(f"⚠️ La captura ha fallado: `{exc}`")
            return
        existe = os.path.exists(SAVED_PATH)
        s = self._find_server(self._saved_load(), interaction.guild.id) or {}
        total = sum(len(u.get("datos", [])) for u in s.get("usuarios", [])) + len(s.get("datos", []))
        await interaction.followup.send(
            f"{'✅ Datos nuevos guardados.' if cambios else 'ℹ️ Sin datos nuevos esta vez.'}\n"
            f"Fichero `data/ai_saved.json`: {'existe' if existe else '**NO existe**'}\n"
            f"Mensajes analizados: {len(historial)} · personas: {len(participantes)} · "
            f"datos en memoria: {total}")

    @app_commands.command(name="ia_memoria", description="Ver lo que la IA ha aprendido de alguien (numerado)")
    @app_commands.describe(usuario="Usuario (vacío = memoria del servidor)")
    async def ia_memoria(self, interaction: discord.Interaction, usuario: discord.Member = None):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        gid = interaction.guild.id
        if usuario:
            u = self._saved_find_user(gid, usuario.id)
            datos = _ordenar(_norm_lista((u or {}).get("datos")))
            titulo = f"🧠 Memoria de {usuario.display_name}"
            if u and u.get("mote"):
                titulo += f" (alias '{u['mote']}')"
        else:
            s = self._find_server(self._saved_load(), gid)
            datos = _ordenar(_norm_lista((s or {}).get("datos")))
            titulo = "🧠 Memoria del servidor"
        if not datos:
            await interaction.response.send_message(f"{titulo}: no hay nada guardado todavía.", ephemeral=True)
            return
        lineas = [f"`{i}.` {d['texto']}  ·  ×{d.get('veces', 1)}" for i, d in enumerate(datos, 1)]
        e = discord.Embed(title=titulo, description="\n".join(lineas)[:3900], color=0x00ff66)
        e.set_footer(text="Usa /ia_olvidar con el número para borrar un dato")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="ia_olvidar", description="Borra un dato concreto que la IA haya aprendido")
    @app_commands.describe(numero="Número del dato (míralo con /ia_memoria)",
                           usuario="Usuario dueño del dato (vacío = memoria del servidor)")
    async def ia_olvidar(self, interaction: discord.Interaction, numero: int, usuario: discord.Member = None):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        gid = interaction.guild.id
        d = self._saved_load()
        s = self._find_server(d, gid)
        if s is None:
            await interaction.response.send_message("No hay memoria en este servidor.", ephemeral=True)
            return
        if usuario:
            destino = next((x for x in s.get("usuarios", []) if x.get("id") == usuario.id), None)
            quien = usuario.display_name
        else:
            destino = s
            quien = "el servidor"
        datos = _ordenar(_norm_lista((destino or {}).get("datos")))
        if not datos or not (1 <= numero <= len(datos)):
            await interaction.response.send_message(
                f"Ese número no existe. Mira los datos con `/ia_memoria`.", ephemeral=True)
            return
        borrado = datos.pop(numero - 1)
        destino["datos"] = datos
        self._save(SAVED_PATH, d)
        await interaction.response.send_message(
            f"🗑️ Olvidado de **{quien}**: {borrado['texto']}", ephemeral=True)

    @app_commands.command(name="ia_reset", description="Borra TODA la memoria aprendida de alguien o del servidor")
    @app_commands.describe(usuario="Usuario a resetear (vacío = memoria aprendida del servidor)",
                           todo="True = borra la memoria aprendida de TODO el servidor y su gente")
    async def ia_reset(self, interaction: discord.Interaction, usuario: discord.Member = None, todo: bool = False):
        if not self._es_admin(interaction):
            await interaction.response.send_message("Necesitas **Gestionar servidor**.", ephemeral=True)
            return
        gid = interaction.guild.id
        d = self._saved_load()
        s = self._find_server(d, gid)
        if s is None:
            await interaction.response.send_message("No hay memoria que borrar.", ephemeral=True)
            return
        if todo:
            s["datos"], s["estilo"], s["usuarios"] = [], [], []
            msg = "🧹 Borrada toda la memoria **aprendida** del servidor (el contexto manual sigue intacto)."
        elif usuario:
            u = next((x for x in s.get("usuarios", []) if x.get("id") == usuario.id), None)
            if u is None:
                await interaction.response.send_message(
                    f"La IA no tiene nada aprendido de {usuario.mention}.", ephemeral=True)
                return
            u["datos"] = []
            msg = f"🧹 Borrada la memoria aprendida de {usuario.mention}."
        else:
            s["datos"] = []
            msg = "🧹 Borrada la memoria aprendida del servidor (la de cada usuario sigue)."
        self._save(SAVED_PATH, d)
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AIChat(bot))
