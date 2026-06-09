"""
Panel web de control — v1

Permite, desde el navegador y en la red local:
  - Ver el estado del bot y de la Raspberry (CPU/RAM/temperatura/uptime/disco).
  - Arrancar / parar / reiniciar el bot.
  - Reiniciar la Pi y lanzar la actualización (startup.sh).
  - Ver los últimos logs del bot.

Corre como un servicio aparte (panel.service), como el usuario 'renox', y solo
puede ejecutar una lista cerrada de comandos con sudo (ver /etc/sudoers.d/discordpanel).
Protegido con contraseña (PANEL_PASSWORD en el .env). Pensado para red local.
"""

import os
import time
import shutil
import secrets
import hmac
import functools
import subprocess
import threading
import collections

from flask import (
    Flask, request, session, redirect, url_for, render_template, flash, jsonify, Response,
    send_from_directory
)
from dotenv import load_dotenv
from waitress import serve

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.dirname(BASE_DIR)            # /home/renox/discord-bot
ENV_PATH = os.path.join(BOT_DIR, ".env")
load_dotenv(ENV_PATH)

# Claves que NO se muestran en el editor (se enmascaran)
SECRETOS = {"DISCORD_TOKEN", "PANEL_PASSWORD", "PANEL_SECRET_KEY"}

PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
PANEL_PORT = int(os.getenv("PANEL_PORT", "8080"))
SECRET = os.getenv("PANEL_SECRET_KEY") or secrets.token_hex(32)
SERVICE = "discordbot"

# HTTPS opcional (si ambos archivos existen, sirve por TLS)
PANEL_SSL_CERT = os.getenv("PANEL_SSL_CERT", "").strip()
PANEL_SSL_KEY = os.getenv("PANEL_SSL_KEY", "").strip()

# Anti-fuerza-bruta del login
MAX_FALLOS = 5
BLOQUEO_SEG = 300
_intentos = {}  # ip -> [fallos, bloqueado_hasta]

# Comandos privilegiados. DEBEN coincidir EXACTAMENTE con /etc/sudoers.d/discordpanel
ACCIONES = {
    "start":   ["sudo", "/usr/bin/systemctl", "start", SERVICE],
    "stop":    ["sudo", "/usr/bin/systemctl", "stop", SERVICE],
    "restart": ["sudo", "/usr/bin/systemctl", "restart", SERVICE],
    "reboot":  ["sudo", "/usr/bin/systemctl", "reboot"],
    "update":  ["sudo", "/bin/bash", os.path.join(BOT_DIR, "startup.sh")],
}

app = Flask(__name__)
app.secret_key = SECRET


# ---------- utilidades de autenticación ----------
def login_required(f):
    @functools.wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrap


@app.context_processor
def inject_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf_token": session.get("csrf", "")}


# ---------- lectura del sistema ----------
def bot_status():
    try:
        r = subprocess.run(["/usr/bin/systemctl", "is-active", SERVICE],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _fmt_uptime(seg):
    if seg is None:
        return "N/D"
    d, seg = divmod(int(seg), 86400)
    h, seg = divmod(seg, 3600)
    m, _ = divmod(seg, 60)
    partes = []
    if d:
        partes.append(f"{d}d")
    if h:
        partes.append(f"{h}h")
    partes.append(f"{m}m")
    return " ".join(partes)


def stats():
    d = {}
    # CPU
    try:
        def rd():
            with open("/proc/stat") as f:
                n = list(map(int, f.readline().split()[1:]))
            return n[3] + (n[4] if len(n) > 4 else 0), sum(n)
        i1, t1 = rd()
        time.sleep(0.3)
        i2, t2 = rd()
        d["cpu"] = round((1 - (i2 - i1) / (t2 - t1)) * 100) if t2 > t1 else None
    except Exception:
        d["cpu"] = None
    # RAM
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for linea in f:
                k, _, v = linea.partition(":")
                info[k] = int(v.strip().split()[0])
        tot = info["MemTotal"]
        av = info.get("MemAvailable", info.get("MemFree", 0))
        d["ram_used"] = round((tot - av) / 1024)
        d["ram_total"] = round(tot / 1024)
    except Exception:
        d["ram_used"] = d["ram_total"] = None
    # Temperatura
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            d["temp"] = round(int(f.read()) / 1000, 1)
    except Exception:
        d["temp"] = None
    # Uptime del sistema
    try:
        with open("/proc/uptime") as f:
            d["uptime"] = _fmt_uptime(float(f.read().split()[0]))
    except Exception:
        d["uptime"] = "N/D"
    # Disco
    try:
        du = shutil.disk_usage("/")
        d["disk_used"] = round(du.used / 1e9, 1)
        d["disk_total"] = round(du.total / 1e9, 1)
    except Exception:
        d["disk_used"] = d["disk_total"] = None
    return d


# ---------- histórico para las gráficas ----------
HIST = collections.deque(maxlen=180)  # ~30 min a 1 muestra/10s


def _sampler():
    while True:
        try:
            s = stats()
            ram_pct = None
            if s.get("ram_used") and s.get("ram_total"):
                ram_pct = round(s["ram_used"] / s["ram_total"] * 100)
            HIST.append({"t": int(time.time()), "cpu": s.get("cpu"), "ram": ram_pct, "temp": s.get("temp")})
        except Exception:
            pass
        time.sleep(10)


threading.Thread(target=_sampler, daemon=True).start()


# ---------- editor del .env ----------
def leer_env():
    """Devuelve la lista de líneas del .env (para reconstruirlo conservando
    comentarios) y un dict {clave: valor}."""
    lineas, valores = [], {}
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            for linea in f:
                lineas.append(linea.rstrip("\n"))
                s = linea.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, _, v = s.partition("=")
                    valores[k.strip()] = v
    except FileNotFoundError:
        pass
    return lineas, valores


def escribir_env(form):
    """Reescribe el .env aplicando los valores del formulario, conservando
    comentarios y orden. Para secretos, vacío = sin cambios."""
    lineas, _ = leer_env()
    nuevas = []
    for linea in lineas:
        s = linea.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.partition("=")[0].strip()
            if k in form:
                nuevo = form.get(k, "")
                if k in SECRETOS and nuevo == "":
                    nuevas.append(linea)  # sin cambios
                else:
                    nuevas.append(f"{k}={nuevo}")
                continue
        nuevas.append(linea)
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(nuevas) + "\n")
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "favicon.ico",
                               mimetype="image/x-icon")


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr or "?"
    if request.method == "POST":
        reg = _intentos.get(ip, [0, 0])
        ahora = time.time()
        if reg[1] > ahora:
            flash(f"Demasiados intentos. Espera {int(reg[1] - ahora)}s.", "error")
            return render_template("login.html")
        pw = request.form.get("password", "")
        if PANEL_PASSWORD and hmac.compare_digest(pw, PANEL_PASSWORD):
            _intentos.pop(ip, None)
            session["auth"] = True
            return redirect(url_for("dashboard"))
        # fallo
        reg[0] += 1
        if reg[0] >= MAX_FALLOS:
            reg[1] = ahora + BLOQUEO_SEG
            reg[0] = 0
            flash(f"Demasiados intentos fallidos. Bloqueado {BLOQUEO_SEG // 60} min.", "error")
        else:
            flash(f"Contraseña incorrecta. ({reg[0]}/{MAX_FALLOS})", "error")
        _intentos[ip] = reg
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", status=bot_status(), st=stats())


@app.route("/api/status")
@login_required
def api_status():
    data = stats()
    data["bot"] = bot_status()
    return jsonify(data)


@app.route("/api/history")
@login_required
def api_history():
    data = list(HIST)
    return jsonify({
        "t": [d["t"] for d in data],
        "cpu": [d["cpu"] for d in data],
        "ram": [d["ram"] for d in data],
        "temp": [d["temp"] for d in data],
    })


@app.route("/config", methods=["GET", "POST"])
@login_required
def config_editor():
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            flash("Token de seguridad inválido. Recarga la página.", "error")
            return redirect(url_for("config_editor"))
        try:
            escribir_env(request.form)
            flash("Configuración guardada. Reinicia el bot para aplicar los cambios.", "ok")
        except Exception as e:
            flash(f"Error guardando: {e}", "error")
        return redirect(url_for("config_editor"))

    lineas, valores = leer_env()
    # Construir la estructura para la plantilla: secciones por comentario
    campos = []
    seccion = None
    for linea in lineas:
        s = linea.strip()
        if s.startswith("#"):
            txt = s.lstrip("# ").strip()
            if txt:
                seccion = txt
        elif s and "=" in s:
            k = s.partition("=")[0].strip()
            v = valores.get(k, "")
            campos.append({
                "key": k,
                "value": "" if k in SECRETOS else v,
                "secret": k in SECRETOS,
                "section": seccion,
            })
            seccion = None
    return render_template("config.html", campos=campos)


@app.route("/action/<name>", methods=["POST"])
@login_required
def action(name):
    if request.form.get("csrf") != session.get("csrf"):
        flash("Token de seguridad inválido. Recarga la página.", "error")
        return redirect(url_for("dashboard"))
    if name not in ACCIONES:
        flash("Acción desconocida.", "error")
        return redirect(url_for("dashboard"))
    cmd = ACCIONES[name]
    try:
        if name in ("reboot", "update"):
            subprocess.Popen(cmd)  # no esperamos (reboot corta todo; update tarda)
            flash(f"Acción '{name}' lanzada.", "ok")
        else:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                flash(f"Acción '{name}' ejecutada correctamente.", "ok")
            else:
                flash(f"Error en '{name}': {(r.stderr or '').strip()[:200]}", "error")
    except Exception as e:
        flash(f"Error ejecutando '{name}': {e}", "error")
    return redirect(url_for("dashboard"))


@app.route("/logs")
@login_required
def logs():
    try:
        r = subprocess.run(
            ["sudo", "/usr/bin/journalctl", "-u", SERVICE, "-n", "80", "--no-pager"],
            capture_output=True, text=True, timeout=15,
        )
        texto = r.stdout or r.stderr or "(sin salida)"
    except Exception as e:
        texto = f"Error leyendo logs: {e}"
    return Response(texto, mimetype="text/plain")


def main():
    if not PANEL_PASSWORD:
        print("⚠️  PANEL_PASSWORD está vacío en el .env; nadie podrá entrar. Defínelo.")
    host = "0.0.0.0"
    usar_https = PANEL_SSL_CERT and PANEL_SSL_KEY and \
        os.path.exists(PANEL_SSL_CERT) and os.path.exists(PANEL_SSL_KEY)
    if usar_https:
        print(f"Panel escuchando en https://0.0.0.0:{PANEL_PORT} (TLS)")
        from werkzeug.serving import run_simple
        run_simple(host, PANEL_PORT, app,
                   ssl_context=(PANEL_SSL_CERT, PANEL_SSL_KEY),
                   threaded=True, use_reloader=False, use_debugger=False)
    else:
        print(f"Panel escuchando en http://0.0.0.0:{PANEL_PORT}")
        serve(app, host=host, port=PANEL_PORT)


if __name__ == "__main__":
    main()
