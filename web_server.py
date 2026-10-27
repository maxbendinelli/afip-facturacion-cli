import csv
import glob
import io
import json
import os
import shutil
import time
import zipfile
from datetime import date, datetime, timedelta
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import Config, ConfigError, load_config, save_env_config
from models import (
    CBTE_LETRA,
    CBTE_NOMBRE,
    CBTE_TIPO,
    COND_IVA_ALIAS,
    COND_IVA_NOMBRE,
    COND_IVA_TODAS,
    COND_IVA_EMISOR,
    COND_IVA_RECEPTOR,
    DOC_TIPO_NOMBRE,
    IVA_ALICUOTAS,
    InvoiceItem,
    InvoiceRequest,
    InvoiceResponse,
)
from padron import buscar_persona
from pdf_generator import generate_pdf, format_pdf_filename
from validators import validar_cuit_afip, validar_formato_cuit
from wsaa import get_token_sign
from wsfev1 import (
    buscar_rango,
    consultar_comprobante,
    get_ultimo_numero, get_ultimo_comprobante_info,
    solicitar_cae,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
CERTS_DIR = BASE_DIR / "certs"
CERTS_DIR.mkdir(exist_ok=True)
COMPROBANTES_DIR = BASE_DIR / "comprobantes"
COMPROBANTES_DIR.mkdir(exist_ok=True)

app = FastAPI(title="ARCA / AFIP Facturación Electrónica", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _last_day_of_month(d: date) -> date:
    next_month = d.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def _parse_doc(raw: str, default_tipo: Optional[int] = None) -> tuple[int, str]:
    raw_clean = str(raw or "").strip().replace("-", "").replace(" ", "").replace(".", "")
    raw_upper = raw_clean.upper()

    # Detección de prefijos si vienen en el texto
    for prefix, tipo in [("CUIT", 80), ("CUIL", 86), ("CDI", 87), ("LE", 89), ("LC", 90), ("DNI", 96), ("PAS", 94), ("CI", 91)]:
        if raw_upper.startswith(prefix):
            clean_num = raw_upper[len(prefix):].strip()
            if clean_num.isdigit():
                return tipo, clean_num

    if default_tipo is not None:
        return default_tipo, raw_clean if raw_clean.isdigit() else "0"

    if raw_clean.isdigit() and len(raw_clean) == 11:
        return 80, raw_clean
    if raw_clean.isdigit() and 6 <= len(raw_clean) <= 8:
        return 96, raw_clean
    if raw_upper in ("SIN_CUIT", "0", ""):
        return 99, "0"
    raise ValueError(f"Formato de documento inválido: '{raw}'")


def _parse_date_afip(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    val = val.strip().replace("-", "/")
    parts = val.split("/")
    if len(parts) == 3:
        d, m, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
        if len(y) == 4:
            return f"{y}{m}{d}"
    clean = re.sub(r"\D", "", val)
    if len(clean) == 8:
        return clean
    return None



# ── MODELOS DE REQUEST ────────────────────────────────────────────────────────


class ItemIn(BaseModel):
    descripcion: str
    cantidad: float = 1.0
    precio_unitario: float
    alicuota_iva: float = 21.0
    alicuota_iva_id: int = 5
    tipo_iva: Optional[str] = "iva"  # "iva", "exento", "no_gravado"


class EmitirIn(BaseModel):
    cbte_tipo: int = 11
    doc_tipo: Optional[int] = None  # 1: Factura A, 6: Factura B, 11: Factura C
    cuit_cliente: str = "SIN_CUIT"
    nombre_cliente: Optional[str] = None
    domicilio_cliente: Optional[str] = None
    concepto: Optional[str] = None
    concepto_afip: int = 2  # 1=productos, 2=servicios, 3=ambos
    condicion_iva_receptor: Optional[int] = None
    condicion_venta: str = "Contado"
    fecha: Optional[str] = None
    periodo_desde: Optional[str] = None
    periodo_hasta: Optional[str] = None
    fecha_vto_pago: Optional[str] = None
    cae: Optional[str] = None
    comprobante: Optional[str] = None
    status: Optional[str] = None
    monto: Optional[float] = None
    items: List[ItemIn] = []
    numero_original: Optional[int] = None
    cbte_tipo_original: Optional[int] = None
    duplicado: bool = False
    triplicado: bool = False
    copias: int = 1
    env: Optional[str] = None
    dry_run: bool = False


class PreviewSampleIn(BaseModel):
    cbte_tipo: Optional[int] = None
    razon_social: Optional[str] = None
    domicilio: Optional[str] = None
    condicion_iva_emisor: Optional[str] = None
    logo_path: Optional[str] = None
    ingresos_brutos: Optional[str] = None
    inicio_actividades: Optional[str] = None
    leyenda: Optional[str] = None
    watermark_text: Optional[str] = None
    watermark_image: Optional[str] = None


class ConfigIn(BaseModel):
    env: str
    cuit: str
    cuit_homo: Optional[str] = ""
    punto_venta: int
    razon_social: Optional[str] = ""
    nombre_fantasia: Optional[str] = ""
    domicilio: Optional[str] = ""
    condicion_iva_emisor: Optional[str] = ""
    logo_path: Optional[str] = ""
    leyenda: Optional[str] = ""
    watermark_text: Optional[str] = ""
    watermark_image: Optional[str] = ""
    inicio_actividades: Optional[str] = ""
    ingresos_brutos: Optional[str] = ""
    limite_cf: Optional[float] = 97673.32
    cert_path_homo: Optional[str] = ""
    key_path_homo: Optional[str] = ""
    cert_path_prod: Optional[str] = ""
    key_path_prod: Optional[str] = ""


class CsrIn(BaseModel):
    cuit: str
    razon_social: str
    bits: int = 2048


class ReimprimirIn(BaseModel):
    cbte_tipo: int
    numero: int
    duplicado: bool = False
    triplicado: bool = False
    copias: int = 1


class LoteRowIn(BaseModel):
    index: int = 0
    tipo: str = "C"
    cbte_tipo: int = 11
    cuit_cliente: str = "SIN_CUIT"
    nombre_cliente: str = "Consumidor Final"
    domicilio_cliente: Optional[str] = None
    concepto: str = "Servicio"
    monto: float = 0.0
    alicuota_iva: float = 21.0
    alicuota_iva_id: Optional[int] = 5
    tipo_iva: Optional[str] = "iva"
    condicion_iva_receptor: int = 5
    condicion_venta: str = "Contado"
    concepto_afip: int = 2
    fecha: Optional[str] = None
    periodo_desde: Optional[str] = None
    periodo_hasta: Optional[str] = None
    fecha_vto_pago: Optional[str] = None
    cae: Optional[str] = None
    comprobante: Optional[str] = None
    status: Optional[str] = None


class LoteEmitirIn(BaseModel):
    rows: List[LoteRowIn]
    env: Optional[str] = None
    environment: Optional[str] = None
    dry_run: bool = True
    duplicado: bool = False
    triplicado: bool = False
    copias: int = 1



# ── ENDPOINTS BÁSICOS Y METADATOS ─────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def get_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Error: static/index.html no encontrado.</h1>", status_code=404)
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/meta")
def get_meta():
    """Retorna diccionarios de tipos de comprobantes, condiciones IVA y alícuotas."""
    return {
        "comprobantes": [
            {"id": k, "nombre": v, "letra": CBTE_LETRA.get(k, "C")}
            for k, v in CBTE_NOMBRE.items()
        ],
        "tipos_doc": [
            {"id": k, "nombre": v} for k, v in DOC_TIPO_NOMBRE.items()
        ],
        "condiciones_iva": [
            {"id": k, "nombre": v} for k, v in COND_IVA_NOMBRE.items()
        ],
        "alicuotas_iva": [
            {"id": v["id"], "tipo": v.get("tipo", "iva"), "porcentaje": float(v["porcentaje"]), "desc": v["desc"]}
            for v in IVA_ALICUOTAS.values()
        ],
    }


# ── CERTIFICADOS Y ARCHIVOS ───────────────────────────────────────────────────


@app.get("/api/certs/list")
def list_certificates():
    """Lista todos los archivos de certificados y claves encontrados en ./certs."""
    results = []
    for ext in ("*.crt", "*.pem", "*.key", "*.csr"):
        for p in CERTS_DIR.rglob(ext):
            rel = str(p.relative_to(BASE_DIR)).replace("\\", "/")
            results.append({
                "path": rel,
                "name": p.name,
                "type": "key" if p.suffix.lower() == ".key" else ("csr" if p.suffix.lower() == ".csr" else "cert"),
                "env": "homo" if "homo" in str(p).lower() else "prod",
            })
    return sorted(results, key=lambda x: x["path"])


@app.post("/api/upload-cert")
async def upload_certificate(file: UploadFile = File(...), target_subfolder: str = Form("")):
    """Sube un archivo de certificado o clave a la carpeta certs/."""
    safe_name = os.path.basename(file.filename)
    dest_dir = CERTS_DIR / target_subfolder if target_subfolder else CERTS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name

    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)

    rel_path = str(dest_path.relative_to(BASE_DIR)).replace("\\", "/")
    return {
        "status": "ok",
        "filename": safe_name,
        "path": rel_path,
        "absolute_path": str(dest_path),
    }


@app.post("/api/upload-asset")
async def upload_asset(file: UploadFile = File(...), asset_type: str = Form("logo")):
    """Sube un asset visual (Logo o Watermark) a static/uploads/."""
    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg"):
        raise HTTPException(status_code=400, detail="Formato de imagen no soportado. Use PNG o JPG.")

    target_filename = f"{asset_type}{ext}"
    dest_path = UPLOADS_DIR / target_filename

    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)

    rel_path = str(dest_path.relative_to(BASE_DIR)).replace("\\", "/")
    return {
        "status": "ok",
        "path": rel_path,
        "url": f"/static/uploads/{target_filename}?t={int(time.time())}",
    }


# ── CONFIGURACIÓN ─────────────────────────────────────────────────────────────


@app.get("/api/config")
def get_config():
    """Obtiene la configuración actual y valida el estado de los certificados."""
    env = os.getenv("AFIP_ENV", "homo").lower()
    if env not in ("homo", "prod"):
        env = "homo"

    try:
        cfg = load_config(env=env, dry_run=True)
    except Exception:
        cfg = None

    cert_homo = os.getenv("AFIP_CERT_PATH_HOMO", "") or os.getenv("AFIP_CERT_PATH", "")
    key_homo = os.getenv("AFIP_KEY_PATH_HOMO", "") or os.getenv("AFIP_KEY_PATH", "")
    cert_prod = os.getenv("AFIP_CERT_PATH_PROD", "") or os.getenv("AFIP_CERT_PATH", "")
    key_prod = os.getenv("AFIP_KEY_PATH_PROD", "") or os.getenv("AFIP_KEY_PATH", "")

    cuit_main = os.getenv("AFIP_CUIT", "")
    cuit_homo = os.getenv("AFIP_CUIT_HOMO", "")
    cuit_prod = os.getenv("AFIP_CUIT_PROD", "")

    return {
        "env": env,
        "cuit": cfg.cuit if cfg else (cuit_homo if env == "homo" and cuit_homo else cuit_main),
        "cuit_main": cuit_main,
        "cuit_homo": cuit_homo,
        "cuit_prod": cuit_prod,
        "punto_venta": cfg.punto_venta if cfg else int(os.getenv("AFIP_PUNTO_VENTA", "1")),
        "razon_social": cfg.razon_social if cfg else os.getenv("AFIP_RAZON_SOCIAL", ""),
        "nombre_fantasia": cfg.nombre_fantasia if cfg else os.getenv("AFIP_NOMBRE_FANTASIA", ""),
        "domicilio": cfg.domicilio if cfg else os.getenv("AFIP_DOMICILIO", ""),
        "condicion_iva_emisor": cfg.condicion_iva_emisor if cfg else os.getenv("AFIP_CONDICION_IVA_EMISOR", ""),
        "logo_path": cfg.logo_path if cfg else os.getenv("AFIP_LOGO_PATH", ""),
        "leyenda": cfg.leyenda if cfg else os.getenv("AFIP_LEYENDA", ""),
        "watermark_text": cfg.watermark_text if cfg else os.getenv("AFIP_WATERMARK_TEXT", ""),
        "watermark_image": cfg.watermark_image if cfg else os.getenv("AFIP_WATERMARK_IMAGE", ""),
        "inicio_actividades": cfg.inicio_actividades if cfg else os.getenv("AFIP_INICIO_ACTIVIDADES", ""),
        "ingresos_brutos": cfg.ingresos_brutos if cfg else os.getenv("AFIP_INGRESOS_BRUTOS", ""),
        "limite_cf": float(cfg.limite_consumidor_final) if cfg else 97673.32,
        "cert_path_homo": cert_homo,
        "key_path_homo": key_homo,
        "cert_homo_exists": os.path.isfile(cert_homo) if cert_homo else False,
        "key_homo_exists": os.path.isfile(key_homo) if key_homo else False,
        "cert_path_prod": cert_prod,
        "key_path_prod": key_prod,
        "cert_prod_exists": os.path.isfile(cert_prod) if cert_prod else False,
        "key_prod_exists": os.path.isfile(key_prod) if key_prod else False,
    }


@app.post("/api/config")
def update_config(payload: ConfigIn):
    """Guarda modificaciones en el archivo .env."""
    cuit_clean = payload.cuit.strip().replace("-", "").replace(" ", "")
    cuit_homo_clean = (payload.cuit_homo or "").strip().replace("-", "").replace(" ", "")

    updates = {
        "AFIP_ENV": payload.env,
        "AFIP_CUIT": cuit_clean,
        "AFIP_CUIT_HOMO": cuit_homo_clean,
        "AFIP_PUNTO_VENTA": str(payload.punto_venta),
        "AFIP_RAZON_SOCIAL": payload.razon_social or "",
        "AFIP_NOMBRE_FANTASIA": payload.nombre_fantasia or "",
        "AFIP_DOMICILIO": payload.domicilio or "",
        "AFIP_CONDICION_IVA_EMISOR": payload.condicion_iva_emisor or "",
        "AFIP_LOGO_PATH": payload.logo_path or "",
        "AFIP_LEYENDA": payload.leyenda or "",
        "AFIP_WATERMARK_TEXT": payload.watermark_text or "",
        "AFIP_WATERMARK_IMAGE": payload.watermark_image or "",
        "AFIP_INICIO_ACTIVIDADES": payload.inicio_actividades or "",
        "AFIP_INGRESOS_BRUTOS": payload.ingresos_brutos or "",
        "AFIP_LIMITE_CF": str(payload.limite_cf or 97673.32),
    }

    if payload.cert_path_homo:
        updates["AFIP_CERT_PATH_HOMO"] = payload.cert_path_homo
    if payload.key_path_homo:
        updates["AFIP_KEY_PATH_HOMO"] = payload.key_path_homo
    if payload.cert_path_prod:
        updates["AFIP_CERT_PATH_PROD"] = payload.cert_path_prod
    if payload.key_path_prod:
        updates["AFIP_KEY_PATH_PROD"] = payload.key_path_prod

    try:
        save_env_config(updates, env_path=str(BASE_DIR / ".env"))
        return {"status": "ok", "message": "Configuración guardada correctamente en .env"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando configuración: {e}")


@app.get("/api/config/condiciones-iva")
def get_condiciones_iva():
    """Retorna las listas oficiales de Condiciones frente al IVA de ARCA/AFIP para Emisor y Receptor."""
    return {
        "emisor": [{"id": k, "nombre": v} for k, v in COND_IVA_EMISOR.items()],
        "receptor": [{"id": k, "nombre": v} for k, v in COND_IVA_RECEPTOR.items()],
    }


@app.post("/api/config/test")
def test_afip_connection(env: Optional[str] = Query(None)):
    """Prueba la conexión completa con AFIP (WSAA y WSFEv1)."""
    target_env = env or os.getenv("AFIP_ENV", "homo").lower()
    t0 = time.time()
    try:
        cfg = load_config(env=target_env, dry_run=False)
        token, sign = get_token_sign(cfg)
        wsaa_ms = int((time.time() - t0) * 1000)

        t1 = time.time()
        ultimo_c = get_ultimo_numero(cfg, token, sign, cbte_tipo=11)
        wsfe_ms = int((time.time() - t1) * 1000)

        return {
            "status": "ok",
            "env": target_env,
            "cuit": cfg.cuit,
            "punto_venta": cfg.punto_venta,
            "wsaa_status": "Conectado y Autorizado",
            "wsaa_tiempo_ms": wsaa_ms,
            "wsfe_status": "Operativo",
            "wsfe_tiempo_ms": wsfe_ms,
            "ultimo_factura_c": ultimo_c,
            "proximo_factura_c": ultimo_c + 1,
        }
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "env": target_env,
                "error": str(e),
                "tiempo_ms": int((time.time() - t0) * 1000),
            },
        )


@app.get("/api/padron/{cuit}")
def get_padron_persona(cuit: str, env: Optional[str] = Query(None)):
    """Consulta los datos de una persona o empresa en el Padrón A13 de AFIP."""
    cuit_clean = cuit.strip().replace("-", "").replace(" ", "")
    ok, err = validar_formato_cuit(cuit_clean)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    # El Padrón A13 es una consulta pública de sólo lectura (sin impacto fiscal).
    # Si hay certificados de producción disponibles, usamos PRODUCCIÓN para obtener nombres reales,
    # ya que en Homologación (awshomo) AFIP inyecta nombres ficticios/anonimizados de prueba.
    if env == "prod" or env is None:
        try:
            cfg_prod = load_config(env="prod", dry_run=False)
            datos = buscar_persona(cfg_prod, cuit_clean)
            if datos:
                return datos
        except Exception:
            pass

    target_env = env or os.getenv("AFIP_ENV", "homo").lower()
    try:
        cfg = load_config(env=target_env, dry_run=False)
        datos = buscar_persona(cfg, cuit_clean)
        if not datos:
            raise HTTPException(status_code=404, detail="CUIT no encontrado en el padrón AFIP.")
        return datos
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando padrón: {e}")


def _format_afip_error(e: Exception) -> str:
    """Traduce errores crudos de AFIP / WSAA a mensajes claros y accionables."""
    msg = str(e)
    if "Computador no autorizado a acceder al servicio" in msg:
        return (
            "Error de autorización AFIP (WSAA): 'Computador no autorizado a acceder al servicio'.\n"
            "Causas y solución:\n"
            "1) En el sitio web de AFIP con Clave Fiscal ('Administrador de Relaciones de Clave Fiscal'), falta delegar/vincular el Alias de su certificado al servicio 'Facturación Electrónica' (wsfe).\n"
            "2) El CUIT en el archivo .env no coincide con el CUIT para el que se emitió el certificado digital (.crt).\n"
            "3) Si el certificado fue tramitado en PRODUCCIÓN, verifique tener AFIP_ENV=prod en el .env (los certificados de producción son rechazados en homologación y viceversa)."
        )
    if "El CEE ya posee comprobantes asociados" in msg:
        return f"Error AFIP: {msg}"
    return f"Error en servicio AFIP: {msg}"


@app.get("/api/comprobantes/ultimo/{cbte_tipo}")
def get_ultimo_cbte(cbte_tipo: int, env: Optional[str] = Query(None)):
    """Obtiene el último número autorizado en AFIP para un tipo de comprobante."""
    target_env = env or os.getenv("AFIP_ENV", "homo").lower()
    try:
        cfg = load_config(env=target_env, dry_run=False)
        token, sign = get_token_sign(cfg)
        ultimo = get_ultimo_numero(cfg, token, sign, cbte_tipo)
        fecha_ultimo = None
        if ultimo > 0:
            try:
                det = consultar_comprobante(cfg, token, sign, cbte_tipo, ultimo)
                fecha_ultimo = det.get("fecha")
            except Exception:
                pass
        return {
            "status": "ok",
            "cbte_tipo": cbte_tipo,
            "tipo_nombre": CBTE_NOMBRE.get(cbte_tipo, str(cbte_tipo)),
            "ultimo_numero": ultimo,
            "proximo_numero": ultimo + 1,
            "fecha_ultimo": fecha_ultimo,
            "punto_venta": cfg.punto_venta,
            "env": target_env,
        }
    except Exception as e:
        return {
            "status": "warning",
            "detail": _format_afip_error(e),
            "cbte_tipo": cbte_tipo,
            "punto_venta": getattr(cfg, "punto_venta", 4) if "cfg" in locals() else 4,
            "env": target_env,
        }


# ── EMISIÓN INDIVIDUAL ────────────────────────────────────────────────────────


@app.post("/api/comprobantes/emitir")
def emitir_comprobante(payload: EmitirIn):
    """Emite un comprobante a AFIP (Factura A, B, C, NC o ND) y genera el PDF."""
    target_env = payload.env or os.getenv("AFIP_ENV", "homo").lower()

    try:
        cfg = load_config(env=target_env, dry_run=payload.dry_run)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    items_list = []
    for it in payload.items:
        qty = Decimal(str(it.cantidad)).quantize(Decimal("0.01"))
        precio = Decimal(str(it.precio_unitario)).quantize(Decimal("0.01"))
        alic = Decimal(str(it.alicuota_iva)).quantize(Decimal("0.1"))
        tipo_it = it.tipo_iva or ("no_gravado" if it.alicuota_iva_id == 1 else "exento" if it.alicuota_iva_id == 2 else "iva")
        items_list.append(
            InvoiceItem(
                descripcion=it.descripcion.strip(),
                cantidad=qty,
                precio_unitario=precio,
                alicuota_iva=alic,
                alicuota_iva_id=it.alicuota_iva_id,
                tipo_iva=tipo_it,
            )
        )

    if items_list:
        if payload.cbte_tipo in (1, 2, 3, 4):
            # Factura A: precio unitario es NETO; se suma IVA sólo a los gravados > 0%
            monto = sum(
                i.subtotal if i.tipo_iva in ("no_gravado", "exento") or i.alicuota_iva_id in (1, 2, 3) else i.total_con_iva
                for i in items_list
            )
        else:
            # Factura B y Factura C: precio unitario es FINAL con IVA incluido (o sin IVA)
            monto = sum(i.subtotal for i in items_list)
    else:
        if payload.monto is None:
            raise HTTPException(status_code=400, detail="Debe indicar el monto o agregar al menos un ítem.")
        try:
            monto = Decimal(str(payload.monto)).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise HTTPException(status_code=400, detail=f"Monto inválido: {payload.monto}")

    if payload.doc_tipo is not None:
        doc_tipo = payload.doc_tipo
        doc_nro = str(payload.cuit_cliente or "").strip().replace("-", "").replace(" ", "").replace(".", "")
        if doc_tipo == 99 and (not doc_nro or doc_nro in ("0", "SIN_CUIT")):
            doc_nro = "0"
    else:
        try:
            doc_tipo, doc_nro = _parse_doc(payload.cuit_cliente)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if payload.cbte_tipo in (1, 2, 3) and doc_tipo != 80:
        raise HTTPException(
            status_code=400,
            detail="Para emitir Factura A es obligatorio indicar el CUIT del receptor (doc_tipo 80).",
        )

    datos_padron = None
    nombre_cliente = payload.nombre_cliente or ""
    domicilio_cliente = (payload.domicilio_cliente or "").strip()

    if doc_tipo == 80:
        if not nombre_cliente or not domicilio_cliente:
            try:
                datos_padron = buscar_persona(cfg, doc_nro)
                if datos_padron:
                    if not nombre_cliente and datos_padron.get("nombre"):
                        nombre_cliente = datos_padron["nombre"]
                    if not domicilio_cliente and datos_padron.get("domicilio"):
                        domicilio_cliente = datos_padron["domicilio"]
            except Exception:
                pass
        if not nombre_cliente:
            raise HTTPException(status_code=400, detail="Debe indicar el nombre o razón social del cliente.")
    elif doc_tipo == 99:
        nombre_cliente = nombre_cliente or "Consumidor Final"
        if monto > cfg.limite_consumidor_final:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"El monto (${monto:,.2f}) supera el límite para Consumidor Final sin identificar "
                    f"(${cfg.limite_consumidor_final:,.2f}). Ingrese CUIT o DNI."
                ),
            )
    else:
        nombre_cliente = nombre_cliente or "Consumidor Final"

    if payload.condicion_iva_receptor:
        condicion_iva = payload.condicion_iva_receptor
    else:
        if payload.cbte_tipo in (1, 2, 3):
            condicion_iva = 1
        elif doc_tipo in (99, 96):
            condicion_iva = 5
        else:
            condicion_iva = 1

    hoy = date.today()
    fecha = payload.fecha or hoy.strftime("%Y%m%d")

    if payload.periodo_desde:
        periodo_desde = payload.periodo_desde
        periodo_hasta = payload.periodo_hasta or _last_day_of_month(hoy).strftime("%Y%m%d")
    else:
        periodo_desde = hoy.replace(day=1).strftime("%Y%m%d")
        periodo_hasta = _last_day_of_month(hoy).strftime("%Y%m%d")

    fecha_vto_pago_afip = payload.fecha_vto_pago or periodo_hasta
    fecha_vto_pago_pdf = payload.fecha_vto_pago or fecha
    if fecha_vto_pago_afip < fecha:
        fecha_vto_pago_afip = fecha
    if fecha_vto_pago_pdf < fecha:
        fecha_vto_pago_pdf = fecha

    concepto_desc = payload.concepto or ""
    if not concepto_desc and items_list:
        concepto_desc = "; ".join(i.descripcion for i in items_list)
    elif not concepto_desc:
        concepto_desc = "Servicios profesionales"

    if payload.dry_run:
        pv = cfg.punto_venta or 4
        letra = CBTE_LETRA.get(payload.cbte_tipo, "C").lower()
        sim_num = 9999
        pdf_name = format_pdf_filename(nombre_cliente, fecha=fecha, directory=COMPROBANTES_DIR)
        pdf_path = COMPROBANTES_DIR / pdf_name
        sim_op_ex = Decimal("0.00")
        sim_tot_conc = Decimal("0.00")
        sim_alics = defaultdict(lambda: {"base": Decimal("0.00"), "iva": Decimal("0.00")})

        if payload.cbte_tipo in (1, 2, 3, 4):
            for i in items_list:
                if i.tipo_iva == "no_gravado" or i.alicuota_iva_id == 1:
                    sim_tot_conc += i.subtotal
                elif i.tipo_iva == "exento" or i.alicuota_iva_id == 2:
                    sim_op_ex += i.subtotal
                elif i.alicuota_iva_id == 3 or i.alicuota_iva == Decimal("0.0"):
                    sim_alics[3]["base"] += i.subtotal
                    sim_alics[3]["iva"] += Decimal("0.00")
                else:
                    sim_alics[i.alicuota_iva_id]["base"] += i.subtotal
                    sim_alics[i.alicuota_iva_id]["iva"] += i.iva_monto
            sim_neto = sum(d["base"] for d in sim_alics.values()) if items_list else (monto / Decimal("1.21")).quantize(Decimal("0.01"))
            sim_iva = sum(d["iva"] for d in sim_alics.values()) if items_list else (monto - sim_neto)
        elif payload.cbte_tipo in (6, 7, 8, 9):
            for i in items_list:
                if i.tipo_iva == "no_gravado" or i.alicuota_iva_id == 1:
                    sim_tot_conc += i.subtotal
                elif i.tipo_iva == "exento" or i.alicuota_iva_id == 2:
                    sim_op_ex += i.subtotal
                elif i.alicuota_iva_id == 3 or i.alicuota_iva == Decimal("0.0"):
                    sim_alics[3]["base"] += i.subtotal
                    sim_alics[3]["iva"] += Decimal("0.00")
                else:
                    factor = Decimal("1.00") + (i.alicuota_iva / Decimal("100"))
                    base_i = (i.subtotal / factor).quantize(Decimal("0.01"))
                    iva_i = i.subtotal - base_i
                    sim_alics[i.alicuota_iva_id]["base"] += base_i
                    sim_alics[i.alicuota_iva_id]["iva"] += iva_i
            sim_neto = sum(d["base"] for d in sim_alics.values()) if items_list else (monto / Decimal("1.21")).quantize(Decimal("0.01"))
            sim_iva = sum(d["iva"] for d in sim_alics.values()) if items_list else (monto - sim_neto)
        else:
            sim_neto = monto
            sim_iva = Decimal("0.00")

        sim_ivas = [
            {"Id": aid, "BaseImp": str(data["base"]), "Importe": str(data["iva"])}
            for aid, data in sim_alics.items()
            if aid in (3, 4, 5, 6, 8, 9) and data["base"] > 0
        ]

        resp_sim = InvoiceResponse(
            cae="SIMULADO_CAE_123456",
            cae_vencimiento=(hoy + timedelta(days=10)).strftime("%Y%m%d"),
            numero=sim_num,
            cbte_tipo=payload.cbte_tipo,
            punto_venta=pv,
            fecha=fecha,
            monto=monto,
            nombre_cliente=nombre_cliente,
            cuit_cliente=doc_nro,
            resultado="A",
            doc_tipo=doc_tipo,
            condicion_iva_receptor=condicion_iva,
            condicion_venta=payload.condicion_venta or "Contado",
            periodo_desde=periodo_desde if payload.concepto_afip in (2, 3) else None,
            periodo_hasta=periodo_hasta if payload.concepto_afip in (2, 3) else None,
            fecha_vto_pago=fecha_vto_pago_pdf,
            domicilio_cliente=domicilio_cliente or None,
            hora=datetime.now().strftime("%H%M%S"),
            items=items_list,
            imp_neto=sim_neto,
            imp_iva=sim_iva,
            imp_op_ex=sim_op_ex,
            imp_tot_conc=sim_tot_conc,
            ivas=sim_ivas,
        )
        generate_pdf(cfg, resp_sim, str(pdf_path), duplicado=payload.duplicado, triplicado=getattr(payload, 'triplicado', False), copias=getattr(payload, 'copias', 1))
        return {
            "status": "ok",
            "modo": "simulacion",
            "cbte_tipo": payload.cbte_tipo,
            "tipo_nombre": CBTE_NOMBRE.get(payload.cbte_tipo),
            "comprobante": f"{pv:04d}-SIM{sim_num:04d}",
            "cae": "SIMULADO_CAE_123456",
            "cae_vencimiento": (hoy + timedelta(days=10)).strftime("%Y%m%d"),
            "monto": str(monto),
            "cliente": nombre_cliente,
            "cuit_cliente": doc_nro,
            "doc_tipo": doc_tipo,
            "condicion_iva_receptor": condicion_iva,
            "env": target_env,
            "pdf_filename": pdf_name,
            "url": f"/api/pdf/{pdf_name}",
        }

    try:
        token, sign = get_token_sign(cfg)
        ultimo = get_ultimo_numero(cfg, token, sign, payload.cbte_tipo)
    except Exception as e:
        raise HTTPException(status_code=400, detail=_format_afip_error(e))
    proximo_nro = ultimo + 1

    # Validación de fecha AFIP: CbteFch no puede ser anterior a la fecha del último comprobante
    if ultimo > 0:
        try:
            det_ult = consultar_comprobante(cfg, token, sign, payload.cbte_tipo, ultimo)
            fch_ult = str(det_ult.get("fecha") or "")
            if fch_ult and len(fch_ult) == 8 and fecha < fch_ult:
                if target_env == "homo":
                    # En homologación se ajusta automáticamente para evitar el error 10016 por pruebas previas
                    fecha = fch_ult
                    if fecha_vto_pago_afip < fecha:
                        fecha_vto_pago_afip = fecha
                    if fecha_vto_pago_pdf < fecha:
                        fecha_vto_pago_pdf = fecha
                else:
                    fch_fmt = f"{fch_ult[6:]}/{fch_ult[4:6]}/{fch_ult[:4]}"
                    fch_req_fmt = f"{fecha[6:]}/{fecha[4:6]}/{fecha[:4]}"
                    raise HTTPException(
                        status_code=400,
                        detail=f"Error AFIP: La fecha ingresada ({fch_req_fmt}) no puede ser anterior a la del último comprobante emitido (#{ultimo} del {fch_fmt}). Selecciona fecha {fch_fmt} o posterior."
                    )
        except HTTPException:
            raise
        except Exception:
            pass

    req = InvoiceRequest(
        cbte_tipo=payload.cbte_tipo,
        cuit_cliente=doc_nro,
        nombre_cliente=nombre_cliente,
        monto=monto,
        concepto=concepto_desc,
        concepto_afip=payload.concepto_afip,
        numero=proximo_nro,
        fecha=fecha,
        fecha_serv_desde=periodo_desde,
        fecha_serv_hasta=periodo_hasta,
        fecha_vto_pago=fecha_vto_pago_afip,
        doc_tipo=doc_tipo,
        doc_nro=doc_nro,
        condicion_iva_receptor=condicion_iva,
        condicion_venta=payload.condicion_venta,
        periodo_desde=periodo_desde if payload.concepto_afip in (2, 3) else None,
        periodo_hasta=periodo_hasta if payload.concepto_afip in (2, 3) else None,
        domicilio_cliente=domicilio_cliente or None,
        items=items_list,
        numero_original=payload.numero_original,
        cbte_tipo_original=payload.cbte_tipo_original,
    )

    try:
        resp = solicitar_cae(cfg, token, sign, req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al solicitar CAE: {e}")

    resp.hora = datetime.now().strftime("%H%M%S")
    resp.fecha_vto_pago = fecha_vto_pago_pdf
    if domicilio_cliente:
        resp.domicilio_cliente = domicilio_cliente
    elif datos_padron and datos_padron.get("domicilio"):
        resp.domicilio_cliente = datos_padron["domicilio"]

    letra = CBTE_LETRA.get(resp.cbte_tipo, "C").lower()
    pdf_filename = format_pdf_filename(resp.nombre_cliente, fecha=resp.fecha, hora=resp.hora, directory=COMPROBANTES_DIR)
    pdf_path = COMPROBANTES_DIR / pdf_filename
    root_pdf_path = BASE_DIR / pdf_filename

    generate_pdf(cfg, resp, str(pdf_path), duplicado=payload.duplicado, triplicado=getattr(payload, 'triplicado', False), copias=getattr(payload, 'copias', 1))
    try:
        generate_pdf(cfg, resp, str(root_pdf_path), duplicado=payload.duplicado, triplicado=getattr(payload, 'triplicado', False), copias=getattr(payload, 'copias', 1))
    except Exception:
        pass

    json_filename = f"comprobante_{letra}_{resp.punto_venta:04d}_{resp.numero:08d}.json"
    json_path = COMPROBANTES_DIR / json_filename
    resp_dict = resp.to_json()
    resp_dict["pdf_filename"] = pdf_filename
    resp_dict["env"] = target_env

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resp_dict, f, ensure_ascii=False, indent=2)

    return resp_dict


# ── FACTURACIÓN POR LOTES (BATCH CSV) ─────────────────────────────────────────


@app.get("/api/lotes/template-csv")
def get_csv_template():
    """Retorna un archivo CSV modelo con ejemplos para descargar."""
    content = (
        "tipo,cuit_cliente,nombre_cliente,domicilio,concepto,monto,alicuota_iva,condicion_iva\n"
        "C,20123456789,Juan Perez,Av. Rivadavia 1234 - CABA,Servicio de consultoria,15000,0,CF\n"
        "B,SIN_CUIT,Consumidor Final,,Articulos de libreria,24200,21,CF\n"
        "A,30712345671,Empresa SA,San Martin 456 - Rosario,Desarrollo de software,50000,21,RI\n"
        "C,27234567894,Maria Gomez,Belgrano 789 - Cordoba,Diseno web,35000,0,MONO\n"
    )
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantilla_facturas_afip.csv"},
    )


def _get_existing_comprobantes_map() -> dict:
    """Retorna un mapa (cuit, cbte_tipo, monto) -> dict de comprobante ya emitido."""
    result = {}
    if not COMPROBANTES_DIR.exists():
        return result
    for p in COMPROBANTES_DIR.glob("comprobante_*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            cuit = str(d.get("cuit_cliente", "")).strip().replace("-", "")
            cbte_tipo = int(d.get("cbte_tipo", 0))
            monto_str = str(Decimal(str(d.get("monto", "0"))).quantize(Decimal("0.01")))
            key = f"{cuit}_{cbte_tipo}_{monto_str}"
            result[key] = {
                "cae": d.get("cae"),
                "comprobante": d.get("comprobante"),
                "pdf_filename": d.get("pdf_filename"),
                "fecha": d.get("fecha"),
            }
        except Exception:
            continue
    return result

@app.post("/api/lotes/parse-csv")
async def parse_lote_csv(file: UploadFile = File(...)):
    """Parsea y valida un archivo CSV para generar el preview de la facturación por lotes."""
    existing_map = _get_existing_comprobantes_map()
    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")

    all_lines = [l for l in text.splitlines() if l.strip()]
    if not all_lines:
        raise HTTPException(status_code=400, detail="El archivo CSV está vacío.")

    # Buscar la línea de encabezado si hay metadatos o resumen al inicio
    header_idx = 0
    for i, line in enumerate(all_lines[:35]):
        ll = line.lower()
        if "destinatario" in ll or "dni/cuit" in ll or "cuit_cliente" in ll or "tipo comp" in ll or "producto o servicio" in ll:
            header_idx = i
            break
        elif "cuit" in ll and "monto" in ll:
            header_idx = i
            break

    sub_lines = all_lines[header_idx:]
    first_line = sub_lines[0]
    delimiter = ";" if ";" in first_line and first_line.count(";") >= first_line.count(",") else ","

    reader = csv.DictReader(sub_lines, delimiter=delimiter)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="No se encontraron encabezados válidos en el CSV.")

    # Mapeo de normalización de columnas a formato estándar
    def _norm_col(col: str) -> str:
        c = (col or "").strip().lower()
        c = c.replace(" ", "_").replace(".", "").replace("/", "_").replace("%", "")
        c = c.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        if "destinatario" in c or "apellido_y_nombre" in c:
            return "nombre_cliente"
        if "domicilio" in c or "direccion" in c:
            return "domicilio_cliente"
        if "dni" in c or "cuit" in c:
            return "cuit_cliente"
        if "producto" in c or "servicio" in c or "concepto" in c or "descripcion" in c:
            return "concepto"
        if "tipo_comp" in c or "tipo_comprobante" in c or "tipo" == c:
            return "tipo"
        if "total" in c or "importe" in c or "monto" in c:
            return "monto"
        if "alic" in c or "alicuota" in c:
            return "alicuota_iva"
        if "condicion_frente" in c or "condicion_iva" in c:
            return "condicion_iva"
        if "condicion_de_venta" in c:
            return "condicion_venta"
        if "emision" in c or "fecha_de_emision" in c:
            return "fecha"
        if "vto" in c or "vencimiento" in c:
            return "fecha_vto_pago"
        if "desde" in c:
            return "periodo_desde"
        if "hasta" in c:
            return "periodo_hasta"
        return c

    normalized_fieldnames = {col: _norm_col(col) for col in reader.fieldnames if col}

    rows = []
    totales = {"count": 0, "monto": 0.0, "validos": 0, "errores": 0, "tipo_a": 0, "tipo_b": 0, "tipo_c": 0}

    for idx, raw_row in enumerate(reader, 1):
        # Ignorar filas completamente vacías
        if not any(v.strip() for v in raw_row.values() if v):
            continue

        row = {normalized_fieldnames.get(k, k): (v or "").strip() for k, v in raw_row.items() if k}

        # Omitir si la columna FACTURA indica explícitamente NO
        factura_flag = (raw_row.get("FACTURA") or raw_row.get("factura") or "").strip().upper()
        if factura_flag == "NO":
            continue

        dni_field = (row.get("cuit_cliente") or row.get("cuit") or row.get("dni") or "").strip()
        nombre = (row.get("nombre_cliente") or row.get("cliente") or row.get("razon_social") or "").strip()
        domicilio = (row.get("domicilio_cliente") or row.get("domicilio") or row.get("direccion") or "").strip()
        monto_raw = (row.get("monto") or row.get("importe") or row.get("precio_unitario") or "0").replace("$", "").replace(" ", "")

        if not nombre and not dni_field and monto_raw in ("", "0"):
            continue

        cuit_raw = dni_field or "SIN_CUIT"

        # Tipo de comprobante (A, B o C)
        tipo_raw = (row.get("tipo") or "C").upper().strip()
        if "FACTURA A" in tipo_raw or tipo_raw == "A":
            tipo_str = "A"
        elif "FACTURA B" in tipo_raw or tipo_raw == "B":
            tipo_str = "B"
        else:
            tipo_str = "C"

        cbte_tipo = CBTE_TIPO.get(tipo_str, 11)
        concepto = (row.get("concepto") or "Servicios").strip()

        # Parsear monto (soporta formatos argentino y estándar)
        if "," in monto_raw and "." in monto_raw:
            monto_raw = monto_raw.replace(".", "").replace(",", ".")
        elif "," in monto_raw and "." not in monto_raw:
            monto_raw = monto_raw.replace(",", ".")
        
        try:
            monto = float(Decimal(monto_raw))
        except Exception:
            monto = 0.0

        # Alícuota IVA y Tipo IVA
        alic_raw = (row.get("alicuota_iva") or ("21" if tipo_str in ("A", "B") else "0")).replace("%", "").strip().upper()
        if "NO GRAV" in alic_raw or "NO_GRAV" in alic_raw or alic_raw == "NG":
            tipo_iva = "no_gravado"
            alic_id = 1
            alic_iva = 0.0
        elif "EXENT" in alic_raw or alic_raw == "EX":
            tipo_iva = "exento"
            alic_id = 2
            alic_iva = 0.0
        elif alic_raw in ("0", "0.0", "0,0"):
            tipo_iva = "iva"
            alic_id = 3
            alic_iva = 0.0
        elif "10.5" in alic_raw or "10,5" in alic_raw:
            tipo_iva = "iva"
            alic_id = 4
            alic_iva = 10.5
        elif "27" in alic_raw:
            tipo_iva = "iva"
            alic_id = 6
            alic_iva = 27.0
        elif "5" in alic_raw and "2.5" not in alic_raw and "10.5" not in alic_raw and "2,5" not in alic_raw and "10,5" not in alic_raw:
            tipo_iva = "iva"
            alic_id = 8
            alic_iva = 5.0
        elif "2.5" in alic_raw or "2,5" in alic_raw:
            tipo_iva = "iva"
            alic_id = 9
            alic_iva = 2.5
        else:
            try:
                val = float(alic_raw.replace(",", "."))
                if val == 0.0:
                    tipo_iva = "iva"
                    alic_id = 3
                    alic_iva = 0.0
                else:
                    tipo_iva = "iva"
                    alic_id = 5
                    alic_iva = val
            except Exception:
                tipo_iva = "iva"
                alic_id = 5 if tipo_str in ("A", "B") else 3
                alic_iva = 21.0 if tipo_str in ("A", "B") else 0.0

        # Condición IVA
        cond_raw = (row.get("condicion_iva") or ("RI" if tipo_str == "A" else "CF")).strip().upper()
        if "RESPONSIBLE" in cond_raw or "INSCRIPTO" in cond_raw:
            cond_id = 1
        elif "EXENTO" in cond_raw:
            cond_id = 4
        elif "MONOTRIBUT" in cond_raw:
            cond_id = 6
        else:
            try:
                cond_id = COND_IVA_ALIAS.get(cond_raw, int(cond_raw) if cond_raw.isdigit() else 5)
            except Exception:
                cond_id = 5

        # Fechas y condición de venta
        f_emision = _parse_date_afip(row.get("fecha"))
        f_vto = _parse_date_afip(row.get("fecha_vto_pago"))
        f_desde = _parse_date_afip(row.get("periodo_desde"))
        f_hasta = _parse_date_afip(row.get("periodo_hasta"))
        cond_venta = (row.get("condicion_venta") or "Contado").strip()

        # Validaciones de la fila
        errors = []
        warnings = []

        if monto <= 0:
            errors.append("El importe debe ser mayor a 0.")

        try:
            doc_tipo, doc_nro = _parse_doc(cuit_raw)
        except ValueError:
            doc_tipo, doc_nro = 99, "0"
            errors.append(f"Documento '{cuit_raw}' inválido.")

        if tipo_str == "A":
            if doc_tipo != 80:
                errors.append("Factura A requiere CUIT de 11 dígitos.")
            else:
                ok, err = validar_formato_cuit(doc_nro)
                if not ok:
                    errors.append(err)

        if not nombre:
            if doc_tipo == 99:
                nombre = "Consumidor Final"
            else:
                warnings.append("Sin nombre: se consultará el padrón al emitir.")

        status = "error" if errors else ("advertencia" if warnings else "valido")

        # Cálculos neto/IVA
        if tipo_str in ("A", "B"):
            if tipo_iva in ("no_gravado", "exento") or alic_id == 3 or alic_iva == 0.0:
                neto = monto
                iva = 0.0
            else:
                neto = round(monto / (1 + (alic_iva / 100)), 2)
                iva = round(monto - neto, 2)
        else:
            neto = monto
            iva = 0.0

        if tipo_str == "A": totales["tipo_a"] += 1
        elif tipo_str == "B": totales["tipo_b"] += 1
        else: totales["tipo_c"] += 1

        totales["count"] += 1
        totales["monto"] += monto
        if status == "error":
            totales["errores"] += 1
        else:
            totales["validos"] += 1

        # Chequear si ya existe emitido previamente
        monto_dec_str = str(Decimal(str(monto)).quantize(Decimal("0.01")))
        cuit_check = str(doc_nro).strip().replace("-", "")
        exist_key = f"{cuit_check}_{cbte_tipo}_{monto_dec_str}"
        exist_info = existing_map.get(exist_key)

        cae_val = None
        cbte_val = None
        pdf_val = None
        if exist_info:
            cae_val = exist_info.get("cae")
            cbte_val = exist_info.get("comprobante")
            pdf_val = exist_info.get("pdf_filename")
            status = "emitido"
            warnings.append(f"Ya emitido: Comprobante {cbte_val} (CAE: {cae_val})")

        rows.append({
            "index": raw_row.get("INDEX") or idx,
            "tipo": tipo_str,
            "cbte_tipo": cbte_tipo,
            "cuit_cliente": cuit_raw,
            "doc_tipo": doc_tipo,
            "doc_nro": doc_nro,
            "nombre_cliente": nombre or "Consumidor Final",
            "domicilio_cliente": domicilio or None,
            "concepto": concepto,
            "monto": monto,
            "neto": neto,
            "iva": iva,
            "alicuota_iva": alic_iva,
            "alicuota_iva_id": alic_id,
            "tipo_iva": tipo_iva,
            "condicion_iva_receptor": cond_id,
            "condicion_venta": cond_venta,
            "concepto_afip": 2,
            "fecha": f_emision,
            "periodo_desde": f_desde,
            "periodo_hasta": f_hasta,
            "fecha_vto_pago": f_vto,
            "cae": cae_val,
            "comprobante": cbte_val,
            "pdf_filename": pdf_val,
            "status": status,
            "errors": errors,
            "warnings": warnings,
        })

    return {
        "status": "ok",
        "totales": totales,
        "rows": rows,
    }


@app.post("/api/lotes/emitir")
def emitir_lote(payload: LoteEmitirIn):
    """Emite un lote de comprobantes validados previamente a AFIP."""
    target_env = payload.env or payload.environment or os.getenv("AFIP_ENV", "homo").lower()

    try:
        cfg = load_config(env=target_env, dry_run=payload.dry_run)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token, sign = (None, None)
    if not payload.dry_run:
        try:
            token, sign = get_token_sign(cfg)
        except Exception as e:
            raise HTTPException(status_code=400, detail=_format_afip_error(e))

    lote_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    resultados = []
    exitosos = 0
    fallidos = 0
    ult_cache = {}
    hoy_dt = date.today()
    min_permitida = hoy_dt - timedelta(days=10)
    max_permitida = hoy_dt + timedelta(days=10)

    # Ordenar cronológicamente por fecha de emisión para respetar la regla de AFIP (CbteFch_N >= CbteFch_{N-1})
    def _row_date_key(it):
        f = getattr(it, "fecha", None) or hoy_dt.strftime("%Y%m%d")
        f_clean = str(f).replace("-", "").replace("/", "")
        try:
            idx_num = int(getattr(it, "index", 0))
        except Exception:
            idx_num = 0
        return (f_clean, idx_num)

    sorted_rows = sorted(payload.rows, key=_row_date_key)

    for item in sorted_rows:
        # Si ya fue autorizado con éxito, no duplicar emisión
        if item.cae and str(item.cae).strip() and not payload.dry_run:
            resultados.append({
                "index": item.index,
                "status": "ok",
                "tipo": item.tipo,
                "comprobante": item.comprobante or "",
                "cae": item.cae,
                "monto": str(item.monto),
                "cliente": item.nombre_cliente,
                "mensaje": "Comprobante ya autorizado previamente",
            })
            exitosos += 1
            continue
        try:
            monto_dec = Decimal(str(item.monto)).quantize(Decimal("0.01"))
            doc_tipo, doc_nro = _parse_doc(item.cuit_cliente)
            hoy = date.today().strftime("%Y%m%d")

            # Crear ítem
            alic_dec = Decimal(str(item.alicuota_iva)).quantize(Decimal("0.1"))
            tipo_it = getattr(item, "tipo_iva", None) or ("no_gravado" if getattr(item, "alicuota_iva_id", 5) == 1 else "exento" if getattr(item, "alicuota_iva_id", 5) == 2 else "iva")
            alic_id = getattr(item, "alicuota_iva_id", None) or (1 if tipo_it == "no_gravado" else 2 if tipo_it == "exento" else 3 if alic_dec == Decimal("0.0") else 5)
            
            # Items según tipo de comprobante:
            if item.cbte_tipo == 1:
                # Factura A: monto del CSV es total, precio unitario de item es NETO
                if tipo_it in ("no_gravado", "exento") or alic_id in (1, 2, 3) or alic_dec == Decimal("0.0"):
                    neto_dec = monto_dec
                    items_obj = [InvoiceItem(descripcion=item.concepto, cantidad=Decimal("1.00"), precio_unitario=neto_dec, alicuota_iva=Decimal("0.0"), alicuota_iva_id=alic_id, tipo_iva=tipo_it)]
                else:
                    neto_dec = (monto_dec / (Decimal("1.00") + (alic_dec / Decimal("100")))).quantize(Decimal("0.01"))
                    items_obj = [InvoiceItem(descripcion=item.concepto, cantidad=Decimal("1.00"), precio_unitario=neto_dec, alicuota_iva=alic_dec, alicuota_iva_id=alic_id, tipo_iva=tipo_it)]
            elif item.cbte_tipo == 6:
                # Factura B: monto del CSV es FINAL con IVA, precio unitario de item es FINAL con IVA
                items_obj = [InvoiceItem(descripcion=item.concepto, cantidad=Decimal("1.00"), precio_unitario=monto_dec, alicuota_iva=alic_dec, alicuota_iva_id=alic_id, tipo_iva=tipo_it)]
            else:
                # Factura C: monto es final sin IVA
                items_obj = [InvoiceItem(descripcion=item.concepto, cantidad=Decimal("1.00"), precio_unitario=monto_dec, alicuota_iva=Decimal("0.0"), alicuota_iva_id=3, tipo_iva="iva")]

            if payload.dry_run:
                pv = cfg.punto_venta or 4
                letra = CBTE_LETRA.get(item.cbte_tipo, "C").lower()
                pdf_name = format_pdf_filename(item.nombre_cliente, fecha=item.fecha or hoy, directory=COMPROBANTES_DIR)
                pdf_path = COMPROBANTES_DIR / pdf_name

                # Generar comprobante PDF simulado de prueba
                serv_desde = item.periodo_desde or (hoy[:6] + "01")
                serv_hasta = item.periodo_hasta or hoy
                vto_pago = item.fecha_vto_pago or (item.fecha or hoy)

                domicilio_item = getattr(item, "domicilio_cliente", None)
                if not domicilio_item and doc_tipo == 80 and not payload.dry_run:
                    try:
                        p_info = buscar_persona(cfg, doc_nro)
                        if p_info and p_info.get("domicilio"):
                            domicilio_item = p_info["domicilio"]
                    except Exception:
                        pass

                resp_sim = InvoiceResponse(
                    cae="SIMULADO_CAE_123456",
                    cae_vencimiento=(hoy_dt + timedelta(days=10)).strftime("%Y%m%d"),
                    numero=int(item.index) if str(item.index).isdigit() else 9999,
                    cbte_tipo=item.cbte_tipo,
                    punto_venta=pv,
                    fecha=item.fecha or hoy,
                    monto=monto_dec,
                    nombre_cliente=item.nombre_cliente,
                    cuit_cliente=doc_nro,
                    domicilio_cliente=domicilio_item,
                    resultado="A",
                    doc_tipo=doc_tipo,
                    condicion_iva_receptor=item.condicion_iva_receptor,
                    condicion_venta=item.condicion_venta or "Contado",
                    periodo_desde=serv_desde,
                    periodo_hasta=serv_hasta,
                    hora=datetime.now().strftime("%H%M%S"),
                    fecha_vto_pago=vto_pago,
                    items=items_obj,
                    imp_neto=monto_dec if item.cbte_tipo not in (1, 6) or alic_dec == Decimal("0.0") else neto_dec,
                    imp_iva=Decimal("0.00") if item.cbte_tipo not in (1, 6) or alic_dec == Decimal("0.0") else (monto_dec - neto_dec),
                )
                generate_pdf(cfg, resp_sim, str(pdf_path), duplicado=payload.duplicado, triplicado=getattr(payload, 'triplicado', False), copias=getattr(payload, 'copias', 1))

                resp_dict = resp_sim.to_json()
                resp_dict["pdf_filename"] = pdf_name
                with open(COMPROBANTES_DIR / f"comprobante_{letra}_{pv:04d}_sim_{item.index:04d}.json", "w", encoding="utf-8") as f:
                    json.dump(resp_dict, f, ensure_ascii=False)

                resultados.append({
                    "index": item.index,
                    "status": "ok",
                    "modo": "simulacion",
                    "tipo": item.tipo,
                    "comprobante": f"{pv:04d}-SIM{item.index:04d}",
                    "cae": "SIMULADO_CAE_123456",
                    "cae_vencimiento": (hoy_dt + timedelta(days=10)).strftime("%Y%m%d"),
                    "monto": str(monto_dec),
                    "cliente": item.nombre_cliente,
                    "pdf_filename": pdf_name,
                    "url": f"/api/pdf/{pdf_name}",
                })
                exitosos += 1
                continue

            # Modo Real AFIP
            cbte_tipo = item.cbte_tipo
            if cbte_tipo not in ult_cache:
                nro, fch = get_ultimo_comprobante_info(cfg, token, sign, cbte_tipo)
                ult_cache[cbte_tipo] = {"nro": nro, "fecha": fch}

            proximo_nro = ult_cache[cbte_tipo]["nro"] + 1

            # Resolución estricta de fecha para cumplir con las reglas de AFIP:
            # 1. Ventana N-10 a N+10 de hoy
            # 2. CbteFch >= fecha del último comprobante emitido
            try:
                dt_deseada = datetime.strptime(item.fecha, "%Y%m%d").date() if item.fecha else hoy_dt
            except Exception:
                dt_deseada = hoy_dt

            if dt_deseada > max_permitida:
                dt_calc = max_permitida
            elif dt_deseada < min_permitida:
                dt_calc = hoy_dt
            else:
                dt_calc = dt_deseada

            ult_fch_str = ult_cache[cbte_tipo]["fecha"]
            if ult_fch_str:
                try:
                    dt_ult = datetime.strptime(ult_fch_str, "%Y%m%d").date()
                    if dt_calc < dt_ult:
                        dt_calc = dt_ult
                except Exception:
                    pass

            fecha_emision = dt_calc.strftime("%Y%m%d")
            serv_desde = item.periodo_desde or (hoy[:6] + "01")
            serv_hasta = item.periodo_hasta or hoy
            vto_pago = item.fecha_vto_pago or fecha_emision
            if vto_pago < fecha_emision:
                vto_pago = fecha_emision

            req = InvoiceRequest(
                cbte_tipo=item.cbte_tipo,
                cuit_cliente=doc_nro,
                nombre_cliente=item.nombre_cliente,
                monto=monto_dec,
                concepto=item.concepto,
                concepto_afip=item.concepto_afip,
                numero=proximo_nro,
                fecha=fecha_emision,
                fecha_serv_desde=serv_desde,
                fecha_serv_hasta=serv_hasta,
                fecha_vto_pago=vto_pago,
                doc_tipo=doc_tipo,
                doc_nro=doc_nro,
                condicion_iva_receptor=item.condicion_iva_receptor,
                condicion_venta=item.condicion_venta or "Contado",
                items=items_obj,
            )

            resp = solicitar_cae(cfg, token, sign, req)
            ult_cache[cbte_tipo] = {"nro": resp.numero, "fecha": resp.fecha}
            resp.hora = datetime.now().strftime("%H%M%S")
            resp.fecha_vto_pago = hoy

            # Generar PDF
            letra = CBTE_LETRA.get(resp.cbte_tipo, "C").lower()
            pdf_name = format_pdf_filename(resp.nombre_cliente, fecha=resp.fecha, hora=resp.hora, directory=COMPROBANTES_DIR)
            generate_pdf(cfg, resp, str(COMPROBANTES_DIR / pdf_name), duplicado=payload.duplicado, triplicado=getattr(payload, 'triplicado', False), copias=getattr(payload, 'copias', 1))

            resp_dict = resp.to_json()
            resp_dict["pdf_filename"] = pdf_name
            with open(COMPROBANTES_DIR / f"comprobante_{letra}_{resp.punto_venta:04d}_{resp.numero:08d}.json", "w") as f:
                json.dump(resp_dict, f, ensure_ascii=False)

            resultados.append({
                "index": item.index,
                "status": "ok",
                "tipo": item.tipo,
                "comprobante": f"{resp.punto_venta:04d}-{resp.numero:08d}",
                "cae": resp.cae,
                "cae_vencimiento": resp.cae_vencimiento,
                "monto": str(resp.monto),
                "cliente": resp.nombre_cliente,
                "pdf_filename": pdf_name,
            })
            exitosos += 1

        except Exception as e:
            if "cbte_tipo" in locals() and cbte_tipo in ult_cache:
                ult_cache.pop(cbte_tipo, None)
            resultados.append({
                "index": item.index,
                "status": "error",
                "tipo": item.tipo,
                "cliente": item.nombre_cliente,
                "monto": str(item.monto),
                "error": str(e),
            })
            fallidos += 1

    # Guardar resumen del lote
    lote_meta = {
        "lote_id": lote_id,
        "env": target_env,
        "dry_run": payload.dry_run,
        "total": len(payload.rows),
        "exitosos": exitosos,
        "fallidos": fallidos,
        "resultados": resultados,
    }
    with open(COMPROBANTES_DIR / f"lote_{lote_id}.json", "w", encoding="utf-8") as f:
        json.dump(lote_meta, f, ensure_ascii=False, indent=2)

    return lote_meta


@app.get("/api/lotes/download-zip/{lote_id}")
def download_lote_zip(lote_id: str):
    """Empaqueta en un archivo ZIP todos los PDFs generados de un lote para su descarga."""
    lote_json_path = COMPROBANTES_DIR / f"lote_{lote_id}.json"
    if not lote_json_path.exists():
        raise HTTPException(status_code=404, detail="Lote no encontrado.")

    with open(lote_json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for res in meta.get("resultados", []):
            if res.get("status") == "ok" and res.get("pdf_filename"):
                pdf_path = COMPROBANTES_DIR / res["pdf_filename"]
                if pdf_path.exists():
                    zip_file.write(pdf_path, arcname=res["pdf_filename"])

    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=comprobantes_lote_{lote_id}.zip"},
    )


# ── CUSTOMIZACIÓN Y PREVIEW PDF DE PRUEBA ─────────────────────────────────────


@app.post("/api/pdf/preview-sample")
def preview_sample_pdf(payload: Optional[PreviewSampleIn] = None):
    """Genera un comprobante de prueba de ejemplo con el logo, watermark y leyenda configurados."""
    try:
        cfg = load_config(env="homo", dry_run=True)
    except Exception:
        cfg = Config(cuit="23255684779", cert_path="", key_path="", punto_venta=4, token_cache_path="", wsdl_cache_path="", env="homo", dry_run=True)

    if payload:
        if payload.razon_social is not None:
            cfg.razon_social = payload.razon_social
        if payload.domicilio is not None:
            cfg.domicilio = payload.domicilio
        if payload.condicion_iva_emisor is not None:
            cfg.condicion_iva_emisor = payload.condicion_iva_emisor
        if payload.logo_path is not None:
            cfg.logo_path = payload.logo_path
        if payload.ingresos_brutos is not None:
            cfg.ingresos_brutos = payload.ingresos_brutos
        if payload.inicio_actividades is not None:
            cfg.inicio_actividades = payload.inicio_actividades
        if payload.leyenda is not None:
            cfg.leyenda = payload.leyenda
        if payload.watermark_text is not None:
            cfg.watermark_text = payload.watermark_text
        if payload.watermark_image is not None:
            cfg.watermark_image = payload.watermark_image

    items = [
        InvoiceItem(descripcion="Servicio de Desarrollo de Software y APIs", cantidad=Decimal("1.00"), precio_unitario=Decimal("85000.00"), alicuota_iva=Decimal("21.0"), alicuota_iva_id=5),
        InvoiceItem(descripcion="Mantenimiento preventivo mensual", cantidad=Decimal("1.00"), precio_unitario=Decimal("25000.00"), alicuota_iva=Decimal("21.0"), alicuota_iva_id=5),
    ]
    subtotal_neto = sum(i.subtotal for i in items)
    iva_total = sum(i.iva_monto for i in items)
    monto_total = subtotal_neto + iva_total

    is_monotributo = any(m in (cfg.condicion_iva_emisor or "").lower() for m in ["monotribut", "exento", "no alcanzado", "eventual"])
    if payload and payload.cbte_tipo:
        preview_tipo = payload.cbte_tipo
    else:
        preview_tipo = 11 if is_monotributo else 6 # Factura C o Factura B a Consumidor Final
    preview_cliente = "CONSUMIDOR FINAL EJEMPLO"
    preview_cuit = "0"
    preview_doc_tipo = 99
    preview_cond_rec = 5

    sample_resp = InvoiceResponse(
        cae="74251829304918",
        cae_vencimiento=date.today().strftime("%Y%m%d"),
        numero=9999,
        cbte_tipo=preview_tipo,
        punto_venta=cfg.punto_venta or 4,
        fecha=date.today().strftime("%Y%m%d"),
        monto=monto_total,
        nombre_cliente=preview_cliente,
        cuit_cliente=preview_cuit,
        resultado="A",
        doc_tipo=preview_doc_tipo,
        condicion_iva_receptor=preview_cond_rec,
        items=items,
        imp_neto=subtotal_neto,
        imp_iva=iva_total if not is_monotributo else Decimal("0.00"),
        ivas=[{"Id": 5, "BaseImp": str(subtotal_neto), "Importe": str(iva_total)}] if not is_monotributo else [],
        hora="123045",
        periodo_desde=date.today().replace(day=1).strftime("%Y%m%d"),
        periodo_hasta=date.today().strftime("%Y%m%d"),
    )

    sample_pdf_path = COMPROBANTES_DIR / "sample_preview.pdf"
    generate_pdf(cfg, sample_resp, str(sample_pdf_path), duplicado=False)

    return {
        "status": "ok",
        "pdf_filename": "sample_preview.pdf",
        "url": f"/api/pdf/sample_preview.pdf?t={int(time.time())}",
    }


# ── HISTORIAL Y CONSULTA ──────────────────────────────────────────────────────


@app.get("/api/comprobantes/consultar/{cbte_tipo}/{numero}")
def get_comprobante_afip(cbte_tipo: int, numero: int, env: Optional[str] = Query(None)):
    """Consulta los datos de un comprobante emitido directamente en AFIP."""
    target_env = env or os.getenv("AFIP_ENV", "homo").lower()
    try:
        cfg = load_config(env=target_env, dry_run=False)
        token, sign = get_token_sign(cfg)
        data = consultar_comprobante(cfg, token, sign, cbte_tipo, numero)
        data["tipo_nombre"] = CBTE_NOMBRE.get(cbte_tipo, str(cbte_tipo))
        data["letra"] = CBTE_LETRA.get(cbte_tipo, "C")
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=_format_afip_error(e))


@app.get("/api/comprobantes/historial")
def list_historial():
    """Lista todos los comprobantes emitidos guardados localmente."""
    historial = []
    for json_file in sorted(COMPROBANTES_DIR.glob("*.json"), reverse=True):
        if json_file.name.startswith("lote_"):
            continue
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                historial.append(data)
        except Exception:
            continue

    if not historial:
        for pdf_file in sorted(BASE_DIR.glob("factura_*.pdf"), reverse=True):
            historial.append({
                "comprobante": pdf_file.stem.replace("factura_", ""),
                "pdf_filename": pdf_file.name,
                "fecha": "",
                "monto": "",
                "cliente": "Consumidor Final",
                "tipo": "Factura C",
            })

    return historial


@app.post("/api/comprobantes/reimprimir")
def reimprimir_comprobante(payload: ReimprimirIn, env: Optional[str] = Query(None)):
    """Reimprime el PDF consultando el comprobante en AFIP."""
    target_env = env or os.getenv("AFIP_ENV", "homo").lower()
    try:
        cfg = load_config(env=target_env, dry_run=False)
        token, sign = get_token_sign(cfg)
        data = consultar_comprobante(cfg, token, sign, payload.cbte_tipo, payload.numero)

        nombre_cliente = "Consumidor Final"
        if data.get("doc_nro") and data["doc_nro"] != "0":
            try:
                p = buscar_persona(cfg, data["doc_nro"])
                if p and p.get("nombre"):
                    nombre_cliente = p["nombre"]
            except Exception:
                pass

        resp = InvoiceResponse(
            cae=data["cae"],
            cae_vencimiento=data["cae_vencimiento"],
            numero=data["numero"],
            cbte_tipo=data["cbte_tipo"],
            punto_venta=data["punto_venta"],
            fecha=data["fecha"],
            monto=Decimal(data["monto"]),
            nombre_cliente=nombre_cliente,
            cuit_cliente=data["doc_nro"],
            resultado=data.get("resultado", "A"),
            doc_tipo=data.get("doc_tipo", 99),
            condicion_iva_receptor=data.get("condicion_iva_receptor", 5),
            periodo_desde=data.get("periodo_desde"),
            periodo_hasta=data.get("periodo_hasta"),
            hora=data.get("hora"),
        )

        letra = CBTE_LETRA.get(resp.cbte_tipo, "C").lower()
        json_path = COMPROBANTES_DIR / f"comprobante_{letra}_{resp.punto_venta:04d}_{resp.numero:08d}.json"
        existing_pdf = None
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    existing_pdf = d.get("pdf_filename")
            except Exception:
                pass

        if existing_pdf:
            pdf_filename = existing_pdf
        else:
            pdf_filename = format_pdf_filename(nombre_cliente, fecha=resp.fecha, hora=resp.hora, directory=COMPROBANTES_DIR)

        pdf_path = COMPROBANTES_DIR / pdf_filename

        generate_pdf(cfg, resp, str(pdf_path), duplicado=payload.duplicado, triplicado=getattr(payload, 'triplicado', False), copias=getattr(payload, 'copias', 1))

        return {
            "status": "ok",
            "pdf_filename": pdf_filename,
            "url": f"/api/pdf/{pdf_filename}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reimprimiendo: {e}")


@app.get("/api/pdf/{filename}")
def serve_pdf(filename: str):
    """Sirve el PDF para previsualización e impresión inline en navegador."""
    clean_name = os.path.basename(filename)
    if not clean_name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Formato de archivo inválido.")

    possible_paths = [
        COMPROBANTES_DIR / clean_name,
        BASE_DIR / clean_name,
    ]

    for p in possible_paths:
        if p.exists():
            return FileResponse(
                path=str(p),
                media_type="application/pdf",
                headers={"Content-Disposition": f"inline; filename={clean_name}"},
            )

    raise HTTPException(status_code=404, detail="Archivo PDF no encontrado.")


@app.get("/api/comprobantes/download-pdf/{filename}")
def download_comprobante_pdf(filename: str):
    """Descarga el comprobante PDF como attachment."""
    clean_name = os.path.basename(filename)
    if not clean_name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Formato de archivo inválido.")

    possible_paths = [
        COMPROBANTES_DIR / clean_name,
        BASE_DIR / clean_name,
    ]

    for p in possible_paths:
        if p.exists():
            return FileResponse(
                path=str(p),
                media_type="application/pdf",
                filename=clean_name,
                headers={"Content-Disposition": f'attachment; filename="{clean_name}"'},
            )

    raise HTTPException(status_code=404, detail="Archivo PDF no encontrado.")


# ── GENERACIÓN CSR ────────────────────────────────────────────────────────────


@app.post("/api/config/generar-csr")
def api_generar_csr(payload: CsrIn):
    """Asistente para generar clave RSA y CSR para dar de alta en AFIP."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cuit_clean = payload.cuit.strip().replace("-", "").replace(" ", "")
    ok, err = validar_formato_cuit(cuit_clean)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    CERTS_DIR.mkdir(exist_ok=True)
    key_path = CERTS_DIR / f"afip_{cuit_clean}.key"
    csr_path = CERTS_DIR / f"afip_{cuit_clean}.csr"

    clave = rsa.generate_private_key(
        public_exponent=65537,
        key_size=payload.bits,
    )

    with open(key_path, "wb") as f:
        f.write(
            clave.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass

    dn = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, payload.razon_social.strip()),
        x509.NameAttribute(NameOID.COMMON_NAME, cuit_clean),
    ])

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(dn)
        .sign(clave, hashes.SHA256())
    )

    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    with open(csr_path, "w", encoding="utf-8") as f:
        f.write(csr_pem)

    return {
        "status": "ok",
        "key_path": str(key_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "csr_path": str(csr_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "csr_content": csr_pem,
        "cuit": cuit_clean,
        "razon_social": payload.razon_social,
        "bits": payload.bits,
    }
