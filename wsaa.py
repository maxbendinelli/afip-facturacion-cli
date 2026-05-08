import base64
import json
import os
import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7

from config import Config


def _build_tra(service: str = "wsfe") -> str:
    now = datetime.now(timezone.utc)
    gen = now - timedelta(minutes=10)
    exp = now + timedelta(hours=12)
    fmt = "%Y-%m-%dT%H:%M:%S+00:00"
    unique_id = str(int(time.time()))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<loginTicketRequest version="1.0">'
        "<header>"
        f"<uniqueId>{unique_id}</uniqueId>"
        f"<generationTime>{gen.strftime(fmt)}</generationTime>"
        f"<expirationTime>{exp.strftime(fmt)}</expirationTime>"
        "</header>"
        f"<service>{service}</service>"
        "</loginTicketRequest>"
    )


def _sign_tra(tra_xml: str, cert_path: str, key_path: str) -> str:
    cert = x509.load_pem_x509_certificate(open(cert_path, "rb").read())
    key = serialization.load_pem_private_key(open(key_path, "rb").read(), password=None)
    signed = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(tra_xml.encode("utf-8"))
        .add_signer(cert, key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )
    return base64.b64encode(signed).decode("ascii")


def _call_wsaa(cms_b64: str, wsaa_url: str, wsdl_cache_path: str) -> tuple[str, str, str]:
    import zeep
    from ssl_transport import build_transport

    transport = build_transport(wsdl_cache_path)
    client = zeep.Client(wsdl=wsaa_url + "?WSDL", transport=transport)
    response_xml = client.service.loginCms(in0=cms_b64)

    root = ET.fromstring(response_xml)
    token = root.find(".//token").text
    sign = root.find(".//sign").text
    exp_str = root.find(".//expirationTime").text
    return token, sign, exp_str


def _load_cache(path: str) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _is_valid(cached: dict) -> bool:
    try:
        expires_at = datetime.fromisoformat(cached["expires_at"])
        return expires_at > datetime.now(timezone.utc) + timedelta(minutes=10)
    except (KeyError, ValueError):
        return False


def _save_cache(path: str, token: str, sign: str, exp_str: str) -> None:
    # exp_str from AFIP is ISO8601 with TZ
    try:
        exp_dt = datetime.fromisoformat(exp_str)
    except ValueError:
        exp_dt = datetime.now(timezone.utc) + timedelta(hours=12)

    data = {"token": token, "sign": sign, "expires_at": exp_dt.isoformat()}
    # Write to a temp file then rename for atomicity
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def get_token_sign(config: Config) -> tuple[str, str]:
    cached = _load_cache(config.token_cache_path)
    if cached and _is_valid(cached):
        return cached["token"], cached["sign"]

    tra = _build_tra("wsfe")
    cms_b64 = _sign_tra(tra, config.cert_path, config.key_path)
    token, sign, exp_str = _call_wsaa(cms_b64, config.wsaa_url, config.wsdl_cache_path)
    _save_cache(config.token_cache_path, token, sign, exp_str)
    return token, sign
