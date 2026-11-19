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
    MAX_INTENTOS_LOGIN = 3
    TIPOS_ALOJAMIENTO = ("Habitación", "Cabaña")

    def __init__(self, db=None):
        self.db = db if db is not None else ConexionDB()

        # Vectores paralelos (valores por defecto si la tabla aún no ha sido leída)
        self.ids_habitaciones = [1, 2, 3, 4]
        self.tipos_habitaciones = ["Habitación", "Habitación", "Habitación", "Habitación"]
        self.habitaciones = ["101", "102", "103", "104"]
        self.tarifas = [45000, 45000, 60000, 70000]

        # Matriz de disponibilidad: 4 habitaciones x 30 días (0: Libre, 1: Ocupada)
        self.dias_mes = 30
        self.matriz_disponibilidad = [
            [0 for _ in range(self.dias_mes)] for _ in range(len(self.habitaciones))
        ]

        self.reservas = []
        self.usuario_actual = None
        self._esquema_inicializado = False
        self.cargar_datos()

    def _leer_entrada(self, prompt):
        """Lee entrada de consola protegiendo EOFError, KeyboardInterrupt y ValueError."""
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            print("\nEntrada cancelada o finalizada por el usuario.")
            return None
        except ValueError:
            print("Error: Entrada inválida.")
            return None

    def _leer_texto(self, prompt, permitir_vacio=False, max_len=None):
        """Solicita una cadena de texto validada. Retorna None si hay EOF/Ctrl+C."""
        while True:
            raw = self._leer_entrada(prompt)
            if raw is None:
                return None
            valor = raw.strip()
            if not valor:
                if permitir_vacio:
                    return ""
                print("Error: Este campo no puede estar vacío.")
                continue
            if max_len is not None and len(valor) > max_len:
                print(f"Error: El texto no puede superar los {max_len} caracteres.")
                continue
            return valor

    def _leer_entero(self, prompt, minimo=None, maximo=None, default=None):
        """Solicita un número entero validando rango. Retorna None si hay EOF/Ctrl+C."""
        while True:
            raw = self._leer_entrada(prompt)
            if raw is None:
                return None
            texto = raw.strip()
            if not texto and default is not None:
                return default
            try:
                valor = int(texto)
            except ValueError:
                print("Error: Ingrese un valor numérico entero válido.")
                continue
            if minimo is not None and valor < minimo:
                print(f"Error: El valor debe ser mayor o igual a {minimo}.")
                continue
            if maximo is not None and valor > maximo:
                print(f"Error: El valor debe ser menor o igual a {maximo}.")
                continue
            return valor

    def _leer_si_no(self, prompt):
        """Solicita confirmación (s/n). Retorna bool o None si hay EOF/Ctrl+C."""
        while True:
            raw = self._leer_entrada(prompt)
            if raw is None:
                return None
            resp = raw.strip().lower()
            if resp in ("s", "si", "sí"):
                return True
            if resp in ("n", "no"):
                return False
            print("Error: Responda 's' para sí o 'n' para no.")

    def _es_admin(self):
        """Retorna True si hay sesión iniciada con rol 'admin'."""
        return bool(self.usuario_actual and self.usuario_actual.get("rol") == "admin")

    def cargar_datos(self):
        """
        Carga los vectores paralelos (habitaciones, tipos y tarifas), la matriz de disponibilidad
        y las reservas activas directamente desde la base de datos MySQL (nexopms_db).
        """
        try:
            if not self._esquema_inicializado and hasattr(self.db, "asegurar_esquema"):
                self.db.asegurar_esquema()
                self._esquema_inicializado = True

            # 1. Poblar vectores paralelos desde la tabla 'habitaciones'
            filas_hab = self.db.obtener_habitaciones_y_tarifas()
            if filas_hab is not None:
                self.ids_habitaciones = [f["id_habitacion"] for f in filas_hab]
                self.tipos_habitaciones = [str(f.get("tipo") or "Habitación") for f in filas_hab]
                self.habitaciones = [str(f["numero_habitacion"]) for f in filas_hab]
                self.tarifas = [int(f["tarifa_base_noche"]) for f in filas_hab]

            # Reiniciar matriz y lista de reservas en memoria antes de consultar ocupación/reservas
            self.matriz_disponibilidad = [
                [0 for _ in range(self.dias_mes)] for _ in range(len(self.habitaciones))
            ]
            self.reservas = []

            # 2. Poblar la matriz desde la tabla 'ocupacion_diaria'
            filas_ocupacion = self.db.obtener_ocupacion_diaria()
            for reg in filas_ocupacion:
                if reg["id_habitacion"] in self.ids_habitaciones:
                    hab_idx = self.ids_habitaciones.index(reg["id_habitacion"])
                    dia_idx = int(reg["dia_mes"]) - 1
                    if 0 <= dia_idx < self.dias_mes:
                        self.matriz_disponibilidad[hab_idx][dia_idx] = 1 if reg["ocupada"] else 0

            # 3. Reconstruir objetos Huesped y Reserva desde las tablas 'reservas' y 'huespedes'
            filas_reservas = self.db.obtener_reservas_activas()
            for r in filas_reservas:
                if r["id_habitacion"] not in self.ids_habitaciones:
                    print(
                        f"Aviso: Reserva #{r.get('id_reserva', '?')} referencia un alojamiento "
                        f"inactivo o inexistente (ID {r['id_habitacion']})."
                    )
                    continue

                hab_idx = self.ids_habitaciones.index(r["id_habitacion"])
                huesped = Huesped(r["rut"], r["nombre"], r["telefono"])
                reserva = Reserva(
                    huesped=huesped,
                    habitacion_idx=hab_idx,
                    dia_inicio=int(r["dia_inicio"]) - 1,
                    dias_estadia=int(r["dias_estadia"]),
                    total=int(r["monto_total"]),
                    incluye_desayuno=bool(r["incluye_desayuno"]),
                    incluye_estacionamiento=bool(r["incluye_estacionamiento"]),
                    estado=r["estado"],
                    habitacion_nombre=r.get("habitacion_nombre"),
                    tipo_alojamiento=r.get("tipo_alojamiento"),
                    tarifa_base_snapshot=r.get("tarifa_base_snapshot"),
                )
                self.reservas.append(reserva)

        except Exception as e:
            print(f"Aviso al sincronizar con MySQL: {e}")

    def iniciar_sesion(self):
        """
        Solicita credenciales de inicio de sesión con un máximo de intentos fallidos.
        Retorna True si la autenticación tiene éxito, False en caso contrario.
        """
        try:
            if hasattr(self.db, "asegurar_esquema"):
                self.db.asegurar_esquema()
                self._esquema_inicializado = True
        except Exception as e:
            print(f"Aviso al inicializar esquema de usuarios: {e}")

        print("\n=== INICIO DE SESIÓN — NEXOPMS ===")
        for intento in range(1, self.MAX_INTENTOS_LOGIN + 1):
            username = self._leer_texto("Usuario: ")
            if username is None:
                return False

            password = self._leer_texto("Contraseña: ")
            if password is None:
                return False

            try:
                usuario = self.db.autenticar_usuario(username, password)
            except Exception as e:
                print(f"Error al validar credenciales: {e}")
                usuario = None

            if usuario is not None:
                self.usuario_actual = usuario
                print(f"Bienvenido/a, {usuario['username']} (Rol: {usuario['rol']}).")
                return True

            restantes = self.MAX_INTENTOS_LOGIN - intento
            if restantes > 0:
                print(f"Credenciales inválidas. Intentos restantes: {restantes}.")
            else:
                print("Máximo de intentos fallidos alcanzado. Saliendo del sistema...")

        return False

    def mostrar_matriz_disponibilidad(self):
        """Muestra en consola la matriz de ocupación del mes en bloques de 15 días."""
        print(f"\n--- MATRIZ DE DISPONIBILIDAD ({self.dias_mes} Días) ---")
        if not self.habitaciones:
            print("No hay habitaciones ni cabañas registradas.\n")
            return

        dias_por_bloque = 15
        ancho_col = max(6, max((len(h) for h in self.habitaciones), default=6))

        for inicio_bloque in range(0, self.dias_mes, dias_por_bloque):
            fin_bloque = min(inicio_bloque + dias_por_bloque, self.dias_mes)
            rango_dias = range(inicio_bloque, fin_bloque)

            print(f"\n[Días {inicio_bloque + 1:02d} al {fin_bloque:02d}]")
            encabezado = f"{'Habit.':^{ancho_col}} | " + " | ".join([f"D{d + 1:02d}" for d in rango_dias])
            separador = "-" * len(encabezado)
            print(encabezado)
            print(separador)

            for i, hab in enumerate(self.habitaciones):
                estado_dias = " | ".join(
                    ["[X]" if self.matriz_disponibilidad[i][d] == 1 else "[ ]" for d in rango_dias]
                )
                print(f"{hab:^{ancho_col}} | {estado_dias}")
            print(separador)

        print("[ ] = Libre  |  [X] = Ocupada\n")

    def consultar_tarifas(self):
        """Muestra las tarifas base de habitaciones/cabañas y servicios adicionales."""
        print("\n--- TARIFARIO BASE Y SERVICIOS ADICIONALES ---")
        if not self.habitaciones:
            print("No hay alojamientos registrados.")
        else:
            for i, hab in enumerate(self.habitaciones):
                tipo = self.tipos_habitaciones[i] if i < len(self.tipos_habitaciones) else "Habitación"
                print(f"{tipo} {hab}: ${self.tarifas[i]:,} / noche")
        print("-" * 46)
        print(f"Servicio Desayuno       : ${self.COSTO_DESAYUNO_NOCHE:,} / noche")
        print(f"Servicio Estacionamiento: ${self.COSTO_ESTACIONAMIENTO_NOCHE:,} / noche")
        print("----------------------------------------------\n")

    def confirmar_y_guardar_reserva(self, nueva_reserva, hab_idx, dia_inicio, dias_estadia):
        """
        Subproceso TO-BE: Doble validación de disponibilidad en la matriz en memoria
        y en la tabla 'ocupacion_diaria' de MySQL justo antes de persistir la transacción.
        """
        if not (0 <= hab_idx < len(self.ids_habitaciones)):
            print("Error de validación: Índice de alojamiento fuera de rango.")
            return False

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

        # Asegurar snapshot de datos del alojamiento al momento de reservar
        if nueva_reserva.habitacion_nombre is None:
            nueva_reserva.habitacion_nombre = self.habitaciones[hab_idx]
        if nueva_reserva.tipo_alojamiento is None:
            nueva_reserva.tipo_alojamiento = (
                self.tipos_habitaciones[hab_idx]
                if hab_idx < len(self.tipos_habitaciones)
                else "Habitación"
            )
        if nueva_reserva.tarifa_base_snapshot is None:
            nueva_reserva.tarifa_base_snapshot = self.tarifas[hab_idx]

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

    def _buscar_indice_alojamiento(self, identificador):
        """Busca un alojamiento por coincidencia exacta o insensible a mayúsculas."""
        if identificador in self.habitaciones:
            return self.habitaciones.index(identificador)
        ident_lower = identificador.strip().lower()
        for idx, hab in enumerate(self.habitaciones):
            if hab.strip().lower() == ident_lower:
                return idx
        return None

    def registrar_reserva(self):
        """Flujo de consola para cotizar y registrar una nueva reserva."""
        print("\n--- NUEVA RESERVA ---")
        self.cargar_datos()
        self.mostrar_matriz_disponibilidad()
        if not self.habitaciones:
            return

        hab_num = self._leer_texto("Ingrese el número de habitación o cabaña (ej. 101): ", max_len=50)
        if hab_num is None:
            return

        hab_idx = self._buscar_indice_alojamiento(hab_num)
        if hab_idx is None:
            print("Error: Habitación o cabaña no existe.")
            return

        hab_nombre = self.habitaciones[hab_idx]
        tipo_hab = self.tipos_habitaciones[hab_idx]

        dia_ingresado = self._leer_entero(
            f"Día de ingreso (1-{self.dias_mes}): ",
            minimo=1,
            maximo=self.dias_mes
        )
        if dia_ingresado is None:
            return
        dia_inicio = dia_ingresado - 1

        dias_estadia = self._leer_entero("Cantidad de noches: ", minimo=1, maximo=self.dias_mes)
        if dias_estadia is None:
            return

        # Validar límites y disponibilidad inicial en la matriz
        if dia_inicio < 0 or dia_inicio + dias_estadia > self.dias_mes:
            print("Error: Las fechas exceden el calendario actual.")
            return

        for d in range(dia_inicio, dia_inicio + dias_estadia):
            if self.matriz_disponibilidad[hab_idx][d] == 1:
                print("Error: El alojamiento está ocupado en las fechas seleccionadas.")
                return

        # Si hay disponibilidad, pedir datos del huésped
        rut = self._leer_texto("RUT del huésped: ", max_len=12)
        if rut is None:
            return
        nombre = self._leer_texto("Nombre del huésped: ", max_len=100)
        if nombre is None:
            return
        telefono = self._leer_texto("Teléfono: ", max_len=20)
        if telefono is None:
            return

        # Compuerta Inclusiva (OR): Servicios adicionales
        print("\n--- SERVICIOS ADICIONALES (Opcionales) ---")
        incluye_desayuno = self._leer_si_no(
            f"¿Desea incluir Desayuno (${self.COSTO_DESAYUNO_NOCHE:,}/noche)? (s/n): "
        )
        if incluye_desayuno is None:
            return

        incluye_estacionamiento = self._leer_si_no(
            f"¿Desea incluir Estacionamiento (${self.COSTO_ESTACIONAMIENTO_NOCHE:,}/noche)? (s/n): "
        )
        if incluye_estacionamiento is None:
            return

        # Cálculo de tarifa según fórmula: (Tarifa_Base + Costo_Desayuno + Costo_Estacionamiento) * Noches_Estadia
        tarifa_base = self.tarifas[hab_idx]
        costo_desayuno = self.COSTO_DESAYUNO_NOCHE if incluye_desayuno else 0
        costo_estacionamiento = self.COSTO_ESTACIONAMIENTO_NOCHE if incluye_estacionamiento else 0
        tarifa_diaria_total = tarifa_base + costo_desayuno + costo_estacionamiento
        costo_total = tarifa_diaria_total * dias_estadia

        print("\n--- RESUMEN DE COTIZACIÓN ---")
        print(f"{tipo_hab} {hab_nombre} (Tarifa base): ${tarifa_base:,} / noche")
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

        confirmar = self._leer_si_no("\n¿Confirmar reserva? (s/n): ")
        if confirmar is True:
            nuevo_huesped = Huesped(rut, nombre, telefono)
            nueva_reserva = Reserva(
                nuevo_huesped,
                hab_idx,
                dia_inicio,
                dias_estadia,
                costo_total,
                incluye_desayuno=incluye_desayuno,
                incluye_estacionamiento=incluye_estacionamiento,
                estado="Confirmada",
                habitacion_nombre=hab_nombre,
                tipo_alojamiento=tipo_hab,
                tarifa_base_snapshot=tarifa_base,
            )
            self.confirmar_y_guardar_reserva(nueva_reserva, hab_idx, dia_inicio, dias_estadia)
        else:
            print("Reserva cancelada.")

    def ver_reservas_activas(self):
        """Lista todas las reservas registradas en la base de datos MySQL."""
        self.cargar_datos()
        print("\n--- RESERVAS ACTIVAS (MySQL) ---")
        if not self.reservas:
            print("No hay reservas registradas.")
            return

        for r in self.reservas:
            if r.habitacion_nombre is not None:
                hab_num = r.habitacion_nombre
            elif 0 <= r.habitacion_idx < len(self.habitaciones):
                hab_num = self.habitaciones[r.habitacion_idx]
            else:
                hab_num = f"ID#{r.habitacion_idx}"

            if r.tipo_alojamiento is not None:
                tipo_hab = r.tipo_alojamiento
            elif 0 <= r.habitacion_idx < len(self.tipos_habitaciones):
                tipo_hab = self.tipos_habitaciones[r.habitacion_idx]
            else:
                tipo_hab = "Habitación"

            servicios = []
            if r.incluye_desayuno:
                servicios.append("Desayuno")
            if r.incluye_estacionamiento:
                servicios.append("Estacionamiento")
            texto_servicios = ", ".join(servicios) if servicios else "Ninguno"

            print(
                f"Estado: [{r.estado}] | Huésped: {r.huesped.nombre} (RUT: {r.huesped.rut}) | "
                f"{tipo_hab}: {hab_num} | Ingreso: Día {r.dia_inicio + 1} | Noches: {r.dias_estadia} | "
                f"Servicios: {texto_servicios} | Total: ${r.total:,}"
            )
        print("--------------------------------\n")

    def _listar_alojamientos(self):
        """Muestra la lista numerada de habitaciones y cabañas registradas."""
        print("\n--- ALOJAMIENTOS REGISTRADOS ---")
        if not self.habitaciones:
            print("No hay alojamientos registrados.")
            return
        for idx, hab in enumerate(self.habitaciones, start=1):
            tipo = self.tipos_habitaciones[idx - 1]
            tarifa = self.tarifas[idx - 1]
            print(f"{idx}. [{tipo}] {hab} — ${tarifa:,} / noche")

    def _seleccionar_tipo_alojamiento(self, permitir_vacio=False, actual=None):
        """Solicita el tipo de alojamiento ('Habitación' o 'Cabaña')."""
        print("Tipos disponibles: 1. Habitación | 2. Cabaña")
        prompt = (
            f"Tipo de alojamiento [{actual}] (Enter para mantener): "
            if permitir_vacio and actual
            else "Seleccione el tipo (1: Habitación, 2: Cabaña): "
        )
        while True:
            raw = self._leer_entrada(prompt)
            if raw is None:
                return None
            texto = raw.strip().lower()
            if not texto and permitir_vacio and actual:
                return actual
            if texto in ("1", "habitacion", "habitación"):
                return "Habitación"
            if texto in ("2", "cabana", "cabaña"):
                return "Cabaña"
            print("Error: Seleccione '1' (Habitación) o '2' (Cabaña).")

    def agregar_alojamiento(self):
        """Agrega una nueva Habitación o Cabaña en BD y sincroniza vectores y matriz."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return

        print("\n--- AGREGAR HABITACIÓN O CABAÑA ---")
        tipo = self._seleccionar_tipo_alojamiento()
        if tipo is None:
            return

        identificador = self._leer_texto(
            "Identificador / número (ej. 105 o Cabaña 1): ",
            max_len=50
        )
        if identificador is None:
            return

        if any(h.strip().lower() == identificador.lower() for h in self.habitaciones):
            print(f"Error: Ya existe un alojamiento con el identificador '{identificador}'.")
            return

        tarifa = self._leer_entero("Tarifa base por noche ($): ", minimo=1, maximo=4294967295)
        if tarifa is None:
            return

        try:
            exito, nuevo_id, msg = self.db.agregar_habitacion(tipo, identificador, tarifa)
        except Exception as e:
            print(f"Error al guardar alojamiento: {e}")
            return

        if not exito or nuevo_id is None:
            print(f"Error: {msg}")
            return

        self.ids_habitaciones.append(nuevo_id)
        self.tipos_habitaciones.append(tipo)
        self.habitaciones.append(identificador)
        self.tarifas.append(tarifa)
        self.matriz_disponibilidad.append([0 for _ in range(self.dias_mes)])
        print(msg)

    def editar_alojamiento(self):
        """Edita tipo, identificador o tarifa base sin alterar reservas ya existentes."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return

        print("\n--- EDITAR HABITACIÓN O CABAÑA ---")
        if not self.habitaciones:
            print("No hay alojamientos registrados.")
            return

        self._listar_alojamientos()
        seleccion = self._leer_entero(
            f"Seleccione el número de lista a editar (1-{len(self.habitaciones)}, 0 para cancelar): ",
            minimo=0,
            maximo=len(self.habitaciones)
        )
        if seleccion is None or seleccion == 0:
            return

        idx = seleccion - 1
        id_hab = self.ids_habitaciones[idx]
        tipo_actual = self.tipos_habitaciones[idx]
        ident_actual = self.habitaciones[idx]
        tarifa_actual = self.tarifas[idx]

        nuevo_tipo = self._seleccionar_tipo_alojamiento(permitir_vacio=True, actual=tipo_actual)
        if nuevo_tipo is None:
            return

        nuevo_ident = self._leer_texto(
            f"Nuevo identificador [{ident_actual}] (Enter para mantener): ",
            permitir_vacio=True,
            max_len=50
        )
        if nuevo_ident is None:
            return
        if not nuevo_ident:
            nuevo_ident = ident_actual

        if any(
            i != idx and h.strip().lower() == nuevo_ident.lower()
            for i, h in enumerate(self.habitaciones)
        ):
            print(f"Error: Ya existe otro alojamiento con el identificador '{nuevo_ident}'.")
            return

        nueva_tarifa = self._leer_entero(
            f"Nueva tarifa base [${tarifa_actual:,}] (Enter para mantener): ",
            minimo=1,
            maximo=4294967295,
            default=tarifa_actual
        )
        if nueva_tarifa is None:
            return

        try:
            exito, msg = self.db.editar_habitacion(id_hab, nuevo_tipo, nuevo_ident, nueva_tarifa)
        except Exception as e:
            print(f"Error al actualizar alojamiento: {e}")
            return

        if not exito:
            print(f"Error: {msg}")
            return

        self.tipos_habitaciones[idx] = nuevo_tipo
        self.habitaciones[idx] = nuevo_ident
        self.tarifas[idx] = nueva_tarifa
        print(msg)

    def eliminar_alojamiento(self):
        """
        Elimina un alojamiento si no posee reservas activas ni días ocupados,
        manteniendo consistentes los vectores, la matriz y los habitacion_idx restantes.
        """
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return

        print("\n--- ELIMINAR HABITACIÓN O CABAÑA ---")
        if not self.habitaciones:
            print("No hay alojamientos registrados.")
            return

        self._listar_alojamientos()
        seleccion = self._leer_entero(
            f"Seleccione el número de lista a eliminar (1-{len(self.habitaciones)}, 0 para cancelar): ",
            minimo=0,
            maximo=len(self.habitaciones)
        )
        if seleccion is None or seleccion == 0:
            return

        idx = seleccion - 1
        id_hab = self.ids_habitaciones[idx]
        nombre_hab = self.habitaciones[idx]

        tiene_ocupacion = any(celda == 1 for celda in self.matriz_disponibilidad[idx])
        tiene_reservas = any(
            r.habitacion_idx == idx and r.estado == "Confirmada"
            for r in self.reservas
        )
        if tiene_ocupacion or tiene_reservas:
            print(
                f"No se puede eliminar '{nombre_hab}': tiene reservas activas o días ocupados registrados."
            )
            return

        try:
            exito, msg = self.db.eliminar_habitacion(id_hab)
        except Exception as e:
            print(f"Error al eliminar alojamiento: {e}")
            return

        if not exito:
            print(f"Error: {msg}")
            return

        self.ids_habitaciones.pop(idx)
        self.tipos_habitaciones.pop(idx)
        self.habitaciones.pop(idx)
        self.tarifas.pop(idx)
        self.matriz_disponibilidad.pop(idx)

        for r in self.reservas:
            if r.habitacion_idx > idx:
                r.habitacion_idx -= 1

        print(msg)

    def menu_administracion(self):
        """Submenú exclusivo para administradores para gestionar habitaciones y cabañas."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return

        while True:
            print("\n--- MÓDULO DE ADMINISTRACIÓN (HABITACIONES / CABAÑAS) ---")
            print("1. Listar habitaciones y cabañas")
            print("2. Agregar habitación o cabaña")
            print("3. Editar habitación o cabaña")
            print("4. Eliminar habitación o cabaña")
            print("5. Volver al menú principal")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                return
            opcion = raw.strip()

            if opcion == "1":
                self.cargar_datos()
                self._listar_alojamientos()
            elif opcion == "2":
                self.agregar_alojamiento()
            elif opcion == "3":
                self.editar_alojamiento()
            elif opcion == "4":
                self.eliminar_alojamiento()
            elif opcion == "5":
                return
            else:
                print("Opción inválida. Intente nuevamente.")

    def iniciar(self):
        """Menú principal interactivo en consola con control de acceso por rol."""
        if self.usuario_actual is None:
            if not self.iniciar_sesion():
                return

        while True:
            rol = self.usuario_actual.get("rol", "recepcionista")
            username = self.usuario_actual.get("username", "")

            print(f"\n=== SISTEMA NEXOPMS (MySQL) === [Usuario: {username} | Rol: {rol}]")
            print("1. Consultar matriz de disponibilidad")
            print("2. Consultar tarifas")
            print("3. Registrar nueva reserva (Cotizar y Confirmar)")
            print("4. Ver reservas activas")

            if rol == "admin":
                print("5. Módulo de Administración (Gestionar Habitaciones / Cabañas)")
                print("6. Cerrar sesión / Cambiar de usuario")
                print("7. Salir")
            else:
                print("5. Cerrar sesión / Cambiar de usuario")
                print("6. Salir")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                print("Cerrando NexoPMS... ¡Hasta pronto!")
                break
            opcion = raw.strip()

            if opcion == "1":
                self.cargar_datos()
                self.mostrar_matriz_disponibilidad()
            elif opcion == "2":
                self.consultar_tarifas()
            elif opcion == "3":
                self.registrar_reserva()
            elif opcion == "4":
                self.ver_reservas_activas()
            elif rol == "admin" and opcion == "5":
                self.menu_administracion()
            elif (rol == "admin" and opcion == "6") or (rol != "admin" and opcion == "5"):
                print(f"Cerrando sesión de '{username}'...")
                self.usuario_actual = None
                if not self.iniciar_sesion():
                    break
            elif (rol == "admin" and opcion == "7") or (rol != "admin" and opcion == "6"):
                print("Cerrando NexoPMS... ¡Hasta pronto!")
                break
            else:
                print("Opción inválida. Intente nuevamente.")


if __name__ == "__main__":
    sistema = NexoPMS()
    sistema.iniciar()
