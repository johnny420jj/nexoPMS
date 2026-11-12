"""
Punto de entrada principal para el sistema NexoPMS.
"""

from huesped import Huesped
from reserva import Reserva
from nexopms import NexoPMS

__all__ = ["Huesped", "Reserva", "NexoPMS", "main"]


def main():
    """Inicializa y ejecuta la interfaz del sistema NexoPMS."""
    sistema = NexoPMS()
    sistema.iniciar()


if __name__ == "__main__":
    main()
