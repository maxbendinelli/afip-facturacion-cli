"""
Generador de PDF para comprobantes electrónicos AFIP/ARCA.
Layout basado en el modelo oficial del facturador online de ARCA.
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
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT

from config import Config
from models import CBTE_NOMBRE, DOC_TIPO_NOMBRE, InvoiceResponse

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

_GREY = colors.Color(0.90, 0.90, 0.90)

_COND_IVA = {
    1: "IVA Responsable Inscripto",
    2: "IVA Responsable No Inscripto",
    3: "IVA No Responsable",
    4: "IVA Exento",
    5: "Consumidor Final",
    6: "Responsable Monotributo",
}


def _fmt_cuit(cuit: str) -> str:
    if len(cuit) == 11:
        return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
    return cuit


def _fmt_fecha(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return yyyymmdd or ""
    return f"{yyyymmdd[6:8]}/{yyyymmdd[4:6]}/{yyyymmdd[:4]}"


def _fmt_num(val) -> str:
    """Formato argentino: 1.234.567,89"""
    try:
        v = Decimal(str(val))
        s = f"{v:,.2f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(val)


def _fmt_hora(hhmmss: str) -> str:
    if not hhmmss or len(hhmmss) < 4:
        return ""
    return f"{hhmmss[:2]}:{hhmmss[2:4]}"


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
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=3, border=1)
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


def _lv(c: canvas.Canvas, x: float, y: float, label: str, value: str, size: float = 8.5) -> float:
    """Dibuja label en negrita + value regular. Retorna el ancho total usado."""
    c.setFont("Helvetica-Bold", size)
    lw = c.stringWidth(label, "Helvetica-Bold", size)
    c.drawString(x, y, label)
    c.setFont("Helvetica", size)
    vw = c.stringWidth(value, "Helvetica", size)
    c.drawString(x + lw, y, value)
    return lw + vw


def _draw_comprobante(c: canvas.Canvas, config: Config, resp: InvoiceResponse,
                      y_start: float, label: str) -> None:
    y = y_start
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.black)
    c.setLineWidth(0.5)

    tipo_nombre = CBTE_NOMBRE.get(resp.cbte_tipo, "Comprobante")
    parts = tipo_nombre.split()
    letra = parts[-1]
    tipo_text = " ".join(parts[:-1]).upper()
    cod_afip = {11: "011", 12: "012", 13: "013"}.get(resp.cbte_tipo, f"0{resp.cbte_tipo:02d}")
    razon = (config.razon_social or "").upper()

    # ── LABEL (ORIGINAL / DUPLICADO / TRIPLICADO) ────────────────────────────
    label_h = 10 * mm
    c.rect(MARGIN, y - label_h, CONTENT_W, label_h)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(MARGIN + CONTENT_W / 2, y - 5 * mm, label)
    y -= label_h

    # ── HEADER BOX ───────────────────────────────────────────────────────────
    BOX_H = 44 * mm
    LEFT_W = CONTENT_W * 0.46
    MID_W = CONTENT_W * 0.09
    RIGHT_W = CONTENT_W - LEFT_W - MID_W
    left_x = MARGIN
    mid_x = left_x + LEFT_W
    right_x = mid_x + MID_W
    box_bot = y - BOX_H

    c.rect(left_x, box_bot, CONTENT_W, BOX_H)
    c.line(mid_x, box_bot, mid_x, y)
    c.line(right_x, box_bot, right_x, y)

    # Columna izquierda
    pad_l = left_x + 3 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(left_x + LEFT_W / 2, y - 8 * mm, razon)

    line_y = box_bot + 3 * mm
    _lv(c, pad_l, line_y, "Condición frente al IVA:  ", "Responsable Monotributo", 8)
    line_y += 5 * mm
    if config.domicilio:
        max_w = LEFT_W - 6 * mm
        lbl_dom = "Domicilio Comercial:  "
        if c.stringWidth(lbl_dom + config.domicilio, "Helvetica", 8) <= max_w:
            _lv(c, pad_l, line_y, lbl_dom, config.domicilio, 8)
            line_y += 5 * mm
        else:
            c.setFont("Helvetica", 8)
            c.drawString(pad_l + 3 * mm, line_y, config.domicilio)
            line_y += 4.5 * mm
            c.setFont("Helvetica-Bold", 8)
            c.drawString(pad_l, line_y, lbl_dom.rstrip())
            line_y += 5 * mm
    _lv(c, pad_l, line_y, "Razón Social:  ", razon, 8)

    # Columna central: letra grande
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(mid_x + MID_W / 2, y - BOX_H / 2 - 2, letra)
    c.setFont("Helvetica", 7)
    c.drawCentredString(mid_x + MID_W / 2, box_bot + 3 * mm, f"COD. {cod_afip}")

    # Columna derecha
    pad_r = right_x + 3 * mm
    tipo_fs = 20 if len(tipo_text) <= 8 else (15 if len(tipo_text) <= 14 else 12)
    c.setFont("Helvetica-Bold", tipo_fs)
    c.drawString(pad_r, y - 9 * mm, tipo_text)

    rline = y - 17 * mm
    _lv(c, pad_r, rline, "Punto de Venta:  ",
        f"{resp.punto_venta:05d}  Comp. Nro:  {resp.numero:08d}", 8)
    rline -= 5 * mm
    fecha_txt = _fmt_fecha(resp.fecha)
    if resp.hora:
        fecha_txt += f"  {_fmt_hora(resp.hora)} hs."
    _lv(c, pad_r, rline, "Fecha de Emisión:  ", fecha_txt, 8)
    rline -= 5 * mm
    _lv(c, pad_r, rline, "CUIT:  ", _fmt_cuit(config.cuit), 8)
    if config.ingresos_brutos:
        rline -= 5 * mm
        _lv(c, pad_r, rline, "Ingresos Brutos:  ", config.ingresos_brutos, 8)
    if config.inicio_actividades:
        rline -= 5 * mm
        _lv(c, pad_r, rline, "Fecha de Inicio de Actividades:  ", config.inicio_actividades, 8)

    y = box_bot

    # ── BARRA PERÍODO ────────────────────────────────────────────────────────
    if resp.periodo_desde and resp.periodo_hasta:
        PH = 7 * mm
        c.setFillColor(_GREY)
        c.rect(MARGIN, y - PH, CONTENT_W, PH, fill=1, stroke=1)
        c.setFillColor(colors.black)
        px = MARGIN + 3 * mm
        py = y - PH / 2 - 1.5 * mm
        used = _lv(c, px, py, "Período Facturado Desde:  ", _fmt_fecha(resp.periodo_desde), 8.5)
        px += used + 5 * mm
        _lv(c, px, py, "Hasta:  ", _fmt_fecha(resp.periodo_hasta), 8.5)
        if resp.fecha_vto_pago:
            vto_lbl = "Fecha de Vto. para el pago:  "
            vto_val = _fmt_fecha(resp.fecha_vto_pago)
            vto_w = (c.stringWidth(vto_lbl, "Helvetica-Bold", 8.5) +
                     c.stringWidth(vto_val, "Helvetica", 8.5))
            _lv(c, MARGIN + CONTENT_W - 3 * mm - vto_w, py, vto_lbl, vto_val, 8.5)
        y -= PH

    # ── BLOQUE COMPRADOR ─────────────────────────────────────────────────────
    BUYER_H = 22 * mm
    BLEFT_W = CONTENT_W * 0.45
    mid_b = MARGIN + BLEFT_W
    c.rect(MARGIN, y - BUYER_H, CONTENT_W, BUYER_H)
    c.line(mid_b, y - BUYER_H, mid_b, y)

    bl = MARGIN + 3 * mm
    br = mid_b + 3 * mm
    by = y - 5.5 * mm
    fs = 8.5
    doc_lbl = DOC_TIPO_NOMBRE.get(resp.doc_tipo, "")
    if doc_lbl and resp.cuit_cliente and resp.cuit_cliente != "0":
        _lv(c, bl, by, f"{doc_lbl}:  ", resp.cuit_cliente, fs)
    by -= 5.5 * mm
    _lv(c, bl, by, "Condición frente al IVA:  ",
        _COND_IVA.get(resp.condicion_iva_receptor, "Consumidor Final"), fs)
    by -= 5.5 * mm
    _lv(c, bl, by, "Condición de venta:  ", resp.condicion_venta, fs)

    # Nombre del receptor: si es largo, achicamos la fuente para que entre
    by2 = y - 5.5 * mm
    nombre_receptor = resp.nombre_cliente or "Consumidor Final"
    right_col_w = CONTENT_W - BLEFT_W - 6 * mm  # espacio disponible
    lbl_rs = "Apellido y Nombre / Razón Social:  "
    lbl_w = c.stringWidth(lbl_rs, "Helvetica-Bold", fs)
    max_nombre_w = right_col_w - lbl_w
    nombre_fs = fs
    while nombre_fs > 6 and c.stringWidth(nombre_receptor, "Helvetica", nombre_fs) > max_nombre_w:
        nombre_fs -= 0.5
    _lv(c, br, by2, lbl_rs, nombre_receptor, nombre_fs)
    by2 -= 5.5 * mm
    # Domicilio: mismo tratamiento
    domicilio_txt = resp.domicilio_cliente or ""
    dom_fs = fs
    lbl_dom = "Domicilio:  "
    lbl_dom_w = c.stringWidth(lbl_dom, "Helvetica-Bold", dom_fs)
    max_dom_w = right_col_w - lbl_dom_w
    while dom_fs > 6 and c.stringWidth(domicilio_txt, "Helvetica", dom_fs) > max_dom_w:
        dom_fs -= 0.5
    _lv(c, br, by2, lbl_dom, domicilio_txt, dom_fs)

    y -= BUYER_H
    y -= 2 * mm

    # ── TABLA DE ÍTEMS (8 columnas) ──────────────────────────────────────────
    col_w = [
        CONTENT_W * 0.055,   # Código
        CONTENT_W * 0.340,   # Producto / Servicio
        CONTENT_W * 0.090,   # Cantidad
        CONTENT_W * 0.110,   # U. Medida
        CONTENT_W * 0.120,   # Precio Unit.
        CONTENT_W * 0.075,   # % Bonif
        CONTENT_W * 0.080,   # Imp. Bonif.
        CONTENT_W * 0.130,   # Subtotal
    ]
    hdr = ["Código", "Producto / Servicio", "Cantidad", "U. Medida",
           "Precio Unit.", "% Bonif", "Imp. Bonif.", "Subtotal"]

    # Estilo para párrafos con word-wrap en la columna de descripción
    _desc_style = ParagraphStyle(
        "ItemDesc",
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
    _desc_hdr_style = ParagraphStyle(
        "ItemDescHdr",
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        alignment=TA_LEFT,
    )

    if resp.items:
        rows = [[
            hdr[0],
            Paragraph(hdr[1], _desc_hdr_style),
            hdr[2], hdr[3], hdr[4], hdr[5], hdr[6], hdr[7],
        ]]
        for item in resp.items:
            rows.append([
                "",
                Paragraph(item.descripcion, _desc_style),
                _fmt_num(item.cantidad),
                "unidades",
                _fmt_num(item.precio_unitario),
                _fmt_num(Decimal("0.00")),
                _fmt_num(Decimal("0.00")),
                _fmt_num(item.subtotal),
            ])
        subtotal = sum(i.subtotal for i in resp.items)
    else:
        rows = [
            [
                hdr[0],
                Paragraph(hdr[1], _desc_hdr_style),
                hdr[2], hdr[3], hdr[4], hdr[5], hdr[6], hdr[7],
            ],
            [
                "",
                Paragraph(resp.concepto or "-", _desc_style),
                _fmt_num(Decimal("1.00")), "unidades",
                _fmt_num(resp.monto),
                _fmt_num(Decimal("0.00")),
                _fmt_num(Decimal("0.00")),
                _fmt_num(resp.monto),
            ],
        ]
        subtotal = resp.monto

    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.black),
        ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 0), ( 1, -1), "LEFT"),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND",    (0, 0), (-1,  0), _GREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
    ]))
    t.wrapOn(c, CONTENT_W, 500 * mm)
    t_h = t._height
    t.drawOn(c, MARGIN, y - t_h)
    y -= t_h + 4 * mm

    # ── TOTALES (tabla de lado a lado) ───────────────────────────────────────
    totals_data = [
        ["Subtotal: $", _fmt_num(subtotal)],
        ["Importe Otros Tributos: $", _fmt_num(Decimal("0.00"))],
        ["Importe Total: $", _fmt_num(resp.monto)],
    ]
    t_tot = Table(totals_data, colWidths=[CONTENT_W * 0.82, CONTENT_W * 0.18])
    t_tot.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, -2), "Helvetica"),
        ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("BOX",           (0, 0), (-1, -1), 0.4, colors.black),
        ("LINEAFTER",     (0, 0), (0, -1), 0.4, colors.black),
        ("LINEBELOW",     (1, 0), (1, -2), 0.4, colors.black),
        ("ALIGN",         (0, 0), (0, -1), "RIGHT"),
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    t_tot.wrapOn(c, CONTENT_W, 50 * mm)
    t_tot_h = t_tot._height
    t_tot.drawOn(c, MARGIN, y - t_tot_h)
    y -= t_tot_h + 5 * mm

    # ── FOOTER ───────────────────────────────────────────────────────────────
    c.setLineWidth(0.3)
    c.line(MARGIN, y, MARGIN + CONTENT_W, y)
    y -= 3 * mm

    qr_size = 25 * mm
    qr_url = _build_qr_url(config, resp)
    qr_path = _qr_png_path(qr_url)
    try:
        c.drawImage(qr_path, MARGIN, y - qr_size, width=qr_size, height=qr_size)
    finally:
        os.unlink(qr_path)

    mid_footer = MARGIN + qr_size + 3 * mm
    c.setFont("Helvetica", 9)
    c.drawCentredString(mid_footer + (CONTENT_W - qr_size - 3 * mm) * 0.30,
                        y - 7 * mm, "Pág. 1/1")

    cae_x = mid_footer + (CONTENT_W - qr_size - 3 * mm) * 0.45
    cae_y = y - 7 * mm
    _lv(c, cae_x, cae_y, "CAE N°:  ", resp.cae, 9)
    cae_y -= 6 * mm
    _lv(c, cae_x, cae_y, "Fecha de Vto. de CAE:  ", _fmt_fecha(resp.cae_vencimiento), 9)

    c.setFont("Helvetica-BoldOblique", 8)
    c.drawString(MARGIN, y - qr_size - 3 * mm, "Comprobante Autorizado")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(MARGIN, y - qr_size - 7.5 * mm,
                 "Esta Agencia no se responsabiliza por los datos ingresados en el detalle de la operación")


def generate_pdf(config: Config, resp: InvoiceResponse, output_path: str,
                 duplicado: bool = False) -> str:
    c = canvas.Canvas(output_path, pagesize=A4)
    _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="ORIGINAL")
    if duplicado:
        c.showPage()
        _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="DUPLICADO")
    c.save()
    return output_path
