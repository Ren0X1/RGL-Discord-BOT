@echo off
REM Si se hace doble clic, relanza en una consola que no se cierra
if not "%~1"=="-run" goto :relanzar
goto :inicio

:relanzar
cmd /k ""%~f0" -run"
exit /b

:inicio
setlocal EnableDelayedExpansion
title Reautorizar Google Drive - RGL Discord BOT
color 0A

REM ============================================================
REM  reautorizar-gdrive.bat
REM  Genera un token nuevo de Google Drive y lo sube a la Pi.
REM  Colocar junto a  scripts\autorizar_gdrive.py  y doble clic.
REM ============================================================

REM ---- Configura aqui tus datos ----
set "PI_USUARIO=renox"
set "PI_HOST=RnxZeroPI"
set "PI_RUTA=~/discord-bot/data/"
REM ----------------------------------

cd /d "%~dp0"

echo.
echo ==========================================================
echo   REAUTORIZAR GOOGLE DRIVE - RGL Discord BOT
echo ==========================================================
echo.
echo  Carpeta actual: %cd%
echo.
echo  IMPORTANTE: antes de seguir, la app de OAuth debe estar
echo  PUBLICADA en Google Cloud Console:
echo    Pantalla de consentimiento - PUBLICAR APLICACION
echo  Si sigue "En prueba", el token caduca a los 7 dias.
echo.
pause

REM ---------- 1) Comprobar Python ----------
echo.
echo [1/5] Comprobando Python...
set "PY="

py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :python_ok

py --version >nul 2>&1
if not errorlevel 1 set "PY=py"
if defined PY goto :python_ok

python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :python_ok

goto :sin_python

:python_ok
echo  Usando: !PY!
!PY! --version
echo  OK

REM ---------- 2) Comprobar ficheros ----------
echo.
echo [2/5] Comprobando ficheros del proyecto...
if not exist "scripts\autorizar_gdrive.py" goto :falta_script
if not exist "data\gdrive_client.json" goto :falta_cliente
echo  OK

REM ---------- 3) Dependencias ----------
echo.
echo [3/5] Instalando dependencias de Google...
!PY! -m pip install --quiet --upgrade google-auth-oauthlib google-api-python-client
if errorlevel 1 goto :error_pip
echo  OK

REM ---------- 4) Autorizar ----------
echo.
echo [4/5] Abriendo el navegador para autorizar...
echo  - Inicia sesion con TU cuenta de Google, la del Google One.
echo  - Si sale "Google no ha verificado esta aplicacion":
echo      Configuracion avanzada - Ir a la app
echo.
if not exist "data\gdrive_token.json" goto :autorizar
echo  Guardando copia del token anterior en TEMP...
REM  OJO: la copia va a %TEMP%, NUNCA dentro del repo,
REM  para que no la detecte el escaneo de secretos de GitHub.
copy /y "data\gdrive_token.json" "%TEMP%\gdrive_token_anterior.json" >nul
del /q "data\gdrive_token.json"
REM  limpiamos un .bak antiguo si quedo de versiones previas del script
if exist "data\gdrive_token.json.bak" del /q "data\gdrive_token.json.bak"

:autorizar
!PY! "scripts\autorizar_gdrive.py"
if errorlevel 1 goto :error_auth
if not exist "data\gdrive_token.json" goto :error_auth
echo  OK - Token generado.

REM ---------- 5) Subir a la Pi ----------
echo.
echo [5/5] Subiendo el token a la Pi: %PI_USUARIO%@%PI_HOST%
where scp >nul 2>&1
if errorlevel 1 goto :sin_scp

scp "data\gdrive_token.json" %PI_USUARIO%@%PI_HOST%:%PI_RUTA%
if errorlevel 1 goto :error_scp
echo  OK - Token subido.

echo.
echo  Ajustando permisos y reiniciando el bot...
ssh %PI_USUARIO%@%PI_HOST% "chmod 600 ~/discord-bot/data/gdrive_token.json && sudo systemctl restart discordbot"
if errorlevel 1 echo  AVISO: reinicia el bot a mano con: sudo systemctl restart discordbot
goto :fin

REM ================= ERRORES =================

:sin_python
color 0C
echo.
echo  ERROR: No encuentro Python en el PATH.
echo   1^) Instalalo desde https://www.python.org/downloads/
echo      y marca "Add Python to PATH".
echo   2^) O desactiva los alias de la Microsoft Store en:
echo      Configuracion - Aplicaciones - Alias de ejecucion
echo.
goto :fin_error

:falta_script
color 0C
echo.
echo  ERROR: No encuentro  scripts\autorizar_gdrive.py
echo  Copia este .bat dentro de la carpeta del proyecto.
echo  Carpeta actual: %cd%
echo.
goto :fin_error

:falta_cliente
color 0C
echo.
echo  ERROR: No encuentro  data\gdrive_client.json
echo.
echo  Descargalo en Google Cloud Console:
echo    APIs y servicios - Credenciales - Crear credenciales
echo    - ID de cliente de OAuth - Aplicacion de escritorio
echo  y guardalo como  data\gdrive_client.json
echo.
goto :fin_error

:error_pip
color 0C
echo.
echo  ERROR instalando dependencias. Revisa tu conexion.
echo  Prueba a mano:  !PY! -m pip install google-auth-oauthlib google-api-python-client
echo.
goto :fin_error

:error_auth
color 0C
echo.
echo  ERROR durante la autorizacion.
if not exist "%TEMP%\gdrive_token_anterior.json" goto :fin_error
echo  Restaurando el token anterior...
copy /y "%TEMP%\gdrive_token_anterior.json" "data\gdrive_token.json" >nul
goto :fin_error

:sin_scp
color 0E
echo.
echo  AVISO: no tienes scp instalado.
echo  Copia el fichero a mano a la Pi:
echo     %cd%\data\gdrive_token.json
echo   hacia  %PI_RUTA%
echo.
goto :fin

:error_scp
color 0E
echo.
echo  AVISO: no se pudo subir por scp. Revisa host, usuario o password.
echo  Prueba con la IP de la Pi en vez del nombre.
echo  El token esta en: %cd%\data\gdrive_token.json
echo.
goto :fin

:fin
echo.
color 0A
echo ==========================================================
echo   LISTO. Ahora prueba en Discord:  /backup
echo ==========================================================
echo.
pause
endlocal
exit /b 0

:fin_error
echo ==========================================================
echo   El proceso NO se ha completado. Mira el error de arriba.
echo ==========================================================
echo.
pause
endlocal
exit /b 1
