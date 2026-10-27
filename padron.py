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


def generar_candidatos_cuil(dni: str) -> list[str]:
    """
    Genera los posibles números de CUIT/CUIL para un DNI dado
    (probando prefijos 20, 27, 23, 24 y calculando el dígito verificador).
    """
    dni_clean = str(dni).strip().replace(".", "").replace("-", "").replace(" ", "")
    if not dni_clean.isdigit() or not (6 <= len(dni_clean) <= 8):
        return []
    dni_8 = dni_clean.zfill(8)
    weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    candidatos = []

    def calc_check(prefix: int) -> int | None:
        base = f"{prefix}{dni_8}"
        total = sum(int(d) * w for d, w in zip(base, weights))
        r = total % 11
        if r == 0:
            return 0
        elif r == 1:
            return None
        return 11 - r

    # 1. Prefijo 20 (masculino)
    c20 = calc_check(20)
    if c20 is not None:
        candidatos.append(f"20{dni_8}{c20}")
    else:
        candidatos.append(f"23{dni_8}9")

    # 2. Prefijo 27 (femenino)
    c27 = calc_check(27)
    if c27 is not None:
        candidatos.append(f"27{dni_8}{c27}")
    else:
        candidatos.append(f"23{dni_8}4")

    # 3. Prefijo 23 (colisión o caso general)
    c23 = calc_check(23)
    if c23 is not None:
        candidatos.append(f"23{dni_8}{c23}")

    # 4. Prefijo 24 (casos especiales)
    c24 = calc_check(24)
    if c24 is not None:
        candidatos.append(f"24{dni_8}{c24}")

    return list(dict.fromkeys(candidatos))


def _buscar_cuit_directo(client, token: str, sign: str, cuit_representada: int, cuit_target: str) -> dict | None:
    import zeep

    try:
        resp = client.service.getPersona(
            token=token,
            sign=sign,
            cuitRepresentada=cuit_representada,
            idPersona=int(cuit_target),
        )
    except zeep.exceptions.Fault as e:
        msg = str(e).lower()
        if "inexistente" in msg or "no es valido" in msg or "no existe" in msg:
            return None
        raise

    if resp is None or not hasattr(resp, "persona") or resp.persona is None:
        return None

    p = resp.persona

    def _clean(val):
        if val is None:
            return ""
        s = str(val).strip()
        return "" if s.upper() == "NONE" else s

    nom_c = _clean(getattr(p, "nombre", None))
    ape_c = _clean(getattr(p, "apellido", None))
    razon_c = _clean(getattr(p, "razonSocial", None))

    if getattr(p, "tipoPersona", None) == "FISICA":
        if nom_c and ape_c:
            nombre = f"{nom_c} {ape_c}".strip().title()
        elif ape_c:
            nombre = ape_c.strip().title()
        elif nom_c:
            nombre = nom_c.strip().title()
        else:
            nombre = razon_c.strip().title()
    else:
        nombre = razon_c.strip().title() or f"{nom_c} {ape_c}".strip().title()

    domicilio_fiscal = next(
        (d for d in (getattr(p, "domicilio", None) or [])
         if getattr(d, "tipoDomicilio", "").upper() == "FISCAL"),
        None,
    )
    if not domicilio_fiscal and getattr(p, "domicilio", None):
        domicilio_fiscal = p.domicilio[0]

    dom_str = None
    if domicilio_fiscal:
        parts = []
        d_dir = _clean(getattr(domicilio_fiscal, "direccion", None))
        d_loc = _clean(getattr(domicilio_fiscal, "localidad", None))
        d_prov = _clean(getattr(domicilio_fiscal, "descripcionProvincia", None))
        d_cp = _clean(getattr(domicilio_fiscal, "codigoPostal", None))

        if d_dir:
            parts.append(d_dir)
        if d_loc:
            parts.append(d_loc)
        if d_prov and d_prov != d_loc:
            parts.append(d_prov)
        if d_cp:
            parts.append(f"CP {d_cp}")
        dom_str = " - ".join(parts) if parts else (d_dir or None)

    return {
        "nombre": nombre,
        "cuit": cuit_target,
        "tipo_persona": getattr(p, "tipoPersona", None),
        "actividad": getattr(p, "descripcionActividadPrincipal", None),
        "domicilio": dom_str,
        "localidad": getattr(domicilio_fiscal, "descripcionProvincia", None) if domicilio_fiscal else None,
    }


def buscar_persona(config: Config, cuit: str) -> dict | None:
    """
    Busca datos de una persona/empresa por CUIT o DNI en el padrón A13.
    - Si se pasa un CUIT (11 dígitos), consulta directamente por ese CUIT.
    - Si se pasa un DNI (6 a 8 dígitos), genera candidatos de CUIL (20, 27, 23, 24)
      y consulta hasta encontrar el registro correspondiente en AFIP.
    Retorna dict con 'nombre', 'domicilio', 'actividad', etc. o None si no se encuentra.
    """
    import zeep

    clean = str(cuit or "").strip().replace("-", "").replace(" ", "").replace(".", "")
    if not clean.isdigit():
        return None

    token, sign = _get_padron_token(config)
    transport = build_transport(config.wsdl_cache_path)
    client = zeep.Client(wsdl=_WSDL[config.env], transport=transport)
    cuit_rep = int(config.cuit)

    if len(clean) == 11:
        return _buscar_cuit_directo(client, token, sign, cuit_rep, clean)

    if 6 <= len(clean) <= 8:
        candidatos = generar_candidatos_cuil(clean)
        for cand in candidatos:
            try:
                res = _buscar_cuit_directo(client, token, sign, cuit_rep, cand)
                if res and res.get("nombre"):
                    res["dni"] = clean
                    return res
            except zeep.exceptions.Fault as e:
                msg = str(e).lower()
                if "inexistente" in msg or "no es valido" in msg or "no existe" in msg:
                    continue
                raise
            except Exception:
                continue

    return None
