"""
Módulo de conexión y acceso a datos MySQL para el sistema NexoPMS.
Gestiona la comunicación con la base de datos 'nexopms_db'.
"""

import mysql.connector
from mysql.connector import Error


class ConexionDB:
    """Administra la conexión a MySQL y las operaciones CRUD de NexoPMS."""

    def __init__(
        self,
        host="127.0.0.1",
        port=3306,
        user="root",
        password="",
        database="nexopms_db"
    ):
        self.config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "charset": "utf8mb4"
        }

    def conectar(self):
        """Establece y retorna una nueva conexión a la base de datos MySQL."""
        return mysql.connector.connect(**self.config)

    def probar_conexion(self):
        """Verifica si la base de datos está accesible."""
        try:
            conn = self.conectar()
            if conn.is_connected():
                conn.close()
                return True
        except Error as e:
            print(f"Error de conexión a MySQL: {e}")
        return False

    def obtener_habitaciones_y_tarifas(self):
        """
        Obtiene las habitaciones activas desde MySQL para poblar
        los vectores paralelos (habitaciones, tarifas e IDs de BD).
        """
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_habitacion, numero_habitacion, tarifa_base_noche "
                "FROM habitaciones WHERE activa = 1 ORDER BY id_habitacion ASC"
            )
            filas = cursor.fetchall()
            cursor.close()
            return filas
        finally:
            if conn and conn.is_connected():
                conn.close()

    def obtener_ocupacion_diaria(self):
        """Obtiene todos los registros de días ocupados en la tabla ocupacion_diaria."""
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_habitacion, dia_mes, ocupada, id_reserva "
                "FROM ocupacion_diaria WHERE ocupada = 1"
            )
            filas = cursor.fetchall()
            cursor.close()
            return filas
        finally:
            if conn and conn.is_connected():
                conn.close()

    def obtener_reservas_activas(self):
        """Obtiene todas las reservas confirmadas junto con los datos del huésped."""
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    r.id_reserva,
                    r.id_habitacion,
                    r.dia_inicio,
                    r.dias_estadia,
                    r.incluye_desayuno,
                    r.incluye_estacionamiento,
                    r.monto_total,
                    r.estado,
                    h.rut,
                    h.nombre,
                    h.telefono
                FROM reservas r
                INNER JOIN huespedes h ON r.id_huesped = h.id_huesped
                WHERE r.estado = 'Confirmada'
                ORDER BY r.id_reserva ASC
                """
            )
            filas = cursor.fetchall()
            cursor.close()
            return filas
        finally:
            if conn and conn.is_connected():
                conn.close()

    def verificar_disponibilidad_db(self, id_habitacion, dia_inicio_bd, dias_estadia):
        """
        Subproceso TO-BE: Verifica directamente en la tabla ocupacion_diaria de MySQL
        que ninguno de los días del rango esté ocupado antes de confirmar.
        """
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor()
            dia_fin_bd = dia_inicio_bd + dias_estadia - 1
            cursor.execute(
                """
                SELECT COUNT(*) FROM ocupacion_diaria
                WHERE id_habitacion = %s
                  AND dia_mes BETWEEN %s AND %s
                  AND ocupada = 1
                """,
                (id_habitacion, dia_inicio_bd, dia_fin_bd)
            )
            (ocupadas,) = cursor.fetchone()
            cursor.close()
            return ocupadas == 0
        finally:
            if conn and conn.is_connected():
                conn.close()

    def guardar_reserva_transaccional(self, nueva_reserva, id_habitacion):
        """
        Guarda de forma atómica (transacción SQL):
        1. El huésped en la tabla 'huespedes' (o actualiza sus datos si el RUT ya existe).
        2. La reserva en la tabla 'reservas'.
        3. Los días bloqueados en la tabla 'ocupacion_diaria' (matriz en BD).
        """
        conn = None
        try:
            conn = self.conectar()
            conn.start_transaction()
            cursor = conn.cursor()

            # 1. Insertar o recuperar el huésped por su RUT
            huesped = nueva_reserva.huesped
            cursor.execute(
                """
                INSERT INTO huespedes (rut, nombre, telefono)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    nombre = VALUES(nombre),
                    telefono = VALUES(telefono),
                    id_huesped = LAST_INSERT_ID(id_huesped)
                """,
                (huesped.rut, huesped.nombre, huesped.telefono)
            )
            id_huesped = cursor.lastrowid

            # En Python dia_inicio es índice 0..29; en MySQL es día calendario 1..30
            dia_inicio_bd = nueva_reserva.dia_inicio + 1

            # 2. Insertar el registro en la tabla 'reservas'
            cursor.execute(
                """
                INSERT INTO reservas (
                    id_huesped,
                    id_habitacion,
                    dia_inicio,
                    dias_estadia,
                    incluye_desayuno,
                    incluye_estacionamiento,
                    monto_total,
                    estado
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_huesped,
                    id_habitacion,
                    dia_inicio_bd,
                    nueva_reserva.dias_estadia,
                    1 if nueva_reserva.incluye_desayuno else 0,
                    1 if nueva_reserva.incluye_estacionamiento else 0,
                    nueva_reserva.total,
                    nueva_reserva.estado
                )
            )
            id_reserva = cursor.lastrowid

            # 3. Bloquear cada día en la tabla 'ocupacion_diaria' (matriz 4x30 en BD)
            for d_offset in range(nueva_reserva.dias_estadia):
                dia_mes = dia_inicio_bd + d_offset
                cursor.execute(
                    """
                    INSERT INTO ocupacion_diaria (id_habitacion, dia_mes, ocupada, id_reserva)
                    VALUES (%s, %s, 1, %s)
                    """,
                    (id_habitacion, dia_mes, id_reserva)
                )

            conn.commit()
            cursor.close()
            return True
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            print(f"Error al guardar la reserva en MySQL: {e}")
            return False
        finally:
            if conn and conn.is_connected():
                conn.close()

