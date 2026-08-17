# 📓 Changelog

Todas las novedades destacables de **RGL Discord BOT**.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es/).

> ℹ️ **Versionado propio**: `MAJOR.FEATURE.MINOR.fFIX` (ej. `1.2.3.f1`).
> El workflow detecta el tipo por el mensaje del commit y sube la parte que toca:
> `major`/BREAKING → **MAJOR** · `feat` → **FEATURE** · `fix` → **FIX** · resto (refactor, chore, docs…) → **MINOR**.
> Al subir una parte, las de su derecha se reinician. Números calculados **simulando** todo el historial desde el primer commit.

---

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
