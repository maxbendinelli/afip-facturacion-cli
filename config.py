import os
from dataclasses import dataclass, field
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


@dataclass
class Config:
    cuit: str
    cert_path: str
    key_path: str
    punto_venta: int
    token_cache_path: str
    wsdl_cache_path: str
    env: str
    dry_run: bool
    razon_social: str = ""
    nombre_fantasia: str = ""
    domicilio: str = ""
    domicilio_fiscal: str = ""
    logo_path: str = ""
    inicio_actividades: str = ""
    ingresos_brutos: str = ""
    limite_consumidor_final: Decimal = field(default_factory=lambda: Decimal("97673.32"))

    @property
    def wsaa_url(self) -> str:
        if self.env == "prod":
            return "https://wsaa.afip.gob.ar/ws/services/LoginCms"
        return "https://wsaahomo.afip.gob.ar/ws/services/LoginCms"

    @property
    def wsfev1_wsdl(self) -> str:
        if self.env == "prod":
            return "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL"
        return "https://wswhomo.afip.gob.ar/wsfev1/service.asmx?WSDL"

    @property
    def padron_wsdl(self) -> str:
        if self.env == "prod":
            return "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL"
        return "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL"


def _resolve_cache_path(base: str, env: str) -> str:
    """Garantiza que el token cache siempre sea específico del entorno (homo/prod)."""
    path = base.removesuffix(".json")
    for sfx in ("_homo", "_prod"):
        if path.endswith(sfx):
            path = path[: -len(sfx)]
            break
    return f"{path}_{env}.json"


def load_config(env: str = "homo", dry_run: bool = False) -> Config:
    if env not in ("homo", "prod"):
        raise ConfigError(f"Entorno inválido: '{env}'. Use 'homo' o 'prod'.")

    cuit = os.getenv("AFIP_CUIT", "").strip().replace("-", "").replace(" ", "")
    if not cuit:
        raise ConfigError("AFIP_CUIT no configurado. Agregue al .env o variable de entorno.")
    if not cuit.isdigit() or len(cuit) != 11:
        raise ConfigError(f"AFIP_CUIT inválido: '{cuit}'. Debe tener 11 dígitos.")

    env_upper = env.upper()
    cert_path = (
        os.getenv(f"AFIP_CERT_PATH_{env_upper}", "").strip()
        or os.getenv("AFIP_CERT_PATH", "").strip()
    )
    key_path = (
        os.getenv(f"AFIP_KEY_PATH_{env_upper}", "").strip()
        or os.getenv("AFIP_KEY_PATH", "").strip()
    )

    if not dry_run:
        if not cert_path:
            raise ConfigError(
                f"Certificado no configurado. Defina AFIP_CERT_PATH_{env_upper} o AFIP_CERT_PATH."
            )
        if not key_path:
            raise ConfigError(
                f"Clave privada no configurada. Defina AFIP_KEY_PATH_{env_upper} o AFIP_KEY_PATH."
            )
        if not os.path.isfile(cert_path):
            raise ConfigError(f"Certificado no encontrado: {cert_path}")
        if not os.path.isfile(key_path):
            raise ConfigError(f"Clave privada no encontrada: {key_path}")

    try:
        punto_venta = int(os.getenv("AFIP_PUNTO_VENTA", "1"))
    except ValueError:
        raise ConfigError("AFIP_PUNTO_VENTA debe ser un número entero.")

    try:
        limite_cf = Decimal(os.getenv("AFIP_LIMITE_CF", "97673.32"))
    except Exception:
        raise ConfigError("AFIP_LIMITE_CF debe ser un número decimal.")

    return Config(
        cuit=cuit,
        cert_path=cert_path,
        key_path=key_path,
        punto_venta=punto_venta,
        token_cache_path=_resolve_cache_path(os.getenv("AFIP_TOKEN_CACHE_PATH", "./.afip_token_cache"), env),
        wsdl_cache_path=os.getenv("AFIP_WSDL_CACHE_PATH", "./.afip_wsdl_cache.db"),
        env=env,
        dry_run=dry_run,
        razon_social=os.getenv("AFIP_RAZON_SOCIAL", ""),
        nombre_fantasia=os.getenv("AFIP_NOMBRE_FANTASIA", ""),
        domicilio=os.getenv("AFIP_DOMICILIO", ""),
        domicilio_fiscal=os.getenv("AFIP_DOMICILIO_FISCAL", "") or os.getenv("AFIP_DOMICILIO", ""),
        logo_path=os.getenv("AFIP_LOGO_PATH", ""),
        inicio_actividades=os.getenv("AFIP_INICIO_ACTIVIDADES", ""),
        ingresos_brutos=os.getenv("AFIP_INGRESOS_BRUTOS", ""),
        limite_consumidor_final=limite_cf,
    )
