#!/usr/bin/env python3
"""
Autoriza al bot a subir backups a TU Google Drive (se hace UNA sola vez).

Cómo usarlo:
  1) En Google Cloud Console crea un "ID de cliente de OAuth" de tipo
     "Aplicación de escritorio" y descarga su JSON.
  2) Guárdalo como  data/gdrive_client.json  (en la raíz del bot).
  3) Ejecuta este script EN UN ORDENADOR CON NAVEGADOR:
         python3 scripts/autorizar_gdrive.py
     Se abrirá el navegador, inicias sesión con tu cuenta de Google y aceptas.
  4) Se crea  data/gdrive_token.json . Cópialo a la Pi, a la misma ruta:
         scp data/gdrive_token.json renox@RnxZeroPI:~/discord-bot/data/

Nota: si prefieres hacerlo directamente en la Pi por SSH, ejecútalo con
      --consola  y te dará una URL para abrir en el navegador de tu PC.
"""

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENTE = os.path.join(RAIZ, "data", "gdrive_client.json")
TOKEN = os.path.join(RAIZ, "data", "gdrive_token.json")


def main():
    if not os.path.exists(CLIENTE):
        print(f"❌ No encuentro {CLIENTE}")
        print("   Descarga el JSON del 'ID de cliente de OAuth' (Aplicación de escritorio)")
        print("   desde Google Cloud Console y guárdalo con ese nombre.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(CLIENTE, SCOPES)

    if "--consola" in sys.argv:
        # Para máquinas sin navegador: levanta el servidor y te da la URL
        creds = flow.run_local_server(host="0.0.0.0", port=8765, open_browser=False,
                                      bind_addr="0.0.0.0")
    else:
        creds = flow.run_local_server(port=0)

    os.makedirs(os.path.dirname(TOKEN), exist_ok=True)
    with open(TOKEN, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.chmod(TOKEN, 0o600)

    print(f"\n✅ Autorizado. Token guardado en: {TOKEN}")
    print("   Cópialo a la Pi (misma ruta) y arranca el bot:")
    print("   scp data/gdrive_token.json usuario@tu-pi:~/discord-bot/data/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
