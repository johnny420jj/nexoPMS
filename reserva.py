"""
Módulo del modelo Reserva para el sistema NexoPMS.
"""

from huesped import Huesped

MAX_INT_UNSIGNED = 4294967295


def _parsear_id_opcional(valor):
    """Convierte un identificador entero positivo válido o retorna None si es inválido."""
    if valor is None or isinstance(valor, (bool, float)):
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    if numero < 1 or numero > MAX_INT_UNSIGNED:
        return None
    return numero


def _normalizar_servicios(servicios, dias_estadia):
    """Normaliza y copia defensivamente una lista de servicios contratados."""
    if not servicios:
        return []
    dias = int(dias_estadia)
    normalizados = []
    for item in servicios:
        if not isinstance(item, dict):
            continue
        id_servicio = _parsear_id_opcional(item.get("id_servicio"))
        raw_nombre = item.get("nombre")
        if raw_nombre is None:
            raw_nombre = item.get("nombre_snapshot", "")
        nombre = str(raw_nombre).strip()

        raw_costo = item.get("costo_unitario")
        if raw_costo is None:
            raw_costo = item.get("costo_unitario_snapshot")
        if raw_costo is None:
            raw_costo = item.get("costo", 0)
        costo_unitario = int(raw_costo)

        raw_subtotal = item.get("subtotal")
        subtotal = int(raw_subtotal) if raw_subtotal is not None else costo_unitario * dias

        normalizados.append({
            "id_servicio": id_servicio,
            "nombre": nombre,
            "costo_unitario": costo_unitario,
            "subtotal": subtotal,
        })
    return normalizados


class Reserva:
    """Representa una reserva de habitación realizada por un huésped."""

    def __init__(
        self,
        huesped,
        habitacion_idx,
        dia_inicio,
        dias_estadia,
        total,
        incluye_desayuno=False,
        incluye_estacionamiento=False,
        estado="Confirmada",
        habitacion_nombre=None,
        tipo_alojamiento=None,
        tarifa_base_snapshot=None,
        id_reserva=None,
        servicios=None
    ):
        self.huesped = huesped
        self.habitacion_idx = habitacion_idx
        self.dia_inicio = dia_inicio
        self.dias_estadia = dias_estadia
        self.total = total
        self.id_reserva = _parsear_id_opcional(id_reserva)
        self.servicios = _normalizar_servicios(servicios, dias_estadia)
        if servicios is None:
            self.incluye_desayuno = bool(incluye_desayuno)
            self.incluye_estacionamiento = bool(incluye_estacionamiento)
        else:
            nombres_lower = [s["nombre"].strip().lower() for s in self.servicios]
            self.incluye_desayuno = any("desayuno" in n for n in nombres_lower)
            self.incluye_estacionamiento = any("estacionamiento" in n for n in nombres_lower)
        self.estado = estado
        self.habitacion_nombre = habitacion_nombre
        self.tipo_alojamiento = tipo_alojamiento
        self.tarifa_base_snapshot = tarifa_base_snapshot

    def to_dict(self):
        """Convierte los atributos de la reserva a un diccionario para serialización JSON."""
        return {
            "id_reserva": self.id_reserva,
            "huesped": self.huesped.to_dict(),
            "habitacion_idx": self.habitacion_idx,
            "dia_inicio": self.dia_inicio,
            "dias_estadia": self.dias_estadia,
            "total": self.total,
            "incluye_desayuno": self.incluye_desayuno,
            "incluye_estacionamiento": self.incluye_estacionamiento,
            "servicios": [dict(s) for s in self.servicios],
            "estado": self.estado,
            "habitacion_nombre": self.habitacion_nombre,
            "tipo_alojamiento": self.tipo_alojamiento,
            "tarifa_base_snapshot": self.tarifa_base_snapshot
        }
