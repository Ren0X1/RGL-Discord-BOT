#!/usr/bin/env bash
#
# startup.sh — Al encender la Pi: actualiza el sistema, sincroniza el bot con
#              GitHub y lo deja corriendo.
#
# A propósito NO usamos 'set -e': si una actualización falla (p.ej. sin red),
# el bot debe arrancar igualmente.

BOT_DIR="/home/renox/discord-bot"
USUARIO="renox"
SERVICIO="discordbot"
RAMA="main"

echo "==> [1/4] Actualizando el sistema..."
sudo apt-get update -y || echo "    (apt update fallo, continuo)"
sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y || echo "    (apt upgrade fallo, continuo)"
sudo apt-get autoremove -y || true

echo "==> [2/4] Sincronizando el bot con GitHub (rama $RAMA)..."
if [ -d "$BOT_DIR/.git" ]; then
    sudo -u "$USUARIO" git -C "$BOT_DIR" fetch origin "$RAMA" \
        && sudo -u "$USUARIO" git -C "$BOT_DIR" reset --hard "origin/$RAMA" \
        || echo "    (sincronizacion fallo, continuo)"
else
    echo "    (la carpeta no es un repo git; ejecuta la preparacion una vez)"
fi

echo "==> [3/4] Actualizando dependencias del bot..."
if [ -x "$BOT_DIR/venv/bin/pip" ]; then
    sudo -u "$USUARIO" "$BOT_DIR/venv/bin/pip" install --upgrade -r "$BOT_DIR/requirements.txt" \
        || echo "    (pip fallo, continuo)"
else
    echo "    (no encuentro el venv; omito dependencias)"
fi

echo "==> [4/4] Arrancando el bot..."
sudo systemctl restart "$SERVICIO"

echo "==> Hecho."
