# AFIP Facturación Electrónica

CLI en Python para emitir, consultar y reimprimir **comprobantes electrónicos** (Factura C, Nota de Débito/Crédito) ante AFIP / ARCA, con generación de PDF normativo (RG 1415/2003) y código QR de verificación.

Orientado a **monotributistas** y pequeñas empresas que necesitan automatizar la facturación sin depender de sistemas de gestión externos.

---

## Características

- Emisión de Factura C, Nota de Débito C y Nota de Crédito C vía WSFEv1
- Soporte de múltiples ítems con cantidades y precios unitarios
- Consulta del padrón A13 para autocompletar nombre y domicilio del receptor
- PDF normativo: encabezado estándar, datos del comprador, detalle, totales, CAE, QR AFIP
- Logo o nombre de fantasía configurables en el encabezado
- Duplicado en segunda página del PDF
- Búsqueda de comprobantes por número, fecha y receptor (consulta directa a AFIP)
- Reimpresión desde JSON guardado o consultando AFIP en tiempo real
- Validación de CUIT/CUIL con dígito verificador y verificación contra padrón
- Caché de tokens WSAA para evitar autenticaciones repetidas
- Soporte de entornos homologación y producción
- Setup interactivo mediante `setup.sh`

---

## Requisitos

- **Python 3.10** o superior
- Conexión a internet (para comunicarse con los servicios web de AFIP)
- **Certificado digital** y **clave privada** emitidos por AFIP para el servicio `wsfe`  
  (ver sección [Obtener certificados AFIP](#obtener-certificados-afip))

Dependencias Python (se instalan automáticamente con el setup):

```
zeep          — cliente SOAP
cryptography  — firma CMS/PKCS#7 para WSAA
python-dotenv — lectura del archivo .env
requests      — HTTP
lxml          — procesamiento XML
reportlab     — generación de PDF
qrcode[pil]   — código QR en el PDF
Pillow        — procesamiento de imágenes
```

---

## Instalación rápida

```bash
git clone https://github.com/TU_USUARIO/afip-facturacion.git
cd afip-facturacion
bash setup.sh
```

El script interactivo:
1. Verifica la versión de Python
2. Crea y activa un entorno virtual `.venv/`
3. Instala todas las dependencias
4. Guía la configuración del archivo `.env`
5. Opcionalmente genera la clave RSA y el CSR para AFIP

---

## Instalación manual

```bash
# Clonar
git clone https://github.com/TU_USUARIO/afip-facturacion.git
cd afip-facturacion

# Entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Dependencias
pip install -r requirements.txt

# Configuración
cp .env.example .env
# Editar .env con sus datos (ver sección Configuración)
```

---

## Obtener certificados AFIP

> Este paso es necesario para comunicarse con los servicios web de AFIP.  
> Si ya tiene un certificado `.crt` y una clave `.key`, puede saltarlo.

### 1. Generar clave privada y CSR

```bash
source .venv/bin/activate
python3 generar_csr.py --cuit 20123456789 --razon-social "Juan Pérez"
```

Esto crea en `./certs/`:
- `afip_20123456789.key` — clave privada RSA (guardar de forma segura)
- `afip_20123456789.csr` — solicitud de certificado para subir a AFIP

### 2. Registrar en el portal AFIP

1. Ingresar a [https://auth.afip.gob.ar/](https://auth.afip.gob.ar/) con clave fiscal nivel 3 o superior
2. Ir a **Servicios → WSASS (Autogestión Servicios Web)**
3. Agregar el servicio **wsfe** (factura electrónica)
4. Subir el contenido del archivo `.csr`
5. Descargar el certificado `.crt` generado por AFIP

### 3. Configurar rutas en `.env`

```env
AFIP_CERT_PATH=./certs/afip_20123456789.crt
AFIP_KEY_PATH=./certs/afip_20123456789.key
```

> **Seguridad:** Los archivos `.key` y `.crt` están en `.gitignore`.  
> **Nunca** los suba a repositorios públicos.

---

## Configuración

Edite el archivo `.env` con sus datos:

```env
# Identificación
AFIP_CUIT=20123456789

# Datos que aparecen en el PDF
AFIP_RAZON_SOCIAL=Juan Pérez
AFIP_NOMBRE_FANTASIA=         # Opcional: aparece prominente; la razón social se muestra como "de Juan Pérez"
AFIP_DOMICILIO=Av. Corrientes 1234, CABA
AFIP_DOMICILIO_FISCAL=        # Si difiere del comercial
AFIP_INICIO_ACTIVIDADES=01/01/2020
AFIP_INGRESOS_BRUTOS=EXENTO   # o el número de inscripción
AFIP_LOGO_PATH=               # Ruta a PNG del logo (opcional)

# Punto de venta (registrado en AFIP)
AFIP_PUNTO_VENTA=1

# Límite para emitir sin identificar al receptor (actualizar según RG vigente)
AFIP_LIMITE_CF=97673.32

# Certificados
AFIP_CERT_PATH=./certs/afip_20123456789.crt
AFIP_KEY_PATH=./certs/afip_20123456789.key

# Caché (se genera automáticamente)
AFIP_TOKEN_CACHE_PATH=./.afip_token_cache_homo.json
AFIP_WSDL_CACHE_PATH=./.afip_wsdl_cache.db
```

---

## Uso

> Activar el entorno virtual antes de usar: `source .venv/bin/activate`

### Emitir factura simple

```bash
# Homologación (pruebas)
python3 facturar.py emitir --homo \
    --cuit-receptor 20111222333 \
    --monto 15000 \
    --concepto "Desarrollo de software — Mes de enero"

# Producción
python3 facturar.py emitir --prod \
    --cuit-receptor 20111222333 \
    --monto 15000 \
    --concepto "Desarrollo de software — Mes de enero" \
    --condicion-venta "Transferencia bancaria 30 días"
```

### Emitir factura con múltiples ítems

```bash
python3 facturar.py emitir --prod \
    --cuit-receptor 30999888777 \
    --item "Consultoría técnica" 10 5000 \
    --item "Gastos de viaje" 1 2500 \
    --concepto-afip 2          # 1=productos, 2=servicios, 3=ambos
```

### Emitir con período de servicio

```bash
python3 facturar.py emitir --prod \
    --cuit-receptor 20111222333 \
    --monto 30000 \
    --concepto "Servicio mensual de soporte" \
    --periodo-desde 20240101 \
    --periodo-hasta 20240131
```

### Generar PDF (duplicado)

Todos los comandos de emisión aceptan `--pdf` y `--duplicado`:

```bash
python3 facturar.py emitir --prod \
    --cuit-receptor 20111222333 \
    --monto 15000 \
    --concepto "Servicio" \
    --pdf factura_enero.pdf \
    --duplicado
```

### Reimprimir desde JSON guardado

Al emitir se puede guardar el JSON de respuesta:

```bash
python3 facturar.py emitir --prod --monto 1000 --concepto "..." | tee factura_001.json

# Reimprimir luego
python3 facturar.py reimprimir factura_001.json --duplicado
python3 facturar.py reimprimir factura_001.json --output factura_copia.pdf
```

### Consultar comprobante desde AFIP

```bash
# Mostrar datos en JSON
python3 facturar.py consultar --prod --numero 5

# Generar PDF desde AFIP
python3 facturar.py consultar --prod --numero 5 --pdf --duplicado
```

### Buscar comprobantes emitidos

```bash
# Por fecha
python3 facturar.py buscar --prod --desde-fecha 20240101 --hasta-fecha 20240131

# Por receptor
python3 facturar.py buscar --prod --receptor 20111222333

# Por rango de número
python3 facturar.py buscar --prod --desde-numero 1 --hasta-numero 50
```

### Nota de Crédito / Débito

```bash
python3 facturar.py emitir --prod \
    --tipo NC \
    --numero-original 5 \
    --cuit-receptor 20111222333 \
    --monto 15000 \
    --concepto "Anulación factura N° 0004-00000005"
```

### Validar CUIT

```bash
python3 facturar.py validar-cuit --prod 20111222333
```

### Generar PDF manualmente (sin emitir)

Útil para reimprimir facturas antiguas con datos manuales:

```bash
python3 facturar.py generar-pdf \
    --numero 1 \
    --fecha 20240115 \
    --cae 74123456789012 \
    --cae-vencimiento 20240125 \
    --monto 15000 \
    --concepto "Servicio de consultoría" \
    --nombre-cliente "Juan Pérez" \
    --output factura_reimpresa.pdf
```

---

## Estructura del proyecto

```
.
├── facturar.py          — CLI principal (punto de entrada)
├── config.py            — Carga y validación de configuración (.env)
├── models.py            — Modelos de datos: InvoiceRequest, InvoiceResponse, InvoiceItem
├── wsaa.py              — Autenticación WSAA (obtención de token y firma)
├── wsfev1.py            — Cliente WSFEv1: emisión, consulta y búsqueda de comprobantes
├── padron.py            — Consulta al padrón A13 de AFIP (datos del receptor)
├── pdf_generator.py     — Generación de PDF normativo con QR
├── validators.py        — Validación de CUIT/CUIL (formato y padrón)
├── ssl_transport.py     — Transporte HTTP con compatibilidad SSL legacy de AFIP
├── generar_csr.py       — Utilidad para generar clave RSA y CSR PKCS#10
├── requirements.txt     — Dependencias Python
├── setup.sh             — Setup interactivo
├── .env.example         — Plantilla de configuración
└── certs/               — Directorio para certificado y clave (en .gitignore)
```

---

## Flujo de autenticación

```
facturar.py
    └── wsaa.py → WSAA (LoginCms) → token + sign  [caché ~/.afip_token_cache_<env>.json]
    └── wsfev1.py → WSFEv1 (FECAESolicitar) → CAE
    └── padron.py → ws_sr_padron_a13 (getPersona) → nombre, domicilio
```

Los tokens WSAA tienen validez de ~12 horas y se reutilizan automáticamente.  
Se mantienen cachés separados para producción y homologación, y para cada servicio web (wsfe, padrón).

---

## Seguridad

- El archivo `.env` contiene su CUIT y rutas a certificados — **no lo comparta ni suba a Git**
- La clave privada (`.key`) permite firmar en su nombre ante AFIP — **trátela como contraseña**
- Los archivos sensibles están en `.gitignore` por defecto
- El transporte usa `SECLEVEL=1` para compatibilidad con los servidores legacy de AFIP sin comprometer la autenticación de certificados del servidor

---

## Entornos

| Flag | Servicio | Uso |
|------|----------|-----|
| `--homo` | wswhomo.afip.gob.ar | Pruebas — los comprobantes no tienen validez |
| `--prod` | servicios1.afip.gov.ar | Producción — comprobantes válidos ante AFIP |

En homologación el punto de venta puede ser el número `1` aunque no esté registrado.

---

## Notas

- Soporta **Factura C** (monotributistas). Para otros tipos de comprobante (A, B) se requieren cambios en `models.py` y `wsfev1.py`.
- El límite de Consumidor Final (`AFIP_LIMITE_CF`) cambia periódicamente — verificar el valor vigente en [afip.gob.ar](https://www.afip.gob.ar).
- La búsqueda de comprobantes (`buscar`) consulta uno por uno vía `FECompConsultar`, por lo que puede ser lenta para rangos amplios.
