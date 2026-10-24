from collections import defaultdict
from decimal import Decimal
from typing import Optional

import zeep

from config import Config
from models import InvoiceItem, InvoiceRequest, InvoiceResponse
from ssl_transport import build_transport


def _build_client(config: Config) -> zeep.Client:
    transport = build_transport(config.wsdl_cache_path)
    return zeep.Client(wsdl=config.wsfev1_wsdl, transport=transport)


def _auth(config: Config, token: str, sign: str) -> dict:
    return {"Token": token, "Sign": sign, "Cuit": config.cuit}


def get_ultimo_comprobante_info(config: Config, token: str, sign: str, cbte_tipo: int) -> tuple[int, str]:
    """Retorna (ultimo_numero, ultima_fecha_yyyymmdd) del punto de venta y tipo."""
    client = _build_client(config)
    auth = _auth(config, token, sign)
    resp = client.service.FECompUltimoAutorizado(
        Auth=auth,
        PtoVta=config.punto_venta,
        CbteTipo=cbte_tipo,
    )
    _check_errors(resp)
    nro = resp.CbteNro or 0
    fch = ""
    if nro > 0:
        try:
            c_resp = client.service.FECompConsultar(
                Auth=auth,
                FeCompConsReq={
                    "PtoVta": config.punto_venta,
                    "CbteTipo": cbte_tipo,
                    "CbteNro": nro,
                },
            )
            if c_resp and c_resp.ResultGet:
                fch = c_resp.ResultGet.CbteFch or ""
        except Exception:
            pass
    return nro, fch


def get_ultimo_numero(config: Config, token: str, sign: str, cbte_tipo: int) -> int:
    client = _build_client(config)
    resp = client.service.FECompUltimoAutorizado(
        Auth=_auth(config, token, sign),
        PtoVta=config.punto_venta,
        CbteTipo=cbte_tipo,
    )
    _check_errors(resp)
    return int(resp.CbteNro)


def solicitar_cae(config: Config, token: str, sign: str, req: InvoiceRequest) -> InvoiceResponse:
    client = _build_client(config)

    # Comprobantes tipo A (1, 2, 3, 4) y B (6, 7, 8, 9) calculan IVA ante AFIP
    is_iva_discriminated = req.cbte_tipo in (1, 2, 3, 4, 6, 7, 8, 9)
    es_tipo_a = req.cbte_tipo in (1, 2, 3, 4)
    es_tipo_b = req.cbte_tipo in (6, 7, 8, 9)

    imp_neto = req.imp_neto
    imp_iva = req.imp_iva
    ivas = list(req.ivas) if req.ivas else []

    if is_iva_discriminated:
        if imp_neto is None or imp_iva is None:
            if req.items:
                alics = defaultdict(lambda: {"base": Decimal("0.00"), "iva": Decimal("0.00")})
                imp_op_ex_items = Decimal("0.00")

                if es_tipo_a:
                    # En Factura A, los precios ingresados son NETOS GRAVADOS (sin IVA).
                    # El IVA se calcula y se suma sobre el precio neto.
                    for it in req.items:
                        alic_id = getattr(it, "alicuota_iva_id", 5)
                        alic_val = getattr(it, "alicuota_iva", Decimal("21.0"))
                        if alic_id == 3 or alic_val == Decimal("0.0"):
                            imp_op_ex_items += it.subtotal
                        else:
                            alics[alic_id]["base"] += it.subtotal
                            alics[alic_id]["iva"] += it.iva_monto
                    imp_neto = sum(d["base"] for d in alics.values())
                    imp_iva = sum(d["iva"] for d in alics.values())
                    imp_total = imp_neto + imp_iva + req.imp_trib + req.imp_op_ex + req.imp_tot_conc
                else:
                    # En Factura B, los precios ingresados son FINALES con IVA incluido.
                    # El total a pagar es la suma de los ítems. El IVA se desglosa internamente para AFIP.
                    items_by_alic = defaultdict(lambda: {"total": Decimal("0.00"), "porc": Decimal("21.0")})
                    for it in req.items:
                        alic_id = getattr(it, "alicuota_iva_id", 5)
                        alic_val = getattr(it, "alicuota_iva", Decimal("21.0"))
                        if alic_id == 3 or alic_val == Decimal("0.0"):
                            imp_op_ex_items += it.subtotal
                        else:
                            items_by_alic[alic_id]["total"] += it.subtotal
                            items_by_alic[alic_id]["porc"] = alic_val

                    for alic_id, data in items_by_alic.items():
                        tot_alic = data["total"]
                        factor = Decimal("1.00") + (data["porc"] / Decimal("100"))
                        base_alic = (tot_alic / factor).quantize(Decimal("0.01"))
                        iva_alic = tot_alic - base_alic
                        alics[alic_id]["base"] = base_alic
                        alics[alic_id]["iva"] = iva_alic

                    imp_neto = sum(d["base"] for d in alics.values())
                    imp_iva = sum(d["iva"] for d in alics.values())
                    imp_total = sum(it.subtotal for it in req.items) + req.imp_trib + req.imp_tot_conc

                if imp_op_ex_items > 0 and req.imp_op_ex == 0:
                    req.imp_op_ex = imp_op_ex_items

                ivas = [
                    {
                        "Id": alic_id,
                        "BaseImp": str(data["base"]),
                        "Importe": str(data["iva"]),
                    }
                    for alic_id, data in alics.items()
                    if alic_id != 3 and data["iva"] > 0
                ]
            else:
                # Sin detalle de ítems (monto directo)
                imp_neto = (req.monto / Decimal("1.21")).quantize(Decimal("0.01"))
                imp_iva = (req.monto - imp_neto).quantize(Decimal("0.01"))
                ivas = [{
                    "Id": 5,
                    "BaseImp": str(imp_neto),
                    "Importe": str(imp_iva),
                }]
                imp_total = imp_neto + imp_iva + req.imp_trib + req.imp_op_ex + req.imp_tot_conc
        else:
            imp_total = imp_neto + imp_iva + req.imp_trib + req.imp_op_ex + req.imp_tot_conc
    else:
        # Factura C
        imp_total = req.monto
        imp_neto = req.monto
        imp_iva = Decimal("0.00")
        ivas = []

    det = {
        "Concepto": req.concepto_afip,
        "DocTipo": req.doc_tipo,
        "DocNro": req.doc_nro,
        "CbteDesde": req.numero,
        "CbteHasta": req.numero,
        "CbteFch": req.fecha,
        "ImpTotal": str(imp_total),
        "ImpTotConc": str(req.imp_tot_conc),
        "ImpNeto": str(imp_neto),
        "ImpOpEx": str(req.imp_op_ex),
        "ImpIVA": str(imp_iva),
        "ImpTrib": str(req.imp_trib),
        "MonId": "PES",
        "MonCotiz": "1",
        "CondicionIVAReceptorId": req.condicion_iva_receptor,
    }

    if is_iva_discriminated and ivas:
        det["Iva"] = {"AlicIva": ivas}

    # Servicios (concepto 2 o 3) requieren fechas de período
    if req.concepto_afip in (2, 3):
        det["FchServDesde"] = req.fecha_serv_desde
        det["FchServHasta"] = req.fecha_serv_hasta
        det["FchVtoPago"] = req.fecha_vto_pago

    # Nota de crédito/débito requiere comprobante asociado
    if req.numero_original is not None:
        det["CbtesAsoc"] = {
            "CbteAsoc": [{
                "Tipo": req.cbte_tipo_original or req.cbte_tipo,
                "PtoVta": config.punto_venta,
                "Nro": req.numero_original,
                "Cuit": config.cuit,
            }]
        }

    resp = client.service.FECAESolicitar(
        Auth=_auth(config, token, sign),
        FeCAEReq={
            "FeCabReq": {
                "CantReg": 1,
                "PtoVta": config.punto_venta,
                "CbteTipo": req.cbte_tipo,
            },
            "FeDetReq": {"FECAEDetRequest": [det]},
        },
    )

    _check_errors(resp)

    det_resp = resp.FeDetResp.FECAEDetResponse[0]
    observaciones = []
    if det_resp.Observaciones and det_resp.Observaciones.Obs:
        observaciones = [
            f"{o.Code}: {o.Msg}" for o in det_resp.Observaciones.Obs
        ]

    if det_resp.Resultado == "R":
        raise RuntimeError(
            f"CAE rechazado. Observaciones: {'; '.join(observaciones) or 'sin detalle'}"
        )

    return InvoiceResponse(
        cae=det_resp.CAE,
        cae_vencimiento=det_resp.CAEFchVto,
        numero=int(det_resp.CbteDesde),
        cbte_tipo=req.cbte_tipo,
        punto_venta=config.punto_venta,
        fecha=det_resp.CbteFch,
        monto=imp_total,
        nombre_cliente=req.nombre_cliente,
        cuit_cliente=req.cuit_cliente,
        resultado=det_resp.Resultado,
        doc_tipo=req.doc_tipo,
        condicion_venta=req.condicion_venta,
        condicion_iva_receptor=req.condicion_iva_receptor,
        concepto=req.concepto,
        periodo_desde=req.periodo_desde,
        periodo_hasta=req.periodo_hasta,
        domicilio_cliente=req.domicilio_cliente,
        items=req.items,
        observaciones=observaciones,
        imp_neto=imp_neto,
        imp_iva=imp_iva,
        imp_trib=req.imp_trib,
        imp_op_ex=req.imp_op_ex,
        ivas=ivas,
    )


def consultar_comprobante(config: Config, token: str, sign: str, cbte_tipo: int, numero: int) -> dict:
    client = _build_client(config)
    resp = client.service.FECompConsultar(
        Auth=_auth(config, token, sign),
        FeCompConsReq={
            "CbteTipo": cbte_tipo,
            "CbteNro": numero,
            "PtoVta": config.punto_venta,
        },
    )
    _check_errors(resp)
    r = resp.ResultGet
    fch_proceso = str(r.FchProceso or "")
    hora = fch_proceso[8:14] if len(fch_proceso) >= 14 else None

    data = {
        "numero": int(r.CbteDesde),
        "cbte_tipo": int(r.CbteTipo),
        "punto_venta": int(r.PtoVta),
        "fecha": r.CbteFch,
        "monto": str(Decimal(str(r.ImpTotal)).quantize(Decimal("0.01"))),
        "cae": r.CodAutorizacion,
        "cae_vencimiento": r.FchVto,
        "doc_tipo": int(r.DocTipo),
        "doc_nro": str(r.DocNro),
        "concepto_afip": int(r.Concepto),
        "condicion_iva_receptor": int(r.CondicionIVAReceptorId or 5),
        "resultado": r.Resultado,
    }
    if hasattr(r, "ImpNeto") and r.ImpNeto is not None:
        data["imp_neto"] = str(Decimal(str(r.ImpNeto)).quantize(Decimal("0.01")))
    if hasattr(r, "ImpIVA") and r.ImpIVA is not None:
        data["imp_iva"] = str(Decimal(str(r.ImpIVA)).quantize(Decimal("0.01")))
    if hasattr(r, "ImpTrib") and r.ImpTrib is not None:
        data["imp_trib"] = str(Decimal(str(r.ImpTrib)).quantize(Decimal("0.01")))
    if hasattr(r, "ImpOpEx") and r.ImpOpEx is not None:
        data["imp_op_ex"] = str(Decimal(str(r.ImpOpEx)).quantize(Decimal("0.01")))
    if hora:
        data["hora"] = hora
    if r.FchServDesde:
        data["periodo_desde"] = r.FchServDesde
    if r.FchServHasta:
        data["periodo_hasta"] = r.FchServHasta
    return data


def buscar_rango(
    config: Config,
    token: str,
    sign: str,
    cbte_tipo: int,
    desde_numero: int = 1,
    hasta_numero: int | None = None,
    desde_fecha: str | None = None,
    hasta_fecha: str | None = None,
    receptor: str | None = None,
) -> list[dict]:
    import sys

    if hasta_numero is None:
        hasta_numero = get_ultimo_numero(config, token, sign, cbte_tipo)

    receptor_norm = receptor.strip().replace("-", "").replace(" ", "") if receptor else None

    results = []
    client = _build_client(config)

    for nro in range(desde_numero, hasta_numero + 1):
        try:
            resp = client.service.FECompConsultar(
                Auth=_auth(config, token, sign),
                FeCompConsReq={"CbteTipo": cbte_tipo, "CbteNro": nro, "PtoVta": config.punto_venta},
            )
            _check_errors(resp)
            r = resp.ResultGet
        except (RuntimeError, Exception):
            continue

        fecha = r.CbteFch or ""
        if desde_fecha and fecha < desde_fecha:
            continue
        if hasta_fecha and fecha > hasta_fecha:
            continue

        doc_nro = str(r.DocNro or "0")
        if receptor_norm and doc_nro != receptor_norm:
            continue

        entry = {
            "numero": int(r.CbteDesde),
            "cbte_tipo": int(r.CbteTipo),
            "punto_venta": int(r.PtoVta),
            "comprobante": f"{int(r.PtoVta):04d}-{int(r.CbteDesde):08d}",
            "fecha": fecha,
            "monto": str(Decimal(str(r.ImpTotal)).quantize(Decimal("0.01"))),
            "cae": r.CodAutorizacion,
            "cae_vencimiento": r.FchVto,
            "doc_tipo": int(r.DocTipo),
            "doc_nro": doc_nro,
        }
        if hasattr(r, "ImpNeto") and r.ImpNeto is not None:
            entry["imp_neto"] = str(Decimal(str(r.ImpNeto)).quantize(Decimal("0.01")))
        if hasattr(r, "ImpIVA") and r.ImpIVA is not None:
            entry["imp_iva"] = str(Decimal(str(r.ImpIVA)).quantize(Decimal("0.01")))
        if r.FchServDesde:
            entry["periodo_desde"] = r.FchServDesde
        if r.FchServHasta:
            entry["periodo_hasta"] = r.FchServHasta
        results.append(entry)

    return results


def _check_errors(resp) -> None:
    if hasattr(resp, "Errors") and resp.Errors and resp.Errors.Err:
        msgs = [f"{e.Code}: {e.Msg}" for e in resp.Errors.Err]
        raise RuntimeError(f"Error AFIP: {'; '.join(msgs)}")
