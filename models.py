from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


CBTE_TIPO = {
    "C": 11,
    "ND": 12,
    "NC": 13,
}

CBTE_NOMBRE = {
    11: "Factura C",
    12: "Nota de Débito C",
    13: "Nota de Crédito C",
}

DOC_TIPO_NOMBRE = {
    80: "CUIT",
    96: "DNI",
    99: "",
}

# Condiciones IVA según RG 5616 / AFIP
COND_IVA_NOMBRE = {
    1: "IVA Responsable Inscripto",
    2: "IVA Responsable No Inscripto",
    3: "IVA No Responsable",
    4: "IVA Sujeto Exento",
    5: "Consumidor Final",
    6: "Responsable Monotributo",
    7: "Sujeto No Categorizado",
    8: "Importador del Exterior",
    9: "Cliente del Exterior",
    10: "IVA Liberado - Ley N° 19.640",
    11: "IVA Responsable Inscripto - Agente de Percepción",
    12: "Pequeño Contribuyente Eventual",
    13: "Monotributista Social",
    14: "Pequeño Contribuyente Eventual Social",
}

# Alias de nombre corto → ID de condición IVA
COND_IVA_ALIAS = {
    # Responsable Inscripto
    "RI": 1,
    "RESPONSABLE_INSCRIPTO": 1,
    "INSCRIPTO": 1,
    # Responsable No Inscripto (categoría histórica)
    "RNI": 2,
    "NO_INSCRIPTO": 2,
    # No Responsable
    "NR": 3,
    "NO_RESPONSABLE": 3,
    # Exento
    "EX": 4,
    "EXENTO": 4,
    "EXENTA": 4,
    # Consumidor Final
    "CF": 5,
    "CONSUMIDOR_FINAL": 5,
    "FINAL": 5,
    # Monotributista
    "MONO": 6,
    "MONOTRIB": 6,
    "MONOTRIBUTISTA": 6,
    # No categorizado
    "NC": 7,
    "NO_CATEGORIZADO": 7,
}


@dataclass
class InvoiceItem:
    descripcion: str
    cantidad: Decimal
    precio_unitario: Decimal

    @property
    def subtotal(self) -> Decimal:
        return (self.cantidad * self.precio_unitario).quantize(Decimal("0.01"))


@dataclass
class InvoiceRequest:
    cbte_tipo: int
    cuit_cliente: str
    nombre_cliente: str
    monto: Decimal
    concepto: str
    concepto_afip: int          # 1=productos, 2=servicios, 3=ambos
    numero: int
    fecha: str                  # YYYYMMDD
    fecha_serv_desde: str       # YYYYMMDD (requerido para concepto 2/3)
    fecha_serv_hasta: str       # YYYYMMDD
    fecha_vto_pago: str         # YYYYMMDD
    doc_tipo: int               # 80=CUIT, 96=DNI, 99=sin identificar
    doc_nro: str
    condicion_iva_receptor: int = 5
    condicion_venta: str = "Contado"
    periodo_desde: Optional[str] = None
    periodo_hasta: Optional[str] = None
    items: list = field(default_factory=list)  # list[InvoiceItem]
    numero_original: Optional[int] = None
    cbte_tipo_original: Optional[int] = None


@dataclass
class InvoiceResponse:
    cae: str
    cae_vencimiento: str
    numero: int
    cbte_tipo: int
    punto_venta: int
    fecha: str
    monto: Decimal
    nombre_cliente: str
    cuit_cliente: str
    resultado: str
    doc_tipo: int = 99
    condicion_venta: str = "Contado"
    condicion_iva_receptor: int = 5
    concepto: str = ""
    periodo_desde: Optional[str] = None
    periodo_hasta: Optional[str] = None
    domicilio_cliente: Optional[str] = None
    hora: Optional[str] = None          # HHMMSS
    fecha_vto_pago: Optional[str] = None  # YYYYMMDD
    items: list = field(default_factory=list)  # list[InvoiceItem]
    observaciones: list = field(default_factory=list)

    def to_json(self) -> dict:
        d = {
            "status": "ok",
            "comprobante": f"{self.punto_venta:04d}-{self.numero:08d}",
            "numero": self.numero,
            "punto_venta": self.punto_venta,
            "cae": self.cae,
            "cae_vencimiento": self.cae_vencimiento,
            "tipo": CBTE_NOMBRE.get(self.cbte_tipo, str(self.cbte_tipo)),
            "cbte_tipo": self.cbte_tipo,
            "fecha": self.fecha,
            "monto": f"{self.monto:.2f}",
            "cliente": self.nombre_cliente,
            "cuit_cliente": self.cuit_cliente,
        }
        d["doc_tipo"] = self.doc_tipo
        d["condicion_venta"] = self.condicion_venta
        d["condicion_iva_receptor"] = self.condicion_iva_receptor
        if self.concepto:
            d["concepto"] = self.concepto
        if self.hora:
            d["hora"] = self.hora
        if self.domicilio_cliente:
            d["domicilio_cliente"] = self.domicilio_cliente
        if self.periodo_desde:
            d["periodo_desde"] = self.periodo_desde
        if self.periodo_hasta:
            d["periodo_hasta"] = self.periodo_hasta
        if self.fecha_vto_pago:
            d["fecha_vto_pago"] = self.fecha_vto_pago
        if self.items:
            d["items"] = [
                {
                    "descripcion": i.descripcion,
                    "cantidad": str(i.cantidad),
                    "precio_unitario": f"{i.precio_unitario:.2f}",
                    "subtotal": f"{i.subtotal:.2f}",
                }
                for i in self.items
            ]
        return d
