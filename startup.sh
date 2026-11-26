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
UV="/home/$USUARIO/.local/bin/uv"

echo "==> [1/5] Actualizando el sistema..."
sudo apt-get update -y || echo "    (apt update fallo, continuo)"
sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y || echo "    (apt upgrade fallo, continuo)"
sudo apt-get autoremove -y || true

echo "==> [2/5] Sincronizando el bot con GitHub (rama $RAMA)..."
if [ -d "$BOT_DIR/.git" ]; then
    # Si algo del repo se quedó de root (un comando con sudo dentro de la
    # carpeta), el fetch falla con 'insufficient permission'. Se repone antes.
    chown -R "$USUARIO:$USUARIO" "$BOT_DIR"
    if sudo -u "$USUARIO" git -C "$BOT_DIR" fetch origin "$RAMA" \
        && sudo -u "$USUARIO" git -C "$BOT_DIR" reset --hard "origin/$RAMA"; then
        echo "    Version: $(cat "$BOT_DIR/VERSION" 2>/dev/null) ($(sudo -u "$USUARIO" git -C "$BOT_DIR" log --oneline -1))"
    else
        echo "    !!! LA SINCRONIZACION HA FALLADO: el bot arrancara con el codigo de antes."
    fi
else
    echo "    (la carpeta no es un repo git; ejecuta la preparacion una vez)"
fi

# Git solo conserva el bit de ejecucion (nada de 777) y, si un fichero se subio
# sin el, cada 'reset --hard' deja los .sh sin permisos. Se reponen aqui para que
# la Pi nunca se quede sin poder ejecutar su propio arranque.
chmod +x "$BOT_DIR"/*.sh 2>/dev/null || true

echo "==> [3/5] Actualizando Python (parches de la misma version)..."
# Python lo instala uv (binario ya compilado). El venv apunta a la version
# menor (3.15), asi que un parche nuevo (3.15.x) se recoge sin rehacer nada.
if [ -x "$UV" ]; then
    sudo -u "$USUARIO" "$UV" python upgrade 3.15 || echo "    (uv python upgrade fallo, continuo)"
else
    echo "    (no encuentro uv; omito)"
fi

echo "==> [4/5] Actualizando dependencias del bot..."
if [ -x "$BOT_DIR/venv/bin/pip" ]; then
    sudo -u "$USUARIO" "$BOT_DIR/venv/bin/pip" install --quiet --upgrade pip \
        || echo "    (pip no se pudo actualizar, continuo)"
    sudo -u "$USUARIO" "$BOT_DIR/venv/bin/pip" install --upgrade --upgrade-strategy eager \
        -r "$BOT_DIR/requirements.txt" || echo "    (pip fallo, continuo)"
else
    echo "    (no encuentro el venv; omito dependencias)"
fi

echo "==> [5/5] Arrancando el bot..."
sudo systemctl restart "$SERVICIO"

echo "==> Hecho."
