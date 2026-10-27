"""
Módulo de envío de facturas y comprobantes electrónicos por correo electrónico (SMTP).
Permite enviar comprobantes individuales y por lotes con el archivo PDF adjunto
y una plantilla de correo profesional en formato HTML y texto plano.
"""
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
import logging
import os
from pathlib import Path
import re
import smtplib
from typing import Any, Dict, Optional

from config import Config

logger = logging.getLogger(__name__)


def is_smtp_configured(config: Config) -> bool:
    """Verifica si los parámetros indispensables de SMTP están configurados."""
    return bool(config.smtp_host and config.smtp_user and config.smtp_password)


def _fmt_moneda(monto: Any) -> str:
    """Formatea monto a formato moneda argentina ($ 1.234,56)."""
    try:
        val = float(str(monto).replace(",", "."))
        s = f"{val:,.2f}"
        return "$" + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"${monto}"


def _fmt_fecha_visual(yyyymmdd: Any) -> str:
    """Convierte fecha YYYYMMDD a DD/MM/YYYY."""
    s = str(yyyymmdd or "").strip().replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[6:8]}/{s[4:6]}/{s[:4]}"
    return str(yyyymmdd or "")


def build_invoice_email_html(
    emisor_nombre: str,
    comprobante: str,
    fecha: str,
    total_str: str,
    cae: str,
    cae_vto: str,
    cliente_nombre: str = "",
    leyenda_emisor: str = "",
    custom_message: Optional[str] = None,
) -> str:
    """Genera plantilla de correo HTML moderna, profesional y responsive."""
    saludo_cliente = f"Estimado/a <strong>{cliente_nombre}</strong>," if cliente_nombre and cliente_nombre.lower() not in ("consumidor final", "cf", "sin identificar", "") else "Estimado/a cliente,"
    leyenda_html = f'<p style="margin: 15px 0 0 0; font-size: 13px; color: #64748B; font-style: italic;">{leyenda_emisor}</p>' if leyenda_emisor else ""
    mensaje_personalizado_html = ""
    if custom_message and str(custom_message).strip():
        msg_limpio = str(custom_message).strip().replace("\n", "<br>")
        mensaje_personalizado_html = f'<div style="margin: 0 0 18px 0; padding: 12px 16px; background-color: #F0FDF4; border-left: 4px solid #10B981; border-radius: 4px; font-size: 14px; color: #065F46; line-height: 1.5;">{msg_limpio}</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Comprobante Electrónico {comprobante}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F8FAFC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1E293B;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #F8FAFC; padding: 25px 10px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; background-color: #FFFFFF; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05); border: 1px solid #E2E8F0;">
          
          <!-- Header -->
          <tr>
            <td style="background: linear-space, #1E293B; background-color: #0F172A; padding: 30px 30px; text-align: left;">
              <span style="display: inline-block; background-color: #2563EB; color: #FFFFFF; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.5px;">Comprobante Electrónico</span>
              <h1 style="margin: 10px 0 0 0; color: #FFFFFF; font-size: 20px; font-weight: 600;">{emisor_nombre}</h1>
              <p style="margin: 4px 0 0 0; color: #94A3B8; font-size: 14px;">Facturación Electrónica Oficial ARCA / AFIP</p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding: 30px 30px 25px 30px;">
              <p style="margin: 0 0 16px 0; font-size: 15px; line-height: 1.5; color: #334155;">
                {saludo_cliente}
              </p>
              {mensaje_personalizado_html}
              <p style="margin: 0 0 24px 0; font-size: 15px; line-height: 1.5; color: #334155;">
                Le hacemos llegar el comprobante electrónico correspondiente a la operación realizada. Adjunto a este correo encontrará el archivo oficial en formato <strong>PDF</strong> para su control y archivo contable.
              </p>

              <!-- Detalles de la Factura -->
              <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #F1F5F9; border-radius: 8px; border: 1px solid #E2E8F0; margin-bottom: 24px;">
                <tr>
                  <td style="padding: 16px 20px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding: 5px 0; font-size: 13px; color: #64748B; width: 45%;">Comprobante:</td>
                        <td style="padding: 5px 0; font-size: 14px; font-weight: 700; color: #0F172A;">{comprobante}</td>
                      </tr>
                      <tr>
                        <td style="padding: 5px 0; font-size: 13px; color: #64748B;">Fecha de Emisión:</td>
                        <td style="padding: 5px 0; font-size: 14px; color: #1E293B;">{fecha}</td>
                      </tr>
                      <tr>
                        <td style="padding: 5px 0; font-size: 13px; color: #64748B;">CAE N°:</td>
                        <td style="padding: 5px 0; font-size: 14px; font-family: monospace; color: #1E293B;">{cae}</td>
                      </tr>
                      <tr>
                        <td style="padding: 5px 0; font-size: 13px; color: #64748B;">Vto. CAE:</td>
                        <td style="padding: 5px 0; font-size: 14px; color: #1E293B;">{cae_vto}</td>
                      </tr>
                      <tr style="border-top: 1px dashed #CBD5E1;">
                        <td style="padding: 12px 0 4px 0; font-size: 15px; font-weight: 700; color: #0F172A;">Importe Total:</td>
                        <td style="padding: 12px 0 4px 0; font-size: 18px; font-weight: 800; color: #10B981;">{total_str}</td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Caja de Adjunto -->
              <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px; margin-bottom: 20px;">
                <tr>
                  <td style="padding: 12px 16px; font-size: 13px; color: #1E40AF;">
                    📎 <strong>Archivo PDF adjunto:</strong> Descargue e imprima el comprobante adjunto directamente desde su visor de correos.
                  </td>
                </tr>
              </table>

              {leyenda_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #F8FAFC; padding: 20px 30px; border-top: 1px solid #E2E8F0; text-align: center;">
              <p style="margin: 0; font-size: 12px; color: #94A3B8;">
                Este es un mensaje automático emitido por el sistema de Facturación Electrónica de <strong>{emisor_nombre}</strong>.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _crear_conexion_smtp(config: Config) -> smtplib.SMTP:
    """Crea y autentica la conexión SMTP según la configuración de seguridad."""
    host = (config.smtp_host or "").strip()
    port = int(config.smtp_port or 587)
    security = (config.smtp_security or "tls").strip().lower()
    timeout = 20

    if security == "ssl" or port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=timeout)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
        if security == "tls":
            server.starttls()

    if config.smtp_user and config.smtp_password:
        server.login(config.smtp_user.strip(), config.smtp_password.strip())

    return server


def test_smtp_connection(config: Config, test_recipient: str) -> Dict[str, Any]:
    """
    Prueba el envío de un correo de prueba a la casilla especificada para validar
    las credenciales y conectividad con el servidor SMTP.
    """
    if not is_smtp_configured(config):
        return {
            "ok": False,
            "error": "Debe configurar Servidor SMTP, Usuario y Contraseña en la Configuración.",
        }

    recipient = test_recipient.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", recipient):
        return {"ok": False, "error": f"Dirección de correo inválida: '{recipient}'"}

    from_name = config.smtp_from_name or config.razon_social or "ARCA Facturación"
    from_email = config.smtp_from_email or config.smtp_user

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(f"Prueba de Configuración SMTP - {from_name}", "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_email))
    msg["To"] = recipient

    txt = (
        f"¡Hola!\n\n"
        f"Este es un correo de prueba exitoso enviado desde el sistema de Facturación Electrónica ARCA.\n\n"
        f"Servidor SMTP: {config.smtp_host}:{config.smtp_port}\n"
        f"Seguridad: {config.smtp_security.upper()}\n"
        f"Remitente: {from_name} <{from_email}>\n"
    )
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #F8FAFC; padding: 20px;">
  <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; padding: 25px; border: 1px solid #E2E8F0;">
    <h2 style="color: #10B981; margin-top: 0;">✓ Conexión SMTP Exitosa</h2>
    <p>El sistema de Facturación Electrónica de <strong>{from_name}</strong> se ha comunicado correctamente con el servidor de correo.</p>
    <ul style="color: #475569; font-size: 14px; line-height: 1.6;">
      <li><strong>Servidor:</strong> {config.smtp_host}:{config.smtp_port}</li>
      <li><strong>Seguridad:</strong> {config.smtp_security.upper()}</li>
      <li><strong>Usuario:</strong> {config.smtp_user}</li>
      <li><strong>Remitente:</strong> {from_name} &lt;{from_email}&gt;</li>
    </ul>
    <p style="font-size: 13px; color: #94A3B8;">Ya puede emitir facturas y enviarlas automáticamente a sus clientes.</p>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(txt, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with _crear_conexion_smtp(config) as server:
            server.send_message(msg)
        return {
            "ok": True,
            "message": f"Correo de prueba enviado con éxito a {recipient}",
        }
    except Exception as e:
        logger.error(f"Error probando conexión SMTP: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def send_invoice_email(
    config: Config,
    recipient_email: str,
    invoice_data: Dict[str, Any],
    pdf_path: str | Path,
    custom_subject: Optional[str] = None,
    custom_message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Envía por correo electrónico la factura al cliente con el PDF oficial adjunto.
    """
    if not recipient_email or not str(recipient_email).strip():
        return {"ok": False, "error": "No se indicó correo electrónico del destinatario."}

    recipient = str(recipient_email).strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", recipient):
        return {"ok": False, "error": f"Formato de correo electrónico inválido: '{recipient}'"}

    if not is_smtp_configured(config):
        return {
            "ok": False,
            "error": "El servidor SMTP no está configurado. Ingrese los datos en la pestaña Configuración.",
        }

    p = Path(pdf_path)
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"Archivo PDF no encontrado: {p.name}"}

    emisor_nombre = config.nombre_fantasia or config.razon_social or "Facturación Electrónica"
    from_name = config.smtp_from_name or emisor_nombre
    from_email = config.smtp_from_email or config.smtp_user

    comprobante_nro = str(invoice_data.get("comprobante") or invoice_data.get("numero") or p.stem)
    monto_fmt = _fmt_moneda(invoice_data.get("monto", "0.00"))
    fecha_fmt = _fmt_fecha_visual(invoice_data.get("fecha", ""))
    cae = str(invoice_data.get("cae") or "--")
    cae_vto = _fmt_fecha_visual(invoice_data.get("cae_vencimiento", ""))
    cliente_nombre = str(invoice_data.get("cliente") or invoice_data.get("nombre_cliente") or "")

    subject = custom_subject or f"Comprobante Electrónico {comprobante_nro} - {emisor_nombre}"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_email))
    msg["To"] = recipient

    # Cuerpo alternativo (HTML y Plaintext)
    alt_part = MIMEMultipart("alternative")

    nota_txt = f"\n{custom_message}\n\n" if custom_message and str(custom_message).strip() else "\n\n"
    txt_body = (
        f"Estimado/a cliente,\n"
        f"{nota_txt}"
        f"Le adjuntamos el comprobante electrónico correspondiente a la operación realizada con {emisor_nombre}.\n\n"
        f"Comprobante: {comprobante_nro}\n"
        f"Fecha: {fecha_fmt}\n"
        f"Importe Total: {monto_fmt}\n"
        f"CAE: {cae} (Vto: {cae_vto})\n\n"
        f"El archivo PDF oficial se encuentra adjunto a este mensaje.\n\n"
        f"Atentamente,\n{emisor_nombre}"
    )
    html_body = build_invoice_email_html(
        emisor_nombre=emisor_nombre,
        comprobante=comprobante_nro,
        fecha=fecha_fmt,
        total_str=monto_fmt,
        cae=cae,
        cae_vto=cae_vto,
        cliente_nombre=cliente_nombre,
        leyenda_emisor=config.leyenda,
        custom_message=custom_message,
    )

    alt_part.attach(MIMEText(txt_body, "plain", "utf-8"))
    alt_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt_part)

    # Adjunto PDF
    try:
        with open(p, "rb") as f:
            pdf_data = f.read()
        attachment = MIMEApplication(pdf_data, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=p.name)
        msg.attach(attachment)
    except Exception as e:
        return {"ok": False, "error": f"Error adjuntando PDF: {e}"}

    # Envío
    try:
        with _crear_conexion_smtp(config) as server:
            server.send_message(msg)
        return {
            "ok": True,
            "message": f"Factura enviada exitosamente a {recipient}",
            "destinatario": recipient,
            "archivo": p.name,
        }
    except Exception as e:
        logger.error(f"Error enviando correo de factura a {recipient}: {e}", exc_info=True)
        return {"ok": False, "error": str(e), "destinatario": recipient}
