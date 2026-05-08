#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from config import ConfigError, load_config
from models import CBTE_TIPO, InvoiceItem, InvoiceRequest


def _last_day_of_month(d: date) -> date:
    next_month = d.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def _parse_doc(raw: str) -> tuple[int, str]:
    digits = raw.strip().replace("-", "").replace(" ", "")
    if digits.isdigit() and len(digits) == 11:
        return 80, digits
    if digits.isdigit() and len(digits) in (7, 8):
        return 96, digits
    if raw.strip().upper() in ("SIN_CUIT", ""):
        return 99, "0"
    raise ValueError(f"Formato de documento inválido: '{raw}'")


def _parse_item(raw: str) -> InvoiceItem:
    """Parsea 'descripcion|cantidad|precio_unitario'."""
    parts = raw.split("|")
    if len(parts) != 3:
        raise ValueError(
            f"Formato de ítem inválido: '{raw}'. Use: 'Descripción|Cantidad|PrecioUnitario'"
        )
    desc, qty_s, price_s = parts
    try:
        qty = Decimal(qty_s.strip()).quantize(Decimal("0.01"))
        price = Decimal(price_s.strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"Cantidad o precio inválido en ítem: '{raw}'")
    if qty <= 0 or price <= 0:
        raise ValueError(f"Cantidad y precio deben ser mayores a cero en ítem: '{raw}'")
    return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price)


def _output(data: dict, exit_code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(exit_code)


def _resolver_nombre(config, doc_tipo: int, doc_nro: str, nombre_arg: str | None) -> tuple[str, dict | None]:
    """Resuelve el nombre del receptor. Retorna (nombre, datos_padron)."""
    if nombre_arg:
        return nombre_arg, None
    if doc_tipo == 99:
        return "Consumidor Final", None
    if doc_tipo in (80, 96) and doc_nro != "0":
        try:
            from padron import buscar_persona
            datos = buscar_persona(config, doc_nro)
            if datos and datos.get("nombre"):
                return datos["nombre"], datos
        except RuntimeError as e:
            sys.stderr.write(f"Advertencia padrón: {e}\n")
        except Exception:
            pass
    return "", None


def cmd_emitir(args) -> None:
    try:
        config = load_config(args.env, args.dry_run)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    # Parsear ítems
    items = []
    if args.item:
        for raw in args.item:
            try:
                items.append(_parse_item(raw))
            except ValueError as e:
                _output({"error": str(e)}, 1)

    # Calcular monto
    if items:
        monto = sum(i.subtotal for i in items)
    else:
        if args.monto is None:
            _output({"error": "Debe proveer --monto o al menos un --item."}, 1)
        try:
            monto = Decimal(str(args.monto)).quantize(Decimal("0.01"))
        except InvalidOperation:
            _output({"error": f"Monto inválido: '{args.monto}'"}, 1)

    # Parsear documento receptor
    try:
        doc_tipo, doc_nro = _parse_doc(args.cuit_cliente)
    except ValueError as e:
        _output({"error": str(e)}, 1)

    # Validar CUIT si corresponde
    if doc_tipo == 80:
        from validators import validar_cuit_afip
        ok, err, datos_padron = validar_cuit_afip(config, doc_nro)
        if not ok:
            _output({"error": f"CUIT inválido: {err}"}, 1)
        if err:  # advertencia no bloqueante
            sys.stderr.write(f"Advertencia: {err}\n")
    else:
        datos_padron = None

    # Validar límite consumidor final
    if doc_tipo == 99 and monto > config.limite_consumidor_final:
        _output({
            "error": (
                f"Monto ${monto:,.2f} supera el límite para Consumidor Final "
                f"(${config.limite_consumidor_final:,.2f}). "
                "Debe proveer el CUIT del receptor con --cuit-cliente."
            )
        }, 1)

    hoy = date.today()
    fecha = args.fecha or hoy.strftime("%Y%m%d")

    if args.periodo_desde:
        periodo_desde = args.periodo_desde
        periodo_hasta = args.periodo_hasta or _last_day_of_month(hoy).strftime("%Y%m%d")
    else:
        periodo_desde = hoy.replace(day=1).strftime("%Y%m%d")
        periodo_hasta = _last_day_of_month(hoy).strftime("%Y%m%d")

    concepto_afip = args.concepto_afip
    condicion_venta = args.condicion_venta

    # Resolver nombre (usa padrón A13 si ya obtuvimos datos; si no, busca)
    if datos_padron and datos_padron.get("nombre"):
        nombre_cliente = args.nombre_cliente or datos_padron["nombre"]
    else:
        nombre_cliente, _ = _resolver_nombre(config, doc_tipo, doc_nro, args.nombre_cliente)

    if not nombre_cliente:
        _output({"error": "No se pudo determinar el nombre del receptor. Use --nombre-cliente."}, 1)

    # Concepto: si hay ítems, usar sus descripciones; si no, usar --concepto
    if items and not args.concepto:
        concepto = "; ".join(i.descripcion for i in items)
    elif args.concepto:
        concepto = args.concepto
    else:
        _output({"error": "Debe proveer --concepto o al menos un --item."}, 1)

    if args.dry_run:
        _output({
            "status": "dry-run-ok",
            "fields": {
                "cbte_tipo": CBTE_TIPO["C"],
                "cuit_emisor": config.cuit,
                "punto_venta": config.punto_venta,
                "doc_tipo": doc_tipo,
                "doc_nro": doc_nro,
                "nombre_cliente": nombre_cliente,
                "monto_total": str(monto),
                "items": [
                    {"descripcion": i.descripcion, "cantidad": str(i.cantidad),
                     "precio_unitario": str(i.precio_unitario), "subtotal": str(i.subtotal)}
                    for i in items
                ] if items else None,
                "concepto": concepto,
                "concepto_afip": concepto_afip,
                "condicion_venta": condicion_venta,
                "periodo": f"{periodo_desde} - {periodo_hasta}",
                "fecha": fecha,
                "env": config.env,
            },
        })

    from wsaa import get_token_sign
    from wsfev1 import get_ultimo_numero, solicitar_cae

    try:
        token, sign = get_token_sign(config)
    except Exception as e:
        _output({"error": f"Autenticación WSAA fallida: {e}"}, 1)

    cbte_tipo = CBTE_TIPO["C"]
    try:
        ultimo = get_ultimo_numero(config, token, sign, cbte_tipo)
    except Exception as e:
        _output({"error": f"Error consultando último número: {e}"}, 1)

    req = InvoiceRequest(
        cbte_tipo=cbte_tipo,
        cuit_cliente=doc_nro,
        nombre_cliente=nombre_cliente,
        monto=monto,
        concepto=concepto,
        concepto_afip=concepto_afip,
        numero=ultimo + 1,
        fecha=fecha,
        fecha_serv_desde=periodo_desde,
        fecha_serv_hasta=periodo_hasta,
        fecha_vto_pago=periodo_hasta,
        doc_tipo=doc_tipo,
        doc_nro=doc_nro,
        condicion_iva_receptor=args.condicion_iva,
        condicion_venta=condicion_venta,
        periodo_desde=periodo_desde if concepto_afip in (2, 3) else None,
        periodo_hasta=periodo_hasta if concepto_afip in (2, 3) else None,
        items=items,
    )

    try:
        resp = solicitar_cae(config, token, sign, req)
    except RuntimeError as e:
        _output({"error": str(e)}, 1)
    except Exception as e:
        _output({"error": f"Error al solicitar CAE: {e}"}, 1)

    resp.hora = datetime.now().strftime("%H%M%S")
    if datos_padron:
        resp.domicilio_cliente = datos_padron.get("domicilio")

    result = resp.to_json()

    if getattr(args, "pdf", False):
        from pdf_generator import generate_pdf
        pdf_path = f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
        generate_pdf(config, resp, pdf_path, duplicado=args.duplicado)
        result["pdf"] = pdf_path

    _output(result)


def cmd_nota(args, es_credito: bool) -> None:
    tipo_key = "NC" if es_credito else "ND"
    cbte_tipo = CBTE_TIPO[tipo_key]

    try:
        config = load_config(args.env, args.dry_run)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    try:
        monto = Decimal(str(args.monto)).quantize(Decimal("0.01"))
    except InvalidOperation:
        _output({"error": f"Monto inválido: '{args.monto}'"}, 1)

    hoy = date.today()
    fecha = hoy.strftime("%Y%m%d")
    primer_dia = hoy.replace(day=1).strftime("%Y%m%d")
    ultimo_dia = _last_day_of_month(hoy).strftime("%Y%m%d")

    if args.dry_run:
        _output({
            "status": "dry-run-ok",
            "fields": {"cbte_tipo": cbte_tipo, "numero_original": args.numero_original,
                       "monto": str(monto), "env": config.env},
        })

    from wsaa import get_token_sign
    from wsfev1 import get_ultimo_numero, solicitar_cae

    try:
        token, sign = get_token_sign(config)
    except Exception as e:
        _output({"error": f"Autenticación WSAA fallida: {e}"}, 1)

    try:
        ultimo = get_ultimo_numero(config, token, sign, cbte_tipo)
    except Exception as e:
        _output({"error": f"Error consultando último número: {e}"}, 1)

    req = InvoiceRequest(
        cbte_tipo=cbte_tipo,
        cuit_cliente=config.cuit,
        nombre_cliente="",
        monto=monto,
        concepto="",
        concepto_afip=2,
        numero=ultimo + 1,
        fecha=fecha,
        fecha_serv_desde=primer_dia,
        fecha_serv_hasta=ultimo_dia,
        fecha_vto_pago=ultimo_dia,
        doc_tipo=80,
        doc_nro=config.cuit,
        numero_original=args.numero_original,
        cbte_tipo_original=CBTE_TIPO["C"],
    )

    try:
        resp = solicitar_cae(config, token, sign, req)
    except RuntimeError as e:
        _output({"error": str(e)}, 1)
    except Exception as e:
        _output({"error": f"Error al solicitar CAE: {e}"}, 1)

    _output(resp.to_json())


def cmd_ultimo_numero(args) -> None:
    if args.tipo not in CBTE_TIPO:
        _output({"error": f"Tipo inválido: '{args.tipo}'. Use C, NC o ND."}, 1)

    try:
        config = load_config(args.env, dry_run=False)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    from wsaa import get_token_sign
    from wsfev1 import get_ultimo_numero

    try:
        token, sign = get_token_sign(config)
    except Exception as e:
        _output({"error": f"Autenticación WSAA fallida: {e}"}, 1)

    cbte_tipo = CBTE_TIPO[args.tipo]
    try:
        numero = get_ultimo_numero(config, token, sign, cbte_tipo)
    except Exception as e:
        _output({"error": str(e)}, 1)

    _output({"status": "ok", "tipo": args.tipo, "cbte_tipo": cbte_tipo,
             "ultimo_numero": numero, "proximo": numero + 1})


def cmd_validar_cuit(args) -> None:
    from validators import validar_formato_cuit, validar_cuit_afip

    cuit = args.cuit.strip().replace("-", "").replace(" ", "")
    ok, err = validar_formato_cuit(cuit)
    if not ok:
        _output({"valido": False, "error": err}, 1)

    if args.afip:
        try:
            config = load_config(args.env, dry_run=True)
        except ConfigError as e:
            _output({"error": str(e)}, 1)
        ok, warn, datos = validar_cuit_afip(config, cuit)
        if not ok:
            _output({"valido": False, "cuit": cuit, "error": warn}, 1)
        result = {"valido": True, "cuit": cuit}
        if warn:
            result["advertencia"] = warn
        if datos:
            result.update(datos)
        _output(result)
    else:
        _output({"valido": True, "cuit": cuit, "formato": "ok"})


def cmd_buscar(args) -> None:
    from wsaa import get_token_sign
    from wsfev1 import buscar_rango

    try:
        config = load_config(args.env, dry_run=False)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    if not any([args.desde_fecha, args.hasta_fecha, args.receptor]):
        _output({"error": "Debe especificar al menos un filtro: --desde-fecha, --hasta-fecha o --receptor."}, 1)

    try:
        token, sign = get_token_sign(config)
    except Exception as e:
        _output({"error": f"Autenticación WSAA fallida: {e}"}, 1)

    cbte_tipo = CBTE_TIPO.get(args.tipo)

    receptor_norm = None
    if args.receptor:
        receptor_norm = args.receptor.strip().replace("-", "").replace(" ", "")

    try:
        resultados = buscar_rango(
            config, token, sign, cbte_tipo,
            desde_numero=args.desde_numero,
            hasta_numero=args.hasta_numero,
            desde_fecha=args.desde_fecha,
            hasta_fecha=args.hasta_fecha,
            receptor=receptor_norm,
        )
    except Exception as e:
        _output({"error": str(e)}, 1)

    _output({"status": "ok", "total": len(resultados), "resultados": resultados})


def cmd_consultar(args) -> None:
    from wsaa import get_token_sign
    from wsfev1 import consultar_comprobante

    try:
        config = load_config(args.env, dry_run=False)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    try:
        token, sign = get_token_sign(config)
    except Exception as e:
        _output({"error": f"Autenticación WSAA fallida: {e}"}, 1)

    cbte_tipo = CBTE_TIPO.get(args.tipo, args.tipo if isinstance(args.tipo, int) else None)
    if cbte_tipo is None:
        _output({"error": f"Tipo inválido: '{args.tipo}'. Use C, NC o ND."}, 1)

    try:
        data = consultar_comprobante(config, token, sign, cbte_tipo, args.numero)
    except RuntimeError as e:
        _output({"error": str(e)}, 1)
    except Exception as e:
        _output({"error": f"Error consultando comprobante: {e}"}, 1)

    # Resolver nombre via padrón si hay CUIT/DNI
    doc_tipo = data["doc_tipo"]
    doc_nro = data["doc_nro"]
    if doc_tipo in (80, 96) and doc_nro not in ("0", ""):
        nombre, _ = _resolver_nombre(config, doc_tipo, doc_nro, None)
    elif doc_tipo == 99:
        nombre = "Consumidor Final"
    else:
        nombre = ""

    data["cliente"] = nombre
    data["cuit_cliente"] = doc_nro
    data["condicion_venta"] = "Contado"

    if not getattr(args, "pdf", False):
        _output({"status": "ok", **data})

    # Generar PDF
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
        nombre_cliente=nombre,
        cuit_cliente=doc_nro,
        resultado=data["resultado"],
        doc_tipo=doc_tipo,
        condicion_venta="Contado",
        condicion_iva_receptor=data.get("condicion_iva_receptor", 5),
        periodo_desde=data.get("periodo_desde"),
        periodo_hasta=data.get("periodo_hasta"),
        hora=data.get("hora"),
    )

    pdf_path = args.output or f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
    generate_pdf(config, resp, pdf_path, duplicado=args.duplicado)
    data["pdf"] = pdf_path
    _output({"status": "ok", **data})


def cmd_reimprimir(args) -> None:
    from pdf_generator import generate_pdf
    from models import InvoiceResponse

    try:
        config = load_config(args.env, dry_run=True)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    try:
        if args.json_file == "-":
            data = json.load(sys.stdin)
        else:
            with open(args.json_file, encoding="utf-8") as f:
                data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _output({"error": f"No se pudo leer el JSON: {e}"}, 1)

    required = ("cae", "cae_vencimiento", "numero", "cbte_tipo", "punto_venta", "fecha", "monto")
    missing = [k for k in required if k not in data]
    if missing:
        _output({"error": f"Campos faltantes en el JSON: {', '.join(missing)}"}, 1)

    items = []
    for it in data.get("items", []):
        items.append(InvoiceItem(
            descripcion=it["descripcion"],
            cantidad=Decimal(it["cantidad"]),
            precio_unitario=Decimal(it["precio_unitario"]),
        ))

    cuit_cliente = data.get("cuit_cliente", "0")
    try:
        doc_tipo, _ = _parse_doc(cuit_cliente)
    except ValueError:
        doc_tipo = data.get("doc_tipo", 99)

    resp = InvoiceResponse(
        cae=data["cae"],
        cae_vencimiento=data["cae_vencimiento"],
        numero=data["numero"],
        cbte_tipo=data["cbte_tipo"],
        punto_venta=data.get("punto_venta", config.punto_venta),
        fecha=data["fecha"],
        monto=Decimal(str(data["monto"])),
        nombre_cliente=data.get("cliente", "Consumidor Final"),
        cuit_cliente=cuit_cliente,
        resultado="A",
        doc_tipo=doc_tipo,
        condicion_venta=data.get("condicion_venta", "Contado"),
        condicion_iva_receptor=data.get("condicion_iva_receptor", 5),
        concepto=data.get("concepto", ""),
        periodo_desde=data.get("periodo_desde"),
        periodo_hasta=data.get("periodo_hasta"),
        domicilio_cliente=data.get("domicilio_cliente"),
        hora=data.get("hora"),
        items=items,
    )

    pdf_path = args.output or f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
    generate_pdf(config, resp, pdf_path, duplicado=args.duplicado)
    _output({"status": "ok", "pdf": pdf_path})


def cmd_generar_pdf(args) -> None:
    from pdf_generator import generate_pdf
    from models import InvoiceResponse

    try:
        config = load_config(args.env, dry_run=True)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    try:
        doc_tipo, _ = _parse_doc(args.cuit_cliente)
    except ValueError:
        doc_tipo = 99

    items = []
    if args.item:
        for raw in args.item:
            try:
                items.append(_parse_item(raw))
            except ValueError as e:
                _output({"error": str(e)}, 1)

    monto = (
        sum(i.subtotal for i in items)
        if items
        else Decimal(str(args.monto)).quantize(Decimal("0.01"))
    )

    resp = InvoiceResponse(
        cae=args.cae,
        cae_vencimiento=args.cae_vencimiento,
        numero=args.numero,
        cbte_tipo=args.cbte_tipo,
        punto_venta=config.punto_venta,
        fecha=args.fecha,
        monto=monto,
        nombre_cliente=args.nombre_cliente,
        cuit_cliente=args.cuit_cliente.replace("-", "").replace(" ", ""),
        resultado="A",
        doc_tipo=doc_tipo,
        condicion_venta=args.condicion_venta,
        periodo_desde=args.periodo_desde,
        periodo_hasta=args.periodo_hasta,
        items=items,
    )

    pdf_path = args.output or f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
    generate_pdf(config, resp, pdf_path, duplicado=args.duplicado)
    _output({"status": "ok", "pdf": pdf_path})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Script CLI de facturación electrónica ARCA/AFIP"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    # --- emitir ---
    p_emit = sub.add_parser("emitir", help="Emitir Factura C")
    p_emit.add_argument("--tipo", choices=["C"], default="C")
    p_emit.add_argument("--cuit-cliente", default="SIN_CUIT", metavar="CUIT|SIN_CUIT")
    p_emit.add_argument("--nombre-cliente", default=None, metavar="NOMBRE",
                        help="Opcional: se resuelve automáticamente por padrón A13 si se pasa CUIT")
    p_emit.add_argument("--monto", type=float, default=None, metavar="IMPORTE",
                        help="Total. Si se usan --item se calcula automáticamente")
    p_emit.add_argument("--item", action="append", metavar="DESC|CANT|PRECIO",
                        help="Ítem de la factura. Repetible. Ej: 'Desarrollo|1|5000'")
    p_emit.add_argument("--concepto", default=None, metavar="DESCRIPCION",
                        help="Concepto general. Opcional si se usan --item")
    p_emit.add_argument("--concepto-afip", type=int, choices=[1, 2, 3], default=2,
                        metavar="{1,2,3}", help="1=productos 2=servicios(default) 3=ambos")
    p_emit.add_argument("--condicion-iva", type=int, default=5, metavar="ID",
                        help="Condición IVA receptor (RG 5616). Default: 5=Consumidor Final")
    p_emit.add_argument("--condicion-venta", default="Contado", metavar="COND")
    p_emit.add_argument("--fecha", metavar="YYYYMMDD", help="Default: hoy")
    p_emit.add_argument("--periodo-desde", metavar="YYYYMMDD")
    p_emit.add_argument("--periodo-hasta", metavar="YYYYMMDD")
    p_emit.add_argument("--env", choices=["homo", "prod"], default="homo")
    p_emit.add_argument("--dry-run", action="store_true")
    p_emit.add_argument("--pdf", action="store_true", help="Generar PDF")
    p_emit.add_argument("--duplicado", action="store_true", help="PDF con duplicado")

    # --- validar-cuit ---
    p_val = sub.add_parser("validar-cuit", help="Validar formato y existencia de un CUIT")
    p_val.add_argument("cuit", metavar="CUIT")
    p_val.add_argument("--afip", action="store_true",
                       help="Confirmar existencia consultando el padrón A13 de AFIP")
    p_val.add_argument("--env", choices=["homo", "prod"], default="prod")

    # --- nota-credito ---
    p_nc = sub.add_parser("nota-credito", help="Emitir Nota de Crédito C (tipo 13)")
    p_nc.add_argument("--numero-original", required=True, type=int, metavar="N")
    p_nc.add_argument("--monto", required=True, type=float, metavar="IMPORTE")
    p_nc.add_argument("--env", choices=["homo", "prod"], default="homo")
    p_nc.add_argument("--dry-run", action="store_true")

    # --- nota-debito ---
    p_nd = sub.add_parser("nota-debito", help="Emitir Nota de Débito C (tipo 12)")
    p_nd.add_argument("--numero-original", required=True, type=int, metavar="N")
    p_nd.add_argument("--monto", required=True, type=float, metavar="IMPORTE")
    p_nd.add_argument("--env", choices=["homo", "prod"], default="homo")
    p_nd.add_argument("--dry-run", action="store_true")

    # --- ultimo-numero ---
    p_un = sub.add_parser("ultimo-numero", help="Consultar el último número emitido")
    p_un.add_argument("--tipo", choices=["C", "NC", "ND"], required=True)
    p_un.add_argument("--env", choices=["homo", "prod"], default="homo")

    # --- buscar ---
    p_bus = sub.add_parser("buscar", help="Buscar comprobantes en AFIP por fecha y/o receptor")
    p_bus.add_argument("--tipo", choices=["C", "NC", "ND"], default="C")
    p_bus.add_argument("--desde-fecha", metavar="YYYYMMDD")
    p_bus.add_argument("--hasta-fecha", metavar="YYYYMMDD")
    p_bus.add_argument("--receptor", metavar="CUIT|DNI", help="CUIT o DNI del receptor")
    p_bus.add_argument("--desde-numero", type=int, default=1, metavar="N",
                       help="Número de comprobante desde donde empezar (default: 1)")
    p_bus.add_argument("--hasta-numero", type=int, default=None, metavar="N",
                       help="Número hasta donde buscar (default: último emitido)")
    p_bus.add_argument("--env", choices=["homo", "prod"], default="prod")

    # --- consultar ---
    p_con = sub.add_parser("consultar", help="Consultar comprobante en AFIP y opcionalmente generar PDF")
    p_con.add_argument("--numero", required=True, type=int, metavar="N")
    p_con.add_argument("--tipo", choices=["C", "NC", "ND"], default="C")
    p_con.add_argument("--pdf", action="store_true", help="Generar PDF con los datos obtenidos de AFIP")
    p_con.add_argument("--duplicado", action="store_true")
    p_con.add_argument("--output", metavar="ARCHIVO.pdf")
    p_con.add_argument("--env", choices=["homo", "prod"], default="prod")

    # --- reimprimir ---
    p_reim = sub.add_parser("reimprimir", help="Generar PDF a partir del JSON de una factura emitida")
    p_reim.add_argument("json_file", metavar="ARCHIVO.json|-",
                        help="JSON devuelto por 'emitir', o '-' para leer de stdin")
    p_reim.add_argument("--duplicado", action="store_true", help="PDF con duplicado")
    p_reim.add_argument("--output", metavar="ARCHIVO.pdf")
    p_reim.add_argument("--env", choices=["homo", "prod"], default="prod")

    # --- generar-pdf ---
    p_pdf = sub.add_parser("generar-pdf", help="Generar PDF de un comprobante ya emitido")
    p_pdf.add_argument("--numero", required=True, type=int)
    p_pdf.add_argument("--cae", required=True)
    p_pdf.add_argument("--cae-vencimiento", required=True, metavar="YYYYMMDD")
    p_pdf.add_argument("--cbte-tipo", type=int, default=11)
    p_pdf.add_argument("--fecha", required=True, metavar="YYYYMMDD")
    p_pdf.add_argument("--monto", type=float, default=None)
    p_pdf.add_argument("--item", action="append", metavar="DESC|CANT|PRECIO")
    p_pdf.add_argument("--nombre-cliente", default="Consumidor Final")
    p_pdf.add_argument("--cuit-cliente", default="SIN_CUIT")
    p_pdf.add_argument("--condicion-venta", default="Contado")
    p_pdf.add_argument("--periodo-desde", metavar="YYYYMMDD")
    p_pdf.add_argument("--periodo-hasta", metavar="YYYYMMDD")
    p_pdf.add_argument("--duplicado", action="store_true")
    p_pdf.add_argument("--env", choices=["homo", "prod"], default="prod")
    p_pdf.add_argument("--output", metavar="ARCHIVO.pdf")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.comando == "emitir":
            cmd_emitir(args)
        elif args.comando == "validar-cuit":
            cmd_validar_cuit(args)
        elif args.comando == "nota-credito":
            cmd_nota(args, es_credito=True)
        elif args.comando == "nota-debito":
            cmd_nota(args, es_credito=False)
        elif args.comando == "ultimo-numero":
            cmd_ultimo_numero(args)
        elif args.comando == "buscar":
            cmd_buscar(args)
        elif args.comando == "consultar":
            cmd_consultar(args)
        elif args.comando == "reimprimir":
            cmd_reimprimir(args)
        elif args.comando == "generar-pdf":
            cmd_generar_pdf(args)
    except SystemExit:
        raise
    except Exception as e:
        _output({"error": str(e)}, 1)


if __name__ == "__main__":
    main()
