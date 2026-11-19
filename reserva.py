"""
Módulo del modelo Reserva para el sistema NexoPMS.
"""

from huesped import Huesped


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
        tarifa_base_snapshot=None
    ):
        self.huesped = huesped
        self.habitacion_idx = habitacion_idx
        self.dia_inicio = dia_inicio
        self.dias_estadia = dias_estadia
        self.total = total
        self.incluye_desayuno = bool(incluye_desayuno)
        self.incluye_estacionamiento = bool(incluye_estacionamiento)
        self.estado = estado
        self.habitacion_nombre = habitacion_nombre
        self.tipo_alojamiento = tipo_alojamiento
        self.tarifa_base_snapshot = tarifa_base_snapshot

    def to_dict(self):
        """Convierte los atributos de la reserva a un diccionario para serialización JSON."""
        return {
            "huesped": self.huesped.to_dict(),
            "habitacion_idx": self.habitacion_idx,
            "dia_inicio": self.dia_inicio,
            "dias_estadia": self.dias_estadia,
            "total": self.total,
            "incluye_desayuno": self.incluye_desayuno,
            "incluye_estacionamiento": self.incluye_estacionamiento,
            "estado": self.estado,
            "habitacion_nombre": self.habitacion_nombre,
            "tipo_alojamiento": self.tipo_alojamiento,
            "tarifa_base_snapshot": self.tarifa_base_snapshot
        }
