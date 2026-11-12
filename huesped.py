"""
Módulo del modelo Huésped para el sistema NexoPMS.
"""


class Huesped:
    """Representa a un huésped del hotel con sus datos de contacto."""

    def __init__(self, rut, nombre, telefono):
        self.rut = rut
        self.nombre = nombre
        self.telefono = telefono

    def to_dict(self):
        """Convierte los atributos del huésped a un diccionario para serialización JSON."""
        return {
            "rut": self.rut,
            "nombre": self.nombre,
            "telefono": self.telefono,
        }
