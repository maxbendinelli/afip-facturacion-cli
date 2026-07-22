#!/usr/bin/env python3
"""
Servidor MCP (Model Context Protocol) para AFIP / ARCA Facturación Electrónica CLI.

Permite a cualquier cliente o agente de IA interactuar directamente con los servicios
web de AFIP (WSFEv1 y Padrón A13) a través de herramientas (tools) tipadas.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from mcp.server.fastmcp import FastMCP

from config import ConfigError, load_config
from models import CBTE_TIPO, COND_IVA_NOMBRE, InvoiceItem, InvoiceRequest
from padron import buscar_persona
from validators import validar_cuit_afip, validar_formato_cuit
from wsaa import get_token_sign
from wsfev1 import buscar_rango, consultar_comprobante, get_ultimo_numero, solicitar_cae

mcp = FastMCP(
    "afip-facturacion",
    instructions="Servidor MCP para emisión de Facturas C, Notas de Crédito/Débito y consulta de Padrón A13 de AFIP/ARCA.",
)


def _last_day_of_month(d: date) -> date:
    next_month = d.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def _parse_doc(raw: str) -> tuple[int, str]:
    digits = raw.strip().replace("-", "").replace(" ", "")
    if digits.isdigit() and len(digits) == 11:
        return 80, digits
    if digits.isdigit() and len(digits) in (7, 8):
        return 96, digits
    if raw.strip().upper() in ("SIN_CUIT", "0", ""):
        return 99, "0"
    raise ValueError(f"Formato de documento inválido: '{raw}'")


def _parse_condicion_iva(raw: str) -> int:
    from facturar import _parse_condicion_iva as parse_iva
    return parse_iva(raw)


def _inferir_condicion_iva(config: Any, doc_tipo: int, doc_nro: str, datos_padron: dict | None) -> int:
    from facturar import _inferir_condicion_iva as infer_iva
    return infer_iva(config, doc_tipo, doc_nro, datos_padron)


@mcp.tool()
def emitir_factura(
    monto: float | None = None,
    concepto: str = "Servicio de consultoría",
    cuit_cliente: str = "0",
    condicion_iva: str | None = None,
    nombre_cliente: str | None = None,
    items: list[dict[str, Any]] | None = None,
    env: str = "homo",
    generar_pdf: bool = True,
    duplicado_pdf: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Emite una Factura C en AFIP/ARCA (vía WSFEv1).

    Args:
        monto: Monto total de la factura (si se especifican items, se calcula automáticamente).
        concepto: Descripción general del concepto facturado.
        cuit_cliente: CUIT/DNI del receptor o "0" para Consumidor Final sin identificar.
        condicion_iva: Condición IVA del receptor (ej: "CF", "RI", "MONO", "EX", o ID numérico 1-14).
        nombre_cliente: Nombre/Razón social del receptor (si se omite, se busca automáticamente en Padrón A13).
        items: Lista de ítems detallados: [{"descripcion": "Producto", "cantidad": 1, "precio_unitario": 1000}].
        env: Ambiente AFIP ("homo" para pruebas / "prod" para producción real).
        generar_pdf: Si es True, genera el archivo PDF oficial.
        duplicado_pdf: Si es True, genera el PDF con la sección DUPLICADO.
        dry_run: Modo simulación sin enviar la solicitud real a AFIP.
    """
    config = load_config(env, dry_run)

    # Parsear ítems
    parsed_items: list[InvoiceItem] = []
    if items:
        for it in items:
            desc = str(it.get("descripcion", "")).strip()
            qty = Decimal(str(it.get("cantidad", 1))).quantize(Decimal("0.01"))
            price = Decimal(str(it.get("precio_unitario", 0))).quantize(Decimal("0.01"))
            parsed_items.append(InvoiceItem(descripcion=desc, cantidad=qty, precio_unitario=price))

    # Calcular monto total
    if parsed_items:
        monto_dec = sum(i.subtotal for i in parsed_items)
    else:
        if monto is None:
            raise ValueError("Debe proveer 'monto' o al menos un elemento en 'items'.")
        monto_dec = Decimal(str(monto)).quantize(Decimal("0.01"))

    # Documento receptor
    doc_tipo, doc_nro = _parse_doc(cuit_cliente)

    # Validar CUIT en padrón si corresponde
    datos_padron = None
    if doc_tipo == 80:
        ok, err, datos_padron = validar_cuit_afip(config, doc_nro)
        if not ok:
            raise ValueError(f"CUIT inválido en AFIP: {err}")

    # Condición IVA
    if condicion_iva is not None:
        cond_iva_id = _parse_condicion_iva(str(condicion_iva))
    else:
        cond_iva_id = _inferir_condicion_iva(config, doc_tipo, doc_nro, datos_padron)
    cond_iva_nombre = COND_IVA_NOMBRE.get(cond_iva_id, str(cond_iva_id))

    if doc_tipo == 99 and monto_dec > config.limite_consumidor_final:
        raise ValueError(
            f"Monto ${monto_dec:,.2f} supera el límite de Consumidor Final sin identificar "
            f"(${config.limite_consumidor_final:,.2f}). Debe especificar cuit_cliente."
        )

    hoy = date.today()
    fecha_str = hoy.strftime("%Y%m%d")
    periodo_desde = hoy.replace(day=1).strftime("%Y%m%d")
    periodo_hasta = _last_day_of_month(hoy).strftime("%Y%m%d")

    # Nombre cliente
    if nombre_cliente:
        final_nombre = nombre_cliente
    elif datos_padron and datos_padron.get("nombre"):
        final_nombre = datos_padron["nombre"]
    elif doc_tipo == 99:
        final_nombre = "Consumidor Final"
    else:
        # buscar en padron
        padron_res = buscar_persona(config, doc_nro)
        final_nombre = (padron_res.get("nombre") if padron_res else "") or "Consumidor Final"

    if parsed_items and not concepto:
        final_concepto = "; ".join(i.descripcion for i in parsed_items)
    else:
        final_concepto = concepto

    if dry_run:
        return {
            "status": "dry-run-ok",
            "fields": {
                "cbte_tipo": CBTE_TIPO["C"],
                "cuit_emisor": config.cuit,
                "doc_tipo": doc_tipo,
                "doc_nro": doc_nro,
                "nombre_cliente": final_nombre,
                "condicion_iva_receptor": cond_iva_id,
                "condicion_iva_nombre": cond_iva_nombre,
                "monto_total": str(monto_dec),
                "concepto": final_concepto,
                "env": config.env,
            },
        }

    token, sign = get_token_sign(config)
    ultimo = get_ultimo_numero(config, token, sign, CBTE_TIPO["C"])

    req = InvoiceRequest(
        cbte_tipo=CBTE_TIPO["C"],
        cuit_cliente=doc_nro,
        nombre_cliente=final_nombre,
        monto=monto_dec,
        concepto=final_concepto,
        concepto_afip=2,  # Servicios
        numero=ultimo + 1,
        fecha=fecha_str,
        fecha_serv_desde=periodo_desde,
        fecha_serv_hasta=periodo_hasta,
        fecha_vto_pago=periodo_hasta,
        doc_tipo=doc_tipo,
        doc_nro=doc_nro,
        condicion_iva_receptor=cond_iva_id,
        condicion_venta="Contado",
        periodo_desde=periodo_desde,
        periodo_hasta=periodo_hasta,
        items=parsed_items,
    )

    resp = solicitar_cae(config, token, sign, req)
    resp.hora = datetime.now().strftime("%H%M%S")
    resp.fecha_vto_pago = fecha_str
    if datos_padron:
        resp.domicilio_cliente = datos_padron.get("domicilio")

    result = resp.to_json()
    result["condicion_iva_nombre"] = cond_iva_nombre

    if generar_pdf:
        from pdf_generator import generate_pdf
        pdf_path = f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
        generate_pdf(config, resp, pdf_path, duplicado=duplicado_pdf)
        result["pdf"] = pdf_path

    return result


@mcp.tool()
def emitir_nota_credito(
    numero_original: int,
    monto: float,
    env: str = "homo",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Emite una Nota de Crédito C vinculada a un comprobante previo.

    Args:
        numero_original: Número de la Factura C original a anular o devolver.
        monto: Monto a acreditar.
        env: Ambiente AFIP ("homo" o "prod").
        dry_run: Modo simulación.
    """
    config = load_config(env, dry_run)
    cbte_tipo = CBTE_TIPO["NC"]
    monto_dec = Decimal(str(monto)).quantize(Decimal("0.01"))

    hoy = date.today()
    fecha_str = hoy.strftime("%Y%m%d")
    primer_dia = hoy.replace(day=1).strftime("%Y%m%d")
    ultimo_dia = _last_day_of_month(hoy).strftime("%Y%m%d")

    if dry_run:
        return {
            "status": "dry-run-ok",
            "fields": {
                "cbte_tipo": cbte_tipo,
                "numero_original": numero_original,
                "monto": str(monto_dec),
                "env": config.env,
            },
        }

    token, sign = get_token_sign(config)
    ultimo = get_ultimo_numero(config, token, sign, cbte_tipo)

    req = InvoiceRequest(
        cbte_tipo=cbte_tipo,
        cuit_cliente=config.cuit,
        nombre_cliente="",
        monto=monto_dec,
        concepto="",
        concepto_afip=2,
        numero=ultimo + 1,
        fecha=fecha_str,
        fecha_serv_desde=primer_dia,
        fecha_serv_hasta=ultimo_dia,
        fecha_vto_pago=ultimo_dia,
        doc_tipo=80,
        doc_nro=config.cuit,
        numero_original=numero_original,
        cbte_tipo_original=CBTE_TIPO["C"],
    )

    resp = solicitar_cae(config, token, sign, req)
    return resp.to_json()


@mcp.tool()
def emitir_nota_debito(
    numero_original: int,
    monto: float,
    env: str = "homo",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Emite una Nota de Débito C vinculada a un comprobante previo.

    Args:
        numero_original: Número de la Factura C original.
        monto: Monto del recargo/débito.
        env: Ambiente AFIP ("homo" o "prod").
        dry_run: Modo simulación.
    """
    config = load_config(env, dry_run)
    cbte_tipo = CBTE_TIPO["ND"]
    monto_dec = Decimal(str(monto)).quantize(Decimal("0.01"))

    hoy = date.today()
    fecha_str = hoy.strftime("%Y%m%d")
    primer_dia = hoy.replace(day=1).strftime("%Y%m%d")
    ultimo_dia = _last_day_of_month(hoy).strftime("%Y%m%d")

    if dry_run:
        return {
            "status": "dry-run-ok",
            "fields": {
                "cbte_tipo": cbte_tipo,
                "numero_original": numero_original,
                "monto": str(monto_dec),
                "env": config.env,
            },
        }

    token, sign = get_token_sign(config)
    ultimo = get_ultimo_numero(config, token, sign, cbte_tipo)

    req = InvoiceRequest(
        cbte_tipo=cbte_tipo,
        cuit_cliente=config.cuit,
        nombre_cliente="",
        monto=monto_dec,
        concepto="",
        concepto_afip=2,
        numero=ultimo + 1,
        fecha=fecha_str,
        fecha_serv_desde=primer_dia,
        fecha_serv_hasta=ultimo_dia,
        fecha_vto_pago=ultimo_dia,
        doc_tipo=80,
        doc_nro=config.cuit,
        numero_original=numero_original,
        cbte_tipo_original=CBTE_TIPO["C"],
    )

    resp = solicitar_cae(config, token, sign, req)
    return resp.to_json()


@mcp.tool()
def consultar_ultimo_comprobante(tipo: str = "C", env: str = "homo") -> dict[str, Any]:
    """Obtiene el último número de comprobante autorizado en AFIP para un tipo determinado.

    Args:
        tipo: Tipo de comprobante ("C", "NC" o "ND").
        env: Ambiente AFIP ("homo" o "prod").
    """
    if tipo.upper() not in CBTE_TIPO:
        raise ValueError(f"Tipo de comprobante inválido: '{tipo}'. Opciones: C, NC, ND.")

    config = load_config(env, dry_run=False)
    token, sign = get_token_sign(config)

    cbte_tipo = CBTE_TIPO[tipo.upper()]
    ultimo = get_ultimo_numero(config, token, sign, cbte_tipo)
    return {
        "status": "ok",
        "tipo": tipo.upper(),
        "cbte_tipo": cbte_tipo,
        "ultimo_numero": ultimo,
        "proximo_numero": ultimo + 1,
    }


@mcp.tool()
def consultar_comprobante(
    numero: int,
    tipo: str = "C",
    env: str = "homo",
    generar_pdf: bool = False,
) -> dict[str, Any]:
    """Consulta el detalle fiscal de un comprobante emitido en AFIP.

    Args:
        numero: Número correlativo del comprobante.
        tipo: Tipo ("C", "NC" o "ND").
        env: Ambiente AFIP ("homo" o "prod").
        generar_pdf: Si es True, genera el PDF local correspondiente.
    """
    if tipo.upper() not in CBTE_TIPO:
        raise ValueError(f"Tipo de comprobante inválido: '{tipo}'. Opciones: C, NC, ND.")

    config = load_config(env, dry_run=False)
    token, sign = get_token_sign(config)

    cbte_tipo = CBTE_TIPO[tipo.upper()]
    data = consultar_comprobante(config, token, sign, cbte_tipo, numero)

    if generar_pdf:
        from pdf_generator import generate_pdf
        from models import InvoiceResponse

        resp = InvoiceResponse(
            cae=data["cae"],
            cae_vencimiento=data["cae_vencimiento"],
            numero=data["numero"],
            cbte_tipo=data["cbte_tipo"],
            punto_venta=data["punto_venta"],
            fecha=data["fecha"],
            monto=Decimal(data["monto"]),
            nombre_cliente=data.get("nombre", "Consumidor Final"),
            cuit_cliente=data.get("doc_nro", "0"),
            resultado=data.get("resultado", "A"),
            doc_tipo=data.get("doc_tipo", 99),
            condicion_venta="Contado",
            condicion_iva_receptor=data.get("condicion_iva_receptor", 5),
        )
        pdf_path = f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
        generate_pdf(config, resp, pdf_path)
        data["pdf"] = pdf_path

    return {"status": "ok", **data}


@mcp.tool()
def consultar_padron_a13(cuit: str, env: str = "homo") -> dict[str, Any]:
    """Consulta los datos fiscales completos de una persona o empresa en el Padrón A13 de AFIP.

    Args:
        cuit: Número de CUIT (con o sin guiones).
        env: Ambiente AFIP ("homo" o "prod").
    """
    config = load_config(env, dry_run=False)
    cuit_clean = cuit.strip().replace("-", "").replace(" ", "")
    datos = buscar_persona(config, cuit_clean)
    if not datos:
        return {"status": "not_found", "cuit": cuit_clean, "mensaje": "CUIT no encontrado en el padrón."}
    return {"status": "ok", **datos}


@mcp.tool()
def validar_cuit(cuit: str, consultar_afip: bool = True, env: str = "homo") -> dict[str, Any]:
    """Valida la validez de un CUIT (formato, algoritmo verificador y opcionalmente padrón AFIP).

    Args:
        cuit: Número de CUIT a validar.
        consultar_afip: Si es True, verifica la existencia en el padrón de AFIP.
        env: Ambiente AFIP ("homo" o "prod").
    """
    cuit_clean = cuit.strip().replace("-", "").replace(" ", "")
    ok, err = validar_formato_cuit(cuit_clean)
    if not ok:
        return {"valido": False, "cuit": cuit_clean, "error": err}

    if consultar_afip:
        config = load_config(env, dry_run=True)
        ok_afip, warn, datos = validar_cuit_afip(config, cuit_clean)
        res = {"valido": ok_afip, "cuit": cuit_clean}
        if warn:
            res["advertencia"] = warn
        if datos:
            res["datos"] = datos
        return res

    return {"valido": True, "cuit": cuit_clean, "formato": "ok"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Servidor MCP para Facturación AFIP/ARCA")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Tipo de transporte MCP: 'stdio' (para IDEs y agentes locales) o 'sse' (servidor HTTP / SSE)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
