"""
Generador de PDF para comprobantes electrónicos AFIP/ARCA.
Layout estándar con QR de verificación, soporte de duplicado y período facturado.
"""
import base64
import io
import json
import os
import tempfile
from decimal import Decimal

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

from config import Config
from models import CBTE_NOMBRE, DOC_TIPO_NOMBRE, InvoiceResponse

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _fmt_cuit(cuit: str) -> str:
    if len(cuit) == 11:
        return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
    return cuit


def _fmt_fecha(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return yyyymmdd or ""
    return f"{yyyymmdd[6:8]}/{yyyymmdd[4:6]}/{yyyymmdd[:4]}"


def _fmt_monto(monto) -> str:
    try:
        val = Decimal(str(monto))
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"$ {formatted}"
    except Exception:
        return f"$ {monto}"


def _build_qr_url(config: Config, resp: InvoiceResponse) -> str:
    payload = {
        "ver": 1,
        "fecha": f"{resp.fecha[:4]}-{resp.fecha[4:6]}-{resp.fecha[6:]}",
        "cuit": int(config.cuit),
        "ptoVta": resp.punto_venta,
        "tipoCmp": resp.cbte_tipo,
        "nroCmp": resp.numero,
        "importe": float(resp.monto),
        "moneda": "PES",
        "ctz": 1,
        "tipoDocRec": resp.doc_tipo,
        "nroDocRec": int(resp.cuit_cliente) if resp.cuit_cliente.isdigit() else 0,
        "tipoCodAut": "E",
        "codAut": int(resp.cae),
    }
    b64 = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return f"https://www.afip.gob.ar/fe/qr/?p={b64}"


def _qr_png_path(url: str) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=3,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(buf.read())
    tmp.close()
    return tmp.name


_COND_IVA_RECEPTOR = {
    1: "IVA RESPONSABLE INSCRIPTO",
    2: "IVA RESPONSABLE NO INSCRIPTO",
    3: "IVA NO RESPONSABLE",
    4: "IVA EXENTO",
    5: "A CONSUMIDOR FINAL",
    6: "RESPONSABLE MONOTRIBUTO",
}


def _fmt_hora(hhmmss: str) -> str:
    if not hhmmss or len(hhmmss) < 4:
        return ""
    return f"{hhmmss[:2]}:{hhmmss[2:4]}"


def _draw_comprobante(c: canvas.Canvas, config: Config, resp: InvoiceResponse,
                      y_start: float, label: str) -> None:
    """Dibuja un comprobante completo en el canvas a partir de y_start."""
    y = y_start
    tipo_nombre = CBTE_NOMBRE.get(resp.cbte_tipo, "Comprobante")
    letra = tipo_nombre.split()[-1]
    cod_afip = {11: "11", 12: "12", 13: "13"}.get(resp.cbte_tipo, "")
    comprobante_num = f"{resp.punto_venta:04d}-{resp.numero:08d}"

    # ── Etiqueta ORIGINAL / DUPLICADO ────────────────────────────────────────
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(MARGIN + CONTENT_W, y, label)
    y -= 5 * mm

    # ── ENCABEZADO ───────────────────────────────────────────────────────────
    box_h = 48 * mm
    left_w = CONTENT_W * 0.60
    mid_w = CONTENT_W * 0.10
    right_w = CONTENT_W * 0.30

    left_x = MARGIN
    mid_x = left_x + left_w
    right_x = mid_x + mid_w

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)

    # Bloque emisor (Sector A)
    tiene_logo = bool(config.logo_path and os.path.isfile(config.logo_path))
    tiene_marca = bool(config.nombre_fantasia or tiene_logo)
    pad = left_x + 3 * mm
    box_bot = y - box_h

    c.rect(left_x, box_bot, left_w, box_h)

    # Marca (logo o nombre de fantasía) en la parte superior
    if tiene_logo:
        logo_max_h = 22 * mm
        logo_max_w = 40 * mm
        c.drawImage(
            config.logo_path, pad, y - 3 * mm - logo_max_h,
            width=logo_max_w, height=logo_max_h,
            preserveAspectRatio=True, anchor="sw", mask="auto",
        )
    elif config.nombre_fantasia:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(pad, y - 9 * mm, config.nombre_fantasia)

    # Datos legales pegados al fondo, de abajo hacia arriba
    dom_fiscal = config.domicilio_fiscal or config.domicilio
    lineas = []
    if dom_fiscal:
        lineas.append(f"Dom. Fiscal: {dom_fiscal}")
    if config.domicilio:
        lineas.append(f"Dom. Comercial: {config.domicilio}")
    if config.inicio_actividades:
        lineas.append(f"Inicio de actividades: {config.inicio_actividades}")
    if config.ingresos_brutos:
        lineas.append(f"Ing. Brutos: {config.ingresos_brutos}")
    lineas.append(f"CUIT: {_fmt_cuit(config.cuit)}")
    lineas.append("RESPONSABLE MONOTRIBUTO")
    if tiene_marca and config.razon_social:
        lineas.append(f"de {config.razon_social}")

    c.setFont("Helvetica", 8)
    line_y = box_bot + 3 * mm
    for linea in lineas:
        c.drawString(pad, line_y, linea)
        line_y += 5 * mm

    # Bloque letra
    c.rect(mid_x, box_bot, mid_w, box_h)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(mid_x + mid_w / 2, y - box_h / 2 - 4, letra)
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(mid_x + mid_w / 2, box_bot + 3 * mm, f"COD. {cod_afip}")

    # Bloque número/fecha pegados al fondo (Sector A derecho)
    fecha_hora = _fmt_fecha(resp.fecha)
    if resp.hora:
        fecha_hora += f"  {_fmt_hora(resp.hora)} hs."
    c.rect(right_x, box_bot, right_w, box_h)
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(right_x + right_w / 2, box_bot + 10 * mm, f"Fecha: {fecha_hora}")
    c.drawCentredString(right_x + right_w / 2, box_bot + 16 * mm, f"Nro.: {comprobante_num}")
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(right_x + right_w / 2, box_bot + 22 * mm, tipo_nombre.upper())

    y -= box_h + 5 * mm

    # ── PERÍODO FACTURADO ─────────────────────────────────────────────────────
    if resp.periodo_desde and resp.periodo_hasta:
        c.setFont("Helvetica", 8)
        periodo_txt = (
            f"Período facturado: {_fmt_fecha(resp.periodo_desde)} "
            f"al {_fmt_fecha(resp.periodo_hasta)}"
        )
        c.drawString(MARGIN, y, periodo_txt)
        y -= 6 * mm

    # ── DATOS DEL COMPRADOR (Sector B) ───────────────────────────────────────
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(MARGIN, y, "DATOS DEL COMPRADOR")
    c.line(MARGIN, y - 1.5 * mm, MARGIN + CONTENT_W, y - 1.5 * mm)
    y -= 6 * mm

    c.setFont("Helvetica", 8.5)
    nombre_display = resp.nombre_cliente or "Consumidor Final"
    c.drawString(MARGIN, y, f"Apellido y Nombre / Razón Social:  {nombre_display}")
    y -= 5 * mm

    if resp.cuit_cliente and resp.cuit_cliente != "0":
        doc_label = DOC_TIPO_NOMBRE.get(resp.doc_tipo, "Doc.")
        c.drawString(MARGIN, y, f"{doc_label}:  {_fmt_cuit(resp.cuit_cliente)}")
        y -= 5 * mm

    cond_iva_label = _COND_IVA_RECEPTOR.get(resp.condicion_iva_receptor, "A CONSUMIDOR FINAL")
    c.drawString(MARGIN, y, f"Condición IVA:  {cond_iva_label}")
    y -= 5 * mm

    if resp.domicilio_cliente:
        c.drawString(MARGIN, y, f"Domicilio:  {resp.domicilio_cliente}")
        y -= 5 * mm

    y -= 3 * mm

    # ── DETALLE (Sector C) ───────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(MARGIN, y, "DESCRIPCIÓN / CONCEPTO")
    c.line(MARGIN, y - 1.5 * mm, MARGIN + CONTENT_W, y - 1.5 * mm)
    y -= 6 * mm

    col_widths = [CONTENT_W * 0.45, CONTENT_W * 0.15, CONTENT_W * 0.15, CONTENT_W * 0.25]

    if resp.items:
        table_data = [["Descripción", "Cant.", "Precio Unit.", "Subtotal"]]
        for item in resp.items:
            table_data.append([
                item.descripcion,
                str(item.cantidad),
                _fmt_monto(item.precio_unitario),
                _fmt_monto(item.subtotal),
            ])
    else:
        col_widths = [CONTENT_W * 0.75, CONTENT_W * 0.25]
        table_data = [
            ["Descripción", "Importe"],
            [resp.concepto or "-", _fmt_monto(resp.monto)],
        ]

    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.88, 0.88, 0.88)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    t.wrapOn(c, CONTENT_W, 50 * mm)
    t_h = t._height
    t.drawOn(c, MARGIN, y - t_h)
    y -= t_h + 3 * mm

    # ── TOTAL ────────────────────────────────────────────────────────────────
    total_data = [["IMPORTE TOTAL", _fmt_monto(resp.monto)]]
    t2 = Table(total_data, colWidths=col_widths)
    t2.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.Color(0.80, 0.80, 0.80)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    t2.wrapOn(c, CONTENT_W, 20 * mm)
    t2_h = t2._height
    t2.drawOn(c, MARGIN, y - t2_h)
    y -= t2_h + 5 * mm

    # ── RECIBI/MOS (Sector D) ────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(MARGIN, y, f"RECIBI/MOS:  {resp.condicion_venta}")
    y -= 8 * mm

    # ── CAE + QR ─────────────────────────────────────────────────────────────
    c.setLineWidth(0.3)
    c.line(MARGIN, y, MARGIN + CONTENT_W, y)
    y -= 5 * mm

    qr_url = _build_qr_url(config, resp)
    qr_path = _qr_png_path(qr_url)
    try:
        qr_size = 30 * mm
        c.drawImage(qr_path, MARGIN, y - qr_size, width=qr_size, height=qr_size)
    finally:
        os.unlink(qr_path)

    c.setFont("Helvetica-Bold", 8)
    tx = MARGIN + qr_size + 5 * mm
    c.drawString(tx, y - 7 * mm, f"CAE N°: {resp.cae}")
    c.setFont("Helvetica", 8)
    c.drawString(tx, y - 13 * mm, f"Fecha de vencimiento CAE: {_fmt_fecha(resp.cae_vencimiento)}")
    c.setFont("Helvetica", 7)
    c.drawString(tx, y - 19 * mm, "Comprobante autorizado por ARCA")
    c.drawString(tx, y - 24 * mm, "Escanee el QR para verificar en afip.gob.ar")


def generate_pdf(config: Config, resp: InvoiceResponse, output_path: str,
                 duplicado: bool = False) -> str:
    c = canvas.Canvas(output_path, pagesize=A4)

    # Página 1: ORIGINAL
    _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="ORIGINAL")

    if duplicado:
        c.showPage()
        _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="DUPLICADO")

    c.save()
    return output_path
