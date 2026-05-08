"""
Transport zeep con SSL de nivel 1 para compatibilidad con los servidores
de producción de AFIP, que usan claves DH pequeñas rechazadas por OpenSSL moderno.
"""
import ssl

import requests
from requests.adapters import HTTPAdapter
from zeep.cache import SqliteCache
from zeep.transports import Transport


class _LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def build_transport(wsdl_cache_path: str) -> Transport:
    session = requests.Session()
    session.mount("https://", _LegacySSLAdapter())
    return Transport(cache=SqliteCache(path=wsdl_cache_path), session=session)
