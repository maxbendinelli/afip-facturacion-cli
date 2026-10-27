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

# Tabla de alícuotas y conceptos de IVA AFIP (WSFEv1 / Comprobantes en Línea)
IVA_ALICUOTAS = {
    1: {"id": 1, "tipo": "no_gravado", "porcentaje": Decimal("0.0"), "desc": "No gravado"},
    2: {"id": 2, "tipo": "exento", "porcentaje": Decimal("0.0"), "desc": "Exento"},
    3: {"id": 3, "tipo": "iva", "porcentaje": Decimal("0.0"), "desc": "0%"},
    4: {"id": 4, "tipo": "iva", "porcentaje": Decimal("10.5"), "desc": "10.5%"},
    5: {"id": 5, "tipo": "iva", "porcentaje": Decimal("21.0"), "desc": "21%"},
    6: {"id": 6, "tipo": "iva", "porcentaje": Decimal("27.0"), "desc": "27%"},
    8: {"id": 8, "tipo": "iva", "porcentaje": Decimal("5.0"), "desc": "5%"},
    9: {"id": 9, "tipo": "iva", "porcentaje": Decimal("2.5"), "desc": "2.5%"},
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

# Condiciones IVA según RG 5616 / WSFEv1 / AFIP Comprobantes en Línea (Catálogo Oficial ARCA)
COND_IVA_NOMBRE = {
    1: "IVA Responsable Inscripto",
    2: "IVA Responsable No Inscripto",
    3: "IVA No Responsable",
    4: "IVA Sujeto Exento",
    5: "Consumidor Final",
    6: "Responsable Monotributo",
    7: "Sujeto No Categorizado",
    8: "Proveedor del Exterior",
    9: "Cliente del Exterior",
    10: "IVA Liberado - Ley Nº 19.640",
    11: "IVA Responsable Inscripto - Agente de Percepción",
    12: "Pequeño Contribuyente Eventual",
    13: "Monotributista Social",
    14: "Pequeño Contribuyente Eventual Social",
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

# Condiciones que aplican específicamente al Emisor en ARCA / AFIP
COND_IVA_EMISOR = {
    1: "IVA Responsable Inscripto",
    6: "Responsable Monotributo",
    4: "IVA Sujeto Exento",
    13: "Monotributista Social",
    16: "Monotributista Trabajador Independiente Promovido",
    10: "IVA Liberado - Ley Nº 19.640",
    11: "IVA Responsable Inscripto - Agente de Percepción",
    15: "IVA No Alcanzado",
    3: "IVA No Responsable",
    12: "Pequeño Contribuyente Eventual",
    14: "Pequeño Contribuyente Eventual Social",
    2: "IVA Responsable No Inscripto",
}

# Condiciones que aplican al Receptor en ARCA / AFIP
COND_IVA_RECEPTOR = COND_IVA_TODAS

# Alias de nombre corto / variaciones → ID de condición IVA
COND_IVA_ALIAS = {
    # 1: Responsable Inscripto
    "RI": 1,
    "RESPONSABLE_INSCRIPTO": 1,
    "IVA_RESPONSABLE_INSCRIPTO": 1,
    "INSCRIPTO": 1,
    "1": 1,

    # 2: IVA Responsable No Inscripto (Legacy)
    "RNI": 2,
    "NO_INSCRIPTO": 2,
    "RESPONSABLE_NO_INSCRIPTO": 2,
    "IVA_RESPONSABLE_NO_INSCRIPTO": 2,
    "2": 2,

    # 3: IVA No Responsable
    "NR": 3,
    "NO_RESPONSABLE": 3,
    "IVA_NO_RESPONSABLE": 3,
    "3": 3,

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

    # 11: IVA Responsable Inscripto - Agente de Percepción
    "AGENTE_PERCEPCION": 11,
    "AGENTE_DE_PERCEPCION": 11,
    "RI_AGENTE_PERCEPCION": 11,
    "IVA_RESPONSABLE_INSCRIPTO_AGENTE_DE_PERCEPCION": 11,
    "11": 11,

    # 12: Pequeño Contribuyente Eventual
    "EVENTUAL": 12,
    "PEQUENO_CONTRIBUYENTE_EVENTUAL": 12,
    "12": 12,

    # 13: Monotributista Social
    "MONOTRIBUTO_SOCIAL": 13,
    "MONOTRIBUTISTA_SOCIAL": 13,
    "MS": 13,
    "13": 13,

    # 14: Pequeño Contribuyente Eventual Social
    "EVENTUAL_SOCIAL": 14,
    "PEQUENO_CONTRIBUYENTE_EVENTUAL_SOCIAL": 14,
    "14": 14,

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
    tipo_iva: str = "iva"  # "iva", "exento", "no_gravado"

    def __post_init__(self):
        if self.tipo_iva == "iva":
            if self.alicuota_iva_id == 1:
                self.tipo_iva = "no_gravado"
            elif self.alicuota_iva_id == 2:
                self.tipo_iva = "exento"

    @property
    def subtotal(self) -> Decimal:
        """Monto neto (cantidad * precio_unitario)."""
        return (self.cantidad * self.precio_unitario).quantize(Decimal("0.01"))

    @property
    def iva_monto(self) -> Decimal:
        """Monto de IVA correspondiente a este ítem."""
        if self.tipo_iva in ("no_gravado", "exento") or self.alicuota_iva_id in (1, 2, 3) or self.alicuota_iva == Decimal("0.0"):
            return Decimal("0.00")
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
    domicilio_cliente: Optional[str] = None
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
    imp_tot_conc: Optional[Decimal] = None
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
        if self.imp_tot_conc is not None:
            d["imp_tot_conc"] = f"{self.imp_tot_conc:.2f}"
        if self.items:
            es_factura_a = self.cbte_tipo in (1, 2, 3, 4)
            items_list_json = []
            for i in self.items:
                tipo_it = getattr(i, "tipo_iva", "iva")
                alic_id = getattr(i, "alicuota_iva_id", 5)
                alic_val = getattr(i, "alicuota_iva", Decimal("21.0"))
                if tipo_it in ("no_gravado", "exento") or alic_id in (1, 2, 3) or alic_val == Decimal("0.0"):
                    iva_monto = Decimal("0.00")
                    total_it = i.subtotal
                elif es_factura_a:
                    iva_monto = i.iva_monto
                    total_it = i.total_con_iva
                else:
                    factor = Decimal("1.00") + (alic_val / Decimal("100"))
                    base_it = (i.subtotal / factor).quantize(Decimal("0.01"))
                    iva_monto = i.subtotal - base_it
                    total_it = i.subtotal

                items_list_json.append({
                    "descripcion": i.descripcion,
                    "cantidad": str(i.cantidad),
                    "precio_unitario": f"{i.precio_unitario:.2f}",
                    "alicuota_iva": str(alic_val),
                    "alicuota_iva_id": alic_id,
                    "tipo_iva": tipo_it,
                    "subtotal": f"{i.subtotal:.2f}",
                    "iva_monto": f"{iva_monto:.2f}",
                    "total": f"{total_it:.2f}",
                })
            d["items"] = items_list_json
        if self.observaciones:
            d["observaciones"] = self.observaciones
        return d
