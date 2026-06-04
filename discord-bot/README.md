# Bot de Discord — logs, voz temporal, recordatorios y avisos de directo

Bot en Python (discord.py 2.x) con cuatro módulos:

1. **Logs** — registra acciones del servidor en un canal (mensajes borrados/editados, entradas/salidas, baneos con moderador, cambios de apodo/roles, cambios de avatar/nombre, creación/borrado de canales y movimientos de voz).
2. **Voz temporal** — al entrar a un canal "lobby" se crea un canal propio (límite 10) y se borra solo cuando queda vacío.
3. **Recordatorios** — `/recordatorio` te escribe por privado en la fecha que indiques.
4. **Avisos de directo** — cuando alguien con cierto rol empieza a transmitir, avisa con `@everyone` y el enlace.
5. **Eventos** — `/evento` crea un evento del servidor con rango de fechas e imagen de portada.

El bot, además, se muestra siempre en estado **ausente** (bola amarilla) con una actividad de "Transmitiendo" que apunta a tu enlace (configurable con `STATUS_TEXT` y `STATUS_URL`).

---

## 1. Crear el bot en Discord

1. Entra en https://discord.com/developers/applications → **New Application**.
2. Pestaña **Bot** → **Add Bot** → copia el **Token** (lo pegas luego en `.env`).
3. En esa misma pestaña, activa los tres **Privileged Gateway Intents**:
   - ✅ Server Members Intent
   - ✅ Presence Intent
   - ✅ Message Content Intent
4. Pestaña **OAuth2 → URL Generator**:
   - Scopes: `bot` y `applications.commands`
   - Permisos del bot: `Manage Channels`, `Move Members`, `View Audit Log`, `Ban Members`, `Manage Events`, `Read Messages/View Channels`, `Send Messages`, `Embed Links`, `Read Message History`, `Mention Everyone`, `Manage Roles` (recomendado).
   - Copia la URL generada, ábrela e invita el bot a tu servidor.

## 2. Sacar los IDs que necesitas

En Discord: **Ajustes de usuario → Avanzado → Modo desarrollador (ON)**. Luego clic derecho sobre cada elemento → **Copiar ID**:

- Canal donde quieres los logs → `LOG_CHANNEL_ID`
- Canal de voz "lobby" → `MAIN_VOICE_CHANNEL_ID`
- (Opcional) categoría donde crear los canales temporales → `TEMP_VOICE_CATEGORY_ID`
- Canal donde anunciar directos → `STREAM_ANNOUNCE_CHANNEL_ID`
- Roles que disparan el aviso de directo → `STREAM_ROLE_IDS` (varios separados por comas)
- (Opcional) tu servidor → `GUILD_ID` (hace que los comandos `/` aparezcan al instante)

## 3. Configurar y ejecutar en local

```bash
# 1. Instala dependencias (Python 3.10+)
pip install -r requirements.txt

# 2. Crea tu archivo .env a partir del ejemplo
cp .env.example .env
# edita .env y rellena el token y los IDs

# 3. Arranca el bot
python bot.py
```

Si todo va bien verás en consola `Conectado como ...`.

## 4. Comandos disponibles

- `/recordatorio cuando:<30m | 2h | 3d | 25/12/2026 09:00> mensaje:<texto>`
- `/recordatorios` — lista los tuyos pendientes
- `/cancelar_recordatorio id:<número>`
- `/evento nombre:<texto> inicio:<25/12/2026 18:00> fin:<25/12/2026 21:00> imagen:<url> [channel_id] [descripcion]` — evento con ubicación; las horas se redondean al cuarto de hora siguiente
- `/clear cantidad:<1-1000>` — borra los últimos N mensajes del canal (requiere permiso Gestionar mensajes)

---

## Notas importantes

- **Avatares/nombres**: se detectan por evento de usuario (Discord no los pone en el audit log). El bot solo loguea cambios de quien comparte tu servidor.
- **Directos**: funciona con el *estado de streaming* (Twitch/YouTube), que sí tiene URL pública. El "Go Live"/compartir pantalla dentro de un canal de voz **no** tiene enlace público y por eso no se puede anunciar con link.
- **Recordatorios**: se guardan en `data/reminders.db` (SQLite), así sobreviven a reinicios. Las fechas absolutas se interpretan en la zona horaria de `TIMEZONE` (por defecto `Europe/Madrid`).
- **Zona horaria**: las fechas se interpretan en `TIMEZONE` (por defecto `Europe/Madrid`). Si está instalado `tzdata` se usa la base oficial; si no, el bot trae un cálculo CET/CEST de respaldo para zonas de Europa central, así que las horas salen bien aunque falte `tzdata`.
- **Sugerencias de comandos**: si defines `GUILD_ID`, al arrancar el bot registra los comandos en tu servidor y **borra los globales antiguos**, eliminando duplicados u obsoletos. Si los cambios tardan en verse, cierra y abre Discord (Ctrl+R).
- **Permisos**: el rol del bot debe estar **por encima** de los canales/roles que gestiona, o algunas acciones fallarán por falta de permisos.
- **Eventos**: el bot necesita el permiso **Gestionar eventos** (Manage Events). Son eventos de tipo externo con **ubicación**: si pasas `channel_id`, se usa el nombre de ese canal como ubicación; si no, pone "Servidor". Las horas de inicio y fin se **redondean al siguiente múltiplo de 15 minutos** (p.ej. 9:51 → 10:00). La imagen debe ser un enlace directo a un `.png`/`.jpg` y pesar menos de 8 MB.
- **/clear**: solo borra en lote mensajes de **menos de 14 días** (límite de Discord). Los más antiguos se saltan para no provocar bloqueos por *rate limit*; el comando te indica cuántos borró de verdad.
- **Status amarillo + enlace**: la bola amarilla es el estado "ausente". El enlace solo es *pulsable* si es de `twitch.tv` o `youtube.com`; con un dominio propio se muestra el texto, pero puede no ser clicable. Cambia el texto/URL en `STATUS_TEXT` y `STATUS_URL`.

## Hosting 24/7

Cuando el bot funcione en local, lo desplegamos. La opción gratis más fiable hoy es una VM **Always Free de Oracle Cloud** corriendo el bot con `systemd` o `screen`. Lo vemos paso a paso cuando llegues a ese punto.
