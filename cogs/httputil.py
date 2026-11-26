"""
Sesión HTTP compartida por todo el bot (no es un cog).

Antes cada comando abría su propia ``aiohttp.ClientSession``: un pool de
conexiones nuevo, su handshake TLS y su resolución DNS en cada llamada. En una
Zero 2 W eso es CPU y memoria tiradas. Ahora hay **una sola sesión** para todo
el proceso, que reutiliza conexiones (keep-alive) y cachea el DNS.

Uso::

    from cogs import httputil

    async with httputil.sesion(20) as session:      # 20 s por petición
        async with session.get(url) as r:
            ...

``sesion()`` no cierra nada al salir: solo aplica un timeout por defecto a las
peticiones hechas dentro del bloque. La sesión real la cierra ``bot.close()``
llamando a :func:`cerrar`.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import aiohttp

_sesion: aiohttp.ClientSession | None = None


def compartida() -> aiohttp.ClientSession:
    """Devuelve la sesión del proceso, creándola la primera vez.

    Se crea de forma perezosa porque una ClientSession tiene que nacer dentro
    del bucle de eventos que la va a usar."""
    global _sesion
    if _sesion is None or _sesion.closed:
        _sesion = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=16, ttl_dns_cache=600),
            timeout=aiohttp.ClientTimeout(total=30),
        )
    return _sesion


class _ConTimeout:
    """Envoltorio fino: pone un timeout por defecto a cada petición y delega
    todo lo demás en la sesión compartida."""

    __slots__ = ("_s", "_t")

    def __init__(self, s: aiohttp.ClientSession, t: aiohttp.ClientTimeout) -> None:
        self._s = s
        self._t = t

    def _con(self, kw: dict) -> dict:
        kw.setdefault("timeout", self._t)
        return kw

    def get(self, url, **kw):
        return self._s.get(url, **self._con(kw))

    def post(self, url, **kw):
        return self._s.post(url, **self._con(kw))

    def put(self, url, **kw):
        return self._s.put(url, **self._con(kw))

    def patch(self, url, **kw):
        return self._s.patch(url, **self._con(kw))

    def delete(self, url, **kw):
        return self._s.delete(url, **self._con(kw))

    def request(self, metodo, url, **kw):
        return self._s.request(metodo, url, **self._con(kw))

    def __getattr__(self, nombre):
        return getattr(self._s, nombre)


@contextlib.asynccontextmanager
async def sesion(total: float = 30) -> AsyncIterator[_ConTimeout]:
    """Bloque de peticiones con ``total`` segundos de timeout por petición."""
    yield _ConTimeout(compartida(), aiohttp.ClientTimeout(total=total))


async def cerrar() -> None:
    """Cierra la sesión compartida (lo llama el bot al apagarse)."""
    global _sesion
    if _sesion is not None and not _sesion.closed:
        await _sesion.close()
    _sesion = None
