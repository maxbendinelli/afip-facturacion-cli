from decimal import Decimal

import zeep

from config import Config
from models import InvoiceRequest, InvoiceResponse
from ssl_transport import build_transport


def _build_client(config: Config) -> zeep.Client:
    transport = build_transport(config.wsdl_cache_path)
    return zeep.Client(wsdl=config.wsfev1_wsdl, transport=transport)


def _auth(config: Config, token: str, sign: str) -> dict:
    return {"Token": token, "Sign": sign, "Cuit": config.cuit}


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

    det = {
        "Concepto": req.concepto_afip,
        "DocTipo": req.doc_tipo,
        "DocNro": req.doc_nro,
        "CbteDesde": req.numero,
        "CbteHasta": req.numero,
        "CbteFch": req.fecha,
        "ImpTotal": str(req.monto),
        "ImpTotConc": "0.00",
        "ImpNeto": str(req.monto),
        "ImpOpEx": "0.00",
        "ImpIVA": "0.00",
        "ImpTrib": "0.00",
        "MonId": "PES",
        "MonCotiz": "1",
        "CondicionIVAReceptorId": req.condicion_iva_receptor,
    }

    # Servicios (concepto 2 o 3) requieren fechas de período
    if req.concepto_afip in (2, 3):
        det["FchServDesde"] = req.fecha_serv_desde
        det["FchServHasta"] = req.fecha_serv_hasta
        det["FchVtoPago"] = req.fecha_vto_pago

    # Nota de crédito/débito requiere comprobante asociado
    if req.numero_original is not None:
        det["CbtesAsoc"] = {
            "CbteAsoc": [{
                "Tipo": req.cbte_tipo_original,
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
        monto=req.monto,
        nombre_cliente=req.nombre_cliente,
        cuit_cliente=req.cuit_cliente,
        resultado=det_resp.Resultado,
        doc_tipo=req.doc_tipo,
        condicion_venta=req.condicion_venta,
        condicion_iva_receptor=req.condicion_iva_receptor,
        concepto=req.concepto,
        periodo_desde=req.periodo_desde,
        periodo_hasta=req.periodo_hasta,
        items=req.items,
        observaciones=observaciones,
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
    total = hasta_numero - desde_numero + 1
    client = _build_client(config)

    for i, nro in enumerate(range(desde_numero, hasta_numero + 1), 1):
        sys.stderr.write(f"\rConsultando {nro}/{hasta_numero} ({i}/{total})...    ")
        sys.stderr.flush()
        try:
            resp = client.service.FECompConsultar(
                Auth=_auth(config, token, sign),
                FeCompConsReq={"CbteTipo": cbte_tipo, "CbteNro": nro, "PtoVta": config.punto_venta},
            )
            _check_errors(resp)
            r = resp.ResultGet
        except RuntimeError:
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
            "comprobante": f"{int(r.PtoVta):04d}-{int(r.CbteDesde):08d}",
            "fecha": fecha,
            "monto": str(Decimal(str(r.ImpTotal)).quantize(Decimal("0.01"))),
            "cae": r.CodAutorizacion,
            "cae_vencimiento": r.FchVto,
            "doc_tipo": int(r.DocTipo),
            "doc_nro": doc_nro,
        }
        if r.FchServDesde:
            entry["periodo_desde"] = r.FchServDesde
        if r.FchServHasta:
            entry["periodo_hasta"] = r.FchServHasta
        results.append(entry)

    sys.stderr.write("\n")
    return results


def _check_errors(resp) -> None:
    if hasattr(resp, "Errors") and resp.Errors and resp.Errors.Err:
        msgs = [f"{e.Code}: {e.Msg}" for e in resp.Errors.Err]
        raise RuntimeError(f"Error AFIP: {'; '.join(msgs)}")
