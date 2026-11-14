"""
Pruebas de verificación automatizadas (smoke tests) para NexoPMS con arquitectura MySQL.
Valida la importación modular, inicialización, lógica de negocio y persistencia
sin requerir interacción manual en consola.
"""

import io
import sys
import unittest


class FakeConexionDB:
    """Simulador de ConexionDB en memoria para pruebas aisladas sin alterar la BD real."""

    def __init__(self):
        self.habitaciones = [
            {"id_habitacion": 1, "numero_habitacion": "101", "tarifa_base_noche": 45000},
            {"id_habitacion": 2, "numero_habitacion": "102", "tarifa_base_noche": 45000},
            {"id_habitacion": 3, "numero_habitacion": "103", "tarifa_base_noche": 60000},
            {"id_habitacion": 4, "numero_habitacion": "104", "tarifa_base_noche": 70000},
        ]
        self.ocupacion = []
        self.reservas = []
        self._next_id = 1

    def obtener_habitaciones_y_tarifas(self):
        return list(self.habitaciones)

    def obtener_ocupacion_diaria(self):
        return list(self.ocupacion)

    def obtener_reservas_activas(self):
        return list(self.reservas)

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
        """Valida que el bucle interactivo del menú principal inicie y termine limpiamente."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        buffer = io.StringIO()
        old_stdout = sys.stdout
        old_stdin = sys.stdin
        try:
            sys.stdout = buffer
            sys.stdin = io.StringIO("5\n")
            sistema.iniciar()
            output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stdin = old_stdin

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


if __name__ == "__main__":
    unittest.main()
