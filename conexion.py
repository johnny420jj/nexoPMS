"""
Módulo de conexión y acceso a datos MySQL para el sistema NexoPMS.
Gestiona la comunicación con la base de datos 'nexopms_db'.
"""

import hashlib
import hmac
import secrets
import mysql.connector
from mysql.connector import Error

PBKDF2_ITERATIONS = 100_000
TIPOS_ALOJAMIENTO_VALIDOS = ("Habitación", "Cabaña")
USUARIOS_SEMILLA = (
    ("admin", "admin123", "admin"),
    ("recepcion", "recep123", "recepcionista"),
)


def hashear_password(password, iterations=PBKDF2_ITERATIONS):
    """Genera un hash PBKDF2-HMAC-SHA256 con salt aleatorio en formato portable."""
    if not isinstance(password, str) or not password:
        raise ValueError("La contraseña debe ser una cadena no vacía.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        int(iterations),
    ).hex()
    return f"pbkdf2_sha256${int(iterations)}${salt}${digest}"


def verificar_password(password, password_hash):
    """Verifica en tiempo constante una contraseña contra un hash pbkdf2_sha256."""
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False
    try:
        algoritmo, iter_str, salt, expected_digest = password_hash.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        if iterations <= 0:
            return False
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            iterations,
        ).hex()
        return hmac.compare_digest(actual_digest, expected_digest)
    except (ValueError, TypeError):
        return False


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
        self._esquema_asegurado = False

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

    def asegurar_esquema(self):
        """
        Crea la tabla 'usuarios' e inserta los usuarios semilla si no existen,
        y migra idempotentemente columnas nuevas en 'habitaciones' y 'reservas'.
        """
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS usuarios (
                    id_usuario INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    rol ENUM('admin', 'recepcionista') NOT NULL,
                    activo TINYINT(1) NOT NULL DEFAULT 1,
                    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE = InnoDB
                """
            )

            for username, raw_password, rol in USUARIOS_SEMILLA:
                cursor.execute(
                    """
                    INSERT IGNORE INTO usuarios (username, password, rol)
                    VALUES (%s, %s, %s)
                    """,
                    (username, hashear_password(raw_password), rol)
                )

            cursor.execute(
                """
                SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'habitaciones'
                """
            )
            cols_hab = {
                row["COLUMN_NAME"].lower(): row for row in cursor.fetchall()
            }
            if cols_hab:
                if "tipo" not in cols_hab:
                    cursor.execute(
                        """
                        ALTER TABLE habitaciones
                        ADD COLUMN tipo ENUM('Habitación', 'Cabaña')
                        NOT NULL DEFAULT 'Habitación' AFTER id_habitacion
                        """
                    )
                num_col = cols_hab.get("numero_habitacion")
                if num_col and (num_col.get("CHARACTER_MAXIMUM_LENGTH") or 0) < 50:
                    cursor.execute(
                        """
                        ALTER TABLE habitaciones
                        MODIFY COLUMN numero_habitacion VARCHAR(50) NOT NULL
                        """
                    )

            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'reservas'
                """
            )
            cols_res = {row["COLUMN_NAME"].lower() for row in cursor.fetchall()}
            if cols_res:
                if "habitacion_nombre" not in cols_res:
                    cursor.execute(
                        "ALTER TABLE reservas ADD COLUMN habitacion_nombre VARCHAR(50) NULL"
                    )
                if "tipo_alojamiento" not in cols_res:
                    cursor.execute(
                        "ALTER TABLE reservas ADD COLUMN tipo_alojamiento VARCHAR(20) NULL"
                    )
                if "tarifa_base_snapshot" not in cols_res:
                    cursor.execute(
                        "ALTER TABLE reservas ADD COLUMN tarifa_base_snapshot INT UNSIGNED NULL"
                    )

            conn.commit()
            cursor.close()
            self._esquema_asegurado = True
            return True
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            print(f"Aviso al verificar esquema en MySQL: {e}")
            return False
        finally:
            if conn and conn.is_connected():
                conn.close()

    def autenticar_usuario(self, username, password):
        """
        Valida las credenciales de un usuario contra la tabla 'usuarios' usando hash.
        Retorna {'id_usuario': ..., 'username': ..., 'rol': ...} o None si falla.
        """
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        username_limpio = username.strip()
        if not username_limpio or not password:
            return None

        if not self._esquema_asegurado:
            self.asegurar_esquema()

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id_usuario, username, password, rol, activo
                FROM usuarios
                WHERE username = %s
                """,
                (username_limpio,)
            )
            fila = cursor.fetchone()
            cursor.close()

            if fila is None or not bool(fila.get("activo", 1)):
                return None
            if not verificar_password(password, fila["password"]):
                return None

            return {
                "id_usuario": fila["id_usuario"],
                "username": fila["username"],
                "rol": fila["rol"],
            }
        except Error as e:
            print(f"Error al autenticar usuario en MySQL: {e}")
            return None
        finally:
            if conn and conn.is_connected():
                conn.close()

    def obtener_habitaciones_y_tarifas(self):
        """
        Obtiene los alojamientos activos desde MySQL para poblar
        los vectores paralelos (habitaciones, tipos, tarifas e IDs de BD).
        """
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_habitacion, tipo, numero_habitacion, tarifa_base_noche "
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
                    r.habitacion_nombre,
                    r.tipo_alojamiento,
                    r.tarifa_base_snapshot,
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

    def agregar_habitacion(self, tipo, numero_habitacion, tarifa_base_noche):
        """
        Inserta una nueva Habitación o Cabaña validando tipo, tarifa y unicidad.
        Retorna (exito, id_habitacion | None, mensaje).
        """
        if tipo not in TIPOS_ALOJAMIENTO_VALIDOS:
            return False, None, "Tipo de alojamiento inválido. Use 'Habitación' o 'Cabaña'."

        identificador = (numero_habitacion or "").strip()
        if not identificador or len(identificador) > 50:
            return False, None, "El identificador debe tener entre 1 y 50 caracteres."

        try:
            tarifa = int(tarifa_base_noche)
        except (TypeError, ValueError):
            return False, None, "La tarifa base debe ser un número entero positivo."
        if tarifa <= 0:
            return False, None, "La tarifa base debe ser mayor a 0."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_habitacion, activa FROM habitaciones WHERE LOWER(numero_habitacion) = LOWER(%s)",
                (identificador,)
            )
            existente = cursor.fetchone()
            if existente is not None:
                if bool(existente.get("activa", 1)):
                    cursor.close()
                    return False, None, f"Ya existe un alojamiento con el identificador '{identificador}'."
                cursor.execute(
                    """
                    UPDATE habitaciones
                    SET tipo = %s, numero_habitacion = %s, tarifa_base_noche = %s, activa = 1
                    WHERE id_habitacion = %s
                    """,
                    (tipo, identificador, tarifa, existente["id_habitacion"])
                )
                id_nuevo = existente["id_habitacion"]
            else:
                cursor.execute(
                    """
                    INSERT INTO habitaciones (tipo, numero_habitacion, tarifa_base_noche, activa)
                    VALUES (%s, %s, %s, 1)
                    """,
                    (tipo, identificador, tarifa)
                )
                id_nuevo = cursor.lastrowid

            conn.commit()
            cursor.close()
            return True, id_nuevo, f"{tipo} '{identificador}' agregada exitosamente."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, None, f"Error al agregar alojamiento en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def editar_habitacion(self, id_habitacion, tipo, numero_habitacion, tarifa_base_noche):
        """
        Actualiza tipo, identificador y tarifa base de un alojamiento sin alterar reservas previas.
        Retorna (exito, mensaje).
        """
        if tipo not in TIPOS_ALOJAMIENTO_VALIDOS:
            return False, "Tipo de alojamiento inválido. Use 'Habitación' o 'Cabaña'."

        identificador = (numero_habitacion or "").strip()
        if not identificador or len(identificador) > 50:
            return False, "El identificador debe tener entre 1 y 50 caracteres."

        try:
            tarifa = int(tarifa_base_noche)
        except (TypeError, ValueError):
            return False, "La tarifa base debe ser un número entero positivo."
        if tarifa <= 0:
            return False, "La tarifa base debe ser mayor a 0."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_habitacion FROM habitaciones WHERE id_habitacion = %s AND activa = 1",
                (id_habitacion,)
            )
            if cursor.fetchone() is None:
                cursor.close()
                return False, "El alojamiento seleccionado no existe o no está activo."

            cursor.execute(
                """
                SELECT id_habitacion
                FROM habitaciones
                WHERE LOWER(numero_habitacion) = LOWER(%s) AND id_habitacion != %s
                """,
                (identificador, id_habitacion)
            )
            if cursor.fetchone() is not None:
                cursor.close()
                return False, f"Ya existe otro alojamiento con el identificador '{identificador}'."

            cursor.execute(
                """
                UPDATE habitaciones
                SET tipo = %s, numero_habitacion = %s, tarifa_base_noche = %s
                WHERE id_habitacion = %s
                """,
                (tipo, identificador, tarifa, id_habitacion)
            )
            conn.commit()
            cursor.close()
            return True, f"{tipo} '{identificador}' actualizada exitosamente."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, f"Error al actualizar alojamiento en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def eliminar_habitacion(self, id_habitacion):
        """
        Elimina un alojamiento solo si no posee reservas activas ni días ocupados.
        Retorna (exito, mensaje).
        """
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COUNT(*) FROM ocupacion_diaria
                WHERE id_habitacion = %s AND ocupada = 1
                """,
                (id_habitacion,)
            )
            (dias_ocupados,) = cursor.fetchone()
            if dias_ocupados > 0:
                cursor.close()
                return False, "No se puede eliminar: el alojamiento tiene días ocupados registrados."

            cursor.execute(
                """
                SELECT COUNT(*) FROM reservas
                WHERE id_habitacion = %s AND estado = 'Confirmada'
                """,
                (id_habitacion,)
            )
            (reservas_activas,) = cursor.fetchone()
            if reservas_activas > 0:
                cursor.close()
                return False, "No se puede eliminar: el alojamiento tiene reservas activas."

            cursor.execute(
                "SELECT COUNT(*) FROM reservas WHERE id_habitacion = %s",
                (id_habitacion,)
            )
            (reservas_historicas,) = cursor.fetchone()

            if reservas_historicas == 0:
                cursor.execute(
                    "DELETE FROM habitaciones WHERE id_habitacion = %s",
                    (id_habitacion,)
                )
            else:
                cursor.execute(
                    "UPDATE habitaciones SET activa = 0 WHERE id_habitacion = %s",
                    (id_habitacion,)
                )

            conn.commit()
            cursor.close()
            return True, "Alojamiento eliminado exitosamente."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, f"Error al eliminar alojamiento en MySQL: {e}"
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
                    estado,
                    habitacion_nombre,
                    tipo_alojamiento,
                    tarifa_base_snapshot
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_huesped,
                    id_habitacion,
                    dia_inicio_bd,
                    nueva_reserva.dias_estadia,
                    1 if nueva_reserva.incluye_desayuno else 0,
                    1 if nueva_reserva.incluye_estacionamiento else 0,
                    nueva_reserva.total,
                    nueva_reserva.estado,
                    getattr(nueva_reserva, "habitacion_nombre", None),
                    getattr(nueva_reserva, "tipo_alojamiento", None),
                    getattr(nueva_reserva, "tarifa_base_snapshot", None)
                )
            )
            id_reserva = cursor.lastrowid

            # 3. Bloquear cada día en la tabla 'ocupacion_diaria' (matriz en BD)
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

