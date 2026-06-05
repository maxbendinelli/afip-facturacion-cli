# afip-facturacion

CLI en Python para facturación electrónica argentina a través de los servicios web de **ARCA/AFIP** (WSFEv1). Permite emitir Facturas C, Notas de Crédito y Débito, consultar comprobantes y generar PDFs con formato oficial.

> Pensado para **monotributistas** que necesitan automatizar o integrar la emisión de comprobantes electrónicos.

## Características

- ✅ Emite **Factura C** para cualquier tipo de receptor (Consumidor Final, RI, Monotributista, Exento, etc.)
- ✅ **Nota de Crédito C** y **Nota de Débito C**
- ✅ Resolución automática del nombre del receptor vía **Padrón A13** de AFIP
- ✅ Inferencia automática de la **condición IVA** del receptor según el documento
- ✅ Generación de **PDF** con formato oficial ARCA (QR, CAE, tabla de ítems)
- ✅ Consulta y búsqueda de comprobantes emitidos
- ✅ Soporte para **homologación y producción**
- ✅ Output en **JSON** — fácil de integrar con otros scripts o sistemas
- ✅ Helper para generar **clave RSA + CSR** para registrar en AFIP

## Requisitos

- Python 3.11+
- Certificado digital emitido por AFIP/ARCA (ver [Configuración inicial](#configuración-inicial))

```bash
pip install -r requirements.txt
```

## Instalación

```bash
git clone https://github.com/tu-usuario/afip-facturacion.git
cd afip-facturacion

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Editar .env con tu CUIT, paths de certificado y punto de venta
```

## Configuración inicial

### 1. Generar clave privada y CSR

```bash
python3 generar_csr.py --cuit 20123456789 --razon-social "Juan Pérez"
```

Esto genera `certs/afip_20123456789.key` (clave privada) y `certs/afip_20123456789.csr` (CSR para subir a AFIP).

### 2. Obtener el certificado en AFIP

1. Ingresá a [auth.afip.gob.ar](https://auth.afip.gob.ar/) con clave fiscal nivel 3+
2. Ir a **Servicios → WSASS (Autogestión Servicios Web)**
3. Agregar el servicio `wsfe` para tu CUIT
4. Subir el contenido del `.csr` generado
5. Descargar el certificado `.crt` y guardarlo en `certs/`

### 3. Configurar el `.env`

```bash
cp .env.example .env
```

Completar al menos:

```env
AFIP_CUIT=20123456789
AFIP_CERT_PATH=./certs/afip_20123456789.crt
AFIP_KEY_PATH=./certs/afip_20123456789.key
AFIP_PUNTO_VENTA=1
AFIP_RAZON_SOCIAL=Juan Pérez
AFIP_DOMICILIO=Av. Corrientes 1234, CABA
```

## Uso

### Emitir Factura C

```bash
# Consumidor final (condición IVA inferida automáticamente)
python3 facturar.py emitir \
  --concepto "Servicio de consultoría - junio 2026" \
  --monto 5000 \
  --env prod --pdf

# Con CUIT (nombre y condición IVA se resuelven automáticamente del padrón)
python3 facturar.py emitir \
  --cuit-cliente 30-71234567-8 \
  --concepto "Desarrollo web" \
  --monto 80000 \
  --env prod --pdf --duplicado

# Especificando condición IVA explícitamente (alias o número)
python3 facturar.py emitir \
  --cuit-cliente 20-98765432-1 \
  --condicion-iva RI \
  --concepto "Consultoría" \
  --monto 100000 \
  --env prod --pdf

# Con múltiples ítems (el monto se calcula automáticamente)
python3 facturar.py emitir \
  --item "Desarrollo|1|50000" \
  --item "Soporte técnico|3|10000" \
  --env prod --pdf --duplicado
```

### Condición IVA del receptor (`--condicion-iva`)

Se puede pasar un **alias** o el **número** del código RG 5616. Si se omite, se infiere según el documento:

| Alias | ID | Descripción |
|-------|----|-------------|
| `CF`, `CONSUMIDOR_FINAL` | 5 | Consumidor Final *(default sin CUIT)* |
| `RI`, `RESPONSABLE_INSCRIPTO` | 1 | IVA Responsable Inscripto *(default con CUIT)* |
| `MONO`, `MONOTRIB` | 6 | Responsable Monotributo |
| `EX`, `EXENTO` | 4 | IVA Sujeto Exento |
| `RNI` | 2 | IVA Responsable No Inscripto |
| `NR` | 3 | IVA No Responsable |

### Nota de Crédito / Débito

```bash
python3 facturar.py nota-credito --numero-original 42 --monto 5000 --env prod
python3 facturar.py nota-debito  --numero-original 42 --monto 1000 --env prod
```

### Consultar comprobantes

```bash
# Último número emitido
python3 facturar.py ultimo-numero --tipo C --env prod

# Consultar un comprobante específico (y opcionalmente generar PDF)
python3 facturar.py consultar --numero 42 --tipo C --env prod --pdf

# Buscar por rango de fechas o receptor
python3 facturar.py buscar --desde-fecha 20260601 --hasta-fecha 20260630 --env prod
python3 facturar.py buscar --receptor 30-71234567-8 --env prod
```

### Validar CUIT

```bash
# Solo formato y dígito verificador
python3 facturar.py validar-cuit 20-12345678-3

# Confirmando existencia en el padrón de AFIP
python3 facturar.py validar-cuit 20-12345678-3 --afip --env prod
```

### Generar PDF de un comprobante ya emitido

```bash
# A partir de datos conocidos
python3 facturar.py generar-pdf \
  --numero 42 \
  --cae 86184331336401 \
  --cae-vencimiento 20260615 \
  --fecha 20260605 \
  --monto 5000 \
  --env prod

# A partir del JSON devuelto por 'emitir'
python3 facturar.py reimprimir factura_0001_00000042.json --env prod
```

### Pruebas en homologación

Usar `--env homo` (o simplemente omitir `--env`, que tiene `homo` como default) para emitir contra el ambiente de pruebas de AFIP sin consecuencias fiscales:

```bash
python3 facturar.py emitir --monto 100 --concepto "Prueba" --dry-run
python3 facturar.py emitir --monto 100 --concepto "Prueba" --env homo
```

## Output JSON

Todos los comandos emiten JSON por stdout:

```json
{
  "status": "ok",
  "comprobante": "0001-00000042",
  "numero": 42,
  "punto_venta": 1,
  "cae": "86184331336401",
  "cae_vencimiento": "20260615",
  "tipo": "Factura C",
  "fecha": "20260605",
  "monto": "5000.00",
  "cliente": "Nombre del receptor",
  "cuit_cliente": "30712345678",
  "condicion_iva_receptor": 1,
  "condicion_iva_nombre": "IVA Responsable Inscripto",
  "pdf": "factura_0001_00000042.pdf"
}
```

Los errores también salen como JSON con exit code 1:

```json
{"error": "descripción del error"}
```

## Estructura del proyecto

```
afip-facturacion/
├── facturar.py         # CLI principal (punto de entrada)
├── models.py           # Modelos de datos (InvoiceRequest, InvoiceResponse, tablas IVA)
├── config.py           # Carga de configuración desde .env
├── wsaa.py             # Autenticación WSAA (token/sign)
├── wsfev1.py           # Facturación WSFEv1 (solicitar CAE, consultar, buscar)
├── padron.py           # Consulta al Padrón A13 de AFIP
├── validators.py       # Validación de CUIT (formato + padrón)
├── pdf_generator.py    # Generación de PDF con ReportLab
├── ssl_transport.py    # Transporte HTTPS con certificado cliente
├── generar_csr.py      # Helper para generar clave RSA + CSR para AFIP
├── requirements.txt
├── .env.example        # Variables de entorno requeridas (sin datos reales)
├── .gitignore
└── certs/              # Certificados (excluidos de git)
    └── .gitkeep
```

## Seguridad

- **Nunca subas** `.env`, certificados (`.pem`, `.crt`, `.key`) ni claves privadas al repositorio
- El `.gitignore` ya los excluye por defecto
- La clave privada RSA se genera localmente con `generar_csr.py` y nunca sale de tu máquina

## Licencia

MIT
