#!/usr/bin/env bash
#
# update.sh — Actualiza la Raspberry Pi y reinicia el bot de Discord.
# Uso:  ./update.sh
#
set -euo pipefail

SERVICIO="discordbot"
BOT_DIR="$HOME/discord-bot"

echo "==> [1/6] Actualizando lista de paquetes..."
sudo apt update

echo "==> [2/6] Actualizando paquetes del sistema..."
sudo apt full-upgrade -y

echo "==> [3/6] Limpiando paquetes innecesarios..."
sudo apt autoremove -y
sudo apt autoclean -y

echo "==> [4/6] Comprobando firmware..."
if command -v rpi-eeprom-update >/dev/null 2>&1; then
    sudo rpi-eeprom-update -a || true
else
    echo "    (esta Pi no usa EEPROM, se omite)"
fi

echo "==> [5/6] Actualizando dependencias del bot..."
if [ -x "$BOT_DIR/venv/bin/pip" ]; then
    "$BOT_DIR/venv/bin/pip" install --quiet --upgrade pip
    if [ -f "$BOT_DIR/requirements.txt" ]; then
        "$BOT_DIR/venv/bin/pip" install --upgrade -r "$BOT_DIR/requirements.txt"
    fi
else
    echo "    (no encuentro el venv del bot, se omite)"
fi

echo "==> [6/6] Reiniciando el bot..."
if systemctl list-unit-files | grep -q "^${SERVICIO}\.service"; then
    sudo systemctl restart "$SERVICIO"
    echo "    Bot reiniciado."
else
    echo "    (servicio $SERVICIO no encontrado, se omite)"
fi

echo
echo "=========================================="
echo " Actualizacion completada."
if [ -f /var/run/reboot-required ]; then
    echo " AVISO: conviene REINICIAR la Pi -> sudo reboot"
fi
echo "=========================================="
