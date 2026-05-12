#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Setup interactivo para AFIP Facturación Electrónica
# Crea el entorno virtual, instala dependencias y configura el archivo .env
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colores ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}${BOLD}══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}${BOLD}  AFIP Facturación Electrónica — Setup Inicial${NC}"
    echo -e "${BLUE}${BOLD}══════════════════════════════════════════════════════${NC}"
    echo ""
}

step()  { echo -e "\n${YELLOW}${BOLD}▶ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
error() { echo -e "${RED}  ✗ $1${NC}"; }
info()  { echo -e "  $1"; }

# Pide un valor con prompt y default opcional
ask() {
    local prompt="$1" default="${2:-}"
    if [ -n "$default" ]; then
        printf "  %s [%s]: " "$prompt" "$default"
    else
        printf "  %s: " "$prompt"
    fi
    read -r _val
    if [ -z "$_val" ] && [ -n "$default" ]; then _val="$default"; fi
    printf '%s' "$_val"
}

# Pide un valor obligatorio (repite hasta que no esté vacío)
ask_req() {
    local prompt="$1" _val=""
    while [ -z "$_val" ]; do
        _val=$(ask "$prompt" "")
        [ -z "$_val" ] && warn "Este campo es obligatorio."
    done
    printf '%s' "$_val"
}

# Pide confirmación s/n
confirm() {
    local prompt="$1" default="${2:-s}"
    local opts="S/n"
    [ "$default" = "n" ] && opts="s/N"
    printf "  %s [%s]: " "$prompt" "$opts"
    read -r _r
    [ -z "$_r" ] && _r="$default"
    [[ "$_r" =~ ^[sSyY]$ ]]
}

# ─────────────────────────────────────────────────────────────────────────────
print_header

# ── 1. Python ─────────────────────────────────────────────────────────────────
step "Verificando Python..."

PYTHON=$(command -v python3 2>/dev/null || true)
if [ -z "$PYTHON" ]; then
    error "Python 3 no encontrado."
    info  "Instalarlo con: sudo apt install python3  (Debian/Ubuntu)"
    info  "                brew install python        (macOS)"
    exit 1
fi

PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")
PY_VER="$PY_MAJOR.$PY_MINOR"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    error "Se requiere Python 3.10 o superior (encontrado: $PY_VER)."
    exit 1
fi
ok "Python $PY_VER"

# ── 2. Entorno virtual ────────────────────────────────────────────────────────
step "Configurando entorno virtual..."

if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
    ok "Entorno virtual creado en .venv/"
else
    ok "Entorno virtual existente (.venv/)"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
ok "Entorno virtual activado"

# ── 3. Dependencias ───────────────────────────────────────────────────────────
step "Instalando dependencias..."

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
ok "Dependencias instaladas"

# ── 4. Configuración .env ─────────────────────────────────────────────────────
step "Configuración de variables de entorno..."

if [ -f ".env" ]; then
    warn "Ya existe un archivo .env."
    if ! confirm "¿Sobreescribir con una nueva configuración?" "n"; then
        ok "Se mantiene el .env existente."
        echo ""
        echo -e "${GREEN}${BOLD}Setup completo.${NC} Active el entorno con:"
        echo "  source .venv/bin/activate"
        echo ""
        echo "Use  python3 facturar.py --help  para ver los comandos disponibles."
        exit 0
    fi
fi

echo ""
echo -e "${BOLD}  ── Datos del emisor (aparecen en el PDF) ──────────────────${NC}"
echo ""

CUIT=$(ask_req "CUIT del emisor (11 dígitos, sin guiones)")
CUIT="${CUIT//[-. ]/}"
if ! [[ "$CUIT" =~ ^[0-9]{11}$ ]]; then
    error "CUIT inválido: debe tener exactamente 11 dígitos."
    exit 1
fi

RAZON_SOCIAL=$(ask "Razón social (nombre legal)" "")
NOMBRE_FANTASIA=$(ask "Nombre de fantasía — encabezado del PDF (dejar vacío si no aplica)" "")
DOMICILIO=$(ask "Domicilio comercial" "")
DOMICILIO_FISCAL=$(ask "Domicilio fiscal si difiere del comercial (vacío para usar el mismo)" "")
INICIO_ACT=$(ask "Inicio de actividades (DD/MM/AAAA)" "")
ING_BRUTOS=$(ask "Ingresos Brutos (número o EXENTO)" "")
LOGO_PATH=$(ask "Ruta al logo PNG (vacío si no aplica)" "")
PUNTO_VENTA=$(ask "Número de punto de venta" "1")
LIMITE_CF=$(ask "Límite para Consumidor Final (pesos)" "97673.32")

echo ""
echo -e "${BOLD}  ── Entorno AFIP ────────────────────────────────────────────${NC}"
echo ""

ENV="homo"
if confirm "¿Usar entorno de PRODUCCIÓN? (responda NO para homologación/pruebas)" "n"; then
    ENV="prod"
    warn "Entorno: PRODUCCIÓN — las facturas emitidas serán válidas ante AFIP."
else
    ok "Entorno: homologación (pruebas, sin efecto real)."
fi

echo ""
echo -e "${BOLD}  ── Certificados WSAA ───────────────────────────────────────${NC}"
echo ""
info "Los certificados se obtienen en el portal AFIP: https://auth.afip.gob.ar/"
info "Servicios → WSASS → Agregar 'wsfe' → subir CSR → descargar .crt"
echo ""

_setup_cert_env() {
    local label="$1"   # "HOMOLOGACIÓN" o "PRODUCCIÓN"
    local env_tag="$2" # "homo" o "prod"
    local default_dir="$3"

    echo ""
    echo -e "${BOLD}  ── Certificado ${label} ────────────────────────${NC}"
    echo ""

    local cert_var="CERT_PATH_${env_tag^^}"
    local key_var="KEY_PATH_${env_tag^^}"

    if confirm "¿Tiene certificado para ${label}?"; then
        printf -v "$cert_var" '%s' "$(ask "Ruta al certificado (.crt / .pem)" "${default_dir}/afip_${CUIT}.crt")"
        printf -v "$key_var"  '%s' "$(ask "Ruta a la clave privada (.key / .pem)" "${default_dir}/afip_${CUIT}.key")"
    else
        if confirm "¿Generar nueva clave RSA y CSR para ${label} ahora?"; then
            [ -z "$RAZON_SOCIAL" ] && RAZON_SOCIAL=$(ask_req "Razón social (requerida para el CSR)")
            mkdir -p "${default_dir}"
            echo ""
            $PYTHON generar_csr.py --cuit "$CUIT" --razon-social "$RAZON_SOCIAL" --out-dir "${default_dir}"
            printf -v "$cert_var" '%s' "${default_dir}/afip_${CUIT}.crt"
            printf -v "$key_var"  '%s' "${default_dir}/afip_${CUIT}.key"
            echo ""
            warn "Suba  ${default_dir}/afip_${CUIT}.csr  al portal AFIP."
            warn "Guarde el certificado descargado en: ${default_dir}/afip_${CUIT}.crt"
        else
            printf -v "$cert_var" '%s' "${default_dir}/afip_${CUIT}.crt"
            printf -v "$key_var"  '%s' "${default_dir}/afip_${CUIT}.key"
            warn "Complete las rutas en el .env cuando tenga los certificados de ${label}."
        fi
    fi
}

_setup_cert_env "HOMOLOGACIÓN" "homo" "./certs/homo"
_setup_cert_env "PRODUCCIÓN"   "prod" "./certs"

# ── Escribir .env ─────────────────────────────────────────────────────────────
cat > .env <<EOF
# AFIP Facturación Electrónica — Configuración local
# ADVERTENCIA: no subir este archivo a repositorios públicos.

# ── Identificación ────────────────────────────────────────────────────────────
AFIP_CUIT=${CUIT}

# ── Datos del emisor (PDF) ────────────────────────────────────────────────────
AFIP_RAZON_SOCIAL=${RAZON_SOCIAL}
AFIP_NOMBRE_FANTASIA=${NOMBRE_FANTASIA}
AFIP_DOMICILIO=${DOMICILIO}
AFIP_DOMICILIO_FISCAL=${DOMICILIO_FISCAL}
AFIP_INICIO_ACTIVIDADES=${INICIO_ACT}
AFIP_INGRESOS_BRUTOS=${ING_BRUTOS}
AFIP_LOGO_PATH=${LOGO_PATH}

# ── Punto de venta ────────────────────────────────────────────────────────────
AFIP_PUNTO_VENTA=${PUNTO_VENTA}

# ── Límite Consumidor Final ───────────────────────────────────────────────────
AFIP_LIMITE_CF=${LIMITE_CF}

# ── Certificados WSAA (separados por entorno) ────────────────────────────────
AFIP_CERT_PATH_HOMO=${CERT_PATH_HOMO}
AFIP_KEY_PATH_HOMO=${KEY_PATH_HOMO}
AFIP_CERT_PATH_PROD=${CERT_PATH_PROD}
AFIP_KEY_PATH_PROD=${KEY_PATH_PROD}

# ── Caché (generado automáticamente) ─────────────────────────────────────────
# El código agrega _{env}.json al prefijo → caches separados para homo y prod
AFIP_TOKEN_CACHE_PATH=./.afip_token_cache
AFIP_WSDL_CACHE_PATH=./.afip_wsdl_cache.db
EOF

echo ""
ok ".env creado"

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Setup completo${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════${NC}"
echo ""
echo "  Active el entorno virtual en cada sesión:"
echo -e "    ${BOLD}source .venv/bin/activate${NC}"
echo ""
echo "  Comandos principales:"
echo -e "    ${BOLD}python3 facturar.py emitir --${ENV} --monto 1000 --concepto 'Prueba'${NC}"
echo -e "    ${BOLD}python3 facturar.py --help${NC}"
echo ""
if [ "$ENV" = "homo" ]; then
    warn "Está en modo HOMOLOGACIÓN. Use --prod para emitir facturas reales."
fi
echo ""
