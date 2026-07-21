---
name: afip-facturacion
description: Guía e instrucciones para instalar, configurar y utilizar el CLI y el servidor MCP de facturación electrónica de AFIP/ARCA (emitir Factura C, Nota de Crédito/Débito, Padrón A13, CSR y generación de PDFs).
---

# Skill: AFIP / ARCA Facturación Electrónica (CLI + Servidor MCP)

Este skill proporciona las instrucciones completas para instalar, configurar y operar la herramienta de facturación electrónica argentina (`afip-facturacion-cli`) para comprobantes de Monotributo / Responsable Inscripto a través de WSFEv1, tanto mediante su CLI (`facturar.py`) como a través de su servidor MCP (`mcp_server.py`).

---

## 1. Requisitos Previos e Instalación

### Requisitos del Sistema
- Python 3.11+
- Clave fiscal nivel 3+ en AFIP/ARCA para obtener el certificado de producción o pruebas.

### Paso a paso de instalación
```bash
# 1. Crear y activar el entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# 2. Instalar dependencias necesarias (incluye mcp)
pip install -r requirements.txt

# 3. Copiar archivo de entorno base
cp .env.example .env
```

---

## 2. Configuración Inicial e Integración con AFIP

### Paso 1: Generar clave privada y solicitud de certificado (CSR)
Ejecutar el script helper indicando el CUIT emisor y la razón social:
```bash
python3 generar_csr.py --cuit 20123456789 --razon-social "Tu Nombre o Empresa"
```
*Esto creará en el directorio `certs/` los archivos `afip_20123456789.key` y `afip_20123456789.csr`.*

### Paso 2: Descargar el certificado desde la web de AFIP
1. Ingresar a [auth.afip.gob.ar](https://auth.afip.gob.ar/) con Clave Fiscal.
2. Ir a **Administración de Relaciones de Clave Fiscal** / **Servicios Web WSASS**.
3. Autorizar el servicio **Facturación Electrónica (`wsfe`)**.
4. En **Crear alias / Certificado**, subir el archivo `.csr` generado.
5. Descargar el certificado resultante `.crt` y guardarlo en la carpeta `certs/`.

### Paso 3: Configurar variables de entorno (`.env`)
Editar el archivo `.env` configurando los datos reales del emisor:
```env
AFIP_CUIT=20123456789
AFIP_CERT_PATH=./certs/afip_20123456789.crt
AFIP_KEY_PATH=./certs/afip_20123456789.key
AFIP_PUNTO_VENTA=1
AFIP_RAZON_SOCIAL=Tu Nombre o Razón Social
AFIP_DOMICILIO=Av. Ejemplo 1234, CABA
```

---

## 3. Uso del Servidor MCP (`mcp_server.py`)

El proyecto incluye un **servidor MCP** listo para que asistentes o agentes de IA ejecuten funciones de facturación directamente como herramientas (Tools).

### Iniciar el servidor
```bash
python3 mcp_server.py
```

### Configuración en clientes MCP (`mcp.json` / Claude Desktop)
```json
{
  "mcpServers": {
    "afip-facturacion": {
      "command": "python3",
      "args": ["/ruta/absoluta/a/afip/mcp_server.py"]
    }
  }
}
```

### Tools expuestas por el servidor MCP:
- `emitir_factura(monto, concepto, cuit_cliente, condicion_iva, items, env, generar_pdf, dry_run)`: Emite Facturas C.
- `emitir_nota_credito(numero_original, monto, env, dry_run)`: Emite Nota de Crédito C.
- `emitir_nota_debito(numero_original, monto, env, dry_run)`: Emite Nota de Débito C.
- `consultar_ultimo_comprobante(tipo, env)`: Obtiene el último número de comprobante.
- `consultar_comprobante(numero, tipo, env, generar_pdf)`: Consulta un comprobante emitido.
- `consultar_padron_a13(cuit, env)`: Consulta datos fiscales en Padrón A13.
- `validar_cuit(cuit, consultar_afip, env)`: Valida formato e inscripción en AFIP.

---

## 4. Uso del CLI tradicional (`facturar.py`)

> **Nota:** Todos los comandos imprimen salida en **JSON** por `stdout`.
> Usar `--env prod` para emitir en producción real, o `--env homo` para pruebas en homologación.

### A. Emitir Factura C

#### 1. Consumidor Final (Monto simple)
```bash
python3 facturar.py emitir \
  --concepto "Servicio de consultoría" \
  --monto 15000 \
  --env prod --pdf
```

#### 2. Receptor con CUIT (Resolución automática vía Padrón A13)
```bash
python3 facturar.py emitir \
  --cuit-cliente 30-71234567-8 \
  --concepto "Desarrollo de Software" \
  --monto 120000 \
  --env prod --pdf --duplicado
```

#### 3. Múltiples Ítems
```bash
python3 facturar.py emitir \
  --cuit-cliente 20-98765432-1 \
  --item "Desarrollo Web|1|100000" \
  --item "Mantenimiento Mensual|2|15000" \
  --env prod --pdf
```

### B. Notas de Crédito y Débito
```bash
python3 facturar.py nota-credito --numero-original 42 --monto 15000 --env prod --pdf
python3 facturar.py nota-debito --numero-original 42 --monto 2500 --env prod --pdf
```

### C. Consultas y Padrón
```bash
python3 facturar.py ultimo-numero --tipo C --env prod
python3 facturar.py consultar --numero 42 --tipo C --env prod --pdf
python3 facturar.py buscar --desde-fecha 20260701 --hasta-fecha 20260731 --env prod
python3 facturar.py validar-cuit 30-71234567-8 --afip --env prod
```

---

## 5. Buenas Prácticas y Seguridad

1. **Entorno de Pruebas**: Probar siempre los comandos agregando `--dry-run` o usando el ambiente `--env homo` por defecto.
2. **Archivos Protegidos**: Jamás subir a repositorios los archivos `.env` ni claves en la carpeta `certs/`.
