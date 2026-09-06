"""
Módulo 19 — Avisos de GitHub (releases, despliegues y repos nuevos).

Antes se vigilaba una lista de repos escrita a mano. Ahora se vigilan **usuarios**
(GITHUB_USERS): el bot se baja todos los repos públicos de cada uno y los sigue
sin que haya que tocar el .env cada vez que se crea uno. GITHUB_REPOS queda para
añadir repos sueltos de otra gente.

Qué anuncia en GITHUB_CHANNEL_ID:
  - 🚀 Releases nuevas.
  - 🌐 Despliegues (Deployments de GitHub: Pages, Vercel, lo que sea). Un repo
    puede no sacar ni una release y aun así publicar web cada dos por tres.
  - 📁 Repos nuevos del usuario.

Los commits sueltos NO se anuncian a propósito: llenaban el canal de ruido y lo
que interesa es la versión publicada, no cada push.

Cómo ahorra peticiones: la lista de repos de un usuario ya trae el `pushed_at` de
cada uno, así que solo se mira por dentro el repo que se ha movido. Las releases,
además, se barren enteras cada par de horas por si alguien publica una release
desde una tag que ya existía (eso no cambia el `pushed_at`).

Para no soltar el histórico de golpe, la primera vez que se ve algo se apunta el
estado SIN anunciar nada. Todo vive en data/github_state.json (entra en backups).
"""

import os
import json
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

log = logging.getLogger("github")

_RAIZ = os.path.dirname(os.path.dirname(__file__))
STATE_PATH = os.path.join(_RAIZ, "data", "github_state.json")
STATE_VIEJO = os.path.join(_RAIZ, "data", "releases_state.json")

API = "https://api.github.com"

# Cada cuánto (minutos) se barren TODAS las releases, se haya movido el repo o no.
# Es solo la red de seguridad por si alguien publica una release desde una tag
# vieja; lo normal (tag empujada) ya cambia el pushed_at y salta al momento.
BARRIDO_MIN = 120
# Repos por página al listar los de un usuario, y tope de páginas (3000 repos de sobra).
POR_PAGINA = 100
MAX_PAGINAS = 3

COLOR_RELEASE = 0x2EA043
COLOR_INFO = 0x58A6FF
COLOR_REPO = 0x8957E5
COLOR_DEPLOY = 0x1F6FEB
COLOR_FALLO = 0xDA3633

# Estados de un Deployment que todavía no son definitivos: si se pilla así, se
# deja para la vuelta siguiente en vez de anunciar "desplegando…".
ESTADOS_PENDIENTES = ("pending", "queued", "in_progress", "")
ICONO_ESTADO = {"success": "🟢", "failure": "🔴", "error": "🔴",
                "inactive": "⚪", "pending": "🟡", "queued": "🟡",
                "in_progress": "🟡"}


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class GitHub(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._estado = self._load()
        self._vuelta = 0
        self._activo = bool(config.GITHUB_CHANNEL_ID and
                            (config.GITHUB_USERS or config.GITHUB_REPOS))
        if self._activo:
            self.comprobar.change_interval(minutes=config.GITHUB_INTERVAL)
            self.comprobar.start()
        else:
            log.info("Avisos de GitHub apagados (falta canal o usuarios/repos).")

    def cog_unload(self):
        self.comprobar.cancel()

    # ---------- estado ----------
    def _load(self):
        """Carga data/github_state.json, migrando el releases_state.json de antes."""
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "repos" in d:
                return d
        except (OSError, ValueError):
            pass
        # Formato viejo: {"owner/repo": "tag"}. Se conserva la tag para no
        # reanunciar la última release de nadie al actualizar.
        estado = {"usuarios": {}, "repos": {}}
        try:
            with open(STATE_VIEJO, encoding="utf-8") as f:
                viejo = json.load(f)
            if isinstance(viejo, dict):
                for repo, tag in viejo.items():
                    if isinstance(tag, str):
                        estado["repos"][repo] = {"tag": tag, "pushed": None,
                                                 "deploy": None, "deploy_pend": False}
                log.info("Migrados %d repos del estado antiguo.", len(estado["repos"]))
        except (OSError, ValueError):
            pass
        return estado

    def _save(self):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._estado, f, ensure_ascii=False, indent=2)

    def _repo_estado(self, repo):
        return self._estado.setdefault("repos", {}).setdefault(
            repo, {"tag": None, "pushed": None,
                   "deploy": None, "deploy_pend": False})

    # ---------- API ----------
    async def _get(self, session, ruta, params=None):
        """GET a la API de GitHub. Devuelve el JSON o None si algo falla."""
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "RGL-Discord-BOT"}
        if config.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
        url = ruta if ruta.startswith("http") else f"{API}{ruta}"
        async with session.get(url, headers=headers, params=params) as r:
            queda = r.headers.get("X-RateLimit-Remaining")
            if queda is not None and queda.isdigit() and int(queda) < 10:
                log.warning("Quedan %s peticiones de GitHub. Pon un GITHUB_TOKEN.", queda)
            if r.status == 404:
                return None
            if r.status == 409:      # repo vacío, sin commits
                return None
            if r.status != 200:
                log.warning("GitHub respondió %s en %s", r.status, url)
                return None
            return await r.json()

    async def _repos_de_usuario(self, session, user):
        """Todos los repos públicos de un usuario, ordenados por último push."""
        salida = []
        for pagina in range(1, MAX_PAGINAS + 1):
            datos = await self._get(session, f"/users/{user}/repos", {
                "per_page": str(POR_PAGINA), "page": str(pagina),
                "sort": "pushed", "type": "owner"})
            if not isinstance(datos, list) or not datos:
                break
            salida.extend(datos)
            if len(datos) < POR_PAGINA:
                break
        return salida

    async def _vigilados(self, session):
        """({full_name: repo}, usuarios listados bien) de los usuarios + repos sueltos.

        Se devuelve aparte qué usuarios han contestado porque si a uno le falla la
        consulta no se le puede dar por fichado: en la vuelta siguiente sus repos
        parecerían nuevos y los anunciaría todos de golpe.
        """
        repos, ok = {}, []
        for user in config.GITHUB_USERS:
            suyos = await self._repos_de_usuario(session, user)
            if not suyos:
                log.warning("El usuario %s no devolvió repos.", user)
                continue
            ok.append(user)
            for r in suyos:
                if r.get("fork") and not config.GITHUB_INCLUIR_FORKS:
                    continue
                if r.get("archived"):
                    continue
                repos[r["full_name"]] = r
        for nombre in config.GITHUB_REPOS:
            if nombre in repos:
                continue
            r = await self._get(session, f"/repos/{nombre}")
            if r:
                repos[r["full_name"]] = r
        return repos, ok

    # ---------- bucle ----------
    @tasks.loop(minutes=15)
    async def comprobar(self):
        await self._pasada()

    @comprobar.before_loop
    async def _antes(self):
        await self.bot.wait_until_ready()

    async def _pasada(self, barrido=False):
        """Una vuelta completa. Devuelve cuántos avisos ha soltado."""
        canal = self.bot.get_channel(config.GITHUB_CHANNEL_ID)
        if canal is None:
            log.warning("No encuentro el canal %s de avisos de GitHub.",
                        config.GITHUB_CHANNEL_ID)
            return 0
        self._vuelta += 1
        cada = max(1, BARRIDO_MIN // max(1, config.GITHUB_INTERVAL))
        barrido = barrido or self._vuelta % cada == 1

        avisos = 0
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                repos, listados = await self._vigilados(session)
            except Exception as exc:
                log.warning("No pude listar los repos: %s", exc)
                return 0
            # Del más viejo al más nuevo, para que lo último que se lee sea lo último que pasó.
            orden = sorted(repos.values(), key=lambda r: r.get("pushed_at") or "")
            for repo in orden:
                try:
                    avisos += await self._procesar(session, canal, repo, barrido)
                except Exception as exc:
                    log.warning("Fallo procesando %s: %s", repo.get("full_name"), exc)
        # Los usuarios quedan marcados al final: hasta que no se ha visto la lista
        # entera no se puede saber qué repo es realmente nuevo.
        for user in listados:
            self._estado.setdefault("usuarios", {})[user.lower()] = _ahora()
        self._save()
        return avisos

    async def _procesar(self, session, canal, repo, barrido):
        nombre = repo["full_name"]
        estado = self._repo_estado(nombre)
        primera = estado.get("pushed") is None and estado.get("tag") is None
        pushed = repo.get("pushed_at")
        movido = pushed != estado.get("pushed")
        avisos = 0

        # ¿Repo nuevo? Solo si el usuario ya estaba fichado de antes; si no, es
        # la primera vuelta y todos sus repos parecerían nuevos.
        dueno = nombre.split("/")[0].lower()
        conocido = dueno in {u.lower() for u in self._estado.get("usuarios", {})}
        if primera and conocido and config.GITHUB_AVISAR_REPOS:
            await self._anunciar_repo(canal, repo)
            avisos += 1

        # Repo recién fichado: se apunta por dónde va y se corta aquí. Mirarle las
        # releases y los despliegues a los 15 repos de golpe se comía de una
        # sentada las 60 peticiones/hora que da la API sin token.
        if primera:
            estado["pushed"] = pushed
            return avisos

        if config.GITHUB_AVISAR_RELEASES and (movido or barrido or estado.get("tag") is None):
            avisos += await self._releases(session, canal, nombre, estado)

        # Un despliegue tarda un rato en terminar: si se pilla a medias se marca
        # pendiente y se vuelve a mirar en la vuelta siguiente, aunque el repo no
        # se haya movido.
        # En el barrido se le mira los despliegues una vez a cada repo aunque no se
        # haya movido: si no, el primer despliegue de cada uno se usaría de
        # referencia y no se anunciaría.
        if config.GITHUB_AVISAR_DEPLOYS and (movido or estado.get("deploy_pend")
                                             or (barrido and not estado.get("deploy_visto"))):
            avisos += await self._deploys(session, canal, repo, estado)

        estado["pushed"] = pushed
        return avisos

    # ---------- releases ----------
    async def _releases(self, session, canal, nombre, estado):
        rel = await self._get(session, f"/repos/{nombre}/releases/latest")
        if not rel:
            return 0
        tag = rel.get("tag_name") or str(rel.get("id") or "")
        if not tag or tag == estado.get("tag"):
            return 0
        previo = estado.get("tag")
        estado["tag"] = tag
        if previo is None:
            return 0        # primera vez que se mira: se apunta y calla
        await self._anunciar_release(canal, nombre, rel)
        return 1

    async def _anunciar_release(self, canal, repo, rel):
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
                            color=COLOR_RELEASE)
        emb.set_author(name=repo, url=f"https://github.com/{repo}")
        if rel.get("published_at"):
            emb.set_footer(text=f"GitHub · publicada {rel['published_at'][:10]}")
        else:
            emb.set_footer(text="GitHub · nueva release")
        autor = rel.get("author") or {}
        if autor.get("avatar_url"):
            emb.set_thumbnail(url=autor["avatar_url"])
        texto = f"📦 **{repo}** acaba de sacar **{nombre}**"
        await self._enviar(canal, config.GITHUB_RELEASES_MENTION, texto, emb)

    # ---------- despliegues ----------
    async def _deploys(self, session, canal, repo, estado):
        nombre = repo["full_name"]
        lista = await self._get(session, f"/repos/{nombre}/deployments", {"per_page": "5"})
        estado["deploy_visto"] = True
        if not isinstance(lista, list) or not lista:
            estado["deploy_pend"] = False
            return 0
        ultimo = lista[0]
        did = ultimo.get("id")
        if did is None or did == estado.get("deploy"):
            estado["deploy_pend"] = False
            return 0

        estados = await self._get(session, f"/repos/{nombre}/deployments/{did}/statuses",
                                  {"per_page": "1"})
        st = (estados or [{}])[0] if isinstance(estados, list) else {}
        cual = (st.get("state") or "").lower()
        if cual in ESTADOS_PENDIENTES:
            estado["deploy_pend"] = True     # aún cociéndose, se mira luego
            return 0

        primero = estado.get("deploy") is None
        estado["deploy"] = did
        estado["deploy_pend"] = False
        if primero:
            return 0        # primera vez que se mira el repo: se apunta y calla
        await self._anunciar_deploy(canal, repo, ultimo, st)
        return 1

    async def _anunciar_deploy(self, canal, repo, dep, st):
        nombre = repo["full_name"]
        entorno = dep.get("environment") or "producción"
        cual = (st.get("state") or "success").lower()
        icono = ICONO_ESTADO.get(cual, "⚪")
        color = COLOR_FALLO if cual in ("failure", "error") else COLOR_DEPLOY
        web = st.get("environment_url") or st.get("target_url") or repo.get("homepage")
        url = web or f"https://github.com/{nombre}/deployments"

        desc = (dep.get("description") or "").strip()
        cuerpo = [f"{icono} Estado: **{cual}**"]
        if desc:
            cuerpo.append(discord.utils.escape_markdown(desc[:200]))
        if web:
            cuerpo.append(f"🔗 {web}")

        emb = discord.Embed(title=f"🌐 Desplegado en {entorno}", url=url,
                            description="\n".join(cuerpo), color=color)
        emb.set_author(name=nombre, url=f"https://github.com/{nombre}")
        ref = dep.get("ref") or ""
        sha = (dep.get("sha") or "")[:7]
        if ref:
            emb.add_field(name="Rama", value=ref[:60], inline=True)
        if sha:
            emb.add_field(name="Commit", value=f"`{sha}`", inline=True)
        avatar = (repo.get("owner") or {}).get("avatar_url")
        if avatar:
            emb.set_thumbnail(url=avatar)
        emb.set_footer(text=f"GitHub · desplegado {(dep.get('created_at') or '')[:10]}")
        await self._enviar(canal, config.GITHUB_DEPLOYS_MENTION,
                           f"🌐 **{nombre}** se acaba de desplegar en **{entorno}**", emb)

    # ---------- repos nuevos ----------
    async def _anunciar_repo(self, canal, repo):
        nombre = repo["full_name"]
        desc = (repo.get("description") or "").strip() or "Sin descripción todavía."
        emb = discord.Embed(title=f"📁 {nombre}", url=repo.get("html_url"),
                            description=desc[:1500], color=COLOR_REPO)
        emb.set_author(name="Repositorio nuevo")
        if repo.get("language"):
            emb.add_field(name="Lenguaje", value=repo["language"], inline=True)
        if repo.get("created_at"):
            emb.set_footer(text=f"GitHub · creado {repo['created_at'][:10]}")
        avatar = (repo.get("owner") or {}).get("avatar_url")
        if avatar:
            emb.set_thumbnail(url=avatar)
        await self._enviar(canal, config.GITHUB_REPOS_MENTION,
                           f"📁 Repo nuevo: **{nombre}**", emb)

    # ---------- envío ----------
    async def _enviar(self, canal, mention, texto, emb):
        mention = (mention or "").strip()
        if mention:
            contenido = f"{mention} {texto}"[:2000]
            permitidos = discord.AllowedMentions(everyone=True, roles=True, users=True)
        else:
            contenido = None
            permitidos = discord.AllowedMentions.none()
        await canal.send(content=contenido, embed=emb, allowed_mentions=permitidos)

    # ---------- comandos ----------
    @app_commands.command(name="github",
                          description="Comprueba ya las releases de los repos vigilados")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_github(self, interaction: discord.Interaction):
        if not self._activo:
            await interaction.response.send_message(
                "Los avisos de GitHub están apagados: falta `GITHUB_CHANNEL_ID` "
                "o `GITHUB_USERS` en `.env.avisos`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        avisos = await self._pasada(barrido=True)
        vigilados = len(self._estado.get("repos", {}))
        await interaction.followup.send(
            f"✅ Comprobados **{vigilados}** repos. Avisos publicados: **{avisos}**.",
            ephemeral=True)

    @app_commands.command(name="github_lista",
                          description="Enseña los usuarios y repos de GitHub que se vigilan")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_lista(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                repos, _ = await self._vigilados(session)
            except Exception as exc:
                await interaction.followup.send(f"⚠️ No pude consultar GitHub: {exc}",
                                                ephemeral=True)
                return

        usuarios = ", ".join(config.GITHUB_USERS) or "—"
        emb = discord.Embed(
            title="🐙 Repos vigilados",
            description=f"**Usuarios:** {usuarios}\n"
                        f"**Repos sueltos:** {', '.join(config.GITHUB_REPOS) or '—'}",
            color=COLOR_INFO)
        lineas = []
        for nombre in sorted(repos, key=lambda n: repos[n].get("pushed_at") or "", reverse=True):
            e = self._estado.get("repos", {}).get(nombre, {})
            marca = e.get("tag") or "—"
            lineas.append(f"`{nombre}` · {marca} · {(repos[nombre].get('pushed_at') or '')[:10]}")
        emb.add_field(name=f"Total: {len(repos)}",
                      value="\n".join(lineas)[:1024] or "—", inline=False)
        avisos = []
        if config.GITHUB_AVISAR_RELEASES:
            avisos.append("releases")
        if config.GITHUB_AVISAR_DEPLOYS:
            avisos.append("despliegues")
        if config.GITHUB_AVISAR_REPOS:
            avisos.append("repos nuevos")
        emb.set_footer(text=f"Avisa de: {', '.join(avisos) or 'nada'} · "
                            f"cada {config.GITHUB_INTERVAL} min")
        await interaction.followup.send(embed=emb, ephemeral=True)


async def setup(bot):
    await bot.add_cog(GitHub(bot))
