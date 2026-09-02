# 📓 Changelog

Todas las novedades destacables de **RGL Discord BOT**.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es/).

> ℹ️ **Versionado propio**: `MAJOR.FEATURE.MINOR.fFIX` (ej. `1.2.3.f1`).
> El workflow detecta el tipo por el mensaje del commit y sube la parte que toca:
> `major`/BREAKING → **MAJOR** · `feat` → **FEATURE** · `fix` → **FIX** · resto (refactor, chore, docs…) → **MINOR**.
> Al subir una parte, las de su derecha se reinician. Números calculados **simulando** todo el historial desde el primer commit.

---

## [1.1.0.f0] - 2026-09-02 · ✨ feature
### 🧠 Mejorado
- 🎨 **Logo del juego en `/cs` y `/rust`**: los dos mensajes llevan ahora el icono oficial de Steam (Counter-Strike 2 y Rust) en la cabecera, con el avatar del jugador donde estaba. Si prefieres subir los logos como emojis del servidor, se pueden enchufar con `CS_EMOJI` y `RUST_EMOJI` en el `.env`.
- 🟢 **Verde y rojo en los números que lo piden**: Discord no deja pintar texto de color dentro de un embed, así que va un punto delante: el Leetify rating, el impacto por ronda (clutch, apertura, como CT/T), el LR de cada partida y el K/D de Rust salen con 🟢 si van a favor y 🔴 si van en contra.
- ✅ **Adiós a los cuadraditos**: las últimas partidas de `/cs` se marcan con ✅ ganada, ❌ perdida y 🟰 empate, que se distinguen de un vistazo (los 🟩🟥🟨 no).
- 📐 **`/rust` mejor repartido**: *Caza*, *Farmeo* y *Cómo la palma* van en ese orden para que los títulos no queden pegados, y las cantidades grandes se abrevian (`462,5K` en vez de `462.537`) para que quepan en su columna.

### 🛠️ Corregido
- 📏 **El texto ya no se cae debajo de su etiqueta**: en las columnas estrechas de Discord solo entran unos 15 caracteres entre etiqueta y valor, y varias filas de `/cs` (*Mecánica*, *Duelos de apertura*) y de `/rust` (*Farmeo*) se pasaban, así que el dato saltaba a la línea siguiente. Se han acortado las etiquetas, se ha reordenado la parrilla (*Trades* sube a la fila de tres columnas y el impacto por ronda baja a la de dos, que es más ancha) y todas las líneas se han medido para dejar margen.

## [1.0.0.f1] - 2026-09-02 · 🛠️ fix
### 🛠️ Corregido
- 🔫 **`/rust` culpaba a la privacidad sin motivo**: Steam responde lo mismo (error 400) cuando el perfil oculta las stats que cuando la cuenta no tiene el juego, y el bot soltaba siempre las instrucciones para cambiar la privacidad. Ahora consulta la lista de juegos para saber cuál de los dos es y responde lo que toca: *"esa cuenta no tiene Rust"* o las instrucciones de privacidad.

## [1.0.0.f0] - 2026-09-02 · 💥 major
### ✨ Añadido
- 🔫 **Stats de Rust**: `/rust [@usuario|url]` con enlace al perfil de Steam, K/D, horas jugadas, logros, puntería por arma con barra, cómo la palma, caza, farmeo, construcción y curiosidades (notas tocadas, metros a caballo, tiempo irradiado…). Los datos salen de la **Steam Web API**, gratis, que publica ~150 contadores del juego. Además `/rust_vincular` y `/rust_desvincular`.
- 🔗 **Una sola vinculación para los dos juegos**: la cuenta de Steam se guarda ahora en `data/steam_links.json` y la comparten `/cs` y `/rust`. Las vinculaciones que ya existían en `data/cs_links.json` **se migran solas** la primera vez, sin tener que volver a vincular a nadie.

### 🧠 Mejorado
- 📊 **`/cs` rediseñado y con mucha más chicha**: la API de Leetify publica 21 métricas y el bot solo usaba 9. Ahora enseña el **Leetify rating** como titular, los rangos que faltaban (**Premier** y **Renown**), las tres habilidades con **barra de progreso**, el impacto por ronda (clutch, apertura y rendimiento **como CT vs como T**), mecánica fina (**counter-strafing**, precisión al avistar), **duelos de apertura** separados por bando, **trades** (a cuántos venga y cuántas veces le vengan), **uso de utilidad** (flashes a rivales y a colegas, flashes que acaban en baja, daño de HE, utilidad sin gastar al morir) y la **forma de las últimas 10 partidas** en cuadritos, con el LR medio y la fuente de cada partida (FACEIT/Premier).
- 👥 **Compañeros del server**: si alguien con quien ha jugado últimamente tiene su Steam vinculado en el Discord, `/cs` lo menciona.
- 🎨 **El color del mensaje habla**: verde, azul, rosa o rojo según el Leetify rating del jugador. Y se pone el **avatar de Steam** como miniatura.
- ⚔️ **`/cs_comparar`** usa también el Leetify rating (antes decidía el ganador solo por puntería) y pinta las habilidades con barras.

### 🛠️ Corregido
- 🔢 **Números mal interpretados en `/cs`**: `clutch`, `apertura` y el rendimiento por bando son ratios por ronda, y se enseñaban en crudo junto a puntuaciones de 0 a 100 (salía un absurdo *"Clutch 0.1"* al lado de *"Aim 98.5"*). Ahora se muestran ×100 y con signo, como los pinta Leetify.
- 📈 Los porcentajes ya no se adivinan con una heurística (`si el valor es ≤ 1, multiplícalo por 100`), que era frágil: cada métrica se formatea según lo que de verdad devuelve la API.
- 🔐 **Los scripts perdían los permisos en cada actualización**: `startup.sh` y `update.sh` estaban guardados en git como `100644`, así que cada `git reset --hard` de la Pi los dejaba sin permiso de ejecución y había que hacerles `chmod` a mano. Ahora git guarda el **bit de ejecución** (`100755`) y se restauran solos al sincronizar; por si acaso, `startup.sh` también repone el permiso de todos los `.sh` después de cada sincronización.

## [0.27.0.f4] - 2026-08-27 · 🛠️ fix
### 🛠️ Corregido
- 📦 **Dependencias al día**: `requirements.txt` fija ahora los mínimos en las últimas versiones publicadas (discord.py 2.7.1, Flask 3.1.3, waitress 3.0.2, python-dotenv 1.2.3, tzdata 2026.3, google-api-python-client 2.199.0, google-auth 2.57.0, google-auth-oauthlib 1.4.1) y declara `aiohttp` y `Werkzeug`, que los cogs y el panel ya importaban directamente sin listarlos.
- 🧹 **`.gitignore`**: se ignora la carpeta `.claude/` (sesiones y ajustes locales de Claude Code).

## [0.27.0.f3] - 2026-08-17 · 🛠️ fix
### 🛠️ Corregido
- 🤫 **El bot no respondía con el modelo nuevo**: `gpt-oss-120b` es un modelo de razonamiento y se gastaba todos los tokens 'pensando', devolviendo respuestas vacías. Ahora se le manda `reasoning_effort=low`, `reasoning_format=hidden` y un presupuesto de tokens suficiente. También se limpian los tokens de control y se avisa en el log si llega una respuesta vacía.

## [0.27.0.f2] - 2026-08-17 · 🛠️ fix
### 🛠️ Corregido
- 🤖 **Modelo de IA actualizado**: Groq apagó `llama-3.3-70b-versatile` el 16/08/2026; ahora se usa `openai/gpt-oss-120b`. Además, si el modelo vuelve a caducar el bot avisa por DM al owner en vez de fallar en silencio.
- 🔇 Silenciados los `CommandNotFound` que llenaban el log al mencionar al bot.

## [0.26.0.f0] - 2026-08-06 · ✨ feature
### ✨ Añadido
- 💾 **Backups a Google Drive**: comprime `data/` cada X horas, lo sube a tu Drive (cuenta de servicio), rota los antiguos y avisa por DM. Comandos `/backup` y `/backups`.

## [0.25.0.f0] - 2026-08-06 · ✨ feature
### ✨ Añadido
- 🧠 **Control de la memoria de la IA**: `/ia_memoria` (ver numerado), `/ia_olvidar` (borrar un dato concreto) y `/ia_reset` (resetear usuario o servidor).
- 🎯 **Perfiles de CS vinculados**: `/cs_vincular` y `/cs_desvincular`; `/cs` ya funciona sin parámetros y acepta @menciones.
- ⚔️ **`/cs_comparar`**: compara hasta 4 perfiles o usuarios (los usuarios deben tener perfil vinculado).
- 🏅 **Niveles y XP**: XP por participar, `/rank` con barra de progreso, `/leaderboard` top 10 y `/xp_dar` / `/xp_reset` para staff.
- 🎛️ **Roles por botón**: paneles configurables por comando (`/roles_crear`, `/roles_add`, `/roles_quitar`, `/roles_listar`, `/roles_publicar`, `/roles_borrar`) con botones persistentes.

## [0.23.0.f0] - 2026-08-06 · ✨ feature
### 🧠 Mejorado
- **Memoria de la IA mucho más lista**: aprende cada 5 mensajes (aunque no responda), de forma **aditiva** (ya no se pisa lo aprendido), mapea a la gente **por número** (no se pierden datos), **refuerza** lo que se repite (`veces`) y **consolida a diario** fusionando duplicados. Migra sola el formato antiguo.
### 🔧 Cambiado
- 🗂️ Los ficheros de la IA (`ai_context.json`, `ai_saved.json`, `ai_state.json`) se guardan ahora en **`data/`** para dejar la raíz más limpia.

## [0.22.0.f0] - 2026-06-20 · ✨ feature
### ✨ Añadido
- 🩺 **Resumen del sistema al arrancar**: publica en el log CPU, RAM, temperatura, disco y versión al iniciarse.
- 📦 **Auto-versionado y releases** con GitHub Actions (formato `MAJOR.FEATURE.MINOR.fFIX`, detectado por el commit), fichero `VERSION` y este `CHANGELOG.md`.
- 🏷️ `/bot` muestra también la versión del bot.
### 🛠️ Corregido
- 🔕 `template_sync` deja de escribir "Plantilla sincronizada" en el log en cada sync (sincroniza en silencio).

## [0.21.0.f0] - 2026-06-19 · ✨ feature
- 🎯 **`/cs`**: estadísticas de Counter-Strike vía **Leetify** (rangos FACEIT/Premier/Wingman/Competitivo, Leetify rating, puntería, winrate y últimas partidas) + enlace a csstats.gg.

## [0.20.0.f0] - 2026-06-19 · ✨ feature
- 🌡️ **Alertas de salud** (DM al owner por temperatura/RAM/disco) y 🚫 **automod** (anti-invitaciones y anti-spam).

## [0.19.0.f0] - 2026-06-19 · ✨ feature
- 🚀 **Avisos de releases de GitHub** con `@everyone`.

## [0.18.0.f0] - 2026-06-15 · ✨ feature
- 🗣️ Ajuste de las directrices de estilo de la IA (respuestas más naturales).

## [0.17.0.f0] - 2026-06-15 · ✨ feature
- 🌅 **Resumen diario** gracioso del chat por la IA.

## [0.16.0.f0] - 2026-06-15 · ✨ feature
- 🏷️ Autocompletado de **nombre y mote** de los usuarios al arrancar (IA).

## [0.15.0.f0] - 2026-06-15 · ✨ feature
- 📖 Mejora de documentación y del manejo de contexto por usuario en la IA.

## [0.14.0.f0] - 2026-06-14 · ✨ feature
- ✂️ **División de mensajes largos** y adaptación de estilo en la IA.

## [0.13.0.f0] - 2026-06-14 · ✨ feature
- 🤖 **Módulo de charla con IA** con memoria y probabilidad de respuesta configurable.

## [0.12.0.f0] - 2026-06-10 · ✨ feature
- 😜 **Probabilidad configurable** en las auto-reacciones.

## [0.11.0.f0] - 2026-06-10 · ✨ feature
- 🎫 **Sistema de tickets** con panel y canales privados.

## [0.10.0.f1] - 2026-06-10 · 🛠️ fix
- 🗳️ Las encuestas **borran el mensaje original** al cerrarse (en vez de desactivar botones).

## [0.10.0.f0] - 2026-06-10 · ✨ feature
- 🗳️ **Encuestas** con botones persistentes y cierre temporizado.

## [0.9.0.f0] - 2026-06-09 · ✨ feature
- 🔄 **Auto-sync de la plantilla** del servidor con intervalo configurable.

## [0.8.2.f0] - 2026-06-09 · 🧹 minor
- ♻️ Refactor de la estructura del código (legibilidad).

## [0.8.1.f0] - 2026-06-09 · 🧹 minor
- ♻️ Refactor de la estructura del código.

## [0.8.0.f0] - 2026-06-09 · ✨ feature
- 🔐 Panel con **HTTPS** (werkzeug, sustituye a cheroot).

## [0.7.0.f0] - 2026-06-09 · ✨ feature
- ℹ️ Módulos **serverinfo** y **stats** + contadores de voz.

## [0.6.0.f0] - 2026-06-08 · ✨ feature
- 😜 Mejoras en **auto-reacciones** y en la carga de logs del dashboard.

## [0.5.0.f0] - 2026-06-08 · ✨ feature
- 😜 **Auto-reacciones** y 📬 **aviso al owner** al arrancar.

## [0.4.0.f0] - 2026-06-08 · ✨ feature
- 🎨 Rediseño del **login** y el **dashboard** del panel.

## [0.3.0.f0] - 2026-06-08 · ✨ feature
- 🖥️ **Panel web** con autenticación y monitorización del sistema.

## [0.2.0.f0] - 2026-06-05 · ✨ feature
- 📅 **Eventos**, 👋 **bienvenidas** y 🎲 **scrims**.

## [0.1.0.f0] - 2026-06-04 · ✨ feature
- 🧱 **Bot base**: 📋 logs, 🔊 voz temporal, ⏰ recordatorios y 📢 avisos de directos.

## [0.0.1.f0] - 2026-06-04 · 🌱 inicial
- 🌱 **Subida inicial**: estructura base del proyecto.
