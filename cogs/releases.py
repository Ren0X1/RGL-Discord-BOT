"""
Módulo 19 — Aviso de nuevas releases de GitHub.

Comprueba cada GITHUB_RELEASES_INTERVAL minutos la última release de cada repo de
GITHUB_RELEASES_REPOS ("owner/repo"). Cuando aparece una nueva, la anuncia en
GITHUB_RELEASES_CHANNEL_ID con un embed y un ping (GITHUB_RELEASES_MENTION, por
defecto @everyone).

Para no spamear, en la primera comprobación de cada repo guarda la versión actual
SIN anunciarla; a partir de ahí solo avisa de las nuevas. El estado se guarda en
data/releases_state.json para que sobreviva a reinicios.
"""

import os
import json
import logging

import aiohttp
import discord
from discord.ext import commands, tasks

import config

log = logging.getLogger("releases")

_RAIZ = os.path.dirname(os.path.dirname(__file__))
STATE_PATH = os.path.join(_RAIZ, "data", "releases_state.json")


class Releases(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._estado = self._load()
        if config.GITHUB_RELEASES_REPOS and config.GITHUB_RELEASES_CHANNEL_ID:
            self.comprobar.change_interval(minutes=config.GITHUB_RELEASES_INTERVAL)
            self.comprobar.start()

    def cog_unload(self):
        self.comprobar.cancel()

    # ---------- estado ----------
    def _load(self):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._estado, f, ensure_ascii=False, indent=2)

    # ---------- GitHub ----------
    async def _ultima_release(self, session, repo):
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "RGL-Discord-BOT"}
        if config.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
        async with session.get(url, headers=headers) as r:
            if r.status == 404:
                return None   # el repo no tiene releases (o no existe)
            if r.status != 200:
                log.warning("GitHub respondió %s para %s", r.status, repo)
                return None
            return await r.json()

    # ---------- bucle ----------
    @tasks.loop(minutes=15)
    async def comprobar(self):
        canal = self.bot.get_channel(config.GITHUB_RELEASES_CHANNEL_ID)
        if canal is None:
            return
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for repo in config.GITHUB_RELEASES_REPOS:
                try:
                    rel = await self._ultima_release(session, repo)
                except Exception as exc:
                    log.warning("Fallo consultando releases de %s: %s", repo, exc)
                    continue
                if not rel:
                    continue
                tag = rel.get("tag_name") or str(rel.get("id") or "")
                if not tag:
                    continue
                previo = self._estado.get(repo)
                if previo is None:
                    self._estado[repo] = tag   # primera vez: guardar sin anunciar
                    self._save()
                    continue
                if tag == previo:
                    continue
                try:
                    await self._anunciar(canal, repo, rel)
                except Exception as exc:
                    log.warning("Fallo anunciando release de %s: %s", repo, exc)
                    continue
                self._estado[repo] = tag
                self._save()

    @comprobar.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()

    # ---------- anuncio ----------
    async def _anunciar(self, canal, repo, rel):
        nombre = rel.get("name") or rel.get("tag_name") or "nueva versión"
        tag = rel.get("tag_name") or ""
        url = rel.get("html_url") or f"https://github.com/{repo}/releases"
        cuerpo = (rel.get("body") or "").strip()
        if len(cuerpo) > 1500:
            cuerpo = cuerpo[:1500].rstrip() + "…"
        titulo = f"🚀 {nombre}"
        if tag and tag not in nombre:
            titulo += f"  ({tag})"
        emb = discord.Embed(title=titulo[:256], url=url,
                            description=cuerpo or "¡Hay versión nueva disponible!",
                            color=0x2ea043)
        emb.set_author(name=repo, url=f"https://github.com/{repo}")
        if rel.get("published_at"):
            emb.set_footer(text=f"GitHub · publicada {rel['published_at'][:10]}")
        else:
            emb.set_footer(text="GitHub · nueva release")
        autor = rel.get("author") or {}
        if autor.get("avatar_url"):
            emb.set_thumbnail(url=autor["avatar_url"])
        mention = (config.GITHUB_RELEASES_MENTION or "").strip()
        contenido = (f"{mention} " if mention else "") + f"📦 **{repo}** acaba de sacar **{nombre}**"
        allowed = discord.AllowedMentions(everyone=True, roles=True, users=True)
        await canal.send(content=contenido[:2000], embed=emb, allowed_mentions=allowed)


async def setup(bot):
    await bot.add_cog(Releases(bot))
