"""
Consulta al padrón A13 de AFIP (ws_sr_padron_a13) para obtener datos de un
contribuyente a partir de su CUIT. No requiere autorización especial — alcanza
con tener el servicio habilitado en el portal AFIP.
"""
import json
import os
from datetime import datetime, timezone, timedelta

from config import Config
from ssl_transport import build_transport
from wsaa import _build_tra, _sign_tra, _call_wsaa, _save_cache

_WSDL = {
    "prod": "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL",
    "homo": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL",
}


def _get_padron_token(config: Config) -> tuple[str, str]:
    cache_path = config.token_cache_path.replace(".json", "_padron_a13.json")
    try:
        with open(cache_path) as f:
            cached = json.load(f)
        exp = datetime.fromisoformat(cached["expires_at"])
        if exp > datetime.now(timezone.utc) + timedelta(minutes=10):
            return cached["token"], cached["sign"]
    except (FileNotFoundError, KeyError, ValueError):
        pass

    tra = _build_tra("ws_sr_padron_a13")
    cms_b64 = _sign_tra(tra, config.cert_path, config.key_path)
    token, sign, exp_str = _call_wsaa(cms_b64, config.wsaa_url, config.wsdl_cache_path)
    _save_cache(cache_path, token, sign, exp_str)
    return token, sign


def buscar_persona(config: Config, cuit: str) -> dict | None:
    """
    Busca datos de una persona/empresa por CUIT en el padrón A13.
    Retorna dict con 'nombre', 'domicilio', 'actividad', etc. o None si no se encuentra.
    """
    import zeep

    token, sign = _get_padron_token(config)
    transport = build_transport(config.wsdl_cache_path)
    client = zeep.Client(wsdl=_WSDL[config.env], transport=transport)

    resp = client.service.getPersona(
        token=token,
        sign=sign,
        cuitRepresentada=int(config.cuit),
        idPersona=int(cuit),
    )

    if resp is None or not hasattr(resp, "persona") or resp.persona is None:
        return None

    p = resp.persona

    if getattr(p, "tipoPersona", None) == "FISICA":
        nombre = f"{getattr(p, 'nombre', '')} {getattr(p, 'apellido', '')}".strip().title()
    else:
        nombre = (getattr(p, "razonSocial", None) or "").strip().title()

    domicilio_fiscal = next(
        (d for d in (getattr(p, "domicilio", None) or [])
         if getattr(d, "tipoDomicilio", "") == "FISCAL"),
        None,
    )

    return {
        "nombre": nombre,
        "cuit": cuit,
        "tipo_persona": getattr(p, "tipoPersona", None),
        "actividad": getattr(p, "descripcionActividadPrincipal", None),
        "domicilio": getattr(domicilio_fiscal, "direccion", None) if domicilio_fiscal else None,
        "localidad": getattr(domicilio_fiscal, "descripcionProvincia", None) if domicilio_fiscal else None,
    }
