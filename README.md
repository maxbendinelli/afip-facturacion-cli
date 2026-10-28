# afip-facturacion-cli

Sistema integral en Python para facturación electrónica argentina a través de los servicios web de **ARCA / AFIP** (WSFEv1 y WSAA). 

Incluye **CLI**, **Dashboard Web interactivo**, **Servidor MCP multiplataforma** para agentes de IA y automatizaciones, **Facturación por Lotes (CSV)** y **Generador de Facturas PDF personalizables** con formato oficial.

🔗 **Repositorio:** [https://github.com/maxbendinelli/afip-facturacion-cli](https://github.com/maxbendinelli/afip-facturacion-cli)

---

## 🚀 Características Principales

- 🧾 **Emisión de Comprobantes Oficiales:** Facturas A, B y C, Notas de Crédito y Débito (A, B y C).
- 🖥️ **Dashboard Web Moderno (GUI):** Interfaz web completa (FastAPI + HTML5/CSS Vanilla) con visor PDF embebido e impresión directa.
- 📦 **Facturación por Lotes Avanzada (CSV):**
  - Carga masiva mediante archivo CSV compatible con exportaciones administrativas y de obras sociales.
  - Tabla interactiva de previsualización antes de emitir (desglose automático de Neto, IVA, Exentos y validación de CUITs).
  - **Soporte Inteligente de Exentos (0% IVA):** Enrutamiento automático a `ImpOpEx` para internación geriátrica y prestaciones médicas exentas (evitando el error 10070 de AFIP).
  - **Resolución Monótona de Fechas:** Garantiza que cada comprobante cumpla con la ventana N-10 a N+10 de servicios y la correlatividad temporal estricta de AFIP (evitando el error 10016).
  - **Protección Anti-Duplicados:** Detección automática de comprobantes previamente autorizados en el período para evitar doble facturación accidental.
  - Modos de ejecución: **Simulación Local (Dry-Run)**, **Homologación AFIP (Testing real sin consecuencias fiscales)** y **Producción Oficial**.
  - Descarga consolidada de todos los comprobantes en un archivo **ZIP**.
- 🪪 **Catálogo Oficial Completo de Documentos (AFIP):** Soporte exhaustivo para CUIT (80), CUIL (86), CDI (87), Libreta de Enrolamiento (89), Libreta Cívica (90), CI Extranjera (91), DNI (96), Pasaporte (94), CI Policía Federal (0), Certificado de Migración (95) y Sin Documento (99).
- 📡 **Monitor AFIP Online en Tiempo Real:** Visualización en vivo del último comprobante registrado en los servidores de AFIP y del próximo número a emitir para cada Punto de Venta y tipo de comprobante.
- 🏛️ **Padrón A13 con Nombres Reales:** Autocompletado instantáneo de Razón Social y Domicilio fiscal consultando en producción para obtener siempre las denominaciones reales, aun en entorno de testing.
- 🎨 **Personalización y Diseño Oficial de Facturas PDF:**
  - Carga de **Logotipo comercial** de la empresa con **alto configurable en milímetros** (`AFIP_LOGO_HEIGHT_MM`, de 6 a 60 mm) y autoexpansión de la cabecera.
  - **Ajuste y Salto de Renglón Automático:** distribución en múltiples renglones por palabras de razones sociales extensas y domicilios largos sin desbordar el comprobante.
  - **Régimen de Transparencia Fiscal al Consumidor (Ley 27.743 - RG 5614/2024):** cálculo y discriminación automática de **IVA Contenido** en Facturas B.
  - **Visualización permanente de Ingresos Brutos** (número de inscripción o `EXENTO`).
  - Recuadro para **Leyenda / Datos Bancarios** (CBU, Alias, Banco, observaciones comerciales).
  - **Marcas de agua** configurables (texto como "ORIGINAL", "DUPLICADO", "PAGADO" o imagen transparente).
  - Botón de previsualización en vivo de factura de muestra con el diseño configurado.
- 🏷️ **Nomenclatura Estandarizada de Archivos PDF:**
  - Rotulado uniforme y ordenado cronológicamente: `AAAA-MM-DD Fact. AAAA-MM <Cliente> <J>.<Z>. <CUIT_EMISOR>_<COD_3D>_<PV_5D>_<NRO_8D>.pdf` (donde `J` es el tipo F/NC/ND, `Z` la letra A/B/C, `COD_3D` el código AFIP y `NRO_8D` el número oficial).
- 📧 **Envío de Facturas por Correo Electrónico (SMTP):**
  - Envío automático de facturas con PDF adjunto para comprobantes individuales o masivos en lote.
  - Soporte para TLS/STARTTLS y SSL directo (Gmail, Outlook, servidores corporativos) con protección anti-rate-limit.
- 🔐 **Selector y Gestor de Certificados:** Explorador visual de archivos `.crt` y `.key`, detección automática en carpetas y subida directa desde el navegador.
- 🏛️ **Padrón A13 de AFIP:** Autocompletado instantáneo de Razón Social y Domicilio fiscal al ingresar el CUIT o DNI del cliente.
- ⚖️ **11 Condiciones Oficiales frente al IVA:** Soporte exhaustivo para todas las condiciones vigentes de AFIP bajo la **RG 5616** con compatibilidad histórica.
- 🤖 **Servidor MCP (Model Context Protocol):** Compatible con Claude Desktop / Code, Cursor, Antigravity, VS Code, n8n, LangChain y bots autónomos (transportes STDIO y SSE/HTTP).
- 🧪 **Modos Homologación y Producción:** Pruebas seguras sin consecuencias fiscales o emisión legal en vivo.

---

## 🖥️ Interfaz Gráfica Web (GUI)

La aplicación incluye un servidor web local y dashboard interactivo que no requiere NodeJS ni compilaciones externas:

```bash
# En Linux / WSL:
python3 run_gui.py
# o bien:
./run_gui.sh

# En Windows:
run_gui.bat
```

Se abrirá automáticamente en tu navegador en `http://localhost:8000`:

| Sección / Pestaña | Descripción |
|---|---|
| **📝 Emisión Individual** | Emisión interactiva de Facturas A, B y C, Notas de Crédito y Débito. Cálculo dinámico de IVA (21%, 10.5%, 27%, etc.), visor PDF integrado e impresión con un clic. |
| **📊 Facturación por Lotes (CSV)** | Carga masiva de comprobantes con previsualización inteligente, corrección de errores previa y descarga de PDFs en `.ZIP`. |
| **📁 Historial de Comprobantes** | Registro, consulta detallada, búsqueda y reimpresión de comprobantes emitidos. |
| **⚙️ Configuración & Diseño** | Configuración de CUIT emisor, puntos de venta, selector/subida de certificados, personalización de diseño (logo, CBU, marcas de agua) y test de conexión con AFIP. |
| **🔑 Asistente CSR / Claves** | Asistente para generar clave privada RSA de 2048/4096 bits y el pedido de certificado (CSR) para subir al portal de AFIP. |

---

## 📦 Requisitos e Instalación

### Requisitos
- **Python 3.11+**
- Certificado digital emitido por AFIP/ARCA (ver [Configuración inicial](#-configuración-inicial))

### Instalación Rápida

```bash
git clone https://github.com/maxbendinelli/afip-facturacion-cli.git
cd afip-facturacion-cli

python3 -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Completar las variables en .env o ajustarlas desde la pestaña Configuración de la GUI
```

---

## ⚙️ Configuración Inicial de Certificados AFIP

### 1. Generar Clave Privada y CSR
Puedes hacerlo desde la pestaña **"Asistente CSR"** de la GUI o vía CLI:

```bash
python3 generar_csr.py --cuit 20123456789 --razon-social "Tu Nombre o Empresa"
```
Esto creará `certs/afip_20123456789.key` y `certs/afip_20123456789.csr`.

### 2. Dar de alta el Certificado en AFIP
1. Ingresá a [auth.afip.gob.ar](https://auth.afip.gob.ar/) con tu Clave Fiscal nivel 3+.
2. Ingresá a **Administración de Certificados Digitales** (o *WSASS* para Homologación).
3. Creá un alias (ej: `facturacion`) y subí el archivo `.csr`.
4. Descargá el certificado `.crt` emitido y guardalo en la carpeta `certs/` (o subilo desde la GUI).
5. En **Administrador de Relaciones de Clave Fiscal**, asociá el computador fiscal al servicio:
   - Para Producción: **Facturación Electrónica** (`wsfe`).
   - Para Homologación: **WSFE - Facturación Electrónica** (ambiente testing).

### 3. Variables de Entorno (`.env`)

```env
# Entorno: 'homo' para testing o 'prod' para legal oficial
AFIP_ENV=homo

# Datos fiscales del emisor
AFIP_CUIT=20123456789
AFIP_PUNTO_VENTA=1
AFIP_RAZON_SOCIAL=Juan Perez
AFIP_DOMICILIO=Av. Corrientes 1234, CABA
AFIP_CONDICION_IVA=Responsable Monotributo
AFIP_INGRESOS_BRUTOS=20123456789

# Rutas de certificados
AFIP_CERT_PATH=./certs/afip_20123456789.crt
AFIP_KEY_PATH=./certs/afip_20123456789.key
AFIP_CERT_PATH_HOMO=./certs/homo/afip_20123456789.crt
AFIP_KEY_PATH_HOMO=./certs/homo/afip_20123456789.key

# Personalización estética de Facturas PDF (Opcional)
AFIP_LOGO_PATH=./static/uploads/logo.png
AFIP_LOGO_HEIGHT_MM=16
AFIP_LEYENDA=Pago por transferencia - CBU: 0110599520000012345678 Alias: MIEMPRESA.PAGOS
AFIP_WATERMARK_TEXT=
AFIP_WATERMARK_IMAGE=

# Configuración de Envío por Email (SMTP - Opcional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=tls
SMTP_USER=tu-cuenta@gmail.com
SMTP_PASSWORD=tu-contraseña-de-aplicacion
SMTP_FROM_NAME="Tu Empresa o Nombre"
SMTP_FROM_EMAIL=tu-cuenta@gmail.com
```

---

## 🏷️ Nomenclatura y Rotulado de Comprobantes

Todos los archivos PDF generados (en emisión manual, simulación, lotes CSV o reimpresión) siguen un formato de rotulado estricto y ordenado cronológicamente:

```text
AAAA-MM-DD Fact. AAAA-MM <Cliente> <J>.<Z>. <CUIT_EMISOR>_<00X>_<PV_5D>_<NRO_8D>.pdf
```

| Elemento | Significado | Ejemplo |
|---|---|---|
| `AAAA-MM-DD` | Fecha de emisión del comprobante | `2026-10-28` |
| `Fact. AAAA-MM` | Mes del período facturado (o mes de emisión si no aplica período) | `Fact. 2026-10` |
| `<Cliente>` | Nombre o Razón Social del destinatario (o `Consumidor Final`) | `M. Bendinelli` |
| `<J>.<Z>.` | Tipo abreviado (`J` = `F`, `NC`, `ND`, `R` / `Z` = letra `A`, `B`, `C`) | `F.B.` / `F.A.` / `NC.B.` |
| `<CUIT_EMISOR>` | CUIT del emisor (11 dígitos continuos) | `23255684779` |
| `<00X>` | Código numérico oficial de comprobante AFIP (3 dígitos) | `006` (Fact. B), `001` (Fact. A), `008` (NC B), `011` (Fact. C) |
| `<PV_5D>` | Punto de venta con relleno a 5 dígitos | `00004` |
| `<NRO_8D>` | Número oficial de comprobante con relleno a 8 dígitos | `00000014` |

**Ejemplo completo:**
```text
2026-10-28 Fact. 2026-10 M. Bendinelli F.B. 23255684779_006_00004_00000014.pdf
```

---

## 📊 Facturación por Lotes (CSV)

La funcionalidad de lotes permite procesar decenas o cientos de comprobantes en segundos.

### Formato del archivo CSV
Se admiten separadores por coma (`,`) o punto y coma (`;`). La plantilla modelo incluye las siguientes columnas:

```csv
tipo,cuit_cliente,nombre_cliente,concepto,monto,alicuota_iva,condicion_iva
C,20123456789,Juan Perez,Servicio de consultoria,15000,0,CF
B,SIN_CUIT,Consumidor Final,Articulos de libreria,24200,21,CF
A,30712345671,Empresa SA,Desarrollo de software,50000,21,RI
C,27234567894,Maria Gomez,Diseno grafico,35000,0,MONO
```

- **tipo:** `A`, `B` o `C`.
- **cuit_cliente:** CUIT de 11 dígitos, DNI o `SIN_CUIT` / `0` (Consumidor Final).
- **monto:** Importe total de la operación (admite formatos `15000`, `15000.50` o `$ 15.000,50`).
- **alicuota_iva:** `21`, `10.5`, `27`, `5`, `2.5` o `0`.
- **condicion_iva:** Siglas (`RI`, `CF`, `MONO`, `EX`, `MS`, `TIP`, `NA`), número de ID (`1`, `4`, `5`, etc.) o descripción.

---

## ⚖️ Condiciones frente al IVA del Receptor (RG 5616)

El sistema implementa el nomenclador oficial completo de AFIP (`FEParamGetCondicionIvaReceptor`):

| ID | Condición frente al IVA | Alias reconocidos en CSV / CLI | Comprobantes admitidos |
|:---:|:---|:---|:---|
| **1** | **IVA Responsable Inscripto** | `RI`, `RESPONSABLE_INSCRIPTO`, `INSCRIPTO` | Factura A, Factura C |
| **4** | **IVA Sujeto Exento** | `EX`, `EXENTO`, `SUJETO_EXENTO` | Factura B, Factura C |
| **5** | **Consumidor Final** | `CF`, `CONSUMIDOR_FINAL`, `FINAL` | Factura B, Factura C |
| **6** | **Responsable Monotributo** | `MONO`, `MONOTRIBUTO`, `MONOTRIBUTISTA` | Factura A (RG 5003), Factura C |
| **7** | **Sujeto No Categorizado** | `NC`, `NO_CATEGORIZADO` | Factura B, Factura C |
| **8** | **Proveedor del Exterior** | `PROVEEDOR_EXTERIOR`, `IMPORTADOR` | Factura B, Factura C |
| **9** | **Cliente del Exterior** | `CLIENTE_EXTERIOR`, `EXPORTACION` | Factura B, Factura C |
| **10** | **IVA Liberado - Ley Nº 19.640** | `LIBERADO`, `LEY_19640`, `TIERRA_DEL_FUEGO` | Factura B, Factura C |
| **13** | **Monotributista Social** | `MS`, `MONOTRIBUTO_SOCIAL` | Factura A (RG 5003), Factura C |
| **15** | **IVA No Alcanzado** | `NA`, `NO_ALCANZADO`, `IVA_NO_ALCANZADO` | Factura B, Factura C |
| **16** | **Monotributista Trabajador Independiente Promovido** | `TIP`, `PROMOVIDO`, `MONOTRIBUTO_PROMOVIDO` | Factura A (RG 5003), Factura C |

---

## 💻 Uso por Línea de Comandos (CLI)

### Emitir Comprobante
```bash
# Factura C a Consumidor Final en Producción con generación de PDF:
python3 facturar.py emitir \
  --concepto "Servicios profesionales" \
  --monto 25000 \
  --env prod --pdf

# Factura con CUIT y resolución automática de Padrón A13:
python3 facturar.py emitir \
  --cuit-cliente 30-71234567-8 \
  --concepto "Desarrollo de Software" \
  --monto 150000 \
  --env prod --pdf --duplicado

# Factura con múltiples ítems:
python3 facturar.py emitir \
  --item "Servicio de Hosting Anual|1|60000" \
  --item "Mantenimiento Mensual|3|15000" \
  --env prod --pdf
```

### Facturación Masiva por Lotes (CSV)
```bash
# Simulación previa en local sin contactar a AFIP (Dry-Run):
python3 facturar.py lote archivo_clientes.csv --dry-run

# Emisión masiva en Producción con PDFs y archivo ZIP consolidado:
python3 facturar.py lote archivo_clientes.csv --env prod --zip facturas_mes.zip
```

### Facturación con diferentes tipos de Documento (RG 5616 / AFIP)
```bash
# Factura B a receptor con DNI, LE, LC o Pasaporte:
python3 facturar.py emitir \
  --tipo B \
  --cuit-cliente 4250492 \
  --doc-tipo DNI \
  --concepto "Servicios de atención permanente" \
  --monto 3146000 \
  --env prod --pdf
```

### Notas de Crédito y Débito
```bash
python3 facturar.py nota-credito --numero-original 27 --monto 15000 --env prod
python3 facturar.py nota-debito  --numero-original 27 --monto 2500 --env prod
```

### Consultas y Reimpresión
```bash
# Consultar el último número emitido:
python3 facturar.py ultimo-numero --tipo C --env prod

# Consultar y regenerar PDF de un comprobante:
python3 facturar.py consultar --numero 27 --tipo C --env prod --pdf

# Validar CUIT en el padrón AFIP:
python3 facturar.py validar-cuit 20-12345678-3 --afip --env prod
```

---

## 🤖 Servidor MCP (Model Context Protocol)

El proyecto incluye un servidor MCP abierto (`mcp_server.py`) que expone las herramientas de AFIP para cualquier asistente o flujo automatizado:

### Modos de Ejecución
```bash
# Modo STDIO (para Cursor, Antigravity, VS Code, Claude Desktop / Code):
python3 mcp_server.py --transport stdio

# Modo SSE / HTTP (para n8n, Flowise, microservicios y bots remotos):
python3 mcp_server.py --transport sse --port 8001
```

### Herramientas MCP Disponibles:
- `emitir_factura`: Emisión de comprobantes con obtención de CAE y PDF.
- `emitir_nota_credito` y `emitir_nota_debito`: Emisión asociada a comprobante previo.
- `consultar_ultimo_comprobante`: Obtiene el último folio autorizado por tipo y punto de venta.
- `consultar_comprobante`: Consulta estado y metadatos de un comprobante en AFIP.
- `consultar_padron_a13`: Obtiene nombre, razón social y domicilio fiscal desde AFIP.
- `validar_cuit`: Valida dígito verificador y estado en el padrón.

---

## 📁 Estructura del Proyecto

```
afip-facturacion-cli/
├── run_gui.py           # Lanzador multiplataforma de la GUI
├── run_gui.sh           # Script de inicio para Linux / macOS / WSL
├── run_gui.bat          # Script de inicio para Windows
├── web_server.py        # API FastAPI y servidor de la interfaz web
├── facturar.py          # CLI de facturación por terminal
├── mcp_server.py        # Servidor MCP (Model Context Protocol)
├── models.py            # Modelos de datos, RG 5616 y nomencladores AFIP
├── config.py            # Gestión de configuración y variables de entorno
├── wsaa.py              # Autenticación WSAA (Ticket de Acceso: Token + Sign)
├── wsfev1.py            # Web Service de Facturación Electrónica WSFEv1
├── padron.py            # Consulta al Padrón de Personas A13 de AFIP
├── validators.py        # Validaciones de CUIT (algoritmo Módulo 11 + AFIP)
├── pdf_generator.py     # Motor ReportLab para facturas oficiales personalizables
├── ssl_transport.py     # Transporte Zeep HTTPS con certificado cliente
├── generar_csr.py       # Generador de clave privada RSA y solicitud CSR
├── static/              # Archivos estáticos del Dashboard Web
│   ├── index.html       # Interfaz gráfica moderna de usuario
│   ├── app.css          # Estilos y diseño responsivo
│   ├── app.js           # Controlador frontend e interactividad
│   └── uploads/         # Directorio de logos y marcas de agua (ignorado en git)
├── comprobantes/        # Facturas PDF y metadatos JSON generados (ignorado en git)
├── certs/               # Certificados y claves privadas (ignorado en git)
├── requirements.txt     # Dependencias de Python
└── .env.example         # Plantilla de variables de entorno
```

---

## 🔒 Seguridad y Privacidad

- ⚠️ **Certificados y Claves:** Los archivos `.crt`, `.key`, `.pem`, `.pfx` y `.csr` están estrictamente excluidos del control de versiones a través de `.gitignore`.
- ⚠️ **Credenciales:** Tu archivo `.env` nunca debe subirse a ningún repositorio público.
- ⚠️ **Datos de Comprobantes:** Los PDFs generados y archivos JSON con datos fiscales de tus clientes se almacenan en `comprobantes/` y se encuentran totalmente protegidos e ignorados por Git.

---

## 📄 Licencia

Distribuido bajo licencia **MIT**. Consulte el archivo `LICENSE` para más información.
