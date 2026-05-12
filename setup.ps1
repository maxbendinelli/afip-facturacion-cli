#Requires -Version 5.1
<#
.SYNOPSIS
    Setup interactivo para AFIP Facturación Electrónica (Windows)
.DESCRIPTION
    Crea el entorno virtual Python, instala dependencias y configura el archivo .env
.NOTES
    Si PowerShell bloquea la ejecución del script, ejecutar primero:
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    Luego:
        .\setup.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "`n▶ $msg" -ForegroundColor Yellow }
function Write-Ok   { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "  ✗ $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "  $msg" }

function Read-Value {
    param([string]$Prompt, [string]$Default = '')
    $display = if ($Default) { "$Prompt [$Default]" } else { $Prompt }
    $val = Read-Host "  $display"
    if ([string]::IsNullOrWhiteSpace($val) -and $Default) { $Default } else { $val.Trim() }
}

function Read-Required {
    param([string]$Prompt)
    $val = ''
    while ([string]::IsNullOrWhiteSpace($val)) {
        $val = (Read-Host "  $Prompt").Trim()
        if ([string]::IsNullOrWhiteSpace($val)) { Write-Warn 'Este campo es obligatorio.' }
    }
    $val
}

function Confirm-Yn {
    param([string]$Prompt, [string]$Default = 's')
    $opts = if ($Default -eq 's') { 'S/n' } else { 's/N' }
    $r = (Read-Host "  $Prompt [$opts]").Trim()
    if ([string]::IsNullOrWhiteSpace($r)) { $r = $Default }
    $r -match '^[sSyY]$'
}

# ── Encabezado ────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Blue
Write-Host '  AFIP Facturación Electrónica — Setup Inicial' -ForegroundColor Blue
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Blue
Write-Host ''

# ── 1. Python ─────────────────────────────────────────────────────────────────
Write-Step 'Verificando Python...'

$PYTHON = $null
foreach ($cmd in @('python', 'py')) {
    try {
        $verOutput = & $cmd --version 2>&1
        if ($verOutput -match 'Python (\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $PYTHON = $cmd
                Write-Ok "Python $major.$minor (comando: $cmd)"
                break
            }
            Write-Warn "Python $major.$minor es demasiado antiguo (mínimo 3.10)."
        }
    } catch { continue }
}

if (-not $PYTHON) {
    Write-Err 'Python 3.10 o superior no encontrado.'
    Write-Info 'Descargarlo de: https://www.python.org/downloads/'
    Write-Info "Durante la instalación marcar: 'Add Python to PATH'"
    exit 1
}

# ── 2. Entorno virtual ────────────────────────────────────────────────────────
Write-Step 'Configurando entorno virtual...'

if (-not (Test-Path '.venv')) {
    & $PYTHON -m venv .venv
    Write-Ok 'Entorno virtual creado en .venv\'
} else {
    Write-Ok 'Entorno virtual existente (.venv\)'
}

$activateScript = Join-Path $PWD '.venv\Scripts\Activate.ps1'
if (-not (Test-Path $activateScript)) {
    Write-Err "No se encontro el script de activacion: $activateScript"
    exit 1
}
& $activateScript
Write-Ok 'Entorno virtual activado'

# ── 3. Dependencias ───────────────────────────────────────────────────────────
Write-Step 'Instalando dependencias...'
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
Write-Ok 'Dependencias instaladas'

# ── 4. Configuración .env ─────────────────────────────────────────────────────
Write-Step 'Configuracion de variables de entorno...'

if (Test-Path '.env') {
    Write-Warn 'Ya existe un archivo .env.'
    if (-not (Confirm-Yn 'Sobreescribir con una nueva configuracion?' 'n')) {
        Write-Ok 'Se mantiene el .env existente.'
        Write-Host ''
        Write-Host 'Setup completo.' -ForegroundColor Green
        Write-Host '  Active el entorno con: .venv\Scripts\activate'
        Write-Host '  Ayuda: python facturar.py --help'
        exit 0
    }
}

Write-Host ''
Write-Host '  -- Datos del emisor (aparecen en el PDF) --' -ForegroundColor Cyan

$CUIT = Read-Required 'CUIT del emisor (11 digitos, sin guiones)'
$CUIT = $CUIT -replace '[-.\s]', ''
if ($CUIT -notmatch '^\d{11}$') {
    Write-Err "CUIT invalido '$CUIT': debe tener exactamente 11 digitos."
    exit 1
}

$RAZON_SOCIAL    = Read-Value 'Razon social (nombre legal)'
$NOMBRE_FANTASIA = Read-Value 'Nombre de fantasia — encabezado PDF (vacio si no aplica)'
$DOMICILIO       = Read-Value 'Domicilio comercial'
$DOM_FISCAL      = Read-Value 'Domicilio fiscal si difiere del comercial (vacio = mismo)'
$INICIO_ACT      = Read-Value 'Inicio de actividades (DD/MM/AAAA)'
$ING_BRUTOS      = Read-Value 'Ingresos Brutos (numero o EXENTO)'
$LOGO_PATH       = Read-Value 'Ruta al logo PNG (vacio si no aplica)'
$PUNTO_VENTA     = Read-Value 'Numero de punto de venta' '1'
$LIMITE_CF       = Read-Value 'Limite para Consumidor Final (pesos)' '97673.32'

Write-Host ''
Write-Host '  -- Entorno AFIP --' -ForegroundColor Cyan
Write-Host ''

$ENV_AFIP = 'homo'
if (Confirm-Yn 'Usar entorno de PRODUCCION? (NO = homologacion/pruebas)' 'n') {
    $ENV_AFIP = 'prod'
    Write-Warn 'Entorno: PRODUCCION — las facturas seran validas ante AFIP.'
} else {
    Write-Ok 'Entorno: homologacion (pruebas, sin efecto real).'
}

Write-Host ''
Write-Host '  -- Certificados WSAA --' -ForegroundColor Cyan
Write-Host ''
Write-Info 'Los certificados se obtienen en: https://auth.afip.gob.ar/'
Write-Info 'Servicios -> WSASS -> Agregar "wsfe" -> subir CSR -> descargar .crt'

function Setup-Cert {
    param([string]$Label, [string]$DefaultDir)
    Write-Host ''
    Write-Host "  -- Certificado $Label --" -ForegroundColor Cyan
    Write-Host ''
    $cert = ''; $key = ''
    if (Confirm-Yn "Tiene certificado para $Label?") {
        $cert = Read-Value 'Ruta al certificado (.crt / .pem)' "$DefaultDir\afip_$CUIT.crt"
        $key  = Read-Value 'Ruta a la clave privada (.key / .pem)' "$DefaultDir\afip_$CUIT.key"
    } else {
        if (Confirm-Yn "Generar nueva clave RSA y CSR para $Label ahora?") {
            if ([string]::IsNullOrWhiteSpace($RAZON_SOCIAL)) {
                $script:RAZON_SOCIAL = Read-Required 'Razon social (requerida para el CSR)'
            }
            New-Item -ItemType Directory -Force -Path $DefaultDir | Out-Null
            Write-Host ''
            & $PYTHON generar_csr.py --cuit $CUIT --razon-social $RAZON_SOCIAL --out-dir $DefaultDir
            $cert = "$DefaultDir\afip_$CUIT.crt"
            $key  = "$DefaultDir\afip_$CUIT.key"
            Write-Host ''
            Write-Warn "Suba  $DefaultDir\afip_$CUIT.csr  al portal AFIP."
            Write-Warn "Guarde el certificado descargado en: $cert"
        } else {
            $cert = "$DefaultDir\afip_$CUIT.crt"
            $key  = "$DefaultDir\afip_$CUIT.key"
            Write-Warn "Complete las rutas en el .env cuando tenga los certificados de $Label."
        }
    }
    return @{ Cert = $cert; Key = $key }
}

$homo = Setup-Cert 'HOMOLOGACION' '.\certs\homo'
$prod = Setup-Cert 'PRODUCCION'   '.\certs'
$CERT_PATH_HOMO = $homo.Cert; $KEY_PATH_HOMO = $homo.Key
$CERT_PATH_PROD = $prod.Cert; $KEY_PATH_PROD = $prod.Key

# ── Escribir .env ─────────────────────────────────────────────────────────────
$envLines = @(
    '# AFIP Facturacion Electronica - Configuracion local'
    '# ADVERTENCIA: no subir este archivo a repositorios publicos.'
    ''
    '# -- Identificacion --'
    "AFIP_CUIT=$CUIT"
    ''
    '# -- Datos del emisor (PDF) --'
    "AFIP_RAZON_SOCIAL=$RAZON_SOCIAL"
    "AFIP_NOMBRE_FANTASIA=$NOMBRE_FANTASIA"
    "AFIP_DOMICILIO=$DOMICILIO"
    "AFIP_DOMICILIO_FISCAL=$DOM_FISCAL"
    "AFIP_INICIO_ACTIVIDADES=$INICIO_ACT"
    "AFIP_INGRESOS_BRUTOS=$ING_BRUTOS"
    "AFIP_LOGO_PATH=$LOGO_PATH"
    ''
    '# -- Punto de venta --'
    "AFIP_PUNTO_VENTA=$PUNTO_VENTA"
    ''
    '# -- Limite Consumidor Final --'
    "AFIP_LIMITE_CF=$LIMITE_CF"
    ''
    '# -- Certificados WSAA (separados por entorno) --'
    "AFIP_CERT_PATH_HOMO=$CERT_PATH_HOMO"
    "AFIP_KEY_PATH_HOMO=$KEY_PATH_HOMO"
    "AFIP_CERT_PATH_PROD=$CERT_PATH_PROD"
    "AFIP_KEY_PATH_PROD=$KEY_PATH_PROD"
    ''
    '# -- Cache (generado automaticamente) --'
    '# El codigo agrega _{env}.json al prefijo: caches separados para homo y prod'
    'AFIP_TOKEN_CACHE_PATH=.\.afip_token_cache'
    'AFIP_WSDL_CACHE_PATH=.\.afip_wsdl_cache.db'
)

Set-Content -Path '.env' -Value $envLines -Encoding UTF8
Write-Ok '.env creado'

# ── Resumen ───────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Green
Write-Host '  Setup completo' -ForegroundColor Green
Write-Host '══════════════════════════════════════════════════════' -ForegroundColor Green
Write-Host ''
Write-Host '  Active el entorno virtual en cada sesion:'
Write-Host '    .venv\Scripts\activate' -ForegroundColor White
Write-Host ''
Write-Host '  Comandos principales:'
Write-Host "    python facturar.py emitir --$ENV_AFIP --monto 1000 --concepto 'Prueba'" -ForegroundColor White
Write-Host '    python facturar.py --help' -ForegroundColor White
Write-Host ''
if ($ENV_AFIP -eq 'homo') {
    Write-Warn 'Esta en modo HOMOLOGACION. Use --prod para emitir facturas reales.'
}
Write-Host ''
