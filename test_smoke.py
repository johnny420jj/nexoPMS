"""
Pruebas de verificación automatizadas (smoke tests) para NexoPMS con arquitectura MySQL.
Valida la importación modular, inicialización, lógica de negocio y persistencia
sin requerir interacción manual en consola.
"""

import io
import sys
import unittest
from unittest.mock import MagicMock, patch

from conexion import ConexionDB, hashear_password, verificar_password


class FakeConexionDB:
    """Simulador de ConexionDB en memoria para pruebas aisladas sin alterar la BD real."""

    def __init__(self):
        self.usuarios = []
        self.habitaciones = [
            {"id_habitacion": 1, "tipo": "Habitación", "numero_habitacion": "101", "tarifa_base_noche": 45000, "activa": 1},
            {"id_habitacion": 2, "tipo": "Habitación", "numero_habitacion": "102", "tarifa_base_noche": 45000, "activa": 1},
            {"id_habitacion": 3, "tipo": "Habitación", "numero_habitacion": "103", "tarifa_base_noche": 60000, "activa": 1},
            {"id_habitacion": 4, "tipo": "Habitación", "numero_habitacion": "104", "tarifa_base_noche": 70000, "activa": 1},
        ]
        self.ocupacion = []
        self.reservas = []
        self._next_id = 1
        self._next_hab_id = 5
        self._next_user_id = 1
        self.asegurar_esquema()

    def asegurar_esquema(self):
        semillas = [
            ("admin", "admin123", "admin"),
            ("recepcion", "recep123", "recepcionista"),
        ]
        existentes = {u["username"] for u in self.usuarios}
        for username, raw_pwd, rol in semillas:
            if username not in existentes:
                self.usuarios.append({
                    "id_usuario": self._next_user_id,
                    "username": username,
                    "password": hashear_password(raw_pwd),
                    "rol": rol,
                    "activo": 1,
                })
                self._next_user_id += 1
        return True

    def autenticar_usuario(self, username, password):
        username_limpio = (username or "").strip()
        if not username_limpio or not isinstance(password, str) or not password:
            return None
        for u in self.usuarios:
            if u["username"] == username_limpio and bool(u.get("activo", 1)):
                if verificar_password(password, u["password"]):
                    return {
                        "id_usuario": u["id_usuario"],
                        "username": u["username"],
                        "rol": u["rol"],
                    }
        return None

    def obtener_habitaciones_y_tarifas(self):
        return [
            {
                "id_habitacion": h["id_habitacion"],
                "tipo": h.get("tipo", "Habitación"),
                "numero_habitacion": h["numero_habitacion"],
                "tarifa_base_noche": h["tarifa_base_noche"],
            }
            for h in sorted(self.habitaciones, key=lambda x: x["id_habitacion"])
            if h.get("activa", 1) == 1
        ]

    def obtener_ocupacion_diaria(self):
        return [dict(o) for o in self.ocupacion if o.get("ocupada") == 1]

    def obtener_reservas_activas(self):
        return [dict(r) for r in self.reservas if r.get("estado") == "Confirmada"]

    def agregar_habitacion(self, tipo, numero_habitacion, tarifa_base_noche):
        if tipo not in ("Habitación", "Cabaña"):
            return False, None, "Tipo de alojamiento inválido."
        ident = (numero_habitacion or "").strip()
        if not ident or len(ident) > 50:
            return False, None, "Identificador inválido."
        tarifa = int(tarifa_base_noche)
        if tarifa <= 0:
            return False, None, "La tarifa base debe ser mayor a 0."

        for h in self.habitaciones:
            if h["numero_habitacion"].strip().lower() == ident.lower():
                if h.get("activa", 1) == 1:
                    return False, None, f"Ya existe un alojamiento con el identificador '{ident}'."
                h["tipo"] = tipo
                h["numero_habitacion"] = ident
                h["tarifa_base_noche"] = tarifa
                h["activa"] = 1
                return True, h["id_habitacion"], f"{tipo} '{ident}' agregada exitosamente."

        nuevo_id = self._next_hab_id
        self._next_hab_id += 1
        self.habitaciones.append({
            "id_habitacion": nuevo_id,
            "tipo": tipo,
            "numero_habitacion": ident,
            "tarifa_base_noche": tarifa,
            "activa": 1,
        })
        return True, nuevo_id, f"{tipo} '{ident}' agregada exitosamente."

    def editar_habitacion(self, id_habitacion, tipo, numero_habitacion, tarifa_base_noche):
        if tipo not in ("Habitación", "Cabaña"):
            return False, "Tipo de alojamiento inválido."
        ident = (numero_habitacion or "").strip()
        if not ident or len(ident) > 50:
            return False, "Identificador inválido."
        tarifa = int(tarifa_base_noche)
        if tarifa <= 0:
            return False, "La tarifa base debe ser mayor a 0."

        objetivo = None
        for h in self.habitaciones:
            if h["id_habitacion"] == id_habitacion and h.get("activa", 1) == 1:
                objetivo = h
            elif h["numero_habitacion"].strip().lower() == ident.lower() and h["id_habitacion"] != id_habitacion:
                return False, f"Ya existe otro alojamiento con el identificador '{ident}'."

        if objetivo is None:
            return False, "El alojamiento seleccionado no existe."

        objetivo["tipo"] = tipo
        objetivo["numero_habitacion"] = ident
        objetivo["tarifa_base_noche"] = tarifa
        return True, f"{tipo} '{ident}' actualizada exitosamente."

    def eliminar_habitacion(self, id_habitacion):
        if any(o["id_habitacion"] == id_habitacion and o.get("ocupada") == 1 for o in self.ocupacion):
            return False, "No se puede eliminar: el alojamiento tiene días ocupados registrados."
        if any(r["id_habitacion"] == id_habitacion and r.get("estado") == "Confirmada" for r in self.reservas):
            return False, "No se puede eliminar: el alojamiento tiene reservas activas."

        tiene_historicas = any(r["id_habitacion"] == id_habitacion for r in self.reservas)
        if tiene_historicas:
            for h in self.habitaciones:
                if h["id_habitacion"] == id_habitacion:
                    h["activa"] = 0
                    break
        else:
            self.habitaciones = [h for h in self.habitaciones if h["id_habitacion"] != id_habitacion]
        return True, "Alojamiento eliminado exitosamente."

    def verificar_disponibilidad_db(self, id_habitacion, dia_inicio_bd, dias_estadia):
        dia_fin_bd = dia_inicio_bd + dias_estadia - 1
        for reg in self.ocupacion:
            if (
                reg["id_habitacion"] == id_habitacion
                and dia_inicio_bd <= reg["dia_mes"] <= dia_fin_bd
                and reg["ocupada"] == 1
            ):
                return False
        return True

    def guardar_reserva_transaccional(self, nueva_reserva, id_habitacion):
        dia_inicio_bd = nueva_reserva.dia_inicio + 1
        if not self.verificar_disponibilidad_db(id_habitacion, dia_inicio_bd, nueva_reserva.dias_estadia):
            return False

        id_reserva = self._next_id
        self._next_id += 1
        self.reservas.append({
            "id_reserva": id_reserva,
            "id_habitacion": id_habitacion,
            "dia_inicio": dia_inicio_bd,
            "dias_estadia": nueva_reserva.dias_estadia,
            "incluye_desayuno": 1 if nueva_reserva.incluye_desayuno else 0,
            "incluye_estacionamiento": 1 if nueva_reserva.incluye_estacionamiento else 0,
            "monto_total": nueva_reserva.total,
            "estado": nueva_reserva.estado,
            "habitacion_nombre": getattr(nueva_reserva, "habitacion_nombre", None),
            "tipo_alojamiento": getattr(nueva_reserva, "tipo_alojamiento", None),
            "tarifa_base_snapshot": getattr(nueva_reserva, "tarifa_base_snapshot", None),
            "rut": nueva_reserva.huesped.rut,
            "nombre": nueva_reserva.huesped.nombre,
            "telefono": nueva_reserva.huesped.telefono,
        })
        for d_offset in range(nueva_reserva.dias_estadia):
            self.ocupacion.append({
                "id_habitacion": id_habitacion,
                "dia_mes": dia_inicio_bd + d_offset,
                "ocupada": 1,
                "id_reserva": id_reserva,
            })
        return True


class TestNexoPMSSmoke(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeConexionDB()

    def test_01_import_modules(self):
        """Valida que todos los módulos se importan correctamente sin dependencias circulares."""
        import huesped
        import reserva
        import conexion
        import nexopms
        import main

        self.assertTrue(hasattr(huesped, "Huesped"))
        self.assertTrue(hasattr(reserva, "Reserva"))
        self.assertTrue(hasattr(conexion, "ConexionDB"))
        self.assertTrue(hasattr(nexopms, "NexoPMS"))
        self.assertTrue(hasattr(main, "NexoPMS"))
        self.assertTrue(hasattr(main, "main"))

    def test_02_huesped_model(self):
        """Valida el funcionamiento de la clase Huesped y su serialización a diccionario."""
        from huesped import Huesped

        h = Huesped("19.876.543-2", "Ana Morales", "+56987654321")
        self.assertEqual(h.rut, "19.876.543-2")
        self.assertEqual(h.nombre, "Ana Morales")
        self.assertEqual(h.telefono, "+56987654321")

        data = h.to_dict()
        self.assertEqual(data, {
            "rut": "19.876.543-2",
            "nombre": "Ana Morales",
            "telefono": "+56987654321"
        })

    def test_03_reserva_model(self):
        """Valida el funcionamiento de la clase Reserva y su serialización a diccionario."""
        from huesped import Huesped
        from reserva import Reserva

        h = Huesped("12.345.678-9", "Juan Silva", "+56912345678")
        r = Reserva(
            huesped=h,
            habitacion_idx=1,
            dia_inicio=5,
            dias_estadia=3,
            total=135000,
            incluye_desayuno=True,
            incluye_estacionamiento=False
        )

        self.assertEqual(r.habitacion_idx, 1)
        self.assertEqual(r.dia_inicio, 5)
        self.assertEqual(r.dias_estadia, 3)
        self.assertEqual(r.total, 135000)
        self.assertTrue(r.incluye_desayuno)
        self.assertFalse(r.incluye_estacionamiento)
        self.assertEqual(r.estado, "Confirmada")

    def test_04_nexopms_initialization(self):
        """Valida inicialización correcta de NexoPMS, vectores paralelos y matriz de 30 días."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        self.assertEqual(sistema.habitaciones, ["101", "102", "103", "104"])
        self.assertEqual(sistema.tarifas, [45000, 45000, 60000, 70000])
        self.assertEqual(sistema.dias_mes, 30)
        self.assertEqual(len(sistema.matriz_disponibilidad), 4)
        for fila in sistema.matriz_disponibilidad:
            self.assertEqual(len(fila), 30)
            self.assertTrue(all(celda == 0 for celda in fila))
        self.assertEqual(len(sistema.reservas), 0)

    def test_05_mostrar_disponibilidad_y_tarifas(self):
        """Valida que los métodos de consulta en consola se ejecuten sin lanzar excepciones."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        buffer = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buffer
            sistema.mostrar_matriz_disponibilidad()
            sistema.consultar_tarifas()
            output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("MATRIZ DE DISPONIBILIDAD (30 Días)", output)
        self.assertIn("TARIFARIO BASE Y SERVICIOS ADICIONALES", output)
        self.assertIn("Habitación 101: $45,000 / noche", output)

    def test_06_confirmar_y_persistencia(self):
        """Valida doble validación, marcado de matriz, guardado y posterior carga desde BD."""
        from huesped import Huesped
        from reserva import Reserva
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        h = Huesped("11.222.333-4", "Test Persistencia", "+56911223344")
        nueva_reserva = Reserva(
            huesped=h,
            habitacion_idx=2,
            dia_inicio=10,
            dias_estadia=4,
            total=240000,
            incluye_desayuno=False,
            incluye_estacionamiento=False
        )

        buffer = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buffer
            exito = sistema.confirmar_y_guardar_reserva(nueva_reserva, 2, 10, 4)
        finally:
            sys.stdout = old_stdout

        self.assertTrue(exito)
        self.assertEqual(len(sistema.reservas), 1)

        for d in range(10, 14):
            self.assertEqual(sistema.matriz_disponibilidad[2][d], 1)
        self.assertEqual(sistema.matriz_disponibilidad[2][9], 0)
        self.assertEqual(sistema.matriz_disponibilidad[2][14], 0)

        otra_reserva = Reserva(
            huesped=h,
            habitacion_idx=2,
            dia_inicio=12,
            dias_estadia=3,
            total=180000
        )
        buffer = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buffer
            fallo = sistema.confirmar_y_guardar_reserva(otra_reserva, 2, 12, 3)
        finally:
            sys.stdout = old_stdout
        self.assertFalse(fallo)

        sistema2 = NexoPMS(db=self.fake_db)
        self.assertEqual(len(sistema2.reservas), 1)
        reserva_cargada = sistema2.reservas[0]
        self.assertEqual(reserva_cargada.huesped.rut, "11.222.333-4")
        self.assertEqual(reserva_cargada.huesped.nombre, "Test Persistencia")
        self.assertEqual(reserva_cargada.habitacion_idx, 2)
        self.assertEqual(reserva_cargada.total, 240000)
        for d in range(10, 14):
            self.assertEqual(sistema2.matriz_disponibilidad[2][d], 1)

    def test_07_menu_iniciar_salida_limpia(self):
        """Valida que iniciar() solicite login, muestre el menú principal y termine limpiamente."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        buffer = io.StringIO()
        old_stdout = sys.stdout
        old_stdin = sys.stdin
        try:
            sys.stdout = buffer
            sys.stdin = io.StringIO("recepcion\nrecep123\n6\n")
            sistema.iniciar()
            output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stdin = old_stdin

        self.assertIn("=== INICIO DE SESIÓN — NEXOPMS ===", output)
        self.assertIn("=== SISTEMA NEXOPMS (MySQL) ===", output)
        self.assertIn("Cerrando NexoPMS... ¡Hasta pronto!", output)

    def test_08_registrar_reserva_interactivo_y_ver_activas(self):
        """Valida el flujo interactivo de registrar_reserva() con cotización y ver_reservas_activas()."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        entradas = "103\n1\n2\n1-9\nPedro\n1234\ns\ns\ns\n"
        buffer = io.StringIO()
        old_stdout = sys.stdout
        old_stdin = sys.stdin
        try:
            sys.stdout = buffer
            sys.stdin = io.StringIO(entradas)
            sistema.registrar_reserva()
            output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stdin = old_stdin

        self.assertIn("RESUMEN DE COTIZACIÓN", output)
        self.assertIn("¡Reserva confirmada y guardada exitosamente en MySQL!", output)
        self.assertEqual(len(sistema.reservas), 1)
        self.assertEqual(sistema.reservas[0].total, 146000)
        self.assertTrue(sistema.reservas[0].incluye_desayuno)
        self.assertTrue(sistema.reservas[0].incluye_estacionamiento)

        buffer = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buffer
            sistema.ver_reservas_activas()
            output_activas = buffer.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("Pedro", output_activas)
        self.assertIn("103", output_activas)
        self.assertIn("Desayuno, Estacionamiento", output_activas)
        self.assertIn("146,000", output_activas)

    def test_09_usuarios_semilla_y_hashing(self):
        """R1/AC1: Verifica usuarios semilla admin y recepcion con contraseñas hasheadas e idempotencia."""
        usernames = {u["username"]: u for u in self.fake_db.usuarios}
        self.assertIn("admin", usernames)
        self.assertIn("recepcion", usernames)
        self.assertEqual(usernames["admin"]["rol"], "admin")
        self.assertEqual(usernames["recepcion"]["rol"], "recepcionista")

        self.assertNotEqual(usernames["admin"]["password"], "admin123")
        self.assertNotEqual(usernames["recepcion"]["password"], "recep123")
        self.assertTrue(usernames["admin"]["password"].startswith("pbkdf2_sha256$"))
        self.assertTrue(usernames["recepcion"]["password"].startswith("pbkdf2_sha256$"))

        self.fake_db.asegurar_esquema()
        self.assertEqual(len(self.fake_db.usuarios), 2)

        auth_admin = self.fake_db.autenticar_usuario("admin", "admin123")
        auth_recep = self.fake_db.autenticar_usuario("recepcion", "recep123")
        self.assertIsNotNone(auth_admin)
        self.assertEqual(auth_admin["rol"], "admin")
        self.assertIsNotNone(auth_recep)
        self.assertEqual(auth_recep["rol"], "recepcionista")
        self.assertIsNone(self.fake_db.autenticar_usuario("admin", "incorrecta"))
        self.assertIsNone(self.fake_db.autenticar_usuario("desconocido", "admin123"))

    def test_10_login_valido_y_limite_intentos(self):
        """R1/AC2: Verifica login válido para ambos roles y salida controlada tras superar intentos fallidos."""
        from nexopms import NexoPMS

        # 3 intentos fallidos -> sale sin mostrar el menú principal
        sistema = NexoPMS(db=self.fake_db)
        buffer = io.StringIO()
        with patch("sys.stdout", buffer), patch("sys.stdin", io.StringIO(
            "admin\nmal1\nrecepcion\nmal2\nadmin\nmal3\n"
        )):
            sistema.iniciar()
        output = buffer.getvalue()
        self.assertIn("Máximo de intentos fallidos alcanzado", output)
        self.assertNotIn("=== SISTEMA NEXOPMS (MySQL) ===", output)
        self.assertIsNone(sistema.usuario_actual)

        # 1 fallo + 1 acierto como admin -> ingresa al menú y sale limpiamente
        sistema2 = NexoPMS(db=self.fake_db)
        buffer2 = io.StringIO()
        with patch("sys.stdout", buffer2), patch("sys.stdin", io.StringIO(
            "admin\nmal\nadmin\nadmin123\n7\n"
        )):
            sistema2.iniciar()
        output2 = buffer2.getvalue()
        self.assertIn("Intentos restantes: 2", output2)
        self.assertIn("Bienvenido/a, admin (Rol: admin)", output2)
        self.assertIn("=== SISTEMA NEXOPMS (MySQL) ===", output2)
        self.assertIn("Cerrando NexoPMS... ¡Hasta pronto!", output2)

    def test_11_menu_por_rol_y_cambio_usuario(self):
        """R1/AC3: Verifica filtrado de menú por rol y cambio de sesión entre recepcionista y admin."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        # Inicia como recepcionista, intenta opción 7 (inválida para recepcionista),
        # luego elige 5 (Cerrar sesión / Cambiar de usuario), inicia como admin, ve Admin y sale con 7.
        script = (
            "recepcion\nrecep123\n"
            "7\n"
            "5\n"
            "admin\nadmin123\n"
            "7\n"
        )
        buffer = io.StringIO()
        with patch("sys.stdout", buffer), patch("sys.stdin", io.StringIO(script)):
            sistema.iniciar()
        output = buffer.getvalue()

        parte_recep, parte_admin = output.split("Cerrando sesión de 'recepcion'...")
        self.assertNotIn("Módulo de Administración", parte_recep)
        self.assertIn("Opción inválida", parte_recep)
        self.assertIn("5. Módulo de Administración (Gestionar Habitaciones / Cabañas)", parte_admin)

        # Acceso directo bloqueado si el rol actual no es admin
        sistema.usuario_actual = {"id_usuario": 2, "username": "recepcion", "rol": "recepcionista"}
        buf_denegado = io.StringIO()
        with patch("sys.stdout", buf_denegado):
            sistema.menu_administracion()
        self.assertIn("Acceso denegado", buf_denegado.getvalue())

    def test_12_agregar_alojamiento_y_duplicado(self):
        """R2.1/AC4: Agregar Habitación/Cabaña actualiza BD, vectores y matriz; rechaza duplicados."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        script = (
            "admin\nadmin123\n"
            "5\n"            # Módulo de Administración
            "2\n"            # Agregar alojamiento
            "2\n"            # Cabaña
            "Cabaña 1\n"     # Identificador
            "85000\n"        # Tarifa
            "2\n"            # Intentar duplicado insensible a mayúsculas
            "2\n"
            "cabaña 1\n"
            "5\n"            # Volver al menú principal
            "2\n"            # Consultar tarifas
            "1\n"            # Consultar matriz de disponibilidad
            "7\n"            # Salir
        )
        buffer = io.StringIO()
        with patch("sys.stdout", buffer), patch("sys.stdin", io.StringIO(script)):
            sistema.iniciar()
        output = buffer.getvalue()

        self.assertIn("Cabaña 'Cabaña 1' agregada exitosamente.", output)
        self.assertIn("Ya existe un alojamiento con el identificador 'cabaña 1'", output)
        self.assertIn("Cabaña Cabaña 1: $85,000 / noche", output)
        self.assertEqual(len(sistema.habitaciones), 5)
        self.assertEqual(sistema.tipos_habitaciones[-1], "Cabaña")
        self.assertEqual(sistema.habitaciones[-1], "Cabaña 1")
        self.assertEqual(sistema.tarifas[-1], 85000)
        self.assertEqual(len(sistema.matriz_disponibilidad), 5)
        self.assertEqual(sistema.matriz_disponibilidad[-1], [0] * 30)

        # Verificar persistencia al recargar
        sistema_recargado = NexoPMS(db=self.fake_db)
        self.assertIn("Cabaña 1", sistema_recargado.habitaciones)
        idx_cab = sistema_recargado.habitaciones.index("Cabaña 1")
        self.assertEqual(sistema_recargado.tipos_habitaciones[idx_cab], "Cabaña")
        self.assertEqual(sistema_recargado.tarifas[idx_cab], 85000)

    def test_13_editar_alojamiento_preserva_reservas_existentes(self):
        """R2.2/AC5: Editar tipo/nombre/tarifa preserva datos y tarifa de reservas existentes."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        # 1. Crear reserva existente en habitación 103 ($60,000/noche, 2 noches + desayuno + estac = $146,000)
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(
            "103\n1\n2\n11.111.111-1\nAna\n9999\ns\ns\ns\n"
        )):
            sistema.registrar_reserva()

        self.assertEqual(len(sistema.reservas), 1)
        self.assertEqual(sistema.reservas[0].total, 146000)

        # 2. Editar 103 (ítem 3) -> Cabaña / Cabaña 3 / $90,000 y luego crear nueva reserva en Cabaña 3
        script_admin = (
            "admin\nadmin123\n"
            "5\n"           # Admin
            "3\n"           # Editar
            "3\n"           # Lista #3 (103)
            "2\n"           # Cabaña
            "Cabaña 3\n"    # Nuevo identificador
            "90000\n"       # Nueva tarifa
            "5\n"           # Volver
            "3\n"           # Nueva reserva con tarifa actualizada
            "Cabaña 3\n10\n2\n22.222.222-2\nLuis\n8888\nn\nn\ns\n"
            "4\n"           # Ver reservas activas
            "7\n"           # Salir
        )
        buffer = io.StringIO()
        with patch("sys.stdout", buffer), patch("sys.stdin", io.StringIO(script_admin)):
            sistema.iniciar()
        output = buffer.getvalue()

        self.assertIn("Cabaña 'Cabaña 3' actualizada exitosamente.", output)
        self.assertEqual(len(sistema.reservas), 2)

        # Reserva previa conserva tarifa y datos originales
        reserva_previa = sistema.reservas[0]
        self.assertEqual(reserva_previa.total, 146000)
        self.assertEqual(reserva_previa.habitacion_nombre, "103")
        self.assertEqual(reserva_previa.tipo_alojamiento, "Habitación")
        self.assertEqual(reserva_previa.tarifa_base_snapshot, 60000)

        # Nueva reserva usa la tarifa actualizada ($90,000 * 2 = $180,000)
        reserva_nueva = sistema.reservas[1]
        self.assertEqual(reserva_nueva.total, 180000)
        self.assertEqual(reserva_nueva.habitacion_nombre, "Cabaña 3")
        self.assertEqual(reserva_nueva.tipo_alojamiento, "Cabaña")

        # En consola se preserva la etiqueta/total original de Ana y la nueva de Luis
        self.assertIn("Huésped: Ana (RUT: 11.111.111-1) | Habitación: 103", output)
        self.assertIn("Total: $146,000", output)
        self.assertIn("Huésped: Luis (RUT: 22.222.222-2) | Cabaña: Cabaña 3", output)
        self.assertIn("Total: $180,000", output)

    def test_14_eliminar_bloqueado_con_reserva_u_ocupacion(self):
        """R2.3/AC6: Bloquea eliminación cuando hay reserva activa o día ocupado en matriz."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        sistema.usuario_actual = {"id_usuario": 1, "username": "admin", "rol": "admin"}

        # Reservar habitación 103 (ítem 3)
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(
            "103\n1\n2\n1-9\nPedro\n1234\nn\nn\ns\n"
        )):
            sistema.registrar_reserva()

        # Marcar manualmente ocupación en 102 (ítem 2) sin reserva formal
        sistema.matriz_disponibilidad[1][4] = 1

        buf1 = io.StringIO()
        with patch("sys.stdout", buf1), patch("sys.stdin", io.StringIO("3\n")):
            sistema.eliminar_alojamiento()
        self.assertIn("No se puede eliminar '103'", buf1.getvalue())

        buf2 = io.StringIO()
        with patch("sys.stdout", buf2), patch("sys.stdin", io.StringIO("2\n")):
            sistema.eliminar_alojamiento()
        self.assertIn("No se puede eliminar '102'", buf2.getvalue())

        self.assertEqual(sistema.habitaciones, ["101", "102", "103", "104"])

    def test_15_eliminar_libre_y_consistencia_habitacion_idx(self):
        """R2.3/AC6: Eliminar alojamiento libre sincroniza BD/vectores/matriz y preserva habitacion_idx."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        # Crear reservas activas en índice 1 ("102") e índice 2 ("103"), dejando índice 0 ("101") libre
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(
            "102\n2\n2\n11.111.111-1\nCarla\n5551\nn\nn\ns\n"
            "103\n5\n3\n22.222.222-2\nDiego\n5552\ns\nn\ns\n"
        )):
            sistema.registrar_reserva()
            sistema.registrar_reserva()

        sistema.usuario_actual = {"id_usuario": 1, "username": "admin", "rol": "admin"}
        buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.stdin", io.StringIO("1\n")):
            sistema.eliminar_alojamiento()

        self.assertIn("Alojamiento eliminado exitosamente.", buf.getvalue())
        self.assertEqual(sistema.habitaciones, ["102", "103", "104"])
        self.assertEqual(sistema.ids_habitaciones, [2, 3, 4])
        self.assertEqual(len(sistema.matriz_disponibilidad), 3)

        # Inmediatamente en memoria: habitacion_idx debe haberse decrementado de (1, 2) a (0, 1)
        self.assertEqual(sistema.reservas[0].habitacion_idx, 0)
        self.assertEqual(sistema.habitaciones[sistema.reservas[0].habitacion_idx], "102")
        self.assertEqual(sistema.reservas[1].habitacion_idx, 1)
        self.assertEqual(sistema.habitaciones[sistema.reservas[1].habitacion_idx], "103")

        # Al recargar desde BD simulada: índices y ocupación siguen alineados
        sistema2 = NexoPMS(db=self.fake_db)
        self.assertEqual(sistema2.habitaciones, ["102", "103", "104"])
        self.assertEqual(sistema2.reservas[0].habitacion_idx, 0)
        self.assertEqual(sistema2.reservas[1].habitacion_idx, 1)
        self.assertEqual(sistema2.matriz_disponibilidad[0][1], 1)
        self.assertEqual(sistema2.matriz_disponibilidad[1][4], 1)

        buf_activas = io.StringIO()
        with patch("sys.stdout", buf_activas):
            sistema2.ver_reservas_activas()
        salida_activas = buf_activas.getvalue()
        self.assertIn("Carla", salida_activas)
        self.assertIn("Habitación: 102", salida_activas)
        self.assertIn("Diego", salida_activas)
        self.assertIn("Habitación: 103", salida_activas)

    def test_16_robustez_inputs_invalidos_y_eof(self):
        """R3/AC7: Entradas inválidas, vacías, fuera de rango, EOFError y KeyboardInterrupt no caen."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        sistema.usuario_actual = {"id_usuario": 1, "username": "admin", "rol": "admin"}

        # Entradas inválidas en registrar_reserva seguidas de EOF
        buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.stdin", io.StringIO("101\nabc\n0\n35\n1\nabc\n0\n")):
            sistema.registrar_reserva()
        self.assertIn("Error: Ingrese un valor numérico entero válido.", buf.getvalue())

        # Entradas inválidas en agregar_alojamiento (tipo inválido, vacío, tarifa negativa/texto/overflow, EOF)
        buf_crud = io.StringIO()
        with patch("sys.stdout", buf_crud), patch("sys.stdin", io.StringIO("9\n1\n\n105\nabc\n-100\n999999999999\n")):
            sistema.agregar_alojamiento()
        out_crud = buf_crud.getvalue()
        self.assertIn("Error: Seleccione '1' (Habitación) o '2' (Cabaña).", out_crud)
        self.assertIn("Error: Este campo no puede estar vacío.", out_crud)
        self.assertIn("Error: El valor debe ser mayor o igual a 1.", out_crud)
        self.assertIn("Error: El valor debe ser menor o igual a 4294967295.", out_crud)

        # KeyboardInterrupt en iniciar() termina limpiamente sin propagar excepción
        with patch("sys.stdout", io.StringIO()), patch("builtins.input", side_effect=KeyboardInterrupt):
            sistema.iniciar()

        # EOF en iniciar_sesion() retorna False limpiamente
        sistema_eof = NexoPMS(db=self.fake_db)
        with patch("sys.stdout", io.StringIO()), patch("builtins.input", side_effect=EOFError):
            self.assertFalse(sistema_eof.iniciar_sesion())

        # ValueError en input() (ej. stdin cerrado) termina limpiamente sin bucle infinito
        sistema_val = NexoPMS(db=self.fake_db)
        with patch("sys.stdout", io.StringIO()), patch(
            "builtins.input", side_effect=ValueError("I/O operation on closed file")
        ) as mock_input:
            self.assertFalse(sistema_val.iniciar_sesion())
            self.assertEqual(mock_input.call_count, 1)

        with patch("sys.stdout", io.StringIO()), patch(
            "builtins.input", side_effect=ValueError("I/O operation on closed file")
        ) as mock_input:
            sistema_val.iniciar()
            self.assertEqual(mock_input.call_count, 1)
            self.assertIsNone(sistema_val.usuario_actual)

        # Con sesión iniciada, ValueError en el menú principal también sale limpiamente
        sistema_val_menu = NexoPMS(db=self.fake_db)
        sistema_val_menu.usuario_actual = {"id_usuario": 1, "username": "admin", "rol": "admin"}
        with patch("sys.stdout", io.StringIO()), patch(
            "builtins.input", side_effect=ValueError("I/O operation on closed file")
        ) as mock_input:
            sistema_val_menu.iniciar()
            self.assertEqual(mock_input.call_count, 1)

        # sys.stdin cerrado real en Python 3.14 no cuelga iniciar_sesion() ni iniciar()
        closed_stdin_1 = io.StringIO("")
        closed_stdin_1.close()
        sistema_closed = NexoPMS(db=self.fake_db)
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", closed_stdin_1):
            self.assertFalse(sistema_closed.iniciar_sesion())

        closed_stdin_2 = io.StringIO("")
        closed_stdin_2.close()
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", closed_stdin_2):
            sistema_closed.iniciar()
            self.assertIsNone(sistema_closed.usuario_actual)

    def test_17_conexion_db_hashing_y_sql_unit(self):
        """R1/R2/R3: Pruebas unitarias de PBKDF2 y métodos SQL de ConexionDB con mock."""
        h1 = hashear_password("secreto123")
        h2 = hashear_password("secreto123")
        self.assertNotEqual(h1, h2)  # Salts distintos
        self.assertTrue(verificar_password("secreto123", h1))
        self.assertFalse(verificar_password("otro", h1))
        self.assertFalse(verificar_password("secreto123", "formato_invalido"))

        # Mockear conexión MySQL para probar ConexionDB sin servidor vivo
        db = ConexionDB()
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(db, "conectar", return_value=mock_conn):
            # Simular autenticar_usuario exitoso sin ejecutar asegurar_esquema previo
            db._esquema_asegurado = True
            mock_cursor.fetchone.return_value = {
                "id_usuario": 1,
                "username": "admin",
                "password": hashear_password("admin123"),
                "rol": "admin",
                "activo": 1,
            }
            user = db.autenticar_usuario("admin", "admin123")
            self.assertEqual(user, {"id_usuario": 1, "username": "admin", "rol": "admin"})
            self.assertIsNone(db.autenticar_usuario("admin", "erronea"))
            self.assertIsNone(db.autenticar_usuario(123, "admin123"))

            # Simular agregar_habitacion
            mock_cursor.fetchone.return_value = None
            mock_cursor.lastrowid = 10
            ok, new_id, _ = db.agregar_habitacion("Cabaña", "Cabaña Bosque", 95000)
            self.assertTrue(ok)
            self.assertEqual(new_id, 10)
            mock_conn.commit.assert_called()

            # Simular eliminar_habitacion bloqueado por reserva activa
            mock_cursor.fetchone.side_effect = [(0,), (1,)]
            ok_del, msg_del = db.eliminar_habitacion(10)
            self.assertFalse(ok_del)
            self.assertIn("reservas activas", msg_del)

            # Simular eliminar_habitacion libre (sin ocupación ni reservas)
            mock_cursor.fetchone.side_effect = [(0,), (0,), (0,)]
            ok_del2, _ = db.eliminar_habitacion(10)
            self.assertTrue(ok_del2)

            # Simular asegurar_esquema usando INSERT IGNORE atómico para usuarios semilla
            mock_cursor.fetchone.side_effect = None
            mock_cursor.fetchall.side_effect = [[], []]
            self.assertTrue(db.asegurar_esquema())
            sql_ejecutado = " ".join(
                call.args[0] for call in mock_cursor.execute.call_args_list if call.args
            )
            self.assertIn("INSERT IGNORE INTO usuarios (username, password, rol)", sql_ejecutado)

        # Verificar que cargar_datos() limpia self.reservas si falla obtener_ocupacion_diaria()
        from huesped import Huesped
        from reserva import Reserva
        from nexopms import NexoPMS

        sistema_parcial = NexoPMS(db=self.fake_db)
        sistema_parcial.reservas.append(Reserva(Huesped("1-9", "Test", "123"), 0, 1, 1, 45000))
        with patch.object(self.fake_db, "obtener_ocupacion_diaria", side_effect=RuntimeError("fallo parcial")), patch(
            "sys.stdout", io.StringIO()
        ):
            sistema_parcial.cargar_datos()
        self.assertEqual(sistema_parcial.reservas, [])


if __name__ == "__main__":
    unittest.main()
