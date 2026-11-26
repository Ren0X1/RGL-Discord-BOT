"""
Ayudas comunes a varios cogs (no es un cog: no va en la tupla COGS).

- :func:`conectar_db`: abre un SQLite en modo WAL, que en la tarjeta SD de la
  Pi escribe mucho menos y no bloquea las lecturas mientras se escribe.
- :class:`Programador`: en vez de mirar la base de datos cada pocos segundos
  "por si acaso", duerme hasta que vence lo siguiente (o hasta que alguien
  le avisa de que hay algo nuevo). En reposo, la Pi no se despierta para nada.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger("util")


def conectar_db(ruta: str) -> sqlite3.Connection:
    """Abre (creando la carpeta si hace falta) una base SQLite en modo WAL."""
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    db = sqlite3.connect(ruta, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")   # seguro con WAL y mucho más ligero
    return db


class Programador:
    """Lanza ``tarea()`` cuando toca.

    ``proximo()`` devuelve el instante (epoch, en segundos) del siguiente
    vencimiento, o ``None`` si no hay nada pendiente. Entre vueltas duerme hasta
    ese instante, como mucho ``maximo`` segundos. Cuando se añade algo nuevo hay
    que llamar a :meth:`avisar` para que recalcule sin esperar.
    """

    def __init__(self, bot, nombre: str, tarea: Callable[[], Awaitable[None]],
                 proximo: Callable[[], float | None], maximo: float = 3600) -> None:
        self.bot = bot
        self.nombre = nombre
        self._tarea = tarea
        self._proximo = proximo
        self._maximo = maximo
        self._evento = asyncio.Event()
        self._task: asyncio.Task | None = None

    def arrancar(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._bucle(), name=f"programador-{self.nombre}")

    def parar(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def avisar(self) -> None:
        """Hay algo nuevo: despierta el bucle para que recalcule."""
        self._evento.set()

    async def _bucle(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            # Se limpia ANTES de trabajar: un aviso que llegue mientras tanto
            # hace que la espera de abajo termine al momento.
            self._evento.clear()
            try:
                await self._tarea()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo en la tarea programada '%s'", self.nombre)
            try:
                prox = self._proximo()
            except Exception:
                log.exception("Fallo calculando el siguiente vencimiento de '%s'", self.nombre)
                prox = None
            espera = self._maximo if prox is None else min(self._maximo, max(1.0, prox - time.time()))
            try:
                await asyncio.wait_for(self._evento.wait(), espera)
            except TimeoutError:
                pass
