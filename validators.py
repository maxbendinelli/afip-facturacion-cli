"""
Validación de CUIT/CUIL: formato, dígito verificador y existencia en AFIP.
"""
from decimal import Decimal


def validar_formato_cuit(cuit: str) -> tuple[bool, str]:
    """Valida formato y dígito verificador. Retorna (ok, mensaje_error)."""
    digits = cuit.strip().replace("-", "").replace(" ", "")
    if not digits.isdigit():
        return False, f"El CUIT '{cuit}' contiene caracteres no numéricos."
    if len(digits) != 11:
        return False, f"El CUIT '{cuit}' debe tener 11 dígitos (tiene {len(digits)})."

    # Prefijos válidos para personas físicas (20,23,24,27) y jurídicas (30,33,34)
    prefijo = int(digits[:2])
    if prefijo not in (20, 23, 24, 27, 30, 33, 34):
        return False, f"Prefijo '{digits[:2]}' inválido para CUIT/CUIL."

    # Verificar dígito verificador
    weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(digits[:10], weights))
    resto = total % 11
    if resto == 0:
        check = 0
    elif resto == 1:
        return False, f"CUIT '{cuit}' inválido: dígito verificador imposible (resto 1)."
    else:
        check = 11 - resto

    if int(digits[10]) != check:
        return False, (
            f"CUIT '{cuit}' inválido: dígito verificador incorrecto "
            f"(esperado {check}, encontrado {digits[10]})."
        )
    return True, ""


def validar_cuit_afip(config, cuit: str) -> tuple[bool, str, dict | None]:
    """
    Valida el CUIT contra el padrón A13 de AFIP.
    Retorna (ok, mensaje_error, datos_persona).
    datos_persona incluye nombre, actividad, domicilio si el CUIT existe.
    """
    ok, err = validar_formato_cuit(cuit)
    if not ok:
        return False, err, None

    try:
        from padron import buscar_persona
        datos = buscar_persona(config, cuit)
        if datos is None:
            return False, f"CUIT {cuit} no encontrado en el padrón AFIP.", None
        if datos.get("estado") == "INACTIVO":
            return False, f"CUIT {cuit} figura como INACTIVO en AFIP.", None
        return True, "", datos
    except Exception as e:
        # Si el padrón falla, al menos el formato es válido
        return True, f"Advertencia: no se pudo confirmar en AFIP ({e})", None
