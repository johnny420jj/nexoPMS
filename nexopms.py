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

        # Vectores paralelos de alojamientos (valores por defecto si la tabla aún no ha sido leída)
        self.ids_habitaciones = [1, 2, 3, 4]
        self.tipos_habitaciones = ["Habitación", "Habitación", "Habitación", "Habitación"]
        self.habitaciones = ["101", "102", "103", "104"]
        self.tarifas = [45000, 45000, 60000, 70000]

        # Vectores paralelos de servicios adicionales (respaldo si la BD aún no responde)
        self.servicios_ids = [1, 2]
        self.servicios_nombres = ["Desayuno", "Estacionamiento"]
        self.servicios_costos = [self.COSTO_DESAYUNO_NOCHE, self.COSTO_ESTACIONAMIENTO_NOCHE]
        self.servicios_disponibles = [True, True]

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

    def _es_gerente(self):
        """Retorna True si hay sesión iniciada con rol 'gerente'."""
        return bool(self.usuario_actual and self.usuario_actual.get("rol") == "gerente")

    def _es_recepcionista(self):
        """Retorna True si hay sesión iniciada con rol 'recepcionista'."""
        return bool(self.usuario_actual and self.usuario_actual.get("rol") == "recepcionista")

    def _puede_ver_reportes(self):
        """Retorna True si el usuario actual es 'admin' o 'gerente' (o uso programático sin sesión)."""
        if self.usuario_actual is None:
            return True
        return self.usuario_actual.get("rol") in ("admin", "gerente")

    def _puede_registrar_reserva(self):
        """Retorna True si el usuario actual puede registrar reservas ('recepcionista' o 'admin')."""
        if self.usuario_actual is None:
            return True
        return self.usuario_actual.get("rol") in ("admin", "recepcionista")

    def sincronizar_servicios(self):
        """Sincroniza los vectores paralelos del catálogo de servicios desde la base de datos."""
        if not hasattr(self.db, "obtener_servicios"):
            return False
        try:
            filas_srv = self.db.obtener_servicios(solo_disponibles=False)
            if isinstance(filas_srv, list):
                ids_tmp = []
                nombres_tmp = []
                costos_tmp = []
                disp_tmp = []
                for s in filas_srv:
                    ids_tmp.append(int(s["id_servicio"]))
                    nombres_tmp.append(str(s["nombre"]))
                    costos_tmp.append(int(s["costo"]))
                    disp_tmp.append(bool(s["disponible"]))
                self.servicios_ids = ids_tmp
                self.servicios_nombres = nombres_tmp
                self.servicios_costos = costos_tmp
                self.servicios_disponibles = disp_tmp
                return True
        except Exception:
            return False
        return False

    def cargar_datos(self):
        """
        Carga los vectores paralelos (habitaciones, tipos, tarifas y servicios), la matriz de
        disponibilidad y las reservas activas directamente desde la base de datos MySQL (nexopms_db).
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

            # 1b. Sincronizar vectores paralelos del catálogo de servicios
            self.sincronizar_servicios()

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
                    id_reserva=r.get("id_reserva"),
                    servicios=r.get("servicios") or None,
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
        """Muestra las tarifas base de habitaciones/cabañas y servicios adicionales disponibles."""
        self.sincronizar_servicios()
        print("\n--- TARIFARIO BASE Y SERVICIOS ADICIONALES ---")
        if not self.habitaciones:
            print("No hay alojamientos registrados.")
        else:
            for i, hab in enumerate(self.habitaciones):
                tipo = self.tipos_habitaciones[i] if i < len(self.tipos_habitaciones) else "Habitación"
                print(f"{tipo} {hab}: ${self.tarifas[i]:,} / noche")
        print("-" * 46)
        servicios_activos = [
            (nombre, costo)
            for nombre, costo, disponible in zip(
                self.servicios_nombres, self.servicios_costos, self.servicios_disponibles
            )
            if disponible
        ]
        if servicios_activos:
            for nombre, costo in servicios_activos:
                print(f"Servicio {nombre:<15}: ${costo:,} / noche")
        else:
            print("No hay servicios adicionales disponibles.")
        print("----------------------------------------------\n")

    def confirmar_y_guardar_reserva(self, nueva_reserva, hab_idx, dia_inicio, dias_estadia):
        """
        Subproceso TO-BE: Doble validación de disponibilidad en la matriz en memoria
        y en la tabla 'ocupacion_diaria' de MySQL justo antes de persistir la transacción.
        """
        if not (0 <= hab_idx < len(self.ids_habitaciones)):
            print("Error de validación: Índice de alojamiento fuera de rango.")
            return False
        if dia_inicio < 0 or dias_estadia < 1 or dia_inicio + dias_estadia > self.dias_mes:
            print("Error de validación: Rango de fechas fuera de los límites del calendario.")
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
        """Flujo de consola para cotizar y registrar una nueva reserva con servicios dinámicos."""
        if not self._puede_registrar_reserva():
            print("Acceso denegado: el rol gerente no está autorizado para registrar nuevas reservas.")
            return

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

        # Selección dinámica de servicios adicionales habilitados en el catálogo
        print("\n--- SERVICIOS ADICIONALES (Opcionales) ---")
        servicios_disponibles_idx = [
            i for i, disp in enumerate(self.servicios_disponibles) if disp
        ]
        servicios_seleccionados = []
        if not servicios_disponibles_idx:
            print("No hay servicios adicionales disponibles en este momento.")
        else:
            for i in servicios_disponibles_idx:
                nombre_srv = self.servicios_nombres[i]
                costo_srv = self.servicios_costos[i]
                incluir = self._leer_si_no(
                    f"¿Desea incluir {nombre_srv} (${costo_srv:,}/noche)? (s/n): "
                )
                if incluir is None:
                    return
                if incluir:
                    servicios_seleccionados.append({
                        "id_servicio": self.servicios_ids[i],
                        "nombre": nombre_srv,
                        "costo_unitario": costo_srv,
                        "subtotal": costo_srv * dias_estadia,
                    })

        # Cálculo de tarifa: (Tarifa_Base + Sum(Costos_Servicios)) * Noches_Estadia
        tarifa_base = self.tarifas[hab_idx]
        costo_servicios_noche = sum(s["costo_unitario"] for s in servicios_seleccionados)
        tarifa_diaria_total = tarifa_base + costo_servicios_noche
        costo_total = tarifa_diaria_total * dias_estadia

        print("\n--- RESUMEN DE COTIZACIÓN ---")
        print(f"{tipo_hab} {hab_nombre} (Tarifa base): ${tarifa_base:,} / noche")
        if servicios_seleccionados:
            for s in servicios_seleccionados:
                print(
                    f"{s['nombre']:<29}: "
                    f"Sí (${s['costo_unitario']:,}/noche | Subtotal: ${s['subtotal']:,})"
                )
        else:
            print("Servicios adicionales        : Ninguno ($0)")
        print(
            f"Fórmula: (${tarifa_base:,} + ${costo_servicios_noche:,}) "
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
                estado="Confirmada",
                habitacion_nombre=hab_nombre,
                tipo_alojamiento=tipo_hab,
                tarifa_base_snapshot=tarifa_base,
                servicios=servicios_seleccionados,
            )
            self.confirmar_y_guardar_reserva(nueva_reserva, hab_idx, dia_inicio, dias_estadia)
        else:
            print("Reserva cancelada.")

    def _formatear_servicios_reserva(self, reserva):
        """Obtiene la representación legible de servicios contratados (con respaldo heredado)."""
        servicios_nombres = [
            str(s["nombre"])
            for s in (getattr(reserva, "servicios", None) or [])
            if s.get("nombre")
        ]
        if not servicios_nombres:
            if getattr(reserva, "incluye_desayuno", False):
                servicios_nombres.append("Desayuno")
            if getattr(reserva, "incluye_estacionamiento", False):
                servicios_nombres.append("Estacionamiento")
        return ", ".join(servicios_nombres) if servicios_nombres else "Ninguno"

    def ver_reservas_activas(self):
        """Lista todas las reservas activas registradas en la base de datos MySQL."""
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

            texto_servicios = self._formatear_servicios_reserva(r)
            prefijo_id = f"ID #{r.id_reserva} | " if getattr(r, "id_reserva", None) is not None else ""

            print(
                f"{prefijo_id}Estado: [{r.estado}] | Huésped: {r.huesped.nombre} (RUT: {r.huesped.rut}) | "
                f"{tipo_hab}: {hab_num} | Ingreso: Día {r.dia_inicio + 1} | Noches: {r.dias_estadia} | "
                f"Servicios: {texto_servicios} | Total: ${r.total:,}"
            )
        print("--------------------------------\n")

    @staticmethod
    def _es_entero_estricto(valor):
        """Retorna True si valor es int (excluyendo bool y float)."""
        return isinstance(valor, int) and not isinstance(valor, bool)

    def _sintetizar_servicios_legacy(self, reserva):
        """Reconstruye servicios desde flags heredados cuando una reserva previa no tiene lista."""
        sintetizados = []
        for id_srv, nombre, costo in zip(
            self.servicios_ids, self.servicios_nombres, self.servicios_costos
        ):
            nl = nombre.strip().lower()
            incluir = (
                (getattr(reserva, "incluye_desayuno", False) and "desayuno" in nl)
                or (getattr(reserva, "incluye_estacionamiento", False) and "estacionamiento" in nl)
            )
            if incluir:
                sintetizados.append({
                    "id_servicio": id_srv,
                    "nombre": nombre,
                    "costo_unitario": costo,
                    "subtotal": costo * reserva.dias_estadia,
                })
        return sintetizados

    def _normalizar_servicios_edicion(self, servicios_base, dias_final):
        """Normaliza, deduplica y recalcula subtotales de servicios para una edición de reserva."""
        if not isinstance(servicios_base, (list, tuple)):
            raise ValueError("El listado de servicios debe ser una lista o tupla.")

        resueltos = []
        vistos = set()
        for item in servicios_base:
            if self._es_entero_estricto(item):
                if item not in self.servicios_ids:
                    raise ValueError(f"El servicio con ID {item} no existe en el catálogo.")
                idx = self.servicios_ids.index(item)
                id_srv = self.servicios_ids[idx]
                nombre = self.servicios_nombres[idx]
                costo_u = self.servicios_costos[idx]
            elif isinstance(item, str):
                nombre_buscado = item.strip().lower()
                match_idx = next(
                    (i for i, n in enumerate(self.servicios_nombres) if n.strip().lower() == nombre_buscado),
                    None,
                )
                if match_idx is None:
                    raise ValueError(f"El servicio '{item}' no existe en el catálogo.")
                id_srv = self.servicios_ids[match_idx]
                nombre = self.servicios_nombres[match_idx]
                costo_u = self.servicios_costos[match_idx]
            elif isinstance(item, dict):
                raw_id = item.get("id_servicio")
                if raw_id is not None:
                    if not self._es_entero_estricto(raw_id) or raw_id < 1:
                        raise ValueError("Identificador de servicio inválido.")
                    id_srv = raw_id
                else:
                    id_srv = None

                raw_nombre = item.get("nombre")
                if raw_nombre is None:
                    raw_nombre = item.get("nombre_snapshot")
                nombre = str(raw_nombre).strip() if raw_nombre is not None else ""

                raw_costo = item.get("costo_unitario")
                if raw_costo is None:
                    raw_costo = item.get("costo_unitario_snapshot")
                if raw_costo is None:
                    raw_costo = item.get("costo")

                if id_srv is None:
                    if not nombre:
                        raise ValueError("Servicio sin identificador ni nombre.")
                    match_idx = next(
                        (i for i, n in enumerate(self.servicios_nombres) if n.strip().lower() == nombre.lower()),
                        None,
                    )
                    if match_idx is None:
                        raise ValueError(f"El servicio '{nombre}' no existe en el catálogo.")
                    id_srv = self.servicios_ids[match_idx]
                    nombre = self.servicios_nombres[match_idx]
                    if raw_costo is None:
                        raw_costo = self.servicios_costos[match_idx]
                else:
                    if id_srv not in self.servicios_ids:
                        raise ValueError(f"El servicio con ID {id_srv} no existe en el catálogo.")
                    match_idx = self.servicios_ids.index(id_srv)
                    if not nombre:
                        nombre = self.servicios_nombres[match_idx]
                    if raw_costo is None:
                        raw_costo = self.servicios_costos[match_idx]

                if not self._es_entero_estricto(raw_costo) or raw_costo < 0:
                    raise ValueError(f"Costo inválido para el servicio '{nombre}'.")
                costo_u = raw_costo
            else:
                raise ValueError("Elemento de servicio inválido.")

            if id_srv in vistos:
                continue
            vistos.add(id_srv)
            resueltos.append({
                "id_servicio": id_srv,
                "nombre": nombre,
                "costo_unitario": costo_u,
                "subtotal": costo_u * dias_final,
            })
        return resueltos

    def editar_reserva_por_id(
        self,
        id_reserva,
        nuevo_habitacion_idx=None,
        nuevo_dia_inicio=None,
        nuevos_dias_estadia=None,
        nuevos_servicios=None,
    ):
        """
        Edita una reserva 'Confirmada' por su ID (dia_inicio 0-based).
        Libera temporalmente los días originales en la matriz de disponibilidad, valida
        el nuevo rango en memoria y BD (excluyendo id_reserva), persiste en BD y actualiza
        la reserva en memoria. Ante cualquier falla o excepción, restaura los días originales.
        """
        if not self._es_entero_estricto(id_reserva) or id_reserva < 1:
            return False, "Identificador de reserva inválido."

        r = next(
            (res for res in self.reservas if res.id_reserva == id_reserva and res.estado == "Confirmada"),
            None,
        )
        if r is None:
            return False, "Reserva activa no encontrada."

        old_hab_idx = r.habitacion_idx
        old_dia_inicio = r.dia_inicio
        old_dias = r.dias_estadia

        if (
            not (0 <= old_hab_idx < len(self.matriz_disponibilidad))
            or old_dia_inicio < 0
            or old_dias < 1
            or old_dia_inicio + old_dias > self.dias_mes
        ):
            return False, "Estado actual de la reserva fuera de los límites del calendario."

        if nuevo_habitacion_idx is not None and not self._es_entero_estricto(nuevo_habitacion_idx):
            return False, "Índice de alojamiento inválido."
        if nuevo_dia_inicio is not None and not self._es_entero_estricto(nuevo_dia_inicio):
            return False, "Día de ingreso inválido."
        if nuevos_dias_estadia is not None and not self._es_entero_estricto(nuevos_dias_estadia):
            return False, "Cantidad de noches inválida."
        if nuevos_servicios is not None and not isinstance(nuevos_servicios, (list, tuple)):
            return False, "El listado de servicios debe ser una lista o tupla."

        hab_idx_final = r.habitacion_idx if nuevo_habitacion_idx is None else nuevo_habitacion_idx
        dia_inicio_final = r.dia_inicio if nuevo_dia_inicio is None else nuevo_dia_inicio
        dias_final = r.dias_estadia if nuevos_dias_estadia is None else nuevos_dias_estadia

        if not (0 <= hab_idx_final < len(self.ids_habitaciones)):
            return False, "El alojamiento seleccionado no existe o está fuera de rango."
        if dia_inicio_final < 0 or dias_final < 1 or dia_inicio_final + dias_final > self.dias_mes:
            return False, "Las fechas seleccionadas exceden los límites del calendario."

        self.sincronizar_servicios()

        # Liberar temporalmente los días anteriores en la matriz en memoria
        for d in range(old_dia_inicio, old_dia_inicio + old_dias):
            self.matriz_disponibilidad[old_hab_idx][d] = 0

        confirmado = False
        try:
            # 1. Validar disponibilidad en la matriz en memoria
            for d in range(dia_inicio_final, dia_inicio_final + dias_final):
                if self.matriz_disponibilidad[hab_idx_final][d] != 0:
                    return False, "El alojamiento no está disponible en las fechas seleccionadas."

            # 2. Validar disponibilidad en BD (1-based, excluyendo la propia reserva)
            id_hab_nuevo = self.ids_habitaciones[hab_idx_final]
            if not self.db.verificar_disponibilidad_db(
                id_hab_nuevo,
                dia_inicio_final + 1,
                dias_final,
                excluir_id_reserva=r.id_reserva,
            ):
                return False, "El alojamiento no está disponible en MySQL para las fechas seleccionadas."

            # 3. Resolver snapshots de alojamiento y tarifa base
            if hab_idx_final != old_hab_idx:
                hab_nombre_final = self.habitaciones[hab_idx_final]
                tipo_aloj_final = self.tipos_habitaciones[hab_idx_final]
                tarifa_base_final = self.tarifas[hab_idx_final]
            else:
                hab_nombre_final = r.habitacion_nombre or self.habitaciones[hab_idx_final]
                tipo_aloj_final = r.tipo_alojamiento or self.tipos_habitaciones[hab_idx_final]
                tarifa_base_final = (
                    r.tarifa_base_snapshot
                    if r.tarifa_base_snapshot is not None
                    else self.tarifas[hab_idx_final]
                )

            # 4. Resolver servicios contratados y recalcular monto total
            if nuevos_servicios is None:
                if r.servicios:
                    servicios_base = r.servicios
                elif r.incluye_desayuno or r.incluye_estacionamiento:
                    servicios_base = self._sintetizar_servicios_legacy(r)
                else:
                    servicios_base = []
            else:
                servicios_base = nuevos_servicios

            servicios_final = self._normalizar_servicios_edicion(servicios_base, dias_final)
            costo_servicios_noche = sum(s["costo_unitario"] for s in servicios_final)
            nuevo_total = (tarifa_base_final + costo_servicios_noche) * dias_final

            # 5. Persistir transaccionalmente en MySQL (dia_inicio_bd es 1-based)
            exito, msg = self.db.editar_reserva_transaccional(
                r.id_reserva,
                id_hab_nuevo,
                dia_inicio_final + 1,
                dias_final,
                nuevo_total,
                servicios_final,
                habitacion_nombre=hab_nombre_final,
                tipo_alojamiento=tipo_aloj_final,
                tarifa_base_snapshot=tarifa_base_final,
            )
            if not exito:
                return False, msg

            # 6. Marcar nuevos días en la matriz y actualizar Reserva en memoria
            for d in range(dia_inicio_final, dia_inicio_final + dias_final):
                self.matriz_disponibilidad[hab_idx_final][d] = 1
            confirmado = True

            r.habitacion_idx = hab_idx_final
            r.dia_inicio = dia_inicio_final
            r.dias_estadia = dias_final
            r.total = nuevo_total
            r.habitacion_nombre = hab_nombre_final
            r.tipo_alojamiento = tipo_aloj_final
            r.tarifa_base_snapshot = tarifa_base_final
            r.servicios = [dict(s) for s in servicios_final]
            nombres_lower = [s["nombre"].strip().lower() for s in r.servicios]
            r.incluye_desayuno = any("desayuno" in n for n in nombres_lower)
            r.incluye_estacionamiento = any("estacionamiento" in n for n in nombres_lower)
            return True, msg
        except Exception as e:
            return False, f"Error al editar reserva: {e}"
        finally:
            if not confirmado:
                for d in range(old_dia_inicio, old_dia_inicio + old_dias):
                    self.matriz_disponibilidad[old_hab_idx][d] = 1

    def editar_reserva(self):
        """Flujo interactivo de consola para editar una reserva activa."""
        print("\n--- EDITAR RESERVA ACTIVA ---")
        self.cargar_datos()
        activas = [
            r for r in self.reservas if r.estado == "Confirmada" and r.id_reserva is not None
        ]
        if not activas:
            print("No hay reservas activas para editar.")
            return

        for idx, r in enumerate(activas, start=1):
            hab_num = (
                r.habitacion_nombre
                if r.habitacion_nombre is not None
                else (
                    self.habitaciones[r.habitacion_idx]
                    if 0 <= r.habitacion_idx < len(self.habitaciones)
                    else f"ID#{r.habitacion_idx}"
                )
            )
            texto_srv = self._formatear_servicios_reserva(r)
            print(
                f"{idx}. [ID #{r.id_reserva}] {r.huesped.nombre} ({r.huesped.rut}) | "
                f"Alojamiento: {hab_num} | Día {r.dia_inicio + 1} ({r.dias_estadia} noches) | "
                f"Servicios: {texto_srv} | Total: ${r.total:,}"
            )

        seleccion = self._leer_entero(
            f"Seleccione la reserva a editar (1-{len(activas)}, 0 para cancelar): ",
            minimo=0,
            maximo=len(activas),
        )
        if seleccion is None or seleccion == 0:
            return

        r = activas[seleccion - 1]
        hab_actual = (
            r.habitacion_nombre
            if r.habitacion_nombre is not None
            else (
                self.habitaciones[r.habitacion_idx]
                if 0 <= r.habitacion_idx < len(self.habitaciones)
                else ""
            )
        )
        nuevo_hab_txt = self._leer_texto(
            f"Nuevo alojamiento [{hab_actual}] (Enter para mantener): ",
            permitir_vacio=True,
            max_len=50,
        )
        if nuevo_hab_txt is None:
            return
        if not nuevo_hab_txt:
            nuevo_hab_idx = r.habitacion_idx
        else:
            nuevo_hab_idx = self._buscar_indice_alojamiento(nuevo_hab_txt)
            if nuevo_hab_idx is None:
                print("Error: Habitación o cabaña no existe.")
                return

        nuevo_dia_ui = self._leer_entero(
            f"Nuevo día de ingreso (1-{self.dias_mes}) [{r.dia_inicio + 1}] (Enter para mantener): ",
            minimo=1,
            maximo=self.dias_mes,
            default=r.dia_inicio + 1,
        )
        if nuevo_dia_ui is None:
            return
        nuevo_dia_inicio = nuevo_dia_ui - 1

        nuevos_dias = self._leer_entero(
            f"Nueva cantidad de noches [{r.dias_estadia}] (Enter para mantener): ",
            minimo=1,
            maximo=self.dias_mes,
            default=r.dias_estadia,
        )
        if nuevos_dias is None:
            return

        if nuevo_dia_inicio + nuevos_dias > self.dias_mes:
            print("Error: Las fechas seleccionadas exceden el calendario actual.")
            return

        modificar_srv = self._leer_si_no("¿Desea modificar los servicios adicionales? (s/n): ")
        if modificar_srv is None:
            return

        if not modificar_srv:
            nuevos_servicios = None
            servicios_preview = (
                r.servicios
                if r.servicios
                else (
                    self._sintetizar_servicios_legacy(r)
                    if (r.incluye_desayuno or r.incluye_estacionamiento)
                    else []
                )
            )
            servicios_preview = self._normalizar_servicios_edicion(servicios_preview, nuevos_dias)
        else:
            servicios_actuales = (
                r.servicios
                if r.servicios
                else (
                    self._sintetizar_servicios_legacy(r)
                    if (r.incluye_desayuno or r.incluye_estacionamiento)
                    else []
                )
            )
            actuales_por_id = {
                s["id_servicio"]: s for s in servicios_actuales if s.get("id_servicio") is not None
            }
            nuevos_servicios = []
            ids_disponibles_mostrados = set()

            for i in range(len(self.servicios_ids)):
                if not self.servicios_disponibles[i]:
                    continue
                id_srv = self.servicios_ids[i]
                nombre_srv = self.servicios_nombres[i]
                costo_srv = (
                    actuales_por_id[id_srv]["costo_unitario"]
                    if id_srv in actuales_por_id
                    else self.servicios_costos[i]
                )
                ids_disponibles_mostrados.add(id_srv)
                resp = self._leer_si_no(
                    f"¿Incluir {nombre_srv} (${costo_srv:,}/noche)? (s/n): "
                )
                if resp is None:
                    return
                if resp:
                    nuevos_servicios.append({
                        "id_servicio": id_srv,
                        "nombre": nombre_srv,
                        "costo_unitario": costo_srv,
                        "subtotal": costo_srv * nuevos_dias,
                    })

            for id_srv, srv_old in actuales_por_id.items():
                if id_srv not in ids_disponibles_mostrados:
                    resp = self._leer_si_no(
                        f"¿Mantener servicio contratado '{srv_old['nombre']}' "
                        f"(${srv_old['costo_unitario']:,}/noche - deshabilitado en catálogo)? (s/n): "
                    )
                    if resp is None:
                        return
                    if resp:
                        nuevos_servicios.append({
                            "id_servicio": id_srv,
                            "nombre": srv_old["nombre"],
                            "costo_unitario": srv_old["costo_unitario"],
                            "subtotal": srv_old["costo_unitario"] * nuevos_dias,
                        })
            servicios_preview = nuevos_servicios

        tarifa_base_preview = (
            self.tarifas[nuevo_hab_idx]
            if nuevo_hab_idx != r.habitacion_idx
            else (
                r.tarifa_base_snapshot
                if r.tarifa_base_snapshot is not None
                else self.tarifas[nuevo_hab_idx]
            )
        )
        costo_srv_preview = sum(s["costo_unitario"] for s in servicios_preview)
        total_preview = (tarifa_base_preview + costo_srv_preview) * nuevos_dias

        print("\n--- RESUMEN DE EDICIÓN ---")
        print(
            f"Alojamiento: {self.tipos_habitaciones[nuevo_hab_idx]} {self.habitaciones[nuevo_hab_idx]} "
            f"(${tarifa_base_preview:,}/noche)"
        )
        print(f"Ingreso: Día {nuevo_dia_ui} | Noches: {nuevos_dias}")
        nombres_preview = ", ".join(s["nombre"] for s in servicios_preview) if servicios_preview else "Ninguno"
        print(f"Servicios: {nombres_preview}")
        print(f"Nuevo Total: ${total_preview:,}")

        confirmar = self._leer_si_no("\n¿Confirmar cambios en la reserva? (s/n): ")
        if confirmar is True:
            exito, msg = self.editar_reserva_por_id(
                r.id_reserva,
                nuevo_habitacion_idx=nuevo_hab_idx,
                nuevo_dia_inicio=nuevo_dia_inicio,
                nuevos_dias_estadia=nuevos_dias,
                nuevos_servicios=nuevos_servicios,
            )
            print(msg if exito else f"Error: {msg}")
        else:
            print("Edición cancelada.")

    def cancelar_reserva_por_id(self, id_reserva):
        """
        Cancela lógicamente una reserva 'Confirmada' en MySQL (estado='Cancelada'),
        libera sus días en matriz_disponibilidad y la retira de la lista de activas.
        """
        if not self._es_entero_estricto(id_reserva) or id_reserva < 1:
            return False, "Identificador de reserva inválido."

        r = next(
            (res for res in self.reservas if res.id_reserva == id_reserva and res.estado == "Confirmada"),
            None,
        )
        if r is None:
            return False, "Reserva activa no encontrada."

        try:
            exito, msg = self.db.cancelar_reserva_transaccional(r.id_reserva)
        except Exception as e:
            return False, f"Error al cancelar reserva: {e}"

        if not exito:
            return False, msg

        if 0 <= r.habitacion_idx < len(self.matriz_disponibilidad):
            for d in range(r.dia_inicio, r.dia_inicio + r.dias_estadia):
                if 0 <= d < self.dias_mes:
                    self.matriz_disponibilidad[r.habitacion_idx][d] = 0

        r.estado = "Cancelada"
        self.reservas = [res for res in self.reservas if res is not r]
        return True, msg

    def cancelar_reserva(self):
        """Flujo interactivo de consola para cancelar lógicamente una reserva activa."""
        print("\n--- CANCELAR RESERVA ACTIVA ---")
        self.cargar_datos()
        activas = [
            r for r in self.reservas if r.estado == "Confirmada" and r.id_reserva is not None
        ]
        if not activas:
            print("No hay reservas activas para cancelar.")
            return

        for idx, r in enumerate(activas, start=1):
            hab_num = (
                r.habitacion_nombre
                if r.habitacion_nombre is not None
                else (
                    self.habitaciones[r.habitacion_idx]
                    if 0 <= r.habitacion_idx < len(self.habitaciones)
                    else f"ID#{r.habitacion_idx}"
                )
            )
            print(
                f"{idx}. [ID #{r.id_reserva}] {r.huesped.nombre} ({r.huesped.rut}) | "
                f"Alojamiento: {hab_num} | Día {r.dia_inicio + 1} ({r.dias_estadia} noches) | "
                f"Total: ${r.total:,}"
            )

        seleccion = self._leer_entero(
            f"Seleccione la reserva a cancelar (1-{len(activas)}, 0 para volver): ",
            minimo=0,
            maximo=len(activas),
        )
        if seleccion is None or seleccion == 0:
            return

        r = activas[seleccion - 1]
        confirmar = self._leer_si_no(
            f"¿Confirmar cancelación de la reserva #{r.id_reserva} de {r.huesped.nombre}? (s/n): "
        )
        if confirmar is True:
            exito, msg = self.cancelar_reserva_por_id(r.id_reserva)
            print(msg if exito else f"Error: {msg}")
        else:
            print("Operación cancelada.")

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

        if not self.ids_habitaciones or nuevo_id > max(self.ids_habitaciones):
            self.ids_habitaciones.append(nuevo_id)
            self.tipos_habitaciones.append(tipo)
            self.habitaciones.append(identificador)
            self.tarifas.append(tarifa)
            self.matriz_disponibilidad.append([0 for _ in range(self.dias_mes)])
        else:
            insert_idx = 0
            while insert_idx < len(self.ids_habitaciones) and self.ids_habitaciones[insert_idx] < nuevo_id:
                insert_idx += 1
            self.ids_habitaciones.insert(insert_idx, nuevo_id)
            self.tipos_habitaciones.insert(insert_idx, tipo)
            self.habitaciones.insert(insert_idx, identificador)
            self.tarifas.insert(insert_idx, tarifa)
            self.matriz_disponibilidad.insert(insert_idx, [0 for _ in range(self.dias_mes)])
            for r in self.reservas:
                if r.habitacion_idx >= insert_idx:
                    r.habitacion_idx += 1
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
            if r.habitacion_idx == idx:
                r.habitacion_idx = -1
            elif r.habitacion_idx > idx:
                r.habitacion_idx -= 1

        print(msg)

    def crear_servicio(self, nombre, costo, disponible=True):
        """Crea un nuevo servicio en el catálogo y resincroniza los vectores paralelos."""
        if self.usuario_actual is not None and not self._es_admin():
            return False, None, "Acceso denegado: función exclusiva para administradores."
        try:
            exito, nuevo_id, msg = self.db.crear_servicio(nombre, costo, disponible=disponible)
        except Exception as e:
            return False, None, f"Error al crear servicio: {e}"
        if exito:
            self.sincronizar_servicios()
        return exito, nuevo_id, msg

    def editar_servicio(self, id_servicio, nombre, costo):
        """Edita nombre/costo de un servicio en el catálogo y resincroniza los vectores paralelos."""
        if self.usuario_actual is not None and not self._es_admin():
            return False, "Acceso denegado: función exclusiva para administradores."
        try:
            exito, msg = self.db.editar_servicio(id_servicio, nombre, costo)
        except Exception as e:
            return False, f"Error al editar servicio: {e}"
        if exito:
            self.sincronizar_servicios()
        return exito, msg

    def cambiar_disponibilidad_servicio(self, id_servicio, disponible=None):
        """Habilita o deshabilita un servicio y resincroniza los vectores paralelos."""
        if self.usuario_actual is not None and not self._es_admin():
            return False, None, "Acceso denegado: función exclusiva para administradores."
        try:
            exito, nuevo_estado, msg = self.db.cambiar_disponibilidad_servicio(
                id_servicio, disponible=disponible
            )
        except Exception as e:
            return False, None, f"Error al cambiar disponibilidad del servicio: {e}"
        if exito:
            self.sincronizar_servicios()
        return exito, nuevo_estado, msg

    def listar_servicios(self):
        """Muestra el catálogo completo de servicios adicionales con su estado."""
        self.sincronizar_servicios()
        print("\n--- CATÁLOGO DE SERVICIOS ADICIONALES ---")
        if not self.servicios_ids:
            print("No hay servicios registrados.")
            return
        for idx, (id_srv, nombre, costo, disp) in enumerate(
            zip(
                self.servicios_ids,
                self.servicios_nombres,
                self.servicios_costos,
                self.servicios_disponibles,
            ),
            start=1,
        ):
            estado = "Habilitado" if disp else "Deshabilitado"
            print(f"{idx}. [#{id_srv}] {nombre} — ${costo:,} / noche [{estado}]")

    def agregar_servicio_cli(self):
        """Flujo interactivo para crear un nuevo servicio adicional (solo admin)."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return

        print("\n--- AGREGAR SERVICIO ADICIONAL ---")
        nombre = self._leer_texto("Nombre del servicio: ", max_len=100)
        if nombre is None:
            return
        costo = self._leer_entero("Costo por noche ($): ", minimo=1, maximo=4294967295)
        if costo is None:
            return

        exito, _, msg = self.crear_servicio(nombre, costo, disponible=True)
        print(msg if exito else f"Error: {msg}")

    def editar_servicio_cli(self):
        """Flujo interactivo para editar nombre y costo de un servicio (solo admin)."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return

        print("\n--- EDITAR SERVICIO ADICIONAL ---")
        self.listar_servicios()
        if not self.servicios_ids:
            return

        seleccion = self._leer_entero(
            f"Seleccione el servicio a editar (1-{len(self.servicios_ids)}, 0 para cancelar): ",
            minimo=0,
            maximo=len(self.servicios_ids),
        )
        if seleccion is None or seleccion == 0:
            return

        idx = seleccion - 1
        id_srv = self.servicios_ids[idx]
        nombre_actual = self.servicios_nombres[idx]
        costo_actual = self.servicios_costos[idx]

        nuevo_nombre = self._leer_texto(
            f"Nuevo nombre [{nombre_actual}] (Enter para mantener): ",
            permitir_vacio=True,
            max_len=100,
        )
        if nuevo_nombre is None:
            return
        if not nuevo_nombre:
            nuevo_nombre = nombre_actual

        nuevo_costo = self._leer_entero(
            f"Nuevo costo [${costo_actual:,}] (Enter para mantener): ",
            minimo=1,
            maximo=4294967295,
            default=costo_actual,
        )
        if nuevo_costo is None:
            return

        exito, msg = self.editar_servicio(id_srv, nuevo_nombre, nuevo_costo)
        print(msg if exito else f"Error: {msg}")

    def cambiar_disponibilidad_servicio_cli(self):
        """Flujo interactivo para habilitar o deshabilitar un servicio (solo admin)."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return

        print("\n--- HABILITAR / DESHABILITAR SERVICIO ---")
        self.listar_servicios()
        if not self.servicios_ids:
            return

        seleccion = self._leer_entero(
            f"Seleccione el servicio a habilitar/deshabilitar (1-{len(self.servicios_ids)}, 0 para cancelar): ",
            minimo=0,
            maximo=len(self.servicios_ids),
        )
        if seleccion is None or seleccion == 0:
            return

        id_srv = self.servicios_ids[seleccion - 1]
        exito, _, msg = self.cambiar_disponibilidad_servicio(id_srv)
        print(msg if exito else f"Error: {msg}")

    def _obtener_historial_reservas(self):
        """Obtiene todas las reservas históricas desde la BD (con fallback a reservas en memoria)."""
        if hasattr(self.db, "obtener_todas_las_reservas"):
            try:
                filas = self.db.obtener_todas_las_reservas()
                if isinstance(filas, list):
                    return filas
            except Exception as e:
                print(f"Aviso al consultar historial de reservas: {e}")
        return [
            {
                "id_reserva": r.id_reserva,
                "monto_total": r.total,
                "estado": r.estado,
                "dias_estadia": r.dias_estadia,
                "incluye_desayuno": 1 if r.incluye_desayuno else 0,
                "incluye_estacionamiento": 1 if r.incluye_estacionamiento else 0,
                "servicios": [dict(s) for s in r.servicios],
            }
            for r in self.reservas
        ]

    def reporte_resumen_reservas(self):
        """
        1. Resumen de Reservas: Total histórico en BD, desglose entre
        'Confirmada' y 'Cancelada', y tasa de cancelación (%).
        """
        if not self._puede_ver_reportes():
            print("Acceso denegado: función exclusiva para administradores y gerentes.")
            return None

        todas = self._obtener_historial_reservas()
        total_historico = len(todas)
        confirmadas = sum(1 for r in todas if r.get("estado") == "Confirmada")
        canceladas = sum(1 for r in todas if r.get("estado") == "Cancelada")
        tasa_cancelacion = (canceladas / total_historico * 100.0) if total_historico > 0 else 0.0

        print("\n--- INFORME 1: RESUMEN DE RESERVAS ---")
        print(f"Total histórico de reservas : {total_historico}")
        print(f"Reservas Confirmadas        : {confirmadas}")
        print(f"Reservas Canceladas         : {canceladas}")
        print(f"Tasa de cancelación         : {tasa_cancelacion:.2f}%")
        print("--------------------------------------")

        return {
            "total_historico": total_historico,
            "confirmadas": confirmadas,
            "canceladas": canceladas,
            "tasa_cancelacion": round(tasa_cancelacion, 2),
        }

    def reporte_ingresos(self):
        """
        2. Informe de Ingresos: Ingresos totales por reservas confirmadas,
        monto retenido/perdido en canceladas y ticket promedio.
        """
        if not self._puede_ver_reportes():
            print("Acceso denegado: función exclusiva para administradores y gerentes.")
            return None

        todas = self._obtener_historial_reservas()
        confirmadas_list = [r for r in todas if r.get("estado") == "Confirmada"]
        canceladas_list = [r for r in todas if r.get("estado") == "Cancelada"]

        ingresos_confirmados = sum(int(r.get("monto_total", 0)) for r in confirmadas_list)
        monto_canceladas = sum(int(r.get("monto_total", 0)) for r in canceladas_list)
        ticket_promedio = (
            (ingresos_confirmados / len(confirmadas_list))
            if confirmadas_list
            else 0.0
        )

        print("\n--- INFORME 2: INFORME DE INGRESOS ---")
        print(f"Ingresos totales (Confirmadas)          : ${ingresos_confirmados:,}")
        print(f"Monto retenido/perdido (Canceladas)     : ${monto_canceladas:,}")
        print(f"Ticket promedio (Reservas Confirmadas)  : ${ticket_promedio:,.2f}")
        print("--------------------------------------")

        return {
            "ingresos_confirmados": ingresos_confirmados,
            "monto_canceladas": monto_canceladas,
            "ticket_promedio": round(ticket_promedio, 2),
        }

    def reporte_ocupacion(self):
        """
        3. Informe de Ocupación: Porcentaje de ocupación calculado directamente
        desde matriz_disponibilidad (general y por habitación/cabaña).
        """
        if not self._puede_ver_reportes():
            print("Acceso denegado: función exclusiva para administradores y gerentes.")
            return None

        self.cargar_datos()
        por_alojamiento = []
        dias_ocupados_total = 0
        capacidad_total_dias = len(self.habitaciones) * self.dias_mes

        print("\n--- INFORME 3: INFORME DE OCUPACIÓN ---")
        if not self.habitaciones:
            print("No hay habitaciones ni cabañas registradas.")
            porcentaje_general = 0.0
        else:
            for i, hab in enumerate(self.habitaciones):
                tipo = (
                    self.tipos_habitaciones[i]
                    if i < len(self.tipos_habitaciones)
                    else "Habitación"
                )
                fila = (
                    self.matriz_disponibilidad[i]
                    if i < len(self.matriz_disponibilidad)
                    else [0] * self.dias_mes
                )
                ocupados = sum(1 for celda in fila if celda == 1)
                dias_ocupados_total += ocupados
                pct = (ocupados / self.dias_mes * 100.0) if self.dias_mes > 0 else 0.0
                por_alojamiento.append({
                    "tipo": tipo,
                    "identificador": hab,
                    "dias_ocupados": ocupados,
                    "dias_totales": self.dias_mes,
                    "porcentaje_ocupacion": round(pct, 2),
                })
                print(
                    f"- {tipo} {hab:<12}: {ocupados:2d}/{self.dias_mes} días ocupados ({pct:.2f}%)"
                )
            porcentaje_general = (
                (dias_ocupados_total / capacidad_total_dias * 100.0)
                if capacidad_total_dias > 0
                else 0.0
            )

        print("-" * 39)
        print(
            f"Ocupación General del Mes: {dias_ocupados_total}/{capacidad_total_dias} días "
            f"({porcentaje_general:.2f}%)"
        )
        print("---------------------------------------")

        return {
            "porcentaje_general": round(porcentaje_general, 2),
            "dias_ocupados_total": dias_ocupados_total,
            "capacidad_total_dias": capacidad_total_dias,
            "por_alojamiento": por_alojamiento,
        }

    def reporte_rendimiento_servicios(self):
        """
        4. Rendimiento de Servicios: Ranking de servicios adicionales contratados
        e ingresos generados por cada servicio del catálogo escalable.
        """
        if not self._puede_ver_reportes():
            print("Acceso denegado: función exclusiva para administradores y gerentes.")
            return None

        self.sincronizar_servicios()
        todas = self._obtener_historial_reservas()

        estadisticas = {}
        for id_srv, nombre, costo, disp in zip(
            self.servicios_ids,
            self.servicios_nombres,
            self.servicios_costos,
            self.servicios_disponibles,
        ):
            estadisticas[id_srv] = {
                "id_servicio": id_srv,
                "nombre": nombre,
                "costo_actual": costo,
                "disponible": disp,
                "contrataciones": 0,
                "ingresos": 0,
            }

        for r in todas:
            if r.get("estado") != "Confirmada":
                continue
            servicios_res = r.get("servicios") or []
            if servicios_res:
                for s in servicios_res:
                    id_srv = s.get("id_servicio")
                    nombre_srv = str(s.get("nombre") or s.get("nombre_snapshot") or "Servicio")
                    subtotal = int(
                        s.get("subtotal")
                        if s.get("subtotal") is not None
                        else int(s.get("costo_unitario", 0)) * int(r.get("dias_estadia", 1))
                    )
                    if id_srv in estadisticas:
                        estadisticas[id_srv]["contrataciones"] += 1
                        estadisticas[id_srv]["ingresos"] += subtotal
                    else:
                        match_id = next(
                            (
                                k for k, v in estadisticas.items()
                                if v["nombre"].strip().lower() == nombre_srv.strip().lower()
                            ),
                            None,
                        )
                        if match_id is not None:
                            estadisticas[match_id]["contrataciones"] += 1
                            estadisticas[match_id]["ingresos"] += subtotal
            else:
                dias = int(r.get("dias_estadia", 1))
                if r.get("incluye_desayuno"):
                    match_des = next(
                        (k for k, v in estadisticas.items() if "desayuno" in v["nombre"].lower()),
                        None,
                    )
                    if match_des is not None:
                        estadisticas[match_des]["contrataciones"] += 1
                        estadisticas[match_des]["ingresos"] += estadisticas[match_des]["costo_actual"] * dias
                if r.get("incluye_estacionamiento"):
                    match_est = next(
                        (k for k, v in estadisticas.items() if "estacionamiento" in v["nombre"].lower()),
                        None,
                    )
                    if match_est is not None:
                        estadisticas[match_est]["contrataciones"] += 1
                        estadisticas[match_est]["ingresos"] += estadisticas[match_est]["costo_actual"] * dias

        ranking = sorted(
            estadisticas.values(),
            key=lambda x: (-x["ingresos"], -x["contrataciones"], x["id_servicio"]),
        )

        print("\n--- INFORME 4: RENDIMIENTO DE SERVICIOS ADICIONALES ---")
        if not ranking:
            print("No hay servicios registrados en el catálogo.")
        else:
            for pos, item in enumerate(ranking, start=1):
                estado_txt = "Activo" if item["disponible"] else "Inactivo"
                print(
                    f"#{pos} {item['nombre']:<18} [{estado_txt}] | "
                    f"Contrataciones: {item['contrataciones']} | "
                    f"Ingresos generados: ${item['ingresos']:,}"
                )
        print("-------------------------------------------------------")
        return ranking

    def generar_todos_los_reportes(self):
        """Ejecuta e imprime los 4 informes del módulo de reportería."""
        if not self._puede_ver_reportes():
            print("Acceso denegado: función exclusiva para administradores y gerentes.")
            return None
        return {
            "resumen_reservas": self.reporte_resumen_reservas(),
            "ingresos": self.reporte_ingresos(),
            "ocupacion": self.reporte_ocupacion(),
            "rendimiento_servicios": self.reporte_rendimiento_servicios(),
        }

    def menu_informes_y_reportes(self):
        """
        Submenú de Informes y Reportes accesible por Admin y Gerente.
        Retorna 'CAMBIAR_USUARIO' si el usuario solicita cerrar sesión desde este submenú.
        """
        if not self._puede_ver_reportes():
            print("Acceso denegado: función exclusiva para administradores y gerentes.")
            return None

        while True:
            print("\n--- MÓDULO DE INFORMES Y REPORTES ---")
            print("1. Resumen de Reservas (Histórico, Confirmadas, Canceladas y Tasa %)")
            print("2. Informe de Ingresos (Confirmados, Perdidos en Canceladas y Ticket Promedio)")
            print("3. Informe de Ocupación (General y por Habitación / Cabaña)")
            print("4. Rendimiento de Servicios Adicionales (Ranking e Ingresos)")
            print("5. Ver todos los informes completos")
            print("6. Cerrar sesión / Cambiar de usuario")
            print("7. Volver al menú principal")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                return None
            opcion = raw.strip()

            if opcion == "1":
                self.reporte_resumen_reservas()
            elif opcion == "2":
                self.reporte_ingresos()
            elif opcion == "3":
                self.reporte_ocupacion()
            elif opcion == "4":
                self.reporte_rendimiento_servicios()
            elif opcion == "5":
                self.generar_todos_los_reportes()
            elif opcion == "6":
                return "CAMBIAR_USUARIO"
            elif opcion == "7":
                return None
            else:
                print("Opción inválida. Intente nuevamente.")

    def menu_administracion_servicios(self):
        """Submenú exclusivo para administradores para gestionar servicios adicionales y costos."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return None

        while True:
            print("\n--- GESTIÓN DE SERVICIOS ADICIONALES Y COSTOS ---")
            print("1. Listar catálogo de servicios adicionales")
            print("2. Crear nuevo servicio adicional")
            print("3. Editar costo o nombre de un servicio")
            print("4. Habilitar / Deshabilitar disponibilidad de un servicio")
            print("5. Cerrar sesión / Cambiar de usuario")
            print("6. Volver")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                return None
            opcion = raw.strip()

            if opcion == "1":
                self.listar_servicios()
            elif opcion == "2":
                self.agregar_servicio_cli()
            elif opcion == "3":
                self.editar_servicio_cli()
            elif opcion == "4":
                self.cambiar_disponibilidad_servicio_cli()
            elif opcion == "5":
                return "CAMBIAR_USUARIO"
            elif opcion == "6":
                return None
            else:
                print("Opción inválida. Intente nuevamente.")

    def menu_administracion(self):
        """
        Submenú exclusivo para administradores para gestionar Habitaciones/Cabañas
        y el catálogo escalable de Servicios Adicionales + Costos.
        """
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return None

        while True:
            print("\n--- MÓDULO DE ADMINISTRACIÓN (HABITACIONES / CABAÑAS / SERVICIOS) ---")
            print("1. Listar habitaciones y cabañas")
            print("2. Agregar habitación o cabaña")
            print("3. Editar habitación o cabaña")
            print("4. Eliminar habitación o cabaña")
            print("5. Volver al menú principal")
            print("6. Gestionar Servicios Adicionales + Costos")
            print("7. Cerrar sesión / Cambiar de usuario")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                return None
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
                return None
            elif opcion == "6":
                accion = self.menu_administracion_servicios()
                if accion == "CAMBIAR_USUARIO":
                    return "CAMBIAR_USUARIO"
            elif opcion == "7":
                return "CAMBIAR_USUARIO"
            else:
                print("Opción inválida. Intente nuevamente.")

    def menu_reservas_admin(self):
        """Submenú jerárquico del Módulo de Reservas para el rol Admin (acceso completo)."""
        if not self._es_admin():
            print("Acceso denegado: función exclusiva para administradores.")
            return None

        while True:
            print("\n--- MÓDULO DE RESERVAS (ADMIN) ---")
            print("1. Consultar matriz de disponibilidad")
            print("2. Consultar tarifas")
            print("3. Registrar nueva reserva (Cotizar y Confirmar)")
            print("4. Editar reserva activa")
            print("5. Cancelar / Eliminar reserva (borrado lógico)")
            print("6. Ver reservas activas")
            print("7. Cerrar sesión / Cambiar de usuario")
            print("8. Volver al menú principal")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                return None
            opcion = raw.strip()

            if opcion == "1":
                self.cargar_datos()
                self.mostrar_matriz_disponibilidad()
            elif opcion == "2":
                self.consultar_tarifas()
            elif opcion == "3":
                self.registrar_reserva()
            elif opcion == "4":
                self.editar_reserva()
            elif opcion == "5":
                self.cancelar_reserva()
            elif opcion == "6":
                self.ver_reservas_activas()
            elif opcion == "7":
                return "CAMBIAR_USUARIO"
            elif opcion == "8":
                return None
            else:
                print("Opción inválida. Intente nuevamente.")

    def menu_gestion_reservas_gerente(self):
        """Submenú para Gerente: Ver, Editar y Cancelar reservas existentes (sin registrar nuevas)."""
        if not (self._es_gerente() or self._es_admin()):
            print("Acceso denegado: función exclusiva para gerentes y administradores.")
            return None

        while True:
            print("\n--- GESTIÓN DE RESERVAS EXISTENTES (GERENCIA) ---")
            print("1. Ver reservas activas")
            print("2. Editar reserva activa")
            print("3. Cancelar / Eliminar reserva (borrado lógico)")
            print("4. Cerrar sesión / Cambiar de usuario")
            print("5. Volver al menú principal")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                return None
            opcion = raw.strip()

            if opcion == "1":
                self.ver_reservas_activas()
            elif opcion == "2":
                self.editar_reserva()
            elif opcion == "3":
                self.cancelar_reserva()
            elif opcion == "4":
                return "CAMBIAR_USUARIO"
            elif opcion == "5":
                return None
            else:
                print("Opción inválida. Intente nuevamente.")

    def _cambiar_sesion_interactiva(self):
        """Cierra la sesión del usuario actual y solicita un nuevo inicio de sesión."""
        username = self.usuario_actual.get("username", "") if self.usuario_actual else ""
        print(f"Cerrando sesión de '{username}'...")
        self.usuario_actual = None
        return self.iniciar_sesion()

    def iniciar(self):
        """Menú principal interactivo en consola con control de acceso por rol (RBAC)."""
        if self.usuario_actual is None:
            if not self.iniciar_sesion():
                return

        while True:
            rol = self.usuario_actual.get("rol", "recepcionista")
            username = self.usuario_actual.get("username", "")

            print(f"\n=== SISTEMA NEXOPMS (MySQL) === [Usuario: {username} | Rol: {rol}]")

            if rol == "admin":
                print("1. Consultar matriz de disponibilidad")
                print("2. Consultar tarifas")
                print("3. Registrar nueva reserva (Cotizar y Confirmar)")
                print("4. Ver reservas activas")
                print("5. Módulo de Administración (Gestionar Habitaciones / Cabañas)")
                print("6. Cerrar sesión / Cambiar de usuario")
                print("7. Salir")
                print("8. Módulo de Reservas (Registrar, Editar, Cancelar, Ver)")
                print("9. Módulo de Informes y Reportes")
            elif rol == "gerente":
                print("1. Consultar habitaciones/cabañas, disponibilidad y tarifas")
                print("2. Gestionar reservas existentes (Ver, Editar y Cancelar reservas)")
                print("3. Módulo de Informes y Reportes")
                print("4. Cerrar sesión / Cambiar de usuario")
                print("5. Salir")
            else:
                # Rol recepcionista
                print("1. Consultar matriz de disponibilidad")
                print("2. Consultar tarifas")
                print("3. Registrar nueva reserva (Cotizar y Confirmar)")
                print("4. Ver reservas activas")
                print("5. Cerrar sesión / Cambiar de usuario")
                print("6. Salir")
                print("7. Editar reserva activa")
                print("8. Cancelar / Eliminar reserva (borrado lógico)")

            raw = self._leer_entrada("Seleccione una opción: ")
            if raw is None:
                print("Cerrando NexoPMS... ¡Hasta pronto!")
                break
            opcion = raw.strip()

            if rol == "admin":
                if opcion == "1":
                    self.cargar_datos()
                    self.mostrar_matriz_disponibilidad()
                elif opcion == "2":
                    self.consultar_tarifas()
                elif opcion == "3":
                    self.registrar_reserva()
                elif opcion == "4":
                    self.ver_reservas_activas()
                elif opcion == "5":
                    accion = self.menu_administracion()
                    if accion == "CAMBIAR_USUARIO":
                        if not self._cambiar_sesion_interactiva():
                            break
                elif opcion == "6":
                    if not self._cambiar_sesion_interactiva():
                        break
                elif opcion == "7":
                    print("Cerrando NexoPMS... ¡Hasta pronto!")
                    break
                elif opcion == "8":
                    accion = self.menu_reservas_admin()
                    if accion == "CAMBIAR_USUARIO":
                        if not self._cambiar_sesion_interactiva():
                            break
                elif opcion == "9":
                    accion = self.menu_informes_y_reportes()
                    if accion == "CAMBIAR_USUARIO":
                        if not self._cambiar_sesion_interactiva():
                            break
                else:
                    print("Opción inválida. Intente nuevamente.")

            elif rol == "gerente":
                if opcion == "1":
                    self.cargar_datos()
                    self._listar_alojamientos()
                    self.mostrar_matriz_disponibilidad()
                    self.consultar_tarifas()
                elif opcion == "2":
                    accion = self.menu_gestion_reservas_gerente()
                    if accion == "CAMBIAR_USUARIO":
                        if not self._cambiar_sesion_interactiva():
                            break
                elif opcion == "3":
                    accion = self.menu_informes_y_reportes()
                    if accion == "CAMBIAR_USUARIO":
                        if not self._cambiar_sesion_interactiva():
                            break
                elif opcion == "4":
                    if not self._cambiar_sesion_interactiva():
                        break
                elif opcion == "5":
                    print("Cerrando NexoPMS... ¡Hasta pronto!")
                    break
                else:
                    print("Opción inválida. Intente nuevamente.")

            else:
                # Rol recepcionista
                if opcion == "1":
                    self.cargar_datos()
                    self.mostrar_matriz_disponibilidad()
                elif opcion == "2":
                    self.consultar_tarifas()
                elif opcion == "3":
                    self.registrar_reserva()
                elif opcion == "4":
                    self.ver_reservas_activas()
                elif opcion == "5":
                    if not self._cambiar_sesion_interactiva():
                        break
                elif opcion == "6":
                    print("Cerrando NexoPMS... ¡Hasta pronto!")
                    break
                elif opcion == "7":
                    self.editar_reserva()
                elif opcion == "8":
                    self.cancelar_reserva()
                else:
                    print("Opción inválida. Intente nuevamente.")


if __name__ == "__main__":
    sistema = NexoPMS()
    sistema.iniciar()
