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
MAX_INT_UNSIGNED = 4294967295
TIPOS_ALOJAMIENTO_VALIDOS = ("Habitación", "Cabaña")
USUARIOS_SEMILLA = (
    ("admin", "admin123", "admin"),
    ("gerente", "gerente123", "gerente"),
    ("recepcion", "recep123", "recepcionista"),
)
SERVICIOS_SEMILLA = (
    ("Desayuno", 5000, True),
    ("Estacionamiento", 8000, True),
)


def _parsear_entero(valor, minimo=1, maximo=MAX_INT_UNSIGNED):
    """Convierte y valida un entero en [minimo, maximo], rechazando booleanos y flotantes."""
    if isinstance(valor, (bool, float)):
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    if numero < minimo or numero > maximo:
        return None
    return numero


def _extraer_campo(fila, clave, indice=0):
    """Extrae un valor desde una fila tipo dict o tupla/lista."""
    if fila is None:
        return None
    if isinstance(fila, dict):
        if clave in fila:
            return fila[clave]
        for k, v in fila.items():
            if str(k).lower() == str(clave).lower():
                return v
        return next(iter(fila.values()), None)
    if isinstance(fila, (tuple, list)):
        return fila[indice] if len(fila) > indice else None
    return None


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
        Crea e idempotentemente migra las tablas base ('usuarios', 'habitaciones',
        'reservas', 'servicios', 'reserva_servicios') e inserta datos semilla.
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
                    rol ENUM('admin', 'gerente', 'recepcionista') NOT NULL,
                    activo TINYINT(1) NOT NULL DEFAULT 1,
                    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE = InnoDB
                """
            )

            cursor.execute(
                """
                SELECT COLUMN_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'usuarios'
                  AND COLUMN_NAME = 'rol'
                """
            )
            row_rol = cursor.fetchone()
            if row_rol:
                raw_col_type = _extraer_campo(row_rol, "COLUMN_TYPE", 0) or ""
                if isinstance(raw_col_type, (bytes, bytearray)):
                    raw_col_type = raw_col_type.decode("utf-8", errors="ignore")
                if "'gerente'" not in str(raw_col_type).lower():
                    cursor.execute(
                        """
                        ALTER TABLE usuarios
                        MODIFY COLUMN rol ENUM('admin', 'gerente', 'recepcionista') NOT NULL
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
                SELECT COLUMN_NAME, COLUMN_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'reservas'
                """
            )
            cols_res = {
                row["COLUMN_NAME"].lower(): row for row in cursor.fetchall()
            }
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
                estado_col = cols_res.get("estado")
                if estado_col:
                    raw_estado_type = estado_col.get("COLUMN_TYPE") or estado_col.get("column_type")
                    if isinstance(raw_estado_type, (bytes, bytearray)):
                        raw_estado_type = raw_estado_type.decode("utf-8", errors="ignore")
                    if raw_estado_type and "'cancelada'" not in str(raw_estado_type).lower():
                        cursor.execute(
                            """
                            ALTER TABLE reservas
                            MODIFY COLUMN estado ENUM('Confirmada', 'Cancelada', 'Finalizada')
                            NOT NULL DEFAULT 'Confirmada'
                            """
                        )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS servicios (
                    id_servicio INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL UNIQUE,
                    costo INT UNSIGNED NOT NULL,
                    disponible TINYINT(1) NOT NULL DEFAULT 1
                ) ENGINE = InnoDB
                """
            )

            for nombre, costo, disponible in SERVICIOS_SEMILLA:
                cursor.execute(
                    """
                    INSERT IGNORE INTO servicios (nombre, costo, disponible)
                    VALUES (%s, %s, %s)
                    """,
                    (nombre, int(costo), 1 if disponible else 0),
                )

            if cols_res:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reserva_servicios (
                        id_reserva_servicio INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                        id_reserva INT UNSIGNED NOT NULL,
                        id_servicio INT UNSIGNED NOT NULL,
                        nombre_snapshot VARCHAR(100) NOT NULL,
                        costo_unitario_snapshot INT UNSIGNED NOT NULL,
                        subtotal INT UNSIGNED NOT NULL,
                        CONSTRAINT uq_reserva_servicio UNIQUE (id_reserva, id_servicio),
                        CONSTRAINT fk_res_serv_reserva FOREIGN KEY (id_reserva)
                            REFERENCES reservas (id_reserva)
                            ON UPDATE CASCADE ON DELETE CASCADE,
                        CONSTRAINT fk_res_serv_servicio FOREIGN KEY (id_servicio)
                            REFERENCES servicios (id_servicio)
                            ON UPDATE CASCADE ON DELETE RESTRICT
                    ) ENGINE = InnoDB
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS configuracion (
                        clave VARCHAR(50) PRIMARY KEY,
                        valor VARCHAR(150) NOT NULL
                    ) ENGINE = InnoDB
                    """
                )
                cursor.execute(
                    """
                    INSERT IGNORE INTO configuracion (clave, valor)
                    VALUES ('nombre_hotel', 'Hotel Los Arrayanes')
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS secuencias (
                        nombre VARCHAR(50) PRIMARY KEY,
                        ultimo_valor INT UNSIGNED NOT NULL
                    ) ENGINE = InnoDB
                    """
                )
                cursor.execute(
                    """
                    INSERT IGNORE INTO secuencias (nombre, ultimo_valor)
                    VALUES ('habitacion', 104), ('cabana', 0)
                    """
                )

                # Migrar columnas mes/anio en reservas y ocupacion_diaria si no existen
                for tabla_cal in ("reservas", "ocupacion_diaria"):
                    cursor.execute(
                        """
                        SELECT COLUMN_NAME
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                        """,
                        (tabla_cal,),
                    )
                    cols_cal = {
                        _extraer_campo(fila, "COLUMN_NAME", 0)
                        for fila in cursor.fetchall()
                    }
                    if cols_cal:
                        if "anio" not in cols_cal:
                            cursor.execute(
                                f"ALTER TABLE {tabla_cal} ADD COLUMN anio SMALLINT UNSIGNED NOT NULL DEFAULT 2026"
                            )
                        if "mes" not in cols_cal:
                            cursor.execute(
                                f"ALTER TABLE {tabla_cal} ADD COLUMN mes TINYINT UNSIGNED NOT NULL DEFAULT 11"
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

    def obtener_nombre_hotel(self):
        """Obtiene el nombre configurable del hotel desde la tabla 'configuracion'."""
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT valor FROM configuracion WHERE clave = 'nombre_hotel'"
            )
            fila = cursor.fetchone()
            cursor.close()
            if fila and fila.get("valor"):
                return str(fila["valor"]).strip()
            return "Hotel Los Arrayanes"
        except Error:
            return "Hotel Los Arrayanes"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def actualizar_nombre_hotel(self, nuevo_nombre):
        """Actualiza el nombre del hotel en la tabla 'configuracion'. Retorna (exito, mensaje)."""
        if not isinstance(nuevo_nombre, str):
            return False, "El nombre del hotel debe ser una cadena de texto."
        nombre_limpio = nuevo_nombre.strip()
        if not nombre_limpio or len(nombre_limpio) > 150:
            return False, "El nombre del hotel debe tener entre 1 y 150 caracteres."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO configuracion (clave, valor)
                VALUES ('nombre_hotel', %s)
                ON DUPLICATE KEY UPDATE valor = VALUES(valor)
                """,
                (nombre_limpio,),
            )
            conn.commit()
            cursor.close()
            return True, f"Nombre del hotel actualizado a '{nombre_limpio}'."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, f"Error al actualizar nombre del hotel en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def obtener_ocupacion_diaria(self, mes=None, anio=None):
        """Obtiene los registros de días ocupados en ocupacion_diaria (opcionalmente filtrados por mes/año)."""
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            if mes is not None and anio is not None:
                cursor.execute(
                    "SELECT id_habitacion, anio, mes, dia_mes, ocupada, id_reserva "
                    "FROM ocupacion_diaria WHERE ocupada = 1 AND mes = %s AND anio = %s",
                    (int(mes), int(anio)),
                )
            else:
                cursor.execute(
                    "SELECT id_habitacion, anio, mes, dia_mes, ocupada, id_reserva "
                    "FROM ocupacion_diaria WHERE ocupada = 1"
                )
            filas = cursor.fetchall()
            cursor.close()
            return filas
        finally:
            if conn and conn.is_connected():
                conn.close()

    def _obtener_reservas(self, solo_activas=True):
        """Obtiene reservas junto con datos del huésped y sus servicios contratados."""
        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            filtro_estado = "WHERE r.estado = 'Confirmada'" if solo_activas else ""
            cursor.execute(
                f"""
                SELECT
                    r.id_reserva,
                    r.id_habitacion,
                    r.anio,
                    r.mes,
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
                {filtro_estado}
                ORDER BY r.id_reserva ASC
                """
            )
            filas = [dict(f) for f in cursor.fetchall()]
            if filas:
                ids = [f["id_reserva"] for f in filas]
                placeholders = ", ".join(["%s"] * len(ids))
                cursor.execute(
                    f"""
                    SELECT
                        id_reserva,
                        id_servicio,
                        nombre_snapshot,
                        costo_unitario_snapshot,
                        subtotal
                    FROM reserva_servicios
                    WHERE id_reserva IN ({placeholders})
                    ORDER BY id_reserva_servicio ASC
                    """,
                    tuple(ids),
                )
                servicios_por_reserva = {}
                for srv in cursor.fetchall():
                    id_res = srv["id_reserva"]
                    servicios_por_reserva.setdefault(id_res, []).append({
                        "id_servicio": int(srv["id_servicio"]),
                        "nombre": str(srv["nombre_snapshot"]),
                        "costo_unitario": int(srv["costo_unitario_snapshot"]),
                        "subtotal": int(srv["subtotal"]),
                    })
                for fila in filas:
                    fila["servicios"] = [
                        dict(s) for s in servicios_por_reserva.get(fila["id_reserva"], [])
                    ]
            cursor.close()
            return filas
        finally:
            if conn and conn.is_connected():
                conn.close()

    def obtener_reservas_activas(self):
        """Obtiene todas las reservas confirmadas junto con huésped y servicios."""
        return self._obtener_reservas(solo_activas=True)

    def obtener_todas_las_reservas(self):
        """Obtiene el historial completo de reservas (confirmadas, canceladas, etc.)."""
        return self._obtener_reservas(solo_activas=False)

    def agregar_habitacion(self, tipo, numero_habitacion, tarifa_base_noche):
        """
        Inserta una nueva Habitación o Cabaña validando tipo, tarifa y unicidad.
        Retorna (exito, id_habitacion | None, mensaje).
        """
        if tipo not in TIPOS_ALOJAMIENTO_VALIDOS:
            return False, None, "Tipo de alojamiento inválido. Use 'Habitación' o 'Cabaña'."

        identificador = (
            numero_habitacion.strip()
            if isinstance(numero_habitacion, str)
            else (str(numero_habitacion).strip() if numero_habitacion is not None else "")
        )
        if not identificador or len(identificador) > 50:
            return False, None, "El identificador debe tener entre 1 y 50 caracteres."

        tarifa = _parsear_entero(tarifa_base_noche, minimo=1, maximo=MAX_INT_UNSIGNED)
        if tarifa is None:
            return False, None, "La tarifa base debe ser un número entero entre 1 y 4294967295."

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

    def agregar_alojamientos_por_secuencia(self, tipo_local, cantidad, tarifa_base_noche):
        """
        Genera en lote habitaciones (tipo_local='Hotel') o cabañas (tipo_local='Cabaña')
        utilizando la tabla de secuencias SQL 'secuencias' para asignar identificadores automáticos.
        Retorna (exito, lista_creados, mensaje).
        """
        if tipo_local not in ("Hotel", "Cabaña"):
            return False, [], "Tipo de local inválido. Seleccione 'Hotel' o 'Cabaña'."

        cant = _parsear_entero(cantidad, minimo=1, maximo=100)
        if cant is None:
            return False, [], "La cantidad debe ser un número entero entre 1 y 100."

        tarifa = _parsear_entero(tarifa_base_noche, minimo=1, maximo=MAX_INT_UNSIGNED)
        if tarifa is None:
            return False, [], "La tarifa base debe ser un número entero entre 1 y 4294967295."

        if not self._esquema_asegurado:
            self.asegurar_esquema()

        es_hotel = (tipo_local == "Hotel")
        seq_nombre = "habitacion" if es_hotel else "cabana"
        tipo_unidad = "Habitación" if es_hotel else "Cabaña"

        conn = None
        try:
            conn = self.conectar()
            conn.start_transaction()
            cursor = conn.cursor(dictionary=True)

            creados = []
            for _ in range(cant):
                # Avanzar secuencia SQL evitando colisiones con identificadores existentes
                while True:
                    cursor.execute(
                        """
                        UPDATE secuencias
                        SET ultimo_valor = LAST_INSERT_ID(ultimo_valor + 1)
                        WHERE nombre = %s
                        """,
                        (seq_nombre,),
                    )
                    cursor.execute("SELECT LAST_INSERT_ID() AS siguiente")
                    siguiente = int(_extraer_campo(cursor.fetchone(), "siguiente", 0))
                    identificador = str(siguiente) if es_hotel else f"Cabaña {siguiente}"

                    cursor.execute(
                        "SELECT id_habitacion, activa FROM habitaciones WHERE LOWER(numero_habitacion) = LOWER(%s)",
                        (identificador,),
                    )
                    existente = cursor.fetchone()
                    if existente is None:
                        cursor.execute(
                            """
                            INSERT INTO habitaciones (tipo, numero_habitacion, tarifa_base_noche, activa)
                            VALUES (%s, %s, %s, 1)
                            """,
                            (tipo_unidad, identificador, tarifa),
                        )
                        creados.append(identificador)
                        break
                    if not bool(existente.get("activa", 1)):
                        cursor.execute(
                            """
                            UPDATE habitaciones
                            SET tipo = %s, numero_habitacion = %s, tarifa_base_noche = %s, activa = 1
                            WHERE id_habitacion = %s
                            """,
                            (tipo_unidad, identificador, tarifa, existente["id_habitacion"]),
                        )
                        creados.append(identificador)
                        break

            conn.commit()
            cursor.close()
            etiqueta = "habitación(es)" if es_hotel else "cabaña(s)"
            resumen = ", ".join(creados)
            return True, creados, f"Se generaron {len(creados)} {etiqueta} por secuencia SQL: {resumen}."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, [], f"Error al generar alojamientos por secuencia en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def editar_habitacion(self, id_habitacion, tipo, numero_habitacion, tarifa_base_noche):
        """
        Actualiza tipo, identificador y tarifa base de un alojamiento sin alterar reservas previas.
        Retorna (exito, mensaje).
        """
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_hab is None:
            return False, "Identificador de alojamiento inválido."

        if tipo not in TIPOS_ALOJAMIENTO_VALIDOS:
            return False, "Tipo de alojamiento inválido. Use 'Habitación' o 'Cabaña'."

        identificador = (
            numero_habitacion.strip()
            if isinstance(numero_habitacion, str)
            else (str(numero_habitacion).strip() if numero_habitacion is not None else "")
        )
        if not identificador or len(identificador) > 50:
            return False, "El identificador debe tener entre 1 y 50 caracteres."

        tarifa = _parsear_entero(tarifa_base_noche, minimo=1, maximo=MAX_INT_UNSIGNED)
        if tarifa is None:
            return False, "La tarifa base debe ser un número entero entre 1 y 4294967295."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_habitacion FROM habitaciones WHERE id_habitacion = %s AND activa = 1",
                (id_hab,)
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
                (identificador, id_hab)
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
                (tipo, identificador, tarifa, id_hab)
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
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_hab is None:
            return False, "Identificador de alojamiento inválido."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COUNT(*) FROM ocupacion_diaria
                WHERE id_habitacion = %s AND ocupada = 1
                """,
                (id_hab,)
            )
            dias_ocupados = _extraer_campo(cursor.fetchone(), "COUNT(*)", 0) or 0
            if dias_ocupados > 0:
                cursor.close()
                return False, "No se puede eliminar: el alojamiento tiene días ocupados registrados."

            cursor.execute(
                """
                SELECT COUNT(*) FROM reservas
                WHERE id_habitacion = %s AND estado = 'Confirmada'
                """,
                (id_hab,)
            )
            reservas_activas = _extraer_campo(cursor.fetchone(), "COUNT(*)", 0) or 0
            if reservas_activas > 0:
                cursor.close()
                return False, "No se puede eliminar: el alojamiento tiene reservas activas."

            cursor.execute(
                "SELECT COUNT(*) FROM reservas WHERE id_habitacion = %s",
                (id_hab,)
            )
            reservas_historicas = _extraer_campo(cursor.fetchone(), "COUNT(*)", 0) or 0

            if reservas_historicas == 0:
                cursor.execute(
                    "DELETE FROM habitaciones WHERE id_habitacion = %s",
                    (id_hab,)
                )
            else:
                cursor.execute(
                    "UPDATE habitaciones SET activa = 0 WHERE id_habitacion = %s",
                    (id_hab,)
                )

            if getattr(cursor, "rowcount", 1) == 0:
                conn.rollback()
                cursor.close()
                return False, "El alojamiento seleccionado no existe."

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

    def obtener_servicios(self, solo_disponibles=False):
        """Obtiene el catálogo de servicios adicionales desde MySQL."""
        if not self._esquema_asegurado:
            self.asegurar_esquema()

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            filtro = "WHERE disponible = 1" if solo_disponibles else ""
            cursor.execute(
                f"SELECT id_servicio, nombre, costo, disponible FROM servicios {filtro} ORDER BY id_servicio ASC"
            )
            filas = [
                {
                    "id_servicio": int(f["id_servicio"]),
                    "nombre": str(f["nombre"]),
                    "costo": int(f["costo"]),
                    "disponible": bool(f["disponible"]),
                }
                for f in cursor.fetchall()
            ]
            cursor.close()
            return filas
        finally:
            if conn and conn.is_connected():
                conn.close()

    def crear_servicio(self, nombre, costo, disponible=True):
        """
        Crea un nuevo servicio adicional validando nombre (1..100), costo (1..MAX_INT_UNSIGNED)
        y unicidad sin distinguir mayúsculas/minúsculas.
        """
        if not self._esquema_asegurado:
            self.asegurar_esquema()

        if not isinstance(nombre, str):
            return False, None, "El nombre del servicio debe ser una cadena de texto."
        nombre_limpio = nombre.strip()
        if not nombre_limpio or len(nombre_limpio) > 100:
            return False, None, "El nombre del servicio debe tener entre 1 y 100 caracteres."

        costo_val = _parsear_entero(costo, minimo=1, maximo=MAX_INT_UNSIGNED)
        if costo_val is None:
            return False, None, "El costo del servicio debe ser un entero entre 1 y 4294967295."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_servicio FROM servicios WHERE LOWER(nombre) = LOWER(%s)",
                (nombre_limpio,),
            )
            if cursor.fetchone() is not None:
                cursor.close()
                return False, None, f"Ya existe un servicio con el nombre '{nombre_limpio}'."

            cursor.execute(
                """
                INSERT INTO servicios (nombre, costo, disponible)
                VALUES (%s, %s, %s)
                """,
                (nombre_limpio, costo_val, 1 if disponible else 0),
            )
            id_nuevo = cursor.lastrowid
            conn.commit()
            cursor.close()
            return True, id_nuevo, f"Servicio '{nombre_limpio}' creado exitosamente."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, None, f"Error al crear servicio en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def editar_servicio(self, id_servicio, nombre, costo):
        """Actualiza nombre y costo en el catálogo sin modificar snapshots históricos."""
        if not self._esquema_asegurado:
            self.asegurar_esquema()

        id_srv = _parsear_entero(id_servicio, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_srv is None:
            return False, "Identificador de servicio inválido."

        if not isinstance(nombre, str):
            return False, "El nombre del servicio debe ser una cadena de texto."
        nombre_limpio = nombre.strip()
        if not nombre_limpio or len(nombre_limpio) > 100:
            return False, "El nombre del servicio debe tener entre 1 y 100 caracteres."

        costo_val = _parsear_entero(costo, minimo=1, maximo=MAX_INT_UNSIGNED)
        if costo_val is None:
            return False, "El costo del servicio debe ser un entero entre 1 y 4294967295."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_servicio FROM servicios WHERE id_servicio = %s",
                (id_srv,),
            )
            if cursor.fetchone() is None:
                cursor.close()
                return False, "El servicio seleccionado no existe."

            cursor.execute(
                """
                SELECT id_servicio FROM servicios
                WHERE LOWER(nombre) = LOWER(%s) AND id_servicio != %s
                """,
                (nombre_limpio, id_srv),
            )
            if cursor.fetchone() is not None:
                cursor.close()
                return False, f"Ya existe otro servicio con el nombre '{nombre_limpio}'."

            cursor.execute(
                """
                UPDATE servicios
                SET nombre = %s, costo = %s
                WHERE id_servicio = %s
                """,
                (nombre_limpio, costo_val, id_srv),
            )
            conn.commit()
            cursor.close()
            return True, f"Servicio '{nombre_limpio}' actualizado exitosamente."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, f"Error al editar servicio en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def cambiar_disponibilidad_servicio(self, id_servicio, disponible=None):
        """Habilita, deshabilita o invierte la disponibilidad de un servicio."""
        if not self._esquema_asegurado:
            self.asegurar_esquema()

        id_srv = _parsear_entero(id_servicio, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_srv is None:
            return False, None, "Identificador de servicio inválido."

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_servicio, nombre, disponible FROM servicios WHERE id_servicio = %s",
                (id_srv,),
            )
            fila = cursor.fetchone()
            if fila is None:
                cursor.close()
                return False, None, "El servicio seleccionado no existe."

            nuevo_estado = (
                (not bool(fila["disponible"]))
                if disponible is None
                else bool(disponible)
            )
            cursor.execute(
                "UPDATE servicios SET disponible = %s WHERE id_servicio = %s",
                (1 if nuevo_estado else 0, id_srv),
            )
            conn.commit()
            cursor.close()
            estado_txt = "habilitado" if nuevo_estado else "deshabilitado"
            return True, nuevo_estado, f"Servicio '{fila['nombre']}' {estado_txt} exitosamente."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, None, f"Error al cambiar disponibilidad del servicio en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def _resolver_servicios_para_persistencia(
        self,
        cursor,
        servicios,
        dias_estadia,
        incluye_desayuno=False,
        incluye_estacionamiento=False,
    ):
        """
        Normaliza y deduplica servicios a persistir en 'reserva_servicios',
        resolviendo IDs por nombre o aplicando compatibilidad heredada si aplica.
        """
        resueltos = []
        vistos = set()

        if servicios:
            for item in servicios:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("id_servicio")
                id_srv = _parsear_entero(raw_id, minimo=1, maximo=MAX_INT_UNSIGNED) if raw_id is not None else None

                raw_nombre = item.get("nombre")
                if raw_nombre is None:
                    raw_nombre = item.get("nombre_snapshot", "")
                nombre = str(raw_nombre).strip()

                raw_costo = item.get("costo_unitario")
                if raw_costo is None:
                    raw_costo = item.get("costo_unitario_snapshot")
                if raw_costo is None:
                    raw_costo = item.get("costo")

                if id_srv is None:
                    if not nombre:
                        raise ValueError("Servicio sin identificador ni nombre.")
                    cursor.execute(
                        "SELECT id_servicio, nombre, costo FROM servicios WHERE LOWER(nombre) = LOWER(%s)",
                        (nombre,),
                    )
                    fila_srv = cursor.fetchone()
                    if fila_srv is None:
                        raise ValueError(f"El servicio '{nombre}' no existe en el catálogo.")
                    id_srv = int(_extraer_campo(fila_srv, "id_servicio", 0))
                    if not nombre:
                        nombre = str(_extraer_campo(fila_srv, "nombre", 1))
                    if raw_costo is None:
                        raw_costo = _extraer_campo(fila_srv, "costo", 2)

                if id_srv in vistos:
                    continue
                vistos.add(id_srv)

                costo_u = _parsear_entero(raw_costo, minimo=0, maximo=MAX_INT_UNSIGNED)
                if costo_u is None:
                    raise ValueError(f"Costo inválido para el servicio '{nombre}'.")

                raw_subtotal = item.get("subtotal")
                if raw_subtotal is None:
                    subtotal = costo_u * dias_estadia
                else:
                    subtotal = _parsear_entero(raw_subtotal, minimo=0, maximo=MAX_INT_UNSIGNED)
                    if subtotal is None:
                        raise ValueError(f"Subtotal inválido para el servicio '{nombre}'.")

                resueltos.append({
                    "id_servicio": id_srv,
                    "nombre": nombre,
                    "costo_unitario": costo_u,
                    "subtotal": subtotal,
                })
            return resueltos

        if incluye_desayuno or incluye_estacionamiento:
            cursor.execute(
                """
                SELECT id_servicio, nombre, costo
                FROM servicios
                WHERE LOWER(nombre) IN ('desayuno', 'estacionamiento')
                ORDER BY id_servicio ASC
                """
            )
            for fila_srv in cursor.fetchall():
                id_srv = int(_extraer_campo(fila_srv, "id_servicio", 0))
                nombre_srv = str(_extraer_campo(fila_srv, "nombre", 1))
                costo_srv = int(_extraer_campo(fila_srv, "costo", 2))
                nombre_lower = nombre_srv.strip().lower()
                incluir = (
                    (incluye_desayuno and "desayuno" in nombre_lower)
                    or (incluye_estacionamiento and "estacionamiento" in nombre_lower)
                )
                if incluir and id_srv not in vistos:
                    vistos.add(id_srv)
                    resueltos.append({
                        "id_servicio": id_srv,
                        "nombre": nombre_srv,
                        "costo_unitario": costo_srv,
                        "subtotal": costo_srv * dias_estadia,
                    })
        return resueltos

    def verificar_disponibilidad_db(
        self,
        id_habitacion,
        dia_inicio_bd,
        dias_estadia,
        excluir_id_reserva=None,
        mes=None,
        anio=None,
    ):
        """
        Verifica directamente en 'ocupacion_diaria' que ninguno de los días del rango
        esté ocupado (excluyendo opcionalmente la reserva en edición y filtrando por mes/año).
        """
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        dia_ini = _parsear_entero(dia_inicio_bd, minimo=1, maximo=31)
        dias = _parsear_entero(dias_estadia, minimo=1, maximo=31)
        if id_hab is None or dia_ini is None or dias is None or (dia_ini + dias - 1) > 31:
            return False

        excluir_id = None
        if excluir_id_reserva is not None:
            excluir_id = _parsear_entero(excluir_id_reserva, minimo=1, maximo=MAX_INT_UNSIGNED)
            if excluir_id is None:
                return False

        filtro_periodo = ""
        params_periodo = []
        if mes is not None and anio is not None:
            mes_val = _parsear_entero(mes, minimo=1, maximo=12)
            anio_val = _parsear_entero(anio, minimo=2000, maximo=2100)
            if mes_val is None or anio_val is None:
                return False
            filtro_periodo = " AND mes = %s AND anio = %s"
            params_periodo = [mes_val, anio_val]

        conn = None
        try:
            conn = self.conectar()
            cursor = conn.cursor()
            dia_fin_bd = dia_ini + dias - 1
            if excluir_id is None:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM ocupacion_diaria
                    WHERE id_habitacion = %s
                      AND dia_mes BETWEEN %s AND %s
                      AND ocupada = 1{filtro_periodo}
                    """,
                    tuple([id_hab, dia_ini, dia_fin_bd] + params_periodo),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM ocupacion_diaria
                    WHERE id_habitacion = %s
                      AND dia_mes BETWEEN %s AND %s
                      AND ocupada = 1
                      AND (id_reserva IS NULL OR id_reserva != %s){filtro_periodo}
                    """,
                    tuple([id_hab, dia_ini, dia_fin_bd, excluir_id] + params_periodo),
                )
            ocupadas = _extraer_campo(cursor.fetchone(), "COUNT(*)", 0) or 0
            cursor.close()
            return ocupadas == 0
        finally:
            if conn and conn.is_connected():
                conn.close()

    def guardar_reserva_transaccional(self, nueva_reserva, id_habitacion, mes=None, anio=None):
        """
        Guarda de forma atómica (transacción SQL):
        1. Verifica conflicto en 'ocupacion_diaria' con bloqueo FOR UPDATE.
        2. Inserta/actualiza el huésped en 'huespedes'.
        3. Inserta la reserva en 'reservas' y sus snapshots en 'reserva_servicios'.
        4. Marca los días en 'ocupacion_diaria' (ON DUPLICATE KEY UPDATE).
        5. Asigna nueva_reserva.id_reserva tras confirmar el commit.
        """
        if nueva_reserva is None:
            return False
        huesped = getattr(nueva_reserva, "huesped", None)
        if huesped is None or not all(hasattr(huesped, attr) for attr in ("rut", "nombre", "telefono")):
            return False
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        dia_inicio_py = _parsear_entero(getattr(nueva_reserva, "dia_inicio", None), minimo=0, maximo=30)
        dias = _parsear_entero(getattr(nueva_reserva, "dias_estadia", None), minimo=1, maximo=31)
        total_val = _parsear_entero(getattr(nueva_reserva, "total", None), minimo=0, maximo=MAX_INT_UNSIGNED)
        if id_hab is None or dia_inicio_py is None or dias is None or total_val is None:
            return False

        mes_val = _parsear_entero(mes if mes is not None else getattr(nueva_reserva, "mes", None), minimo=1, maximo=12) or 11
        anio_val = _parsear_entero(anio if anio is not None else getattr(nueva_reserva, "anio", None), minimo=2000, maximo=2100) or 2026

        dia_inicio_bd = dia_inicio_py + 1
        dia_fin_bd = dia_inicio_bd + dias - 1
        if dia_fin_bd > 31:
            return False

        conn = None
        try:
            conn = self.conectar()
            conn.start_transaction()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COUNT(*) FROM ocupacion_diaria
                WHERE id_habitacion = %s
                  AND anio = %s
                  AND mes = %s
                  AND dia_mes BETWEEN %s AND %s
                  AND ocupada = 1
                FOR UPDATE
                """,
                (id_hab, anio_val, mes_val, dia_inicio_bd, dia_fin_bd),
            )
            ocupadas = _extraer_campo(cursor.fetchone(), "COUNT(*)", 0) or 0
            if ocupadas > 0:
                conn.rollback()
                cursor.close()
                return False

            cursor.execute(
                """
                INSERT INTO huespedes (rut, nombre, telefono)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    nombre = VALUES(nombre),
                    telefono = VALUES(telefono),
                    id_huesped = LAST_INSERT_ID(id_huesped)
                """,
                (huesped.rut, huesped.nombre, huesped.telefono),
            )
            id_huesped = cursor.lastrowid

            incluye_desayuno = bool(getattr(nueva_reserva, "incluye_desayuno", False))
            incluye_estacionamiento = bool(getattr(nueva_reserva, "incluye_estacionamiento", False))
            servicios_actuales = list(getattr(nueva_reserva, "servicios", []) or [])
            servicios_resueltos = self._resolver_servicios_para_persistencia(
                cursor,
                servicios_actuales,
                dias,
                incluye_desayuno=incluye_desayuno,
                incluye_estacionamiento=incluye_estacionamiento,
            )

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
                    tarifa_base_snapshot,
                    anio,
                    mes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_huesped,
                    id_hab,
                    dia_inicio_bd,
                    dias,
                    1 if incluye_desayuno else 0,
                    1 if incluye_estacionamiento else 0,
                    total_val,
                    getattr(nueva_reserva, "estado", "Confirmada") or "Confirmada",
                    getattr(nueva_reserva, "habitacion_nombre", None),
                    getattr(nueva_reserva, "tipo_alojamiento", None),
                    getattr(nueva_reserva, "tarifa_base_snapshot", None),
                    anio_val,
                    mes_val,
                ),
            )
            id_reserva = cursor.lastrowid

            for srv in servicios_resueltos:
                cursor.execute(
                    """
                    INSERT INTO reserva_servicios (
                        id_reserva,
                        id_servicio,
                        nombre_snapshot,
                        costo_unitario_snapshot,
                        subtotal
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        id_reserva,
                        srv["id_servicio"],
                        srv["nombre"],
                        srv["costo_unitario"],
                        srv["subtotal"],
                    ),
                )

            for d_offset in range(dias):
                dia_mes = dia_inicio_bd + d_offset
                cursor.execute(
                    """
                    INSERT INTO ocupacion_diaria (id_habitacion, anio, mes, dia_mes, ocupada, id_reserva)
                    VALUES (%s, %s, %s, %s, 1, %s)
                    ON DUPLICATE KEY UPDATE
                        ocupada = 1,
                        id_reserva = VALUES(id_reserva)
                    """,
                    (id_hab, anio_val, mes_val, dia_mes, id_reserva),
                )

            conn.commit()
            cursor.close()
            nueva_reserva.id_reserva = id_reserva
            nueva_reserva.mes = mes_val
            nueva_reserva.anio = anio_val
            if not servicios_actuales and servicios_resueltos:
                nueva_reserva.servicios = [dict(s) for s in servicios_resueltos]
            return True
        except (Error, ValueError) as e:
            if conn and conn.is_connected():
                conn.rollback()
            print(f"Error al guardar la reserva en MySQL: {e}")
            return False
        finally:
            if conn and conn.is_connected():
                conn.close()

    def editar_reserva_transaccional(
        self,
        id_reserva,
        id_habitacion,
        dia_inicio_bd,
        dias_estadia,
        monto_total,
        servicios,
        habitacion_nombre=None,
        tipo_alojamiento=None,
        tarifa_base_snapshot=None,
        mes=None,
        anio=None,
    ):
        """
        Actualiza atómicamente una reserva en estado 'Confirmada', revalidando
        disponibilidad excluyendo su propia ocupación y reemplazando sus snapshots de servicios.
        """
        id_res = _parsear_entero(id_reserva, minimo=1, maximo=MAX_INT_UNSIGNED)
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        dia_ini = _parsear_entero(dia_inicio_bd, minimo=1, maximo=31)
        dias = _parsear_entero(dias_estadia, minimo=1, maximo=31)
        total_val = _parsear_entero(monto_total, minimo=0, maximo=MAX_INT_UNSIGNED)

        if id_res is None or id_hab is None or dia_ini is None or dias is None or total_val is None:
            return False, "Parámetros inválidos para editar la reserva."
        dia_fin = dia_ini + dias - 1
        if dia_fin > 31:
            return False, "El rango de días excede el límite del mes (1..31)."

        conn = None
        try:
            conn = self.conectar()
            conn.start_transaction()
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT id_reserva, estado, anio, mes FROM reservas WHERE id_reserva = %s FOR UPDATE",
                (id_res,),
            )
            fila_res = cursor.fetchone()
            if fila_res is None:
                conn.rollback()
                cursor.close()
                return False, "La reserva seleccionada no existe."
            if _extraer_campo(fila_res, "estado", 1) != "Confirmada":
                conn.rollback()
                cursor.close()
                return False, "Solo se pueden editar reservas en estado 'Confirmada'."

            anio_val = _parsear_entero(anio, minimo=2000, maximo=2100) or _parsear_entero(_extraer_campo(fila_res, "anio", 2), minimo=2000, maximo=2100) or 2026
            mes_val = _parsear_entero(mes, minimo=1, maximo=12) or _parsear_entero(_extraer_campo(fila_res, "mes", 3), minimo=1, maximo=12) or 11

            cursor.execute(
                """
                SELECT id_habitacion, tipo, numero_habitacion, tarifa_base_noche, activa
                FROM habitaciones
                WHERE id_habitacion = %s
                FOR UPDATE
                """,
                (id_hab,),
            )
            fila_hab = cursor.fetchone()
            if fila_hab is None or not bool(_extraer_campo(fila_hab, "activa", 4)):
                conn.rollback()
                cursor.close()
                return False, "El alojamiento seleccionado no existe o no está activo."

            hab_nombre_final = (
                habitacion_nombre
                if habitacion_nombre is not None
                else _extraer_campo(fila_hab, "numero_habitacion", 2)
            )
            tipo_aloj_final = (
                tipo_alojamiento
                if tipo_alojamiento is not None
                else _extraer_campo(fila_hab, "tipo", 1)
            )
            tarifa_snap_final = (
                tarifa_base_snapshot
                if tarifa_base_snapshot is not None
                else int(_extraer_campo(fila_hab, "tarifa_base_noche", 3))
            )

            cursor.execute(
                """
                SELECT COUNT(*) AS ocupadas
                FROM ocupacion_diaria
                WHERE id_habitacion = %s
                  AND anio = %s
                  AND mes = %s
                  AND dia_mes BETWEEN %s AND %s
                  AND ocupada = 1
                  AND (id_reserva IS NULL OR id_reserva != %s)
                FOR UPDATE
                """,
                (id_hab, anio_val, mes_val, dia_ini, dia_fin, id_res),
            )
            ocupadas = _extraer_campo(cursor.fetchone(), "ocupadas", 0) or 0
            if ocupadas > 0:
                conn.rollback()
                cursor.close()
                return False, "El alojamiento no está disponible para las fechas seleccionadas."

            servicios_norm = self._resolver_servicios_para_persistencia(
                cursor,
                servicios or [],
                dias,
                incluye_desayuno=False,
                incluye_estacionamiento=False,
            )
            nombres_lower = [s["nombre"].strip().lower() for s in servicios_norm]
            incluye_des = 1 if any("desayuno" in n for n in nombres_lower) else 0
            incluye_est = 1 if any("estacionamiento" in n for n in nombres_lower) else 0

            cursor.execute(
                "DELETE FROM ocupacion_diaria WHERE id_reserva = %s",
                (id_res,),
            )

            cursor.execute(
                """
                UPDATE reservas
                SET id_habitacion = %s,
                    anio = %s,
                    mes = %s,
                    dia_inicio = %s,
                    dias_estadia = %s,
                    incluye_desayuno = %s,
                    incluye_estacionamiento = %s,
                    monto_total = %s,
                    habitacion_nombre = %s,
                    tipo_alojamiento = %s,
                    tarifa_base_snapshot = %s
                WHERE id_reserva = %s
                """,
                (
                    id_hab,
                    anio_val,
                    mes_val,
                    dia_ini,
                    dias,
                    incluye_des,
                    incluye_est,
                    total_val,
                    hab_nombre_final,
                    tipo_aloj_final,
                    tarifa_snap_final,
                    id_res,
                ),
            )

            cursor.execute(
                "DELETE FROM reserva_servicios WHERE id_reserva = %s",
                (id_res,),
            )
            for srv in servicios_norm:
                cursor.execute(
                    """
                    INSERT INTO reserva_servicios (
                        id_reserva,
                        id_servicio,
                        nombre_snapshot,
                        costo_unitario_snapshot,
                        subtotal
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        id_res,
                        srv["id_servicio"],
                        srv["nombre"],
                        srv["costo_unitario"],
                        srv["subtotal"],
                    ),
                )

            for d_offset in range(dias):
                dia_mes = dia_ini + d_offset
                cursor.execute(
                    """
                    INSERT INTO ocupacion_diaria (id_habitacion, anio, mes, dia_mes, ocupada, id_reserva)
                    VALUES (%s, %s, %s, %s, 1, %s)
                    ON DUPLICATE KEY UPDATE
                        ocupada = 1,
                        id_reserva = VALUES(id_reserva)
                    """,
                    (id_hab, anio_val, mes_val, dia_mes, id_res),
                )

            conn.commit()
            cursor.close()
            return True, "Reserva actualizada exitosamente."
        except (Error, ValueError) as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, f"Error al editar reserva en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    def cancelar_reserva_transaccional(self, id_reserva):
        """
        Cancela lógicamente una reserva (estado = 'Cancelada') y libera sus días
        en 'ocupacion_diaria', conservando intacto el registro histórico y sus servicios.
        """
        id_res = _parsear_entero(id_reserva, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_res is None:
            return False, "Identificador de reserva inválido."

        conn = None
        try:
            conn = self.conectar()
            conn.start_transaction()
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT id_reserva, estado FROM reservas WHERE id_reserva = %s FOR UPDATE",
                (id_res,),
            )
            fila_res = cursor.fetchone()
            if fila_res is None:
                conn.rollback()
                cursor.close()
                return False, "La reserva seleccionada no existe."
            if _extraer_campo(fila_res, "estado", 1) != "Confirmada":
                conn.rollback()
                cursor.close()
                return False, "Solo se pueden cancelar reservas en estado 'Confirmada'."

            cursor.execute(
                "UPDATE reservas SET estado = 'Cancelada' WHERE id_reserva = %s",
                (id_res,),
            )
            cursor.execute(
                "DELETE FROM ocupacion_diaria WHERE id_reserva = %s",
                (id_res,),
            )

            conn.commit()
            cursor.close()
            return True, "Reserva cancelada exitosamente."
        except Error as e:
            if conn and conn.is_connected():
                conn.rollback()
            return False, f"Error al cancelar reserva en MySQL: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

