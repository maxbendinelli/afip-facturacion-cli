#!/usr/bin/env python3
"""
Genera una clave privada RSA y un CSR en formato PKCS#10 para registrar
en el portal de ARCA/AFIP y obtener el certificado de firma electrónica.

Uso:
    python3 generar_csr.py --cuit 20123456789 --razon-social "Mi Empresa SA"
    python3 generar_csr.py --cuit 20123456789 --razon-social "Juan Pérez"

Los archivos generados se guardan en ./certs/:
    afip_<cuit>.key  — clave privada RSA (guardar en lugar seguro, NO subir a AFIP)
    afip_<cuit>.csr  — CSR en formato PEM para subir al portal de AFIP/ARCA
"""
import argparse
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generar_csr(cuit: str, razon_social: str, bits: int, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    key_path = out_dir / f"afip_{cuit}.key"
    csr_path = out_dir / f"afip_{cuit}.csr"

    # Generar clave privada RSA
    print(f"Generando clave RSA de {bits} bits...", end=" ", flush=True)
    clave = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
    )
    print("OK")

    # Guardar clave privada en formato PEM (sin contraseña)
    with open(key_path, "wb") as f:
        f.write(clave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    os.chmod(key_path, 0o600)
    print(f"Clave privada guardada en: {key_path}")

    # Construir Distinguished Name (DN)
    # AFIP requiere como mínimo CN con el CUIT y C=AR
    dn = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, razon_social),
        x509.NameAttribute(NameOID.COMMON_NAME, cuit),
    ])

    # Construir y firmar el CSR (PKCS#10)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(dn)
        .sign(clave, hashes.SHA256())
    )

    # Guardar CSR en formato PEM
    with open(csr_path, "wb") as f:
        f.write(csr.public_bytes(serialization.Encoding.PEM))
    print(f"CSR guardado en:           {csr_path}")

    # Mostrar contenido del CSR para verificación
    print()
    print("=== Contenido del CSR ===")
    print(f"  Sujeto:       {csr.subject.rfc4514_string()}")
    print(f"  Algoritmo:    {csr.signature_hash_algorithm.name.upper()}")
    print(f"  Clave pública RSA {bits} bits")
    print(f"  Firma válida: {csr.is_signature_valid}")
    print()
    print("Próximos pasos:")
    print(f"  1. Ingresar a https://auth.afip.gob.ar/ con clave fiscal nivel 3+")
    print(f"  2. Ir a: Servicios → WSASS (Autogestión Servicios Web)")
    print(f"  3. Agregar el servicio 'wsfe' para el CUIT {cuit}")
    print(f"  4. Subir el contenido de {csr_path}")
    print(f"  5. Descargar el certificado .crt y guardarlo en {out_dir}/afip_{cuit}.crt")
    print(f"  6. Configurar en .env:")
    print(f"       AFIP_CERT_PATH={out_dir}/afip_{cuit}.crt")
    print(f"       AFIP_KEY_PATH={key_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera clave RSA + CSR PKCS#10 para ARCA/AFIP"
    )
    parser.add_argument(
        "--cuit", required=True,
        help="CUIT del emisor (11 dígitos, sin guiones)"
    )
    parser.add_argument(
        "--razon-social", required=True,
        metavar="NOMBRE",
        help='Razón social o nombre completo (ej: "Juan Pérez")'
    )
    parser.add_argument(
        "--bits", type=int, choices=[2048, 4096], default=2048,
        help="Longitud de la clave RSA (default: 2048)"
    )
    parser.add_argument(
        "--out-dir", default="./certs",
        metavar="DIR",
        help="Directorio de salida (default: ./certs)"
    )
    args = parser.parse_args()

    cuit = args.cuit.strip().replace("-", "").replace(" ", "")
    if not cuit.isdigit() or len(cuit) != 11:
        print(f"Error: CUIT inválido '{cuit}'. Debe tener exactamente 11 dígitos.", file=sys.stderr)
        sys.exit(1)

    generar_csr(
        cuit=cuit,
        razon_social=args.razon_social,
        bits=args.bits,
        out_dir=Path(args.out_dir),
    )


if __name__ == "__main__":
    main()
