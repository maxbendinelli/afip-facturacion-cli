"""
Generador de PDF para comprobantes electrónicos AFIP/ARCA (Facturas A, B, C, NC y ND).
Layout basado en el modelo oficial del facturador online de ARCA con soporte para
personalización: Logo, Leyenda / Datos bancarios y Marca de agua (Watermark).
"""
import base64
from collections import defaultdict
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Optional
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
from models import (
    CBTE_NOMBRE,
    CBTE_LETRA,
    DOC_TIPO_NOMBRE,
    InvoiceResponse,
    IVA_ALICUOTAS,
    COND_IVA_TODAS,
    COND_IVA_ALIAS,
)

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

_GREY = colors.Color(0.90, 0.90, 0.90)

_COND_IVA = COND_IVA_TODAS


def is_consumidor_final(nombre: Optional[str]) -> bool:
    """Determina si el cliente es Consumidor Final o sin identificar."""
    if not nombre:
        return True
    clean = re.sub(r"[^a-zA-Z0-9]+", "", str(nombre)).lower()
    return clean in {
        "",
        "consumidorfinal",
        "consumidorfinalejemplo",
        "cf",
        "sinidentificar",
        "sincuit",
        "sinnombre",
        "clienteocasional",
    }


def sanitize_nombre_archivo(nombre: Optional[str]) -> str:
    """Limpia el nombre y apellido del cliente para generar un nombre de archivo seguro."""
    if not nombre:
        return ""
    s = str(nombre).strip()
    s = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


_TIPO_CBTE_ABREV = {
    1: "F", 6: "F", 11: "F",
    2: "ND", 7: "ND", 12: "ND",
    3: "NC", 8: "NC", 13: "NC",
    4: "R", 9: "R", 15: "R",
}


def _nombre_para_archivo(nombre: Optional[str], max_len: int = 60) -> str:
    """Nombre del cliente apto para nombre de archivo (ASCII, sin caracteres reservados)."""
    if not nombre:
        return ""
    s = unicodedata.normalize("NFKD", str(nombre))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r'[\\/:*?"<>|%#\r\n\t]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    return s


def format_pdf_filename(
    nombre_cliente: Optional[str] = None,
    fecha: Optional[str] = None,
    hora: Optional[str] = None,
    directory: Optional[Path] = None,
    *,
    cbte_tipo: Optional[int] = None,
    cuit_emisor: Optional[str] = None,
    punto_venta: Optional[int] = None,
    numero: Optional[int] = None,
    periodo_desde: Optional[str] = None,
) -> str:
    """
    Genera el nombre de archivo PDF.

    Con los datos del comprobante (cbte_tipo, cuit_emisor, punto_venta y numero):
      AAAA-MM-DD Fact. AAAA-MM <Cliente> <J>.<Z>. <CUIT emisor>_<cod 3d>_<PV 5d>_<Nro 8d>.pdf
      ej: 2026-10-28 Fact. 2026-10 M. Bendinelli F.B. 23255684779_006_00003_00000123.pdf
      J = F / NC / ND (tipo de comprobante), Z = letra (A, B o C).
      Si es consumidor final / sin identificar se omite el nombre del cliente.

    Sin esos datos (compatibilidad):
      YYYYMMDDHHMMSS-Nombre-Apellido.pdf  (o YYYYMMDDHHMMSS.pdf)
    """
    now = datetime.now()
    f_str = str(fecha).strip() if fecha else ""
    h_str = str(hora).strip() if hora else ""

    date_part = f_str if (len(f_str) == 8 and f_str.isdigit()) else now.strftime("%Y%m%d")

    if cbte_tipo is not None and cuit_emisor and punto_venta is not None and numero is not None:
        p_str = str(periodo_desde).strip() if periodo_desde else ""
        period_part = p_str[:6] if (len(p_str) >= 6 and p_str[:6].isdigit()) else date_part[:6]
        tipo_j = _TIPO_CBTE_ABREV.get(int(cbte_tipo), "F")
        letra_z = CBTE_LETRA.get(int(cbte_tipo), "C")
        cuit_s = re.sub(r"\D", "", str(cuit_emisor))

        partes = [
            f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}",
            "Fact.",
            f"{period_part[:4]}-{period_part[4:6]}",
        ]
        if not is_consumidor_final(nombre_cliente):
            nom = _nombre_para_archivo(nombre_cliente)
        else:
            nom = "Consumidor Final"
        if nom:
            partes.append(nom)
        partes.append(f"{tipo_j}.{letra_z}.")
        partes.append(f"{cuit_s}_{int(cbte_tipo):03d}_{int(punto_venta):05d}_{int(numero):08d}")
        base_name = " ".join(partes)
    else:
        time_part = h_str if (len(h_str) == 6 and h_str.isdigit()) else now.strftime("%H%M%S")
        ts = f"{date_part}{time_part}"
        if is_consumidor_final(nombre_cliente):
            base_name = ts
        else:
            safe_name = sanitize_nombre_archivo(nombre_cliente)
            base_name = f"{ts}-{safe_name}" if safe_name else ts

    filename = f"{base_name}.pdf"

    if directory:
        d = Path(directory)
        candidate = filename
        counter = 1
        while (d / candidate).exists():
            candidate = f"{base_name}_{counter}.pdf"
            counter += 1
        filename = candidate

    return filename


def pdf_filename_for(config: Config, resp: InvoiceResponse, directory: Optional[Path] = None,
                     reuse_existing: bool = False) -> str:
    """Nombre de archivo estándar para un comprobante ya emitido (o simulado).

    Con reuse_existing=True, si el archivo ya existe se devuelve el mismo nombre (se sobreescribe)
    en lugar de agregar un sufijo numérico.
    """
    kwargs = dict(
        cbte_tipo=resp.cbte_tipo,
        cuit_emisor=config.cuit,
        punto_venta=resp.punto_venta,
        numero=resp.numero,
        periodo_desde=resp.periodo_desde,
    )
    if reuse_existing:
        return format_pdf_filename(resp.nombre_cliente, fecha=resp.fecha, hora=resp.hora, **kwargs)
    return format_pdf_filename(resp.nombre_cliente, fecha=resp.fecha, hora=resp.hora,
                               directory=directory, **kwargs)


def _wrap_text(c: canvas.Canvas, text: str, font: str, size: float,
               first_w: float, rest_w: float) -> list:
    """Corte de línea por palabras; la 1.ª línea tiene first_w y el resto rest_w."""
    first_w = max(first_w, 20.0)
    rest_w = max(rest_w, 20.0)
    words = str(text or "").replace("\n", " ").split()
    lines: list = []
    cur = ""
    width = first_w
    for w in words:
        trial = f"{cur} {w}" if cur else w
        if c.stringWidth(trial, font, size) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
            width = rest_w
        while len(w) > 1 and c.stringWidth(w, font, size) > width:
            n = len(w)
            while n > 1 and c.stringWidth(w[:n], font, size) > width:
                n -= 1
            lines.append(w[:n])
            w = w[n:]
            width = rest_w
        cur = w
    if cur or not lines:
        lines.append(cur)
    return lines


def _fmt_cuit(cuit: str) -> str:
    cuit = str(cuit).strip()
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
        "nroDocRec": int(resp.cuit_cliente) if str(resp.cuit_cliente).isdigit() else 0,
        "tipoCodAut": "E",
        "codAut": int(resp.cae) if str(resp.cae).isdigit() else 74251829304918,
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


def _iva_contenido(resp: InvoiceResponse) -> Decimal:
    """IVA total del comprobante. Prueba, en orden: ImpIVA, alícuotas informadas,
    desglose de ítems y diferencia total - neto - otros importes."""
    zero = Decimal("0.00")

    def _dec(v) -> Decimal:
        try:
            return Decimal(str(v))
        except Exception:
            return zero

    imp_iva = _dec(getattr(resp, "imp_iva", None) or 0)
    if imp_iva > zero:
        return imp_iva

    if getattr(resp, "ivas", None):
        total = sum((_dec(iv.get("Importe", 0)) for iv in resp.ivas), zero)
        if total > zero:
            return total

    total_items = zero
    for it in getattr(resp, "items", None) or []:
        alic_id = getattr(it, "alicuota_iva_id", 5)
        alic = _dec(getattr(it, "alicuota_iva", 0))
        if getattr(it, "tipo_iva", "iva") != "iva" or alic_id in (1, 2, 3) or alic <= zero:
            continue
        if resp.cbte_tipo in (1, 2, 3, 4):
            total_items += _dec(it.iva_monto)           # precio neto: IVA se suma
        else:
            bruto = _dec(it.subtotal)                   # precio final: IVA contenido
            neto = (bruto / (Decimal("1") + alic / Decimal("100"))).quantize(Decimal("0.01"))
            total_items += bruto - neto
    if total_items > zero:
        return total_items

    if getattr(resp, "imp_neto", None) is not None:
        calc = (_dec(resp.monto) - _dec(resp.imp_neto) - _dec(getattr(resp, "imp_trib", None) or 0)
                - _dec(getattr(resp, "imp_op_ex", None) or 0) - _dec(getattr(resp, "imp_tot_conc", None) or 0))
        if calc > zero:
            return calc
    return zero


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
    # ── MARCA DE AGUA (WATERMARK) ───────────────────────────────────────────
    if config.watermark_text:
        c.saveState()
        c.setFont("Helvetica-Bold", 46)
        c.setFillColor(colors.Color(0.88, 0.88, 0.88, alpha=0.18))
        c.translate(PAGE_W / 2, PAGE_H / 2)
        c.rotate(45)
        c.drawCentredString(0, 0, config.watermark_text.upper())
        c.restoreState()

    wm_file = _resolve_image_path(config.watermark_image)
    if wm_file:
        c.saveState()
        try:
            wm_w = 90 * mm
            wm_h = 90 * mm
            c.drawImage(wm_file, (PAGE_W - wm_w) / 2, (PAGE_H - wm_h) / 2,
                        width=wm_w, height=wm_h, mask='auto', preserveAspectRatio=True)
        except Exception:
            pass
        c.restoreState()

    y = y_start
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.black)
    c.setLineWidth(0.5)

    tipo_nombre = CBTE_NOMBRE.get(resp.cbte_tipo, "Comprobante")
    parts = tipo_nombre.split()
    letra = CBTE_LETRA.get(resp.cbte_tipo, parts[-1] if parts else "C")
    tipo_text = " ".join(parts[:-1]).upper() if len(parts) > 1 else tipo_nombre.upper()
    cod_afip = f"{resp.cbte_tipo:03d}"
    razon = (config.razon_social or "").upper()

    # Condición IVA Emisor
    cond_emisor = config.condicion_iva_emisor
    if cond_emisor and str(cond_emisor).strip().isdigit():
        cond_emisor = _COND_IVA.get(int(str(cond_emisor).strip()), cond_emisor)
    elif cond_emisor and cond_emisor.strip().upper() in COND_IVA_ALIAS:
        cond_emisor = _COND_IVA.get(COND_IVA_ALIAS[cond_emisor.strip().upper()], cond_emisor)

    if not cond_emisor:
        if resp.cbte_tipo in (1, 2, 3, 4, 6, 7, 8, 9):
            cond_emisor = "IVA Responsable Inscripto"
        else:
            cond_emisor = "Responsable Monotributo"

    # ── LABEL (ORIGINAL / DUPLICADO / TRIPLICADO) ────────────────────────────
    label_h = 10 * mm
    c.rect(MARGIN, y - label_h, CONTENT_W, label_h)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(MARGIN + CONTENT_W / 2, y - 5 * mm, label)
    y -= label_h

    # ── HEADER BOX ───────────────────────────────────────────────────────────
    # Logo (tamaño configurable): se resuelve antes para dimensionar la caja
    logo_file = _resolve_image_path(config.logo_path)
    has_logo = bool(logo_file and os.path.isfile(logo_file))
    try:
        _lh = float(getattr(config, "logo_height_mm", 16.0) or 16.0)
    except (TypeError, ValueError):
        _lh = 16.0
    logo_h = max(6.0, min(_lh, 60.0)) * mm
    BOX_H = max(44 * mm, logo_h + 28 * mm) if has_logo else 44 * mm
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

    # Columna izquierda: Logo y/o Razón Social
    pad_l = left_x + 3 * mm

    if has_logo:
        drawn = False
        logo_avail_w = LEFT_W - 8 * mm
        try:
            _lw = float(getattr(config, "logo_width_mm", 0.0) or 0.0)
        except (TypeError, ValueError):
            _lw = 0.0
        logo_max_w = min(_lw * mm, logo_avail_w) if _lw > 0 else logo_avail_w
        logo_max_h = logo_h
        logo_x = left_x + (LEFT_W - logo_max_w) / 2
        logo_y = y - 2 * mm - logo_max_h
        try:
            c.drawImage(
                logo_file,
                logo_x,
                logo_y,
                width=logo_max_w,
                height=logo_max_h,
                preserveAspectRatio=True,
                anchor='c',
                mask='auto'
            )
            drawn = True
        except Exception:
            try:
                c.drawImage(
                    logo_file,
                    logo_x,
                    logo_y,
                    width=logo_max_w,
                    height=logo_max_h,
                    preserveAspectRatio=True,
                    anchor='c'
                )
                drawn = True
            except Exception:
                drawn = False

        if drawn:
            _rs_fs = 8.5
            while _rs_fs > 6 and c.stringWidth(razon, "Helvetica-Bold", _rs_fs) > LEFT_W - 6 * mm:
                _rs_fs -= 0.5
            c.setFont("Helvetica-Bold", _rs_fs)
            c.drawCentredString(left_x + LEFT_W / 2, logo_y - 4 * mm, razon)
        else:
            c.setFont("Helvetica-Bold", 11)
            c.drawCentredString(left_x + LEFT_W / 2, y - 8 * mm, razon)
    else:
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(left_x + LEFT_W / 2, y - 8 * mm, razon)

    line_y = box_bot + 3 * mm
    _lv(c, pad_l, line_y, "Condición frente al IVA:  ", cond_emisor, 8)
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
    _lv(c, pad_r, rline, "Fecha de Emisión:  ", fecha_txt, 8)
    rline -= 5 * mm
    _lv(c, pad_r, rline, "CUIT:  ", _fmt_cuit(config.cuit), 8)
    ib_text = (config.ingresos_brutos or "").strip()
    if not ib_text:
        ib_text = "EXENTO" if "monotribut" in (cond_emisor or "").lower() else _fmt_cuit(config.cuit)
    rline -= 5 * mm
    _lv(c, pad_r, rline, "Ingresos Brutos:  ", ib_text, 8)
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
    BLEFT_W = CONTENT_W * 0.45
    mid_b = MARGIN + BLEFT_W
    fs = 8.5
    lead = fs * 1.25          # interlineado dentro de un mismo dato
    row_gap = 5.0             # separación entre datos (pt)
    left_col_w = BLEFT_W - 6 * mm
    right_col_w = CONTENT_W - BLEFT_W - 6 * mm

    def _layout_rows(rows, col_w):
        """rows: [(label, valor)] -> [(label, [líneas])] con corte de línea por palabras."""
        out = []
        for lbl, val in rows:
            lw = c.stringWidth(lbl, "Helvetica-Bold", fs)
            out.append((lbl, lw, _wrap_text(c, val, "Helvetica", fs, col_w - lw, col_w)))
        return out

    def _rows_height(layout):
        n_lines = sum(len(ls) for _, _, ls in layout)
        return (n_lines - 1) * lead + (len(layout) - 1) * row_gap if layout else 0

    def _draw_rows(layout, x, y_first):
        yy = y_first
        for lbl, lw, ls in layout:
            c.setFont("Helvetica-Bold", fs)
            c.drawString(x, yy, lbl)
            c.setFont("Helvetica", fs)
            c.drawString(x + lw, yy, ls[0])
            for extra in ls[1:]:
                yy -= lead
                c.drawString(x, yy, extra)
            yy -= lead + row_gap

    doc_lbl = DOC_TIPO_NOMBRE.get(resp.doc_tipo, "")
    left_rows = []
    if doc_lbl and resp.cuit_cliente and resp.cuit_cliente != "0":
        left_rows.append((f"{doc_lbl}:  ", str(resp.cuit_cliente)))
    else:
        left_rows.append(("", ""))   # mantiene el lugar, como en el modelo oficial
    left_rows.append(("Condición frente al IVA:  ",
                      _COND_IVA.get(resp.condicion_iva_receptor, "Consumidor Final")))
    left_rows.append(("Condición de venta:  ", resp.condicion_venta or ""))

    if is_consumidor_final(resp.nombre_cliente):
        nombre_receptor = ""
    else:
        nombre_receptor = resp.nombre_cliente or ""
    right_rows = [
        ("Apellido y Nombre / Razón Social:  ", nombre_receptor),
        ("Domicilio:  ", resp.domicilio_cliente or ""),
    ]

    left_layout = _layout_rows(left_rows, left_col_w)
    right_layout = _layout_rows(right_rows, right_col_w)
    first_off = 5.5 * mm
    content_h = first_off + max(_rows_height(left_layout), _rows_height(right_layout)) + 3 * mm
    BUYER_H = max(22 * mm, content_h)

    c.rect(MARGIN, y - BUYER_H, CONTENT_W, BUYER_H)
    c.line(mid_b, y - BUYER_H, mid_b, y)

    _draw_rows(left_layout, MARGIN + 3 * mm, y - first_off)
    _draw_rows(right_layout, mid_b + 3 * mm, y - first_off)

    y -= BUYER_H
    y -= 2 * mm

    # ── ESTILOS DE DESCRIPCIÓN ───────────────────────────────────────────────
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

    es_factura_a = resp.cbte_tipo in (1, 2, 3)

    if es_factura_a:
        col_w = [
            CONTENT_W * 0.060,   # Código
            CONTENT_W * 0.380,   # Producto / Servicio
            CONTENT_W * 0.080,   # Cantidad
            CONTENT_W * 0.100,   # U. Medida
            CONTENT_W * 0.120,   # Precio Unit.
            CONTENT_W * 0.100,   # % Alícuota IVA
            CONTENT_W * 0.160,   # Subtotal
        ]
        hdr = ["Código", "Producto / Servicio", "Cantidad", "U. Medida",
               "Precio Unit.", "Alícuota IVA", "Subtotal"]

        if resp.items:
            rows = [[
                hdr[0], Paragraph(hdr[1], _desc_hdr_style), hdr[2], hdr[3], hdr[4], hdr[5], hdr[6]
            ]]
            for item in resp.items:
                alic_id = getattr(item, "alicuota_iva_id", 5)
                tipo_it = getattr(item, "tipo_iva", "iva")
                if tipo_it == "no_gravado" or alic_id == 1:
                    alic_text = "No gravado"
                elif tipo_it == "exento" or alic_id == 2:
                    alic_text = "Exento"
                elif alic_id == 3 or getattr(item, "alicuota_iva", Decimal("21.0")) == Decimal("0.0"):
                    alic_text = "0%"
                else:
                    alic_val = getattr(item, "alicuota_iva", Decimal("21.0"))
                    val_str = f"{alic_val}".replace(".0", "") if f"{alic_val}".endswith(".0") else f"{alic_val}"
                    alic_text = f"{val_str}%"
                rows.append([
                    "",
                    Paragraph(item.descripcion, _desc_style),
                    _fmt_num(item.cantidad),
                    "unidades",
                    _fmt_num(item.precio_unitario),
                    alic_text,
                    _fmt_num(item.subtotal),
                ])
            subtotal_neto = sum(i.subtotal for i in resp.items)
        else:
            rows = [
                [hdr[0], Paragraph(hdr[1], _desc_hdr_style), hdr[2], hdr[3], hdr[4], hdr[5], hdr[6]],
                [
                    "", Paragraph(resp.concepto or "-", _desc_style),
                    _fmt_num(Decimal("1.00")), "unidades",
                    _fmt_num(resp.imp_neto if resp.imp_neto is not None else resp.monto),
                    "21%",
                    _fmt_num(resp.imp_neto if resp.imp_neto is not None else resp.monto),
                ],
            ]
            subtotal_neto = resp.imp_neto if resp.imp_neto is not None else resp.monto
    else:
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

        if resp.items:
            rows = [[
                hdr[0], Paragraph(hdr[1], _desc_hdr_style), hdr[2], hdr[3], hdr[4], hdr[5], hdr[6], hdr[7]
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
            subtotal_neto = sum(i.subtotal for i in resp.items)
        else:
            rows = [
                [hdr[0], Paragraph(hdr[1], _desc_hdr_style), hdr[2], hdr[3], hdr[4], hdr[5], hdr[6], hdr[7]],
                [
                    "", Paragraph(resp.concepto or "-", _desc_style),
                    _fmt_num(Decimal("1.00")), "unidades",
                    _fmt_num(resp.monto),
                    _fmt_num(Decimal("0.00")),
                    _fmt_num(Decimal("0.00")),
                    _fmt_num(resp.monto),
                ],
            ]
            subtotal_neto = resp.monto

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
    y -= t_h + 3 * mm

    # ── LEYENDA ADICIONAL / DATOS DE PAGO (SI ESTÁ CONFIGURADA) ──────────────
    if getattr(config, "leyenda", None) and config.leyenda.strip():
        _leyenda_style = ParagraphStyle(
            "Leyenda",
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.Color(0.2, 0.2, 0.2),
            alignment=TA_LEFT,
        )
        leyenda_clean = config.leyenda.strip().replace("\n", "<br/>")
        leyenda_p = Paragraph(f"<b>Información adicional / Datos de pago:</b><br/>{leyenda_clean}", _leyenda_style)
        l_w, l_h = leyenda_p.wrap(CONTENT_W - 6 * mm, 30 * mm)
        box_h = l_h + 3 * mm
        c.setFillColor(colors.Color(0.96, 0.96, 0.96))
        c.roundRect(MARGIN, y - box_h, CONTENT_W, box_h, 2, fill=1, stroke=1)
        c.setFillColor(colors.black)
        leyenda_p.drawOn(c, MARGIN + 3 * mm, y - box_h + 1.5 * mm)
        y -= box_h + 3 * mm

    # ── TOTALES Y RÉGIMEN TRANSPARENCIA FISCAL (LEY 27.743 - RG 5614/2024) ──
    es_factura_b = resp.cbte_tipo in (6, 7, 8)

    if es_factura_a:
        totals_data = [
            ["Importe Neto Gravado: $", _fmt_num(resp.imp_neto if resp.imp_neto is not None else subtotal_neto)],
        ]
        if getattr(resp, "imp_tot_conc", None) and resp.imp_tot_conc > Decimal("0.00"):
            totals_data.append(["Importe No Gravado: $", _fmt_num(resp.imp_tot_conc)])
        if getattr(resp, "imp_op_ex", None) and resp.imp_op_ex > Decimal("0.00"):
            totals_data.append(["Importe Exento: $", _fmt_num(resp.imp_op_ex)])

        if resp.ivas:
            for iv in resp.ivas:
                alic_id = int(iv["Id"])
                porc_desc = IVA_ALICUOTAS.get(alic_id, {}).get("desc", f"Alic. {alic_id}")
                totals_data.append([f"IVA {porc_desc}: $", _fmt_num(iv.get("Importe", "0.00"))])
        elif resp.items and _iva_contenido(resp) > Decimal("0.00"):
            iva_por_alic = defaultdict(Decimal)
            for it in resp.items:
                if getattr(it, "iva_monto", Decimal("0.00")) > Decimal("0.00"):
                    iva_por_alic[it.alicuota_iva] += it.iva_monto
            for alic_val, monto_iva in sorted(iva_por_alic.items()):
                totals_data.append([f"IVA {format(Decimal(alic_val).normalize(), 'f')}%: $", _fmt_num(monto_iva)])
        elif _iva_contenido(resp) > Decimal("0.00"):
            totals_data.append(["IVA 21%: $", _fmt_num(_iva_contenido(resp))])

        totals_data.append(["Importe Otros Tributos: $", _fmt_num(resp.imp_trib or Decimal("0.00"))])
        totals_data.append(["Importe Total: $", _fmt_num(resp.monto)])

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
    elif es_factura_b:
        # Régimen de Transparencia Fiscal al Consumidor (Ley 27.743 - RG 5614/2024)
        # Aplica a Responsables Inscriptos cuando emiten Factura B a Consumidor Final
        iva_contenido = _iva_contenido(resp)

        otros_trib = resp.imp_trib or Decimal("0.00")

        w_left_label = CONTENT_W * 0.38
        w_left_val = CONTENT_W * 0.18
        w_right_label = CONTENT_W * 0.26
        w_right_val = CONTENT_W * 0.18

        combined_rows = [
            [
                "Régimen de Transparencia Fiscal al Consumidor (Ley 27.743)",
                "",
                "Subtotal: $",
                _fmt_num(subtotal_neto),
            ],
            [
                "IVA Contenido: $",
                _fmt_num(iva_contenido),
                "Importe Otros Tributos: $",
                _fmt_num(otros_trib),
            ],
            [
                "Otros Impuestos Nacionales Indirectos: $",
                _fmt_num(otros_trib),
                "Importe Total: $",
                _fmt_num(resp.monto),
            ],
        ]

        t_tot = Table(combined_rows, colWidths=[w_left_label, w_left_val, w_right_label, w_right_val])
        t_tot.setStyle(TableStyle([
            # Encabezado Transparencia Fiscal
            ("SPAN",          (0, 0), (1, 0)),
            ("BACKGROUND",    (0, 0), (1, 0), _GREY),
            ("FONTNAME",      (0, 0), (1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (1, 0), 7.5),
            ("ALIGN",         (0, 0), (1, 0), "CENTER"),

            # Bloque izquierdo (Ley 27.743)
            ("BOX",           (0, 0), (1, -1), 0.4, colors.black),
            ("FONTNAME",      (0, 1), (0, -1), "Helvetica"),
            ("FONTNAME",      (1, 1), (1, -1), "Helvetica"),
            ("FONTSIZE",      (0, 1), (1, -1), 7.5),
            ("ALIGN",         (0, 1), (0, -1), "LEFT"),
            ("ALIGN",         (1, 1), (1, -1), "RIGHT"),
            ("LINEBELOW",     (0, 0), (1, 0), 0.4, colors.black),
            ("LINEBELOW",     (0, 1), (1, 1), 0.4, colors.black),
            ("LINEAFTER",     (0, 1), (0, -1), 0.4, colors.black),

            # Bloque derecho (Totales)
            ("BOX",           (2, 0), (3, -1), 0.4, colors.black),
            ("FONTNAME",      (2, 0), (3, -2), "Helvetica"),
            ("FONTNAME",      (2, -1), (3, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (2, 0), (3, -1), 8),
            ("ALIGN",         (2, 0), (2, -1), "RIGHT"),
            ("ALIGN",         (3, 0), (3, -1), "RIGHT"),
            ("LINEAFTER",     (2, 0), (2, -1), 0.4, colors.black),
            ("LINEBELOW",     (2, 0), (3, -2), 0.4, colors.black),

            # Padding
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ]))
    else:
        # Facturas C y demás comprobantes sin IVA discriminado (Monotributo / Exento)
        totals_data = [
            ["Subtotal: $", _fmt_num(subtotal_neto)],
            ["Importe Otros Tributos: $", _fmt_num(resp.imp_trib or Decimal("0.00"))],
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

    t_tot.wrapOn(c, CONTENT_W, 60 * mm)
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



def _resolve_image_path(p: str | None) -> str | None:
    if not p:
        return None
    p = str(p).strip().strip('"').strip("'")
    if not p:
        return None
    # Translate Windows path (e.g. C:\... or C:/...) to WSL (/mnt/c/...)
    if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
        drive = p[0].lower()
        subpath = p[2:].replace("\\", "/").lstrip("/")
        wsl_path = f"/mnt/{drive}/{subpath}"
        if os.path.isfile(wsl_path):
            return wsl_path
    if os.path.isfile(p):
        return os.path.abspath(p)
    base_dir = Path(__file__).resolve().parent
    rel_p = base_dir / p
    if rel_p.is_file():
        return str(rel_p.resolve())
    if p.startswith("./") or p.startswith(".\\"):
        alt = base_dir / p[2:]
        if alt.is_file():
            return str(alt.resolve())
    return None

def generate_pdf(config: Config, resp: InvoiceResponse, output_path: str,
                 duplicado: bool = False,
                 triplicado: bool = False,
                 copias: int = 1) -> str:
    c = canvas.Canvas(output_path, pagesize=A4)
    _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="ORIGINAL")
    if triplicado or copias >= 3:
        c.showPage()
        _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="DUPLICADO")
        c.showPage()
        _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="TRIPLICADO")
    elif duplicado or copias == 2:
        c.showPage()
        _draw_comprobante(c, config, resp, y_start=PAGE_H - MARGIN, label="DUPLICADO")
    c.save()
    return output_path
