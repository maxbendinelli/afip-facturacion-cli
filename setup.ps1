# ─────────────────────────────────────────────────────────────────────────────
# Setup interactivo para AFIP Facturación Electrónica (PowerShell)
# Crea el entorno virtual, instala dependencias y configura el archivo .env
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

function Print-Header {
    Write-Host "" -ForegroundColor Cyan
    Write-Host "══════════════════════════════════════════════════════" -ForegroundColor Cyan -Object "  AFIP Facturación Electrónica — Setup Inicial"
    Write-Host "══════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
}

function Step([string]$msg) { Write-Host "`n▶ $msg" -ForegroundColor Yellow -Style Bold }
function Ok([string]$msg)   { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Error-Msg([string]$msg) { Write-Host "  ✗ $msg" -ForegroundColor Red }
function Info([string]$msg)  { Write-Host "  $msg" }

function Ask([string]$prompt, [string]$default) {
    if ($default) {
        $val = Read-Host "  $prompt [$default]"
    } else {
        $val = Read-Host "  $prompt"
    }
    if ([string]::IsNullOrWhiteSpace($val) -and $default) { return $default }
    return $val
}

function Ask-Required([string]$prompt) {
    $val = ""
    while ([string]::IsNullOrWhiteSpace($val)) {
        $val = Read-Host "  $prompt"
        if ([string]::IsNullOrWhiteSpace($val)) { Warn "Este campo es obligatorio." }
    }
    return $val
}

function Confirm-Action([string]$prompt, [string]$default = "s") {
    $opts = "S/n"
    if ($default -eq "n") { $opts = "s/N" }
    $res = Read-Host "  $prompt [$opts]"
    if ([string]::IsNullOrWhiteSpace($res)) { $res = $default }
    return ($res -match "^[sSyY]$")
}

# ─────────────────────────────────────────────────────────────────────────────
Print-Header

# ── 1. Python ─────────────────────────────────────────────────────────────────
Step "Verificando Python..."

$PYTHON = "python"
try {
    $verString = python --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw }
} catch {
    try {
        $verString = python3 --version 2>&1
        $PYTHON = "python3"
    } catch {
        Error-Msg "Python no encontrado."
        Info "Asegúrese de tener Python 3.10+ instalado y en su PATH."
        exit 1
    }
}

$pyVer = & $PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$major = [int]$pyVer.Split('.')[0]
$minor = [int]$pyVer.Split('.')[1]

if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
    Error-Msg "Se requiere Python 3.10 o superior (encontrado: $pyVer)."
    exit 1
}
Ok "Python $pyVer"

# ── 2. Entorno virtual ────────────────────────────────────────────────────────
Step "Configurando entorno virtual..."

if (-not (Test-Path ".venv")) {
    & $PYTHON -m venv .venv
    Ok "Entorno virtual creado en .venv/"
} else {
    Ok "Entorno virtual existente (.venv/)"
}

# En PowerShell, activamos el script directamente
$ACTIVATE_SCRIPT = ".\.venv\Scripts\Activate.ps1"
if (Test-Path $ACTIVATE_SCRIPT) {
    . $ACTIVATE_SCRIPT
    Ok "Entorno virtual activado"
} else {
    # Caso para entornos no-Windows si alguien corre esto en Linux con pwsh
    $ACTIVATE_SCRIPT_NIX = "./.venv/bin/Activate.ps1"
    if (Test-Path $ACTIVATE_SCRIPT_NIX) {
        . $ACTIVATE_SCRIPT_NIX
        Ok "Entorno virtual activado"
    } else {
        Warn "No se pudo encontrar el script de activación. Continuando sin activar..."
    }
}

# ── 3. Dependencias ───────────────────────────────────────────────────────────
Step "Instalando dependencias..."

python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
Ok "Dependencias instaladas"

# ── 4. Configuración .env ─────────────────────────────────────────────────────
Step "Configuración de variables de entorno..."

if (Test-Path ".env") {
    Warn "Ya existe un archivo .env."
    if (-not (Confirm-Action "¿Sobreescribir con una nueva configuración?" "n")) {
        Ok "Se mantiene el .env existente."
        Write-Host "`nSetup completo." -ForegroundColor Green
        Info "Active el entorno con: . .\.venv\Scripts\Activate.ps1"
        Info "Use: python facturar.py --help"
        exit 0
    }
}

Write-Host "`n  ── Datos del emisor (aparecen en el PDF) ──────────────────" -ForegroundColor Cyan

$CUIT = Ask-Required "CUIT del emisor (11 dígitos, sin guiones)"
$CUIT = $CUIT -replace "[-. ]", ""
if ($CUIT -notmatch "^[0-9]{11}$") {
    Error-Msg "CUIT inválido: debe tener exactamente 11 dígitos."
    exit 1
}

$RAZON_SOCIAL = Ask "Razón social (nombre legal)" ""
$NOMBRE_FANTASIA = Ask "Nombre de fantasía — encabezado del PDF (dejar vacío si no aplica)" ""
$DOMICILIO = Ask "Domicilio comercial" ""
$DOMICILIO_FISCAL = Ask "Domicilio fiscal si difiere del comercial (vacío para usar el mismo)" ""
$INICIO_ACT = Ask "Inicio de actividades (DD/MM/AAAA)" ""
$ING_BRUTOS = Ask "Ingresos Brutos (número o EXENTO)" ""
$LOGO_PATH = Ask "Ruta al logo PNG (vacío si no aplica)" ""
$PUNTO_VENTA = Ask "Número de punto de venta" "1"
$LIMITE_CF = Ask "Límite para Consumidor Final (pesos)" "97673.32"

Write-Host "`n  ── Entorno AFIP ────────────────────────────────────────────" -ForegroundColor Cyan

$ENV_AFIP = "homo"
if (Confirm-Action "¿Usar entorno de PRODUCCIÓN? (responda NO para homologación/pruebas)" "n") {
    $ENV_AFIP = "prod"
    Warn "Entorno: PRODUCCIÓN — las facturas emitidas serán válidas ante AFIP."
} else {
    Ok "Entorno: homologación (pruebas, sin efecto real)."
}

Write-Host "`n  ── Certificados WSAA ───────────────────────────────────────" -ForegroundColor Cyan
Info "Los certificados se obtienen en el portal AFIP: https://auth.afip.gob.ar/"
Info "Servicios → WSASS → Agregar 'wsfe' → subir CSR → descargar .crt"

$CERT_PATH = ""
$KEY_PATH = ""

if (Confirm-Action "¿Ya tiene el certificado (.crt) y la clave privada (.key)?") {
    $CERT_PATH = Ask "Ruta al certificado (.crt / .pem)" "./certs/afip_$($CUIT).crt"
    $KEY_PATH = Ask  "Ruta a la clave privada (.key / .pem)" "./certs/afip_$($CUIT).key"
} else {
    if (Confirm-Action "¿Generar nueva clave RSA y CSR ahora?") {
        if ([string]::IsNullOrWhiteSpace($RAZON_SOCIAL)) { $RAZON_SOCIAL = Ask-Required "Razón social (requerida para el CSR)" }
        Write-Host ""
        python generar_csr.py --cuit "$CUIT" --razon-social "$RAZON_SOCIAL"
        $CERT_PATH = "./certs/afip_$($CUIT).crt"
        $KEY_PATH = "./certs/afip_$($CUIT).key"
        Write-Host ""
        Warn "Se generó la clave privada y el CSR."
        Warn "Suba  ./certs/afip_$($CUIT).csr  al portal AFIP."
        Warn "Cuando descargue el certificado, guárdelo en: $CERT_PATH"
        Warn "Luego puede editar el .env directamente o volver a ejecutar este script."
    } else {
        $CERT_PATH = "./certs/afip_$($CUIT).crt"
        $KEY_PATH = "./certs/afip_$($CUIT).key"
        Warn "Complete AFIP_CERT_PATH y AFIP_KEY_PATH en el archivo .env cuando tenga los certificados."
    }
}

# ── Escribir .env ─────────────────────────────────────────────────────────────
$envContent = @"
# AFIP Facturación Electrónica — Configuración local
# ADVERTENCIA: no subir este archivo a repositorios públicos.

# ── Identificación ────────────────────────────────────────────────────────────
AFIP_CUIT=$CUIT

# ── Datos del emisor (PDF) ────────────────────────────────────────────────────
AFIP_RAZON_SOCIAL=$RAZON_SOCIAL
AFIP_NOMBRE_FANTASIA=$NOMBRE_FANTASIA
AFIP_DOMICILIO=$DOMICILIO
AFIP_DOMICILIO_FISCAL=$DOMICILIO_FISCAL
AFIP_INICIO_ACTIVIDADES=$INICIO_ACT
AFIP_INGRESOS_BRUTOS=$ING_BRUTOS
AFIP_LOGO_PATH=$LOGO_PATH

# ── Punto de venta ────────────────────────────────────────────────────────────
AFIP_PUNTO_VENTA=$PUNTO_VENTA

# ── Límite Consumidor Final ───────────────────────────────────────────────────
AFIP_LIMITE_CF=$LIMITE_CF

# ── Certificados WSAA ─────────────────────────────────────────────────────────
AFIP_CERT_PATH=$CERT_PATH
AFIP_KEY_PATH=$KEY_PATH

# ── Caché (generado automáticamente) ─────────────────────────────────────────
AFIP_TOKEN_CACHE_PATH=./.afip_token_cache_$($ENV_AFIP).json
AFIP_WSDL_CACHE_PATH=./.afip_wsdl_cache.db
"@

Set-Content -Path ".env" -Value $envContent -Encoding utf8
Write-Host "`n  ✓ .env creado" -ForegroundColor Green

# ── Resumen ───────────────────────────────────────────────────────────────────
Write-Host "`n══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Setup completo" -ForegroundColor Green
Write-Host "══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Active el entorno virtual en cada sesión:"
Write-Host "    . .\.venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Comandos principales:"
Write-Host "    python facturar.py emitir --$ENV_AFIP --monto 1000 --concepto 'Prueba'" -ForegroundColor Cyan
Write-Host "    python facturar.py --help" -ForegroundColor Cyan
Write-Host ""
if ($ENV_AFIP -eq "homo") {
    Warn "Está en modo HOMOLOGACIÓN. Use --prod para emitir facturas reales."
}
Write-Host ""
