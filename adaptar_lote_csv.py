#!/usr/bin/env python3
"""
Script utilitario para adaptar planillas CSV de facturación automática
al formato estándar de lote o emitir directamente.
"""
import sys
import os
import csv
import re
from decimal import Decimal
from pathlib import Path


def parse_date_afip(val: str):
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


def parse_doc(raw: str):
    raw_s = str(raw or "").strip().replace("-", "").replace(" ", "").replace(".", "")
    if raw_s.isdigit() and len(raw_s) == 11:
        return 80, raw_s
    if raw_s.isdigit() and 6 <= len(raw_s) <= 8:
        return 96, raw_s
    if raw_s.upper() in ("SIN_CUIT", "0", ""):
        return 99, "0"
    return 99, raw_s


def adaptar_csv(input_path: str, output_path: str = None):
    p = Path(input_path)
    if not p.exists():
        print(f"Error: no existe el archivo {input_path}")
        sys.exit(1)

    with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
        all_lines = [l for l in f.readlines() if l.strip()]

    # Buscar línea de encabezado
    header_idx = 0
    for i, line in enumerate(all_lines[:35]):
        ll = line.lower()
        if "destinatario" in ll or "dni/cuit" in ll or "cuit_cliente" in ll or "tipo comp" in ll:
            header_idx = i
            break

    sub_lines = all_lines[header_idx:]
    delim = ";" if ";" in sub_lines[0] and sub_lines[0].count(";") >= sub_lines[0].count(",") else ","

    reader = csv.DictReader(sub_lines, delimiter=delim)
    filas_adaptadas = []

    for raw_row in reader:
        if not any(v.strip() for v in raw_row.values() if v):
            continue

        factura_flag = (raw_row.get("FACTURA") or raw_row.get("factura") or "").strip().upper()
        if factura_flag == "NO":
            continue

        nombre = (raw_row.get("Destinatario Factura") or raw_row.get("nombre_cliente") or "").strip()
        doc_raw = (raw_row.get("Dni/cuit") or raw_row.get("cuit_cliente") or "").strip()
        monto_raw = (raw_row.get("Total") or raw_row.get("monto") or "0").strip().replace("$", "").replace(" ", "")

        if not nombre and not doc_raw and monto_raw in ("", "0"):
            continue

        tipo_raw = (raw_row.get("TIPO COMP.") or raw_row.get("tipo") or "C").upper().strip()
        tipo = "A" if "FACTURA A" in tipo_raw else ("B" if "FACTURA B" in tipo_raw else "C")

        # Formato de importe
        if "," in monto_raw and "." in monto_raw:
            monto_raw = monto_raw.replace(".", "").replace(",", ".")
        elif "," in monto_raw:
            monto_raw = monto_raw.replace(",", ".")
        monto = float(Decimal(monto_raw))

        # Alícuota
        alic_raw = (raw_row.get("Alic. IVA %") or raw_row.get("alicuota_iva") or "").strip().upper()
        if "EXENTO" in alic_raw or alic_raw == "0":
            alic_iva = 0.0
        elif "21" in alic_raw:
            alic_iva = 21.0
        elif "10.5" in alic_raw or "10,5" in alic_raw:
            alic_iva = 10.5
        elif "27" in alic_raw:
            alic_iva = 27.0
        else:
            alic_iva = 21.0 if tipo in ("A", "B") else 0.0

        # Condición IVA
        cond_raw = (raw_row.get("condicion frente al IVA") or raw_row.get("condicion_iva") or "").strip().upper()
        if "RESPONSIBLE" in cond_raw or "INSCRIPTO" in cond_raw:
            cond_iva = "RI"
        elif "EXENTO" in cond_raw:
            cond_iva = "EX"
        elif "MONOTRIBUT" in cond_raw:
            cond_iva = "MONO"
        else:
            cond_iva = "CF"

        concepto = (raw_row.get("Producto o Servicio") or raw_row.get("concepto") or "Servicios").strip()

        filas_adaptadas.append({
            "tipo": tipo,
            "cuit_cliente": doc_raw or "SIN_CUIT",
            "nombre_cliente": nombre,
            "concepto": concepto,
            "monto": f"{monto:.2f}",
            "alicuota_iva": alic_iva,
            "condicion_iva": cond_iva,
        })

    if not output_path:
        output_path = str(p.parent / f"{p.stem}_estandarizado.csv")

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["tipo", "cuit_cliente", "nombre_cliente", "concepto", "monto", "alicuota_iva", "condicion_iva"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filas_adaptadas)

    print(f"✅ Archivo adaptado exitosamente con {len(filas_adaptadas)} comprobantes:")
    print(f"👉 Destino: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 adaptar_lote_csv.py <ruta_archivo.csv> [ruta_salida.csv]")
        sys.exit(1)

    archivo = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else None
    adaptar_csv(archivo, salida)
