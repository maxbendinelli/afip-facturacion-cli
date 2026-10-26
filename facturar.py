#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from config import ConfigError, load_config
from models import CBTE_TIPO, COND_IVA_ALIAS, COND_IVA_NOMBRE, InvoiceItem, InvoiceRequest


def _last_day_of_month(d: date) -> date:
    next_month = d.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


DOC_ALIAS = {
    "CUIT": 80,
    "CUIL": 86,
    "CDI": 87,
    "LE": 89,
    "LC": 90,
    "CI": 91,
    "CI_EXTRANJERA": 91,
    "DNI": 96,
    "PAS": 94,
    "PASAPORTE": 94,
    "CI_POLICIA": 0,
    "POLICIA": 0,
    "MIGRACION": 95,
    "SIN_CUIT": 99,
    "CONSUMIDOR_FINAL": 99,
}

def _parse_doc(raw: str, default_tipo: int | None = None) -> tuple[int, str]:
    raw_s = str(raw or "").strip().replace("-", "").replace(" ", "").replace(".", "")
    raw_upper = raw_s.upper()

    for prefix, tipo in [("CUIT", 80), ("CUIL", 86), ("CDI", 87), ("LE", 89), ("LC", 90), ("DNI", 96), ("PAS", 94), ("CI", 91)]:
        if raw_upper.startswith(prefix):
            clean_num = raw_upper[len(prefix):].strip()
            if clean_num.isdigit():
                return tipo, clean_num

    if default_tipo is not None:
        return default_tipo, raw_s if raw_s.isdigit() else "0"

    if raw_s.isdigit() and len(raw_s) == 11:
        return 80, raw_s
    if raw_s.isdigit() and 6 <= len(raw_s) <= 8:
        return 96, raw_s
    if raw_upper in ("SIN_CUIT", "0", ""):
        return 99, "0"
    raise ValueError(f"Formato de documento inválido: '{raw}'")


def _parse_item(raw: str) -> InvoiceItem:
    """Parsea 'descripcion|cantidad|precio_unitario' o 'descripcion|cantidad|precio_unitario|alicuota'."""
    parts = raw.split("|")
    if len(parts) == 3:
        desc, qty_s, price_s = parts
        alic_s = "21"
    elif len(parts) == 4:
        desc, qty_s, price_s, alic_s = parts
    else:
        raise ValueError(
            f"Formato de ítem inválido: '{raw}'. Use: 'Descripción|Cantidad|PrecioUnitario' o 'Descripción|Cantidad|PrecioUnitario|Alicuota'"
        )
    try:
        qty = Decimal(qty_s.strip()).quantize(Decimal("0.01"))
        price = Decimal(price_s.strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"Cantidad o precio inválido en ítem: '{raw}'")
    if qty <= 0 or price == 0:
        raise ValueError(f"Cantidad debe ser mayor a cero y precio distinto de cero en ítem: '{raw}'")

    alic_raw = alic_s.strip().upper().replace("%", "")
    if "NO GRAV" in alic_raw or "NG" == alic_raw:
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("0.0"), alicuota_iva_id=1, tipo_iva="no_gravado")
    elif "EXENT" in alic_raw or "EX" == alic_raw:
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("0.0"), alicuota_iva_id=2, tipo_iva="exento")
    elif alic_raw in ("0", "0.0"):
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("0.0"), alicuota_iva_id=3, tipo_iva="iva")
    elif "10.5" in alic_raw or "10,5" in alic_raw:
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("10.5"), alicuota_iva_id=4, tipo_iva="iva")
    elif "27" in alic_raw:
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("27.0"), alicuota_iva_id=6, tipo_iva="iva")
    elif "5" in alic_raw and "2.5" not in alic_raw and "10.5" not in alic_raw:
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("5.0"), alicuota_iva_id=8, tipo_iva="iva")
    elif "2.5" in alic_raw or "2,5" in alic_raw:
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("2.5"), alicuota_iva_id=9, tipo_iva="iva")
    else:
        return InvoiceItem(descripcion=desc.strip(), cantidad=qty, precio_unitario=price, alicuota_iva=Decimal("21.0"), alicuota_iva_id=5, tipo_iva="iva")


def _parse_condicion_iva(raw: str) -> int:
    """Acepta un número de condición IVA o un alias de texto (CF, RI, MONO, etc.).

    Aliases disponibles:
      CF / CONSUMIDOR_FINAL / FINAL        -> 5
      RI / RESPONSABLE_INSCRIPTO           -> 1
      EX / EXENTO / EXENTA                 -> 4
      MONO / MONOTRIB / MONOTRIBUTISTA     -> 6
      RNI / NO_INSCRIPTO                   -> 2
      NR / NO_RESPONSABLE                  -> 3
      NC / NO_CATEGORIZADO                 -> 7
    """
    raw = raw.strip()
    if raw.isdigit():
        val = int(raw)
        if val not in COND_IVA_NOMBRE:
            raise ValueError(
                f"Condición IVA '{val}' desconocida. Valores válidos: "
                + ", ".join(f"{k}={v}" for k, v in COND_IVA_NOMBRE.items())
            )
        return val
    key = raw.upper().replace(" ", "_").replace("-", "_")
    if key in COND_IVA_ALIAS:
        return COND_IVA_ALIAS[key]
    raise ValueError(
        f"Condición IVA '{raw}' inválida. "
        "Use un número (1-14) o un alias como: CF, RI, MONO, EX, RNI, NR."
    )


def _inferir_condicion_iva(config, doc_tipo: int, doc_nro: str, datos_padron: dict | None) -> int:
    """Infiere la condición IVA del receptor cuando no se especifica explícitamente.

    Lógica:
    - doc_tipo 99 (sin identificar) → Consumidor Final (5)
    - doc_tipo 96 (DNI)             → Consumidor Final (5)
    - doc_tipo 80 (CUIT) con datos de padrón que indiquen monotributo → 6
    - doc_tipo 80 (CUIT) sin padrón o sin categoría clara → RI (1) como default seguro
    """
    if doc_tipo in (99, 96):
        return 5  # Consumidor Final
    # CUIT: intentar extraer del padrón
    if datos_padron:
        cat = str(datos_padron.get("categoria_monotributo") or "").strip().upper()
        if cat:  # cualquier categoría A-K indica monotributista
            return 6
        actividad = str(datos_padron.get("actividad_monotributo") or "").strip()
        if actividad:
            return 6
    # Default para CUIT desconocido: RI
    return 1


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
        if getattr(args, "cuit_emisor", None):
            config.cuit = args.cuit_emisor.strip().replace("-", "").replace(" ", "")
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
        cbte_letra = getattr(args, "tipo", "C").upper()
        if cbte_letra in ("A", "NDA", "NCA"):
            monto = sum(i.total_con_iva for i in items)
        else:
            monto = sum(i.subtotal for i in items)
    else:
        if args.monto is None:
            _output({"error": "Debe proveer --monto o al menos un --item."}, 1)
        try:
            monto = Decimal(str(args.monto)).quantize(Decimal("0.01"))
        except InvalidOperation:
            _output({"error": f"Monto inválido: '{args.monto}'"}, 1)

    # Parsear documento receptor
    doc_tipo_override = None
    if getattr(args, "doc_tipo", None):
        raw_dt = str(args.doc_tipo).strip().upper()
        doc_tipo_override = int(raw_dt) if raw_dt.isdigit() else DOC_ALIAS.get(raw_dt)
        if doc_tipo_override is None:
            _output({"error": f"Tipo de documento inválido: '{args.doc_tipo}'"}, 1)

    try:
        doc_tipo, doc_nro = _parse_doc(args.cuit_cliente, default_tipo=doc_tipo_override)
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

    # Resolver condición IVA del receptor
    if args.condicion_iva is not None:
        try:
            condicion_iva = _parse_condicion_iva(str(args.condicion_iva))
        except ValueError as e:
            _output({"error": str(e)}, 1)
    else:
        condicion_iva = _inferir_condicion_iva(config, doc_tipo, doc_nro, datos_padron)
    condicion_iva_nombre = COND_IVA_NOMBRE.get(condicion_iva, str(condicion_iva))

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

    fecha_vto_pago_afip = args.fecha_vto_pago or periodo_hasta
    fecha_vto_pago_pdf = args.fecha_vto_pago or fecha

    concepto_afip = args.concepto_afip
    condicion_venta = args.condicion_venta

    # Resolver nombre (usa padrón A13 si ya obtuvimos datos; si no, busca)
    if datos_padron and datos_padron.get("nombre"):
        nombre_cliente = args.nombre_cliente or datos_padron["nombre"]
    else:
        nombre_cliente, _ = _resolver_nombre(config, doc_tipo, doc_nro, args.nombre_cliente)

    if not nombre_cliente:
        _output({"error": "No se pudo determinar el nombre del receptor. Use --nombre-cliente."}, 1)

    domicilio_cliente = getattr(args, "domicilio_cliente", None)
    if not domicilio_cliente and datos_padron and datos_padron.get("domicilio"):
        domicilio_cliente = datos_padron["domicilio"]

    # Concepto: si hay ítems, usar sus descripciones; si no, usar --concepto
    if items and not args.concepto:
        concepto = "; ".join(i.descripcion for i in items)
    elif args.concepto:
        concepto = args.concepto
    else:
        _output({"error": "Debe proveer --concepto o al menos un --item."}, 1)

    if args.dry_run:
        from models import InvoiceResponse
        from pdf_generator import generate_pdf
        cbte_tipo = CBTE_TIPO.get(getattr(args, "tipo", "C").upper(), 11)
        letra = getattr(args, "tipo", "C").upper()
        pdf_path = None
        if args.pdf:
            pdf_path = f"comprobante_{letra.lower()}_{config.punto_venta:04d}_simulado.pdf"
            resp_sim = InvoiceResponse(
                cae="SIMULADO_CAE_123456",
                cae_vencimiento=(date.today() + timedelta(days=10)).strftime("%Y%m%d"),
                numero=9999,
                cbte_tipo=cbte_tipo,
                punto_venta=config.punto_venta,
                fecha=fecha,
                monto=monto,
                nombre_cliente=nombre_cliente,
                cuit_cliente=doc_nro,
                resultado="A",
                doc_tipo=doc_tipo,
                condicion_iva_receptor=condicion_iva,
                condicion_venta=condicion_venta or "Contado",
                periodo_desde=periodo_desde,
                periodo_hasta=periodo_hasta,
                fecha_vto_pago=fecha_vto_pago_pdf,
                domicilio_cliente=domicilio_cliente,
                hora=datetime.now().strftime("%H%M%S"),
                items=items,
            )
            generate_pdf(config, resp_sim, pdf_path, duplicado=args.duplicado, triplicado=getattr(args, "triplicado", False))

        _output({
            "status": "dry-run-ok",
            "pdf": pdf_path,
            "fields": {
                "cbte_tipo": cbte_tipo,
                "cuit_emisor": config.cuit,
                "punto_venta": config.punto_venta,
                "doc_tipo": doc_tipo,
                "doc_nro": doc_nro,
                "nombre_cliente": nombre_cliente,
                "condicion_iva_receptor": condicion_iva,
                "condicion_iva_nombre": condicion_iva_nombre,
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

    cbte_tipo = CBTE_TIPO.get(getattr(args, "tipo", "C").upper(), 11)
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
        fecha_vto_pago=fecha_vto_pago_afip,
        doc_tipo=doc_tipo,
        doc_nro=doc_nro,
        condicion_iva_receptor=condicion_iva,
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
    resp.fecha_vto_pago = fecha_vto_pago_pdf
    if domicilio_cliente:
        resp.domicilio_cliente = domicilio_cliente
    elif datos_padron and datos_padron.get("domicilio"):
        resp.domicilio_cliente = datos_padron["domicilio"]

    result = resp.to_json()
    result["condicion_iva_nombre"] = condicion_iva_nombre

    if getattr(args, "pdf", False):
        from pdf_generator import generate_pdf
        pdf_path = f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
        generate_pdf(config, resp, pdf_path, duplicado=args.duplicado, triplicado=getattr(args, "triplicado", False))
        result["pdf"] = pdf_path

    _output(result)


def cmd_nota(args, es_credito: bool) -> None:
    letra = getattr(args, "tipo", "C").upper()
    tipo_key = f"NC{letra}" if es_credito else f"ND{letra}"
    cbte_tipo = CBTE_TIPO.get(tipo_key, CBTE_TIPO["NC" if es_credito else "ND"])

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
        cbte_tipo_original=CBTE_TIPO.get(getattr(args, "tipo", "C").upper(), 11),
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
    generate_pdf(config, resp, pdf_path, duplicado=args.duplicado, triplicado=getattr(args, "triplicado", False))
    data["pdf"] = pdf_path
    _output({"status": "ok", **data})


def cmd_reimprimir(args) -> None:
    from pdf_generator import generate_pdf
    from models import InvoiceResponse
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
    generate_pdf(config, resp, pdf_path, duplicado=args.duplicado, triplicado=getattr(args, "triplicado", False))
    _output({"status": "ok", "pdf": pdf_path})


def cmd_generar_pdf(args) -> None:
    from pdf_generator import generate_pdf
    from models import InvoiceResponse
    from models import InvoiceResponse

    try:
        config = load_config(args.env, dry_run=True)
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    sin_cuit = args.cuit_cliente == "SIN_CUIT"
    try:
        doc_tipo, _ = _parse_doc(args.cuit_cliente)
    except ValueError:
        doc_tipo = 99

    if sin_cuit and args.nombre_cliente != "Consumidor Final":
        _output({"error": "Se requiere --cuit-cliente cuando el destinatario no es Consumidor Final."}, 1)

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
        fecha_vto_pago=args.fecha_vto_pago or args.fecha,
        items=items,
    )

    pdf_path = args.output or f"factura_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
    generate_pdf(config, resp, pdf_path, duplicado=args.duplicado, triplicado=getattr(args, "triplicado", False))
    _output({"status": "ok", "pdf": pdf_path})



def cmd_lote(args) -> None:
    from pathlib import Path
    import csv
    import zipfile
    from wsfev1 import get_ultimo_comprobante_info, solicitar_cae
    from wsaa import get_token_sign
    from pdf_generator import generate_pdf
    from models import InvoiceResponse

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        _output({"error": f"Archivo CSV no encontrado: {args.csv_file}"}, 1)

    try:
        config = load_config(args.env, args.dry_run)
        if getattr(args, "cuit_emisor", None):
            config.cuit = args.cuit_emisor.strip().replace("-", "").replace(" ", "")
    except ConfigError as e:
        _output({"error": str(e)}, 1)

    raw_bytes = csv_path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")

    all_lines = [l for l in text.splitlines() if l.strip()]
    if not all_lines:
        _output({"error": "El archivo CSV está vacío."}, 1)

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
    parsed_rows = []

    def _parse_d_afip(val):
        if not val: return None
        v = str(val).strip().replace("-", "").replace("/", "")
        if len(v) == 8 and v.isdigit(): return v
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try: return datetime.strptime(str(val).strip(), fmt).strftime("%Y%m%d")
            except Exception: pass
        return None

    # Mapeo de existentes en comprobantes/ para evitar duplicados
    comprobantes_dir = Path("./comprobantes")
    comprobantes_dir.mkdir(parents=True, exist_ok=True)
    existing_map = {}
    for p in comprobantes_dir.glob("comprobante_*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            cuit_e = str(d.get("cuit_cliente", "")).strip().replace("-", "")
            cbte_e = int(d.get("cbte_tipo", 0))
            monto_e = str(Decimal(str(d.get("monto", "0"))).quantize(Decimal("0.01")))
            existing_map[f"{cuit_e}_{cbte_e}_{monto_e}"] = d
        except Exception:
            continue

    col_map = {
        "destinatario factura": "nombre_cliente", "cliente": "nombre_cliente",
        "dni/cuit": "cuit_cliente", "cuit": "cuit_cliente", "dni": "cuit_cliente",
        "tipo comp.": "tipo", "tipo": "tipo",
        "total": "monto", "importe": "monto", "monto": "monto",
        "alic. iva %": "alicuota_iva", "iva": "alicuota_iva",
        "fecha": "fecha", "f.emision": "fecha",
        "desde": "periodo_desde", "hasta": "periodo_hasta",
        "f.vto": "fecha_vto_pago", "concepto": "concepto",
    }

    for idx, raw_row in enumerate(reader, 1):
        row = {col_map.get(k.strip().lower(), k.strip().lower()): v for k, v in raw_row.items() if k}
        if str(row.get("factura") or "").strip().upper() == "NO":
            continue

        dni_field = (row.get("cuit_cliente") or "").strip()
        nombre = (row.get("nombre_cliente") or "").strip()
        monto_raw = (row.get("monto") or "0").replace("$", "").replace(" ", "")
        if not nombre and not dni_field and monto_raw in ("", "0"):
            continue

        tipo_raw = (row.get("tipo") or "C").upper().strip()
        if "FACTURA A" in tipo_raw or tipo_raw == "A": tipo_str = "A"
        elif "FACTURA B" in tipo_raw or tipo_raw == "B": tipo_str = "B"
        else: tipo_str = "C"

        cbte_tipo = CBTE_TIPO.get(tipo_str, 11)
        concepto = (row.get("concepto") or "Servicios").strip()

        if "," in monto_raw and "." in monto_raw:
            monto_raw = monto_raw.replace(".", "").replace(",", ".")
        elif "," in monto_raw and "." not in monto_raw:
            monto_raw = monto_raw.replace(",", ".")
        try: monto = float(monto_raw)
        except Exception: monto = 0.0

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
        elif "5" in alic_raw and "2.5" not in alic_raw and "10.5" not in alic_raw:
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

        cond_id = 1 if tipo_str == "A" else 5
        try: doc_tipo, doc_nro = _parse_doc(dni_field)
        except Exception: doc_tipo, doc_nro = (99, "0")

        f_emision = _parse_d_afip(row.get("fecha"))
        f_desde = _parse_d_afip(row.get("periodo_desde"))
        f_hasta = _parse_d_afip(row.get("periodo_hasta"))
        f_vto = _parse_d_afip(row.get("fecha_vto_pago"))

        monto_dec_str = str(Decimal(str(monto)).quantize(Decimal("0.01")))
        exist_key = f"{doc_nro}_{cbte_tipo}_{monto_dec_str}"
        exist_info = existing_map.get(exist_key)

        parsed_rows.append({
            "index": int(raw_row.get("INDEX") or idx) if str(raw_row.get("INDEX") or idx).isdigit() else idx,
            "tipo": tipo_str,
            "cbte_tipo": cbte_tipo,
            "cuit_cliente": doc_nro,
            "doc_tipo": doc_tipo,
            "doc_nro": doc_nro,
            "nombre_cliente": nombre or "Consumidor Final",
            "domicilio_cliente": (row.get("domicilio_cliente") or "").strip() or None,
            "concepto": concepto,
            "monto": monto,
            "alicuota_iva": alic_iva,
            "alicuota_iva_id": alic_id,
            "tipo_iva": tipo_iva,
            "condicion_iva_receptor": cond_id,
            "condicion_venta": (row.get("condicion_venta") or "Contado").strip(),
            "concepto_afip": 2,
            "fecha": f_emision,
            "periodo_desde": f_desde,
            "periodo_hasta": f_hasta,
            "fecha_vto_pago": f_vto,
            "cae": exist_info.get("cae") if exist_info else None,
            "comprobante": exist_info.get("comprobante") if exist_info else None,
            "pdf_filename": exist_info.get("pdf_filename") if exist_info else None,
            "ya_emitido": bool(exist_info),
        })

    hoy_dt = date.today()

    # Ordenar cronológicamente por fecha de emisión para respetar la regla de AFIP (CbteFch_N >= CbteFch_{N-1})
    def _row_date_key_cli(r):
        f = r.get("fecha") or hoy_dt.strftime("%Y%m%d")
        f_clean = str(f).replace("-", "").replace("/", "")
        idx = r.get("index") or 0
        try:
            idx_num = int(idx)
        except Exception:
            idx_num = 0
        return (f_clean, idx_num)

    parsed_rows = sorted(parsed_rows, key=_row_date_key_cli)

    sys.stderr.write(f"\n📦 Lote cargado: {len(parsed_rows)} comprobantes interpretados y ordenados cronológicamente.\n")
    ya_emitidos = sum(1 for r in parsed_rows if r["ya_emitido"])
    if ya_emitidos > 0:
        sys.stderr.write(f"ℹ️  {ya_emitidos} comprobantes ya fueron emitidos previamente y se omitirán para no duplicar.\n")

    pendientes = [r for r in parsed_rows if not r["ya_emitido"]]
    sys.stderr.write(f"🚀 Pendientes de emisión: {len(pendientes)} comprobantes en entorno {config.env.upper()}\n\n")

    token, sign = (None, None)
    if not config.dry_run:
        token, sign = get_token_sign(config)

    ult_cache = {}
    hoy_dt = date.today()
    min_permitida = hoy_dt - timedelta(days=10)
    max_permitida = hoy_dt + timedelta(days=10)

    resultados = []
    exitosos = 0
    fallidos = 0
    generated_pdfs = []

    for item in parsed_rows:
        if item["ya_emitido"] and not config.dry_run:
            resultados.append({
                "index": item["index"],
                "status": "ok",
                "tipo": item["tipo"],
                "comprobante": item["comprobante"],
                "cae": item["cae"],
                "monto": item["monto"],
                "cliente": item["nombre_cliente"],
                "mensaje": "Previamente emitido",
            })
            exitosos += 1
            continue

        try:
            monto_dec = Decimal(str(item["monto"])).quantize(Decimal("0.01"))
            alic_dec = Decimal(str(item["alicuota_iva"])).quantize(Decimal("0.1"))
            tipo_it = item.get("tipo_iva") or ("no_gravado" if item.get("alicuota_iva_id") == 1 else "exento" if item.get("alicuota_iva_id") == 2 else "iva")
            alic_id = item.get("alicuota_iva_id") or (1 if tipo_it == "no_gravado" else 2 if tipo_it == "exento" else 3 if alic_dec == Decimal("0.0") else 5)

            if item["cbte_tipo"] == 1:
                if tipo_it in ("no_gravado", "exento") or alic_id in (1, 2, 3) or alic_dec == Decimal("0.0"):
                    neto_dec = monto_dec
                    items_obj = [InvoiceItem(descripcion=item["concepto"], cantidad=Decimal("1.00"), precio_unitario=neto_dec, alicuota_iva=Decimal("0.0"), alicuota_iva_id=alic_id, tipo_iva=tipo_it)]
                else:
                    neto_dec = (monto_dec / (Decimal("1.00") + (alic_dec / Decimal("100")))).quantize(Decimal("0.01"))
                    items_obj = [InvoiceItem(descripcion=item["concepto"], cantidad=Decimal("1.00"), precio_unitario=neto_dec, alicuota_iva=alic_dec, alicuota_iva_id=alic_id, tipo_iva=tipo_it)]
            elif item["cbte_tipo"] == 6:
                items_obj = [InvoiceItem(descripcion=item["concepto"], cantidad=Decimal("1.00"), precio_unitario=monto_dec, alicuota_iva=alic_dec, alicuota_iva_id=alic_id, tipo_iva=tipo_it)]
            else:
                items_obj = [InvoiceItem(descripcion=item["concepto"], cantidad=Decimal("1.00"), precio_unitario=monto_dec, alicuota_iva=Decimal("0.0"), alicuota_iva_id=3, tipo_iva="iva")]

            if config.dry_run:
                pv = config.punto_venta or 4
                letra = "A" if item["cbte_tipo"] == 1 else ("B" if item["cbte_tipo"] == 6 else "C")
                pdf_name = f"comprobante_{letra.lower()}_{pv:04d}_sim_{item['index']:04d}.pdf"
                pdf_path = comprobantes_dir / pdf_name

                serv_desde = item.get("periodo_desde") or (hoy_dt.strftime("%Y%m") + "01")
                serv_hasta = item.get("periodo_hasta") or hoy_dt.strftime("%Y%m%d")
                vto_pago = item.get("fecha_vto_pago") or item.get("fecha") or hoy_dt.strftime("%Y%m%d")

                resp_sim = InvoiceResponse(
                    cae="SIMULADO_CAE_123456",
                    cae_vencimiento=(hoy_dt + timedelta(days=10)).strftime("%Y%m%d"),
                    numero=int(item["index"]) if str(item["index"]).isdigit() else 9999,
                    cbte_tipo=item["cbte_tipo"],
                    punto_venta=pv,
                    fecha=item.get("fecha") or hoy_dt.strftime("%Y%m%d"),
                    monto=monto_dec,
                    nombre_cliente=item["nombre_cliente"],
                    cuit_cliente=item["doc_nro"],
                    resultado="A",
                    doc_tipo=item["doc_tipo"],
                    condicion_iva_receptor=item["condicion_iva_receptor"],
                    condicion_venta=item["condicion_venta"],
                    periodo_desde=serv_desde,
                    periodo_hasta=serv_hasta,
                    hora=datetime.now().strftime("%H%M%S"),
                    fecha_vto_pago=vto_pago,
                    items=items_obj,
                    imp_neto=monto_dec if item["cbte_tipo"] not in (1, 6) or alic_dec == Decimal("0.0") else neto_dec,
                    imp_iva=Decimal("0.00") if item["cbte_tipo"] not in (1, 6) or alic_dec == Decimal("0.0") else (monto_dec - neto_dec),
                )

                if args.pdf:
                    generate_pdf(config, resp_sim, str(pdf_path), duplicado=args.duplicado, triplicado=getattr(args, "triplicado", False))
                    generated_pdfs.append(pdf_path)

                resultados.append({
                    "index": item["index"],
                    "status": "ok",
                    "modo": "simulacion",
                    "tipo": item["tipo"],
                    "comprobante": f"{pv:04d}-SIM{item['index']:04d}",
                    "cae": "SIMULADO_CAE_123456",
                    "monto": str(monto_dec),
                    "cliente": item["nombre_cliente"],
                    "pdf": str(pdf_path) if args.pdf else None,
                })
                exitosos += 1
                sys.stderr.write(f"  [DRY-RUN] #{item['index']} {item['tipo']} {item['nombre_cliente']} -> $ {monto_dec:,.2f} (PDF: {pdf_name})\n")
                continue

            cbte_tipo = item["cbte_tipo"]
            if cbte_tipo not in ult_cache:
                nro, fch = get_ultimo_comprobante_info(config, token, sign, cbte_tipo)
                ult_cache[cbte_tipo] = {"nro": nro, "fecha": fch}

            proximo_nro = ult_cache[cbte_tipo]["nro"] + 1

            try: dt_deseada = datetime.strptime(item["fecha"], "%Y%m%d").date() if item.get("fecha") else hoy_dt
            except Exception: dt_deseada = hoy_dt

            if dt_deseada > max_permitida: dt_calc = max_permitida
            elif dt_deseada < min_permitida: dt_calc = hoy_dt
            else: dt_calc = dt_deseada

            ult_fch_str = ult_cache[cbte_tipo]["fecha"]
            if ult_fch_str:
                try:
                    dt_ult = datetime.strptime(ult_fch_str, "%Y%m%d").date()
                    if dt_calc < dt_ult: dt_calc = dt_ult
                except Exception: pass

            fecha_emision = dt_calc.strftime("%Y%m%d")
            serv_desde = item.get("periodo_desde") or (hoy_dt.strftime("%Y%m") + "01")
            serv_hasta = item.get("periodo_hasta") or hoy_dt.strftime("%Y%m%d")
            vto_pago = item.get("fecha_vto_pago") or fecha_emision
            if vto_pago < fecha_emision: vto_pago = fecha_emision

            req = InvoiceRequest(
                cbte_tipo=cbte_tipo,
                cuit_cliente=item["doc_nro"],
                nombre_cliente=item["nombre_cliente"],
                monto=monto_dec,
                concepto=item["concepto"],
                concepto_afip=item["concepto_afip"],
                numero=proximo_nro,
                fecha=fecha_emision,
                fecha_serv_desde=serv_desde,
                fecha_serv_hasta=serv_hasta,
                fecha_vto_pago=vto_pago,
                doc_tipo=item["doc_tipo"],
                doc_nro=item["doc_nro"],
                condicion_iva_receptor=item["condicion_iva_receptor"],
                condicion_venta=item["condicion_venta"],
                items=items_obj,
            )

            resp = solicitar_cae(config, token, sign, req)
            ult_cache[cbte_tipo] = {"nro": resp.numero, "fecha": resp.fecha}
            resp.hora = datetime.now().strftime("%H%M%S")
            resp.fecha_vto_pago = vto_pago

            letra = "A" if cbte_tipo == 1 else ("B" if cbte_tipo == 6 else "C")
            pdf_name = f"comprobante_{letra.lower()}_{resp.punto_venta:04d}_{resp.numero:08d}.pdf"
            pdf_path = comprobantes_dir / pdf_name
            if args.pdf:
                generate_pdf(config, resp, str(pdf_path), duplicado=args.duplicado, triplicado=getattr(args, "triplicado", False))
                generated_pdfs.append(pdf_path)

            resp_dict = resp.to_json()
            resp_dict["pdf_filename"] = pdf_name
            with open(comprobantes_dir / f"comprobante_{letra.lower()}_{resp.punto_venta:04d}_{resp.numero:08d}.json", "w", encoding="utf-8") as f:
                json.dump(resp_dict, f, ensure_ascii=False)

            resultados.append({
                "index": item["index"],
                "status": "ok",
                "tipo": item["tipo"],
                "comprobante": f"{resp.punto_venta:04d}-{resp.numero:08d}",
                "cae": resp.cae,
                "cae_vencimiento": resp.cae_vencimiento,
                "monto": str(resp.monto),
                "cliente": resp.nombre_cliente,
                "pdf": str(pdf_path) if args.pdf else None,
            })
            exitosos += 1
            sys.stderr.write(f"  ✓ [{exitosos}/{len(parsed_rows)}] {item['tipo']} {resp.punto_venta:04d}-{resp.numero:08d} CAE:{resp.cae} -> {resp.nombre_cliente}\n")

        except Exception as e:
            if "cbte_tipo" in locals() and cbte_tipo in ult_cache:
                ult_cache.pop(cbte_tipo, None)
            resultados.append({
                "index": item["index"],
                "status": "error",
                "tipo": item["tipo"],
                "cliente": item["nombre_cliente"],
                "monto": str(item["monto"]),
                "error": str(e),
            })
            fallidos += 1
            sys.stderr.write(f"  ✕ [{item['index']}] ERROR {item['nombre_cliente']}: {e}\n")

    # Si se pide zip consolidado
    if getattr(args, "zip", None) and generated_pdfs:
        zip_path = Path(args.zip)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in generated_pdfs:
                if p.exists():
                    zf.write(p, arcname=p.name)
        sys.stderr.write(f"\n🗜️  Archivo ZIP consolidado creado en: {zip_path.resolve()}\n")

    resumen = {
        "status": "ok" if fallidos == 0 else "parcial",
        "total": len(parsed_rows),
        "exitosos": exitosos,
        "fallidos": fallidos,
        "resultados": resultados,
    }
    _output(resumen, 0 if fallidos == 0 else 1)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Script CLI de facturación electrónica ARCA/AFIP"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    # --- emitir ---
    p_emit = sub.add_parser("emitir", help="Emitir Factura C")
    p_emit.add_argument("--tipo", choices=["A", "B", "C"], default="C", help="Tipo de factura: A, B o C (default: C)")
    p_emit.add_argument("--cuit-cliente", default="SIN_CUIT", metavar="CUIT|SIN_CUIT")
    p_emit.add_argument("--nombre-cliente", default=None, metavar="NOMBRE",
                        help="Opcional: se resuelve automáticamente por padrón A13 si se pasa CUIT")
    p_emit.add_argument("--domicilio-cliente", default=None, metavar="DOMICILIO",
                        help="Domicilio del cliente / receptor")
    p_emit.add_argument("--monto", type=float, default=None, metavar="IMPORTE",
                        help="Total. Si se usan --item se calcula automáticamente")
    p_emit.add_argument("--item", action="append", metavar="DESC|CANT|PRECIO",
                        help="Ítem de la factura. Repetible. Ej: 'Desarrollo|1|5000'")
    p_emit.add_argument("--concepto", default=None, metavar="DESCRIPCION",
                        help="Concepto general. Opcional si se usan --item")
    p_emit.add_argument("--concepto-afip", type=int, choices=[1, 2, 3], default=2,
                        metavar="{1,2,3}", help="1=productos 2=servicios(default) 3=ambos")
    p_emit.add_argument("--doc-tipo", default=None, metavar="TIPO",
                        help="Tipo de documento (CUIT, CUIL, DNI, LE, LC, PASAPORTE, etc., o código 80, 86, 96, 89, 90, 94...)")
    p_emit.add_argument("--condicion-iva", default=None, metavar="COND",
                        help=(
                            "Condición IVA del receptor. Puede ser un número (RG 5616) "
                            "o un alias: CF=Consumidor Final, RI=Resp. Inscripto, "
                            "MONO/MONOTRIB=Monotributista, EX/EXENTO=Exento, "
                            "RNI=Resp. No Inscripto, NR=No Responsable. "
                            "Si se omite, se infiere según el documento: "
                            "sin CUIT/DNI → CF; DNI → CF; CUIT → RI (o Mono si el padrón lo indica)."
                        ))
    p_emit.add_argument("--condicion-venta", default="Contado", metavar="COND")
    p_emit.add_argument("--fecha", metavar="YYYYMMDD", help="Default: hoy")
    p_emit.add_argument("--periodo-desde", metavar="YYYYMMDD")
    p_emit.add_argument("--periodo-hasta", metavar="YYYYMMDD")
    p_emit.add_argument("--fecha-vto-pago", default=None, metavar="YYYYMMDD",
                        help="Fecha vto. pago para PDF. Default: fecha de emisión")
    p_emit.add_argument("--env", choices=["homo", "prod"], default="homo")
    p_emit.add_argument("--dry-run", action="store_true")
    p_emit.add_argument("--pdf", action="store_true", help="Generar PDF")
    p_emit.add_argument("--duplicado", action="store_true", help="PDF con duplicado")
    p_emit.add_argument("--triplicado", action="store_true", help="PDF con original, duplicado y triplicado")
    p_emit.add_argument("--cuit-emisor", default=None, metavar="CUIT", help="Opcional: sobreescribir el CUIT del emisor para realizar pruebas")

    # --- validar-cuit ---
    p_val = sub.add_parser("validar-cuit", help="Validar formato y existencia de un CUIT")
    p_val.add_argument("cuit", metavar="CUIT")
    p_val.add_argument("--afip", action="store_true",
                       help="Confirmar existencia consultando el padrón A13 de AFIP")
    p_val.add_argument("--env", choices=["homo", "prod"], default="prod")

    # --- nota-credito ---
    p_nc = sub.add_parser("nota-credito", help="Emitir Nota de Crédito (A, B o C)")
    p_nc.add_argument("--tipo", choices=["A", "B", "C"], default="C", help="Tipo: A, B o C")
    p_nc.add_argument("--numero-original", required=True, type=int, metavar="N")
    p_nc.add_argument("--monto", required=True, type=float, metavar="IMPORTE")
    p_nc.add_argument("--env", choices=["homo", "prod"], default="homo")
    p_nc.add_argument("--dry-run", action="store_true")

    # --- nota-debito ---
    p_nd = sub.add_parser("nota-debito", help="Emitir Nota de Débito (A, B o C)")
    p_nd.add_argument("--tipo", choices=["A", "B", "C"], default="C", help="Tipo: A, B o C")
    p_nd.add_argument("--numero-original", required=True, type=int, metavar="N")
    p_nd.add_argument("--monto", required=True, type=float, metavar="IMPORTE")
    p_nd.add_argument("--env", choices=["homo", "prod"], default="homo")
    p_nd.add_argument("--dry-run", action="store_true")

    # --- ultimo-numero ---
    p_un = sub.add_parser("ultimo-numero", help="Consultar el último número emitido")
    p_un.add_argument("--tipo", choices=["A", "B", "C", "NCA", "NCB", "NCC", "NDA", "NDB", "NDC", "NC", "ND"], required=True)
    p_un.add_argument("--env", choices=["homo", "prod"], default="homo")

    # --- buscar ---
    p_bus = sub.add_parser("buscar", help="Buscar comprobantes en AFIP por fecha y/o receptor")
    p_bus.add_argument("--tipo", choices=["A", "B", "C", "NCA", "NCB", "NCC", "NDA", "NDB", "NDC", "NC", "ND"], default="C")
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
    p_con.add_argument("--tipo", choices=["A", "B", "C", "NCA", "NCB", "NCC", "NDA", "NDB", "NDC", "NC", "ND"], default="C")
    p_con.add_argument("--pdf", action="store_true", help="Generar PDF con los datos obtenidos de AFIP")
    p_con.add_argument("--duplicado", action="store_true")
    p_con.add_argument("--triplicado", action="store_true", help="PDF con triplicado")
    p_con.add_argument("--output", metavar="ARCHIVO.pdf")
    p_con.add_argument("--env", choices=["homo", "prod"], default="prod")

    # --- reimprimir ---
    p_reim = sub.add_parser("reimprimir", help="Generar PDF a partir del JSON de una factura emitida")
    p_reim.add_argument("json_file", metavar="ARCHIVO.json|-",
                        help="JSON devuelto por 'emitir', o '-' para leer de stdin")
    p_reim.add_argument("--duplicado", action="store_true", help="PDF con duplicado")
    p_reim.add_argument("--triplicado", action="store_true", help="PDF con triplicado")
    p_reim.add_argument("--output", metavar="ARCHIVO.pdf")
    p_reim.add_argument("--env", choices=["homo", "prod"], default="prod")

    # --- lote ---
    p_lote = sub.add_parser("lote", help="Emitir facturación masiva por lotes desde un archivo CSV")
    p_lote.add_argument("csv_file", metavar="ARCHIVO.csv", help="Ruta al archivo CSV con comprobantes")
    p_lote.add_argument("--env", choices=["homo", "prod"], default="homo", help="Entorno: 'homo' para testing o 'prod' para legal (default: homo)")
    p_lote.add_argument("--dry-run", action="store_true", help="Simulación local sin contactar a AFIP")
    p_lote.add_argument("--pdf", action="store_true", default=True, help="Generar comprobantes en PDF (default: True)")
    p_lote.add_argument("--duplicado", action="store_true", help="Generar ejemplares duplicados")
    p_lote.add_argument("--triplicado", action="store_true", help="Generar ejemplares hasta triplicado")
    p_lote.add_argument("--zip", metavar="SALIDA.zip", default=None, help="Empaquetar todos los PDFs en un archivo ZIP")
    p_lote.add_argument("--cuit-emisor", default=None, metavar="CUIT", help="Opcional: sobreescribir el CUIT del emisor para realizar pruebas")

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
    p_pdf.add_argument("--cuit-cliente", default="SIN_CUIT",
                       help="DNI/CUIT del destinatario. Requerido salvo Consumidor Final sin datos.")
    p_pdf.add_argument("--condicion-venta", default="Contado")
    p_pdf.add_argument("--periodo-desde", metavar="YYYYMMDD")
    p_pdf.add_argument("--periodo-hasta", metavar="YYYYMMDD")
    p_pdf.add_argument("--fecha-vto-pago", default=None, metavar="YYYYMMDD")
    p_pdf.add_argument("--duplicado", action="store_true")
    p_pdf.add_argument("--triplicado", action="store_true", help="PDF con triplicado")
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
        elif args.comando == "lote":
            cmd_lote(args)
    except SystemExit:
        raise
    except Exception as e:
        _output({"error": str(e)}, 1)


if __name__ == "__main__":
    main()
