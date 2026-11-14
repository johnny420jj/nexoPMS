"""
Módulo principal del sistema de gestión hotelera NexoPMS.
Contiene la clase NexoPMS que administra disponibilidad, reservas y persistencia en MySQL.
"""

from huesped import Huesped
from reserva import Reserva
from conexion import ConexionDB


class NexoPMS:
    """Sistema de gestión hotelera (Property Management System) conectado a MySQL."""

    COSTO_DESAYUNO_NOCHE = 5000
    COSTO_ESTACIONAMIENTO_NOCHE = 8000

    def __init__(self, db=None):
        self.db = db if db is not None else ConexionDB()

        # Vectores paralelos (valores por defecto si la tabla aún no ha sido leída)
        self.ids_habitaciones = [1, 2, 3, 4]
        self.habitaciones = ["101", "102", "103", "104"]
        self.tarifas = [45000, 45000, 60000, 70000]

        # Matriz de disponibilidad: 4 habitaciones x 30 días (0: Libre, 1: Ocupada)
        self.dias_mes = 30
        self.matriz_disponibilidad = [
            [0 for _ in range(self.dias_mes)] for _ in range(len(self.habitaciones))
        ]

        self.reservas = []
        self.cargar_datos()

    def cargar_datos(self):
        """
        Carga los vectores paralelos (habitaciones y tarifas), la matriz de disponibilidad
        y las reservas activas directamente desde la base de datos MySQL (nexopms_db).
        """
        try:
            # 1. Poblar vectores paralelos desde la tabla 'habitaciones'
            filas_hab = self.db.obtener_habitaciones_y_tarifas()
            if filas_hab:
                self.ids_habitaciones = [f["id_habitacion"] for f in filas_hab]
                self.habitaciones = [str(f["numero_habitacion"]) for f in filas_hab]
                self.tarifas = [int(f["tarifa_base_noche"]) for f in filas_hab]

            # Reiniciar matriz en memoria (filas = habitaciones, columnas = 30 días)
            self.matriz_disponibilidad = [
                [0 for _ in range(self.dias_mes)] for _ in range(len(self.habitaciones))
            ]

            # 2. Poblar la matriz 4x30 desde la tabla 'ocupacion_diaria'
            filas_ocupacion = self.db.obtener_ocupacion_diaria()
            for reg in filas_ocupacion:
                if reg["id_habitacion"] in self.ids_habitaciones:
                    hab_idx = self.ids_habitaciones.index(reg["id_habitacion"])
                    dia_idx = int(reg["dia_mes"]) - 1
                    if 0 <= dia_idx < self.dias_mes:
                        self.matriz_disponibilidad[hab_idx][dia_idx] = 1 if reg["ocupada"] else 0

            # 3. Reconstruir objetos Huesped y Reserva desde las tablas 'reservas' y 'huespedes'
            self.reservas = []
            filas_reservas = self.db.obtener_reservas_activas()
            for r in filas_reservas:
                if r["id_habitacion"] in self.ids_habitaciones:
                    hab_idx = self.ids_habitaciones.index(r["id_habitacion"])
                else:
                    hab_idx = 0

                huesped = Huesped(r["rut"], r["nombre"], r["telefono"])
                reserva = Reserva(
                    huesped=huesped,
                    habitacion_idx=hab_idx,
                    dia_inicio=int(r["dia_inicio"]) - 1,
                    dias_estadia=int(r["dias_estadia"]),
                    total=int(r["monto_total"]),
                    incluye_desayuno=bool(r["incluye_desayuno"]),
                    incluye_estacionamiento=bool(r["incluye_estacionamiento"]),
                    estado=r["estado"]
                )
                self.reservas.append(reserva)

        except Exception as e:
            print(f"Aviso al sincronizar con MySQL: {e}")

    def mostrar_matriz_disponibilidad(self):
        """Muestra en consola la matriz de ocupación del mes en bloques de 15 días."""
        print(f"\n--- MATRIZ DE DISPONIBILIDAD ({self.dias_mes} Días) ---")
        dias_por_bloque = 15

        for inicio_bloque in range(0, self.dias_mes, dias_por_bloque):
            fin_bloque = min(inicio_bloque + dias_por_bloque, self.dias_mes)
            rango_dias = range(inicio_bloque, fin_bloque)

            print(f"\n[Días {inicio_bloque + 1:02d} al {fin_bloque:02d}]")
            encabezado = "Habit. | " + " | ".join([f"D{d + 1:02d}" for d in rango_dias])
            separador = "-" * len(encabezado)
            print(encabezado)
            print(separador)

            for i, hab in enumerate(self.habitaciones):
                estado_dias = " | ".join(
                    ["[X]" if self.matriz_disponibilidad[i][d] == 1 else "[ ]" for d in rango_dias]
                )
                print(f"{hab:^6} | {estado_dias}")
            print(separador)

        print("[ ] = Libre  |  [X] = Ocupada\n")

    def consultar_tarifas(self):
        """Muestra las tarifas base de habitaciones y servicios adicionales."""
        print("\n--- TARIFARIO BASE Y SERVICIOS ADICIONALES ---")
        for i, hab in enumerate(self.habitaciones):
            print(f"Habitación {hab}: ${self.tarifas[i]:,} / noche")
        print("-" * 46)
        print(f"Servicio Desayuno       : ${self.COSTO_DESAYUNO_NOCHE:,} / noche")
        print(f"Servicio Estacionamiento: ${self.COSTO_ESTACIONAMIENTO_NOCHE:,} / noche")
        print("----------------------------------------------\n")

    def confirmar_y_guardar_reserva(self, nueva_reserva, hab_idx, dia_inicio, dias_estadia):
        """
        Subproceso TO-BE: Doble validación de disponibilidad en la matriz en memoria
        y en la tabla 'ocupacion_diaria' de MySQL justo antes de persistir la transacción.
        """
        # 1. Validación en matriz en memoria
        for d in range(dia_inicio, dia_inicio + dias_estadia):
            if self.matriz_disponibilidad[hab_idx][d] != 0:
                print("Error de validación: La habitación ya no se encuentra disponible en las fechas indicadas.")
                return False

        id_habitacion = self.ids_habitaciones[hab_idx]
        dia_inicio_bd = dia_inicio + 1

        # 2. Doble validación contra la base de datos MySQL
        if not self.db.verificar_disponibilidad_db(id_habitacion, dia_inicio_bd, dias_estadia):
            print("Error de validación en BD: Las fechas acaban de ser ocupadas en el servidor MySQL.")
            self.cargar_datos()
            return False

        # 3. Guardar transaccionalmente en MySQL (huespedes, reservas y ocupacion_diaria)
        nueva_reserva.estado = "Confirmada"
        if not self.db.guardar_reserva_transaccional(nueva_reserva, id_habitacion):
            return False

        # 4. Actualizar matriz en memoria y lista local de reservas
        for d in range(dia_inicio, dia_inicio + dias_estadia):
            self.matriz_disponibilidad[hab_idx][d] = 1

        self.reservas.append(nueva_reserva)
        print("¡Reserva confirmada y guardada exitosamente en MySQL!")
        return True

    def registrar_reserva(self):
        """Flujo de consola para cotizar y registrar una nueva reserva."""
        print("\n--- NUEVA RESERVA ---")
        self.cargar_datos()
        self.mostrar_matriz_disponibilidad()

        try:
            hab_num = input("Ingrese el número de habitación (ej. 101): ").strip()
            if hab_num not in self.habitaciones:
                print("Error: Habitación no existe.")
                return

            hab_idx = self.habitaciones.index(hab_num)
            dia_inicio = int(input(f"Día de ingreso (1-{self.dias_mes}): ")) - 1
            dias_estadia = int(input("Cantidad de noches: "))

            if dias_estadia <= 0:
                print("Error: La cantidad de noches debe ser mayor a 0.")
                return

            # Validar límites y disponibilidad inicial en la matriz
            if dia_inicio < 0 or dia_inicio + dias_estadia > self.dias_mes:
                print("Error: Las fechas exceden el calendario actual.")
                return

            for d in range(dia_inicio, dia_inicio + dias_estadia):
                if self.matriz_disponibilidad[hab_idx][d] == 1:
                    print("Error: La habitación está ocupada en las fechas seleccionadas.")
                    return

            # Si hay disponibilidad, pedir datos del huésped
            rut = input("RUT del huésped: ").strip()
            nombre = input("Nombre del huésped: ").strip()
            telefono = input("Teléfono: ").strip()

            # Compuerta Inclusiva (OR): Servicios adicionales
            print("\n--- SERVICIOS ADICIONALES (Opcionales) ---")
            resp_desayuno = input(
                f"¿Desea incluir Desayuno (${self.COSTO_DESAYUNO_NOCHE:,}/noche)? (s/n): "
            ).strip().lower()
            incluye_desayuno = (resp_desayuno == 's')

            resp_estacionamiento = input(
                f"¿Desea incluir Estacionamiento (${self.COSTO_ESTACIONAMIENTO_NOCHE:,}/noche)? (s/n): "
            ).strip().lower()
            incluye_estacionamiento = (resp_estacionamiento == 's')

            # Cálculo de tarifa según fórmula: (Tarifa_Base + Costo_Desayuno + Costo_Estacionamiento) * Noches_Estadia
            tarifa_base = self.tarifas[hab_idx]
            costo_desayuno = self.COSTO_DESAYUNO_NOCHE if incluye_desayuno else 0
            costo_estacionamiento = self.COSTO_ESTACIONAMIENTO_NOCHE if incluye_estacionamiento else 0
            tarifa_diaria_total = tarifa_base + costo_desayuno + costo_estacionamiento
            costo_total = tarifa_diaria_total * dias_estadia

            print("\n--- RESUMEN DE COTIZACIÓN ---")
            print(f"Habitación {hab_num} (Tarifa base): ${tarifa_base:,} / noche")
            print(
                f"Desayuno                     : "
                f"{'Sí ($' + format(costo_desayuno, ',') + '/noche)' if incluye_desayuno else 'No ($0)'}"
            )
            print(
                f"Estacionamiento              : "
                f"{'Sí ($' + format(costo_estacionamiento, ',') + '/noche)' if incluye_estacionamiento else 'No ($0)'}"
            )
            print(
                f"Fórmula: (${tarifa_base:,} + ${costo_desayuno:,} + ${costo_estacionamiento:,}) "
                f"x {dias_estadia} noche(s) = ${costo_total:,}"
            )

            confirmar = input("\n¿Confirmar reserva? (s/n): ").strip().lower()
            if confirmar == 's':
                nuevo_huesped = Huesped(rut, nombre, telefono)
                nueva_reserva = Reserva(
                    nuevo_huesped,
                    hab_idx,
                    dia_inicio,
                    dias_estadia,
                    costo_total,
                    incluye_desayuno=incluye_desayuno,
                    incluye_estacionamiento=incluye_estacionamiento,
                    estado="Confirmada"
                )
                self.confirmar_y_guardar_reserva(nueva_reserva, hab_idx, dia_inicio, dias_estadia)
            else:
                print("Reserva cancelada.")

        except ValueError:
            print("Error: Ingrese valores numéricos válidos para los días.")

    def ver_reservas_activas(self):
        """Lista todas las reservas registradas en la base de datos MySQL."""
        self.cargar_datos()
        print("\n--- RESERVAS ACTIVAS (MySQL) ---")
        if not self.reservas:
            print("No hay reservas registradas.")
            return

        for r in self.reservas:
            hab_num = self.habitaciones[r.habitacion_idx]
            servicios = []
            if r.incluye_desayuno:
                servicios.append("Desayuno")
            if r.incluye_estacionamiento:
                servicios.append("Estacionamiento")
            texto_servicios = ", ".join(servicios) if servicios else "Ninguno"

            print(
                f"Estado: [{r.estado}] | Huésped: {r.huesped.nombre} (RUT: {r.huesped.rut}) | "
                f"Habitación: {hab_num} | Ingreso: Día {r.dia_inicio + 1} | Noches: {r.dias_estadia} | "
                f"Servicios: {texto_servicios} | Total: ${r.total:,}"
            )
        print("--------------------------------\n")

    def iniciar(self):
        """Menú principal interactivo en consola."""
        while True:
            print("\n=== SISTEMA NEXOPMS (MySQL) ===")
            print("1. Consultar matriz de disponibilidad")
            print("2. Consultar tarifas")
            print("3. Registrar nueva reserva (Cotizar y Confirmar)")
            print("4. Ver reservas activas")
            print("5. Salir")

            opcion = input("Seleccione una opción: ")

            if opcion == '1':
                self.cargar_datos()
                self.mostrar_matriz_disponibilidad()
            elif opcion == '2':
                self.consultar_tarifas()
            elif opcion == '3':
                self.registrar_reserva()
            elif opcion == '4':
                self.ver_reservas_activas()
            elif opcion == '5':
                print("Cerrando NexoPMS... ¡Hasta pronto!")
                break
            else:
                print("Opción inválida. Intente nuevamente.")


if __name__ == "__main__":
    sistema = NexoPMS()
    sistema.iniciar()
