"""
Punto de entrada principal para el sistema NexoPMS.
"""

from huesped import Huesped
from reserva import Reserva
from conexion import ConexionDB
from nexopms import NexoPMS

__all__ = ["Huesped", "Reserva", "ConexionDB", "NexoPMS", "main"]


def main():
    """Inicializa y ejecuta la interfaz del sistema NexoPMS."""
    try:
        sistema = NexoPMS()
        sistema.iniciar()
    except KeyboardInterrupt:
        print("\nCerrando NexoPMS... ¡Hasta pronto!")


if __name__ == "__main__":
    main()
