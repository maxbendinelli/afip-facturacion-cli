from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, List, Dict, Any


CBTE_TIPO = {
    # Facturas
    "A": 1,
    "B": 6,
    "C": 11,
    # Notas de Débito
    "NDA": 2,
    "NDB": 7,
    "NDC": 12,
    "ND": 12,  # alias para C
    # Notas de Crédito
    "NCA": 3,
    "NCB": 8,
    "NCC": 13,
    "NC": 13,  # alias para C
    # Recibos
    "RA": 4,
    "RB": 9,
    "RC": 15,
}

CBTE_NOMBRE = {
    1: "Factura A",
    2: "Nota de Débito A",
    3: "Nota de Crédito A",
    4: "Recibo A",
    6: "Factura B",
    7: "Nota de Débito B",
    8: "Nota de Crédito B",
    9: "Recibo B",
    11: "Factura C",
    12: "Nota de Débito C",
    13: "Nota de Crédito C",
    15: "Recibo C",
}

CBTE_LETRA = {
    1: "A", 2: "A", 3: "A", 4: "A",
    6: "B", 7: "B", 8: "B", 9: "B",
    11: "C", 12: "C", 13: "C", 15: "C",
}

# Tabla de alícuotas AFIP (WSFEv1)
IVA_ALICUOTAS = {
    3: {"id": 3, "porcentaje": Decimal("0.0"), "desc": "0%"},
    4: {"id": 4, "porcentaje": Decimal("10.5"), "desc": "10.5%"},
    5: {"id": 5, "porcentaje": Decimal("21.0"), "desc": "21%"},
    6: {"id": 6, "porcentaje": Decimal("27.0"), "desc": "27%"},
    8: {"id": 8, "porcentaje": Decimal("5.0"), "desc": "5%"},
    9: {"id": 9, "porcentaje": Decimal("2.5"), "desc": "2.5%"},
}

DOC_TIPO_NOMBRE = {
    80: "CUIT",
    86: "CUIL",
    87: "CDI",
    89: "LE",
    90: "LC",
    91: "CI Extranjera",
    96: "DNI",
    94: "Pasaporte",
    0: "CI Policía Federal",
    95: "Certificado de Migración",
    92: "En trámite",
    93: "Acta Nacimiento",
    99: "Doc. (Otro) / Consumidor Final",
}

# Condiciones IVA según RG 5616 / WSFEv1 / AFIP Comprobantes en Línea
COND_IVA_NOMBRE = {
    1: "IVA Responsable Inscripto",
    4: "IVA Sujeto Exento",
    5: "Consumidor Final",
    6: "Responsable Monotributo",
    7: "Sujeto No Categorizado",
    8: "Proveedor del Exterior",
    9: "Cliente del Exterior",
    10: "IVA Liberado - Ley Nº 19.640",
    13: "Monotributista Social",
    15: "IVA No Alcanzado",
    16: "Monotributista Trabajador Independiente Promovido",
}

# Compatibilidad con comprobantes históricos o códigos legados de AFIP
COND_IVA_LEGACY = {
    2: "IVA Responsable No Inscripto",
    3: "IVA No Responsable",
    11: "IVA Responsable Inscripto - Agente de Percepción",
    12: "Pequeño Contribuyente Eventual",
    14: "Pequeño Contribuyente Eventual Social",
}

# Diccionario completo para descripciones en reportes y comprobantes
COND_IVA_TODAS = {**COND_IVA_LEGACY, **COND_IVA_NOMBRE}

# Alias de nombre corto / variaciones → ID de condición IVA
COND_IVA_ALIAS = {
    # 1: Responsable Inscripto
    "RI": 1,
    "RESPONSABLE_INSCRIPTO": 1,
    "IVA_RESPONSABLE_INSCRIPTO": 1,
    "INSCRIPTO": 1,
    "1": 1,

    # 4: IVA Sujeto Exento
    "EX": 4,
    "EXENTO": 4,
    "EXENTA": 4,
    "SUJETO_EXENTO": 4,
    "IVA_SUJETO_EXENTO": 4,
    "IVA_EXENTO": 4,
    "4": 4,

    # 5: Consumidor Final
    "CF": 5,
    "CONSUMIDOR_FINAL": 5,
    "FINAL": 5,
    "5": 5,

    # 6: Responsable Monotributo
    "MONO": 6,
    "MONOTRIBUTO": 6,
    "MONOTRIB": 6,
    "MONOTRIBUTISTA": 6,
    "RESPONSABLE_MONOTRIBUTO": 6,
    "6": 6,

    # 7: Sujeto No Categorizado
    "NC": 7,
    "NO_CATEGORIZADO": 7,
    "SUJETO_NO_CATEGORIZADO": 7,
    "7": 7,

    # 8: Proveedor del Exterior
    "PROVEEDOR_EXTERIOR": 8,
    "PROVEEDOR_DEL_EXTERIOR": 8,
    "IMPORTADOR": 8,
    "IMPORTADOR_DEL_EXTERIOR": 8,
    "8": 8,

    # 9: Cliente del Exterior
    "CLIENTE_EXTERIOR": 9,
    "CLIENTE_DEL_EXTERIOR": 9,
    "EXPORTACION": 9,
    "9": 9,

    # 10: IVA Liberado - Ley Nº 19.640
    "LIBERADO": 10,
    "IVA_LIBERADO": 10,
    "LEY_19640": 10,
    "LEY_N_19640": 10,
    "TIERRA_DEL_FUEGO": 10,
    "10": 10,

    # 13: Monotributista Social
    "MONOTRIBUTO_SOCIAL": 13,
    "MONOTRIBUTISTA_SOCIAL": 13,
    "MS": 13,
    "13": 13,

    # 15: IVA No Alcanzado
    "NO_ALCANZADO": 15,
    "IVA_NO_ALCANZADO": 15,
    "NA": 15,
    "15": 15,

    # 16: Monotributista Trabajador Independiente Promovido
    "TRABAJADOR_INDEPENDIENTE_PROMOVIDO": 16,
    "MONOTRIBUTO_PROMOVIDO": 16,
    "MONOTRIBUTISTA_PROMOVIDO": 16,
    "MONOTRIBUTISTA_TRABAJADOR_INDEPENDIENTE_PROMOVIDO": 16,
    "TIP": 16,
    "PROMOVIDO": 16,
    "16": 16,
}


@dataclass
class InvoiceItem:
    descripcion: str
    cantidad: Decimal
    precio_unitario: Decimal
    alicuota_iva: Decimal = Decimal("21.0")
    alicuota_iva_id: int = 5

    @property
    def subtotal(self) -> Decimal:
        """Monto neto (cantidad * precio_unitario)."""
        return (self.cantidad * self.precio_unitario).quantize(Decimal("0.01"))

    @property
    def iva_monto(self) -> Decimal:
        """Monto de IVA correspondiente a este ítem."""
        return (self.subtotal * (self.alicuota_iva / Decimal("100"))).quantize(Decimal("0.01"))

    @property
    def total_con_iva(self) -> Decimal:
        """Subtotal neto + IVA."""
        return self.subtotal + self.iva_monto


@dataclass
class InvoiceRequest:
    cbte_tipo: int
    cuit_cliente: str
    nombre_cliente: str
    monto: Decimal                      # Total final a cobrar (ImpTotal)
    concepto: str
    concepto_afip: int                  # 1=productos, 2=servicios, 3=ambos
    numero: int
    fecha: str                          # YYYYMMDD
    fecha_serv_desde: str               # YYYYMMDD (requerido para concepto 2/3)
    fecha_serv_hasta: str               # YYYYMMDD
    fecha_vto_pago: str                 # YYYYMMDD
    doc_tipo: int                       # 80=CUIT, 96=DNI, 99=sin identificar
    doc_nro: str
    condicion_iva_receptor: int = 5
    condicion_venta: str = "Contado"
    periodo_desde: Optional[str] = None
    periodo_hasta: Optional[str] = None
    items: list = field(default_factory=list)  # list[InvoiceItem]
    numero_original: Optional[int] = None
    cbte_tipo_original: Optional[int] = None
    imp_neto: Optional[Decimal] = None
    imp_iva: Optional[Decimal] = None
    imp_op_ex: Decimal = field(default_factory=lambda: Decimal("0.00"))
    imp_tot_conc: Decimal = field(default_factory=lambda: Decimal("0.00"))
    imp_trib: Decimal = field(default_factory=lambda: Decimal("0.00"))
    ivas: list = field(default_factory=list)  # list of dicts {"Id": int, "BaseImp": str, "Importe": str}


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
    imp_neto: Optional[Decimal] = None
    imp_iva: Optional[Decimal] = None
    imp_trib: Optional[Decimal] = None
    imp_op_ex: Optional[Decimal] = None
    ivas: list = field(default_factory=list)

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
            "letra": CBTE_LETRA.get(self.cbte_tipo, "C"),
            "fecha": self.fecha,
            "monto": f"{self.monto:.2f}",
            "cliente": self.nombre_cliente,
            "cuit_cliente": self.cuit_cliente,
        }
        d["doc_tipo"] = self.doc_tipo
        d["condicion_venta"] = self.condicion_venta
        d["condicion_iva_receptor"] = self.condicion_iva_receptor
        if self.imp_neto is not None:
            d["imp_neto"] = f"{self.imp_neto:.2f}"
        if self.imp_iva is not None:
            d["imp_iva"] = f"{self.imp_iva:.2f}"
        if self.imp_trib is not None:
            d["imp_trib"] = f"{self.imp_trib:.2f}"
        if self.imp_op_ex is not None:
            d["imp_op_ex"] = f"{self.imp_op_ex:.2f}"
        if self.ivas:
            d["ivas"] = self.ivas
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
            es_factura_a = self.cbte_tipo in (1, 2, 3, 4)
            d["items"] = [
                {
                    "descripcion": i.descripcion,
                    "cantidad": str(i.cantidad),
                    "precio_unitario": f"{i.precio_unitario:.2f}",
                    "alicuota_iva": str(getattr(i, "alicuota_iva", Decimal("21.0"))),
                    "alicuota_iva_id": getattr(i, "alicuota_iva_id", 5),
                    "subtotal": f"{i.subtotal:.2f}",
                    "iva_monto": f"{getattr(i, 'iva_monto', Decimal('0.00')):.2f}" if es_factura_a else f"{(i.subtotal - (i.subtotal / (Decimal('1.00') + (getattr(i, 'alicuota_iva', Decimal('21.0')) / Decimal('100'))))).quantize(Decimal('0.01')):.2f}",
                    "total": f"{getattr(i, 'total_con_iva', i.subtotal):.2f}" if es_factura_a else f"{i.subtotal:.2f}",
                }
                for i in self.items
            ]
        if self.observaciones:
            d["observaciones"] = self.observaciones
        return d
