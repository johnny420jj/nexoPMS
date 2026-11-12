"""
Pruebas de verificación automatizadas (smoke tests) para NexoPMS.
Valida la importación modular, inicialización, lógica de negocio y persistencia
sin requerir interacción manual en consola.
"""

import io
import json
import os
import sys
import tempfile
import unittest


class TestNexoPMSSmoke(unittest.TestCase):
    def setUp(self):
        # Crear archivo temporal para aislar pruebas de persistencia
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.temp_file.close()
        self.test_json_path = self.temp_file.name
        if os.path.exists(self.test_json_path):
            os.remove(self.test_json_path)

    def tearDown(self):
        # Limpiar archivo temporal si fue generado
        if os.path.exists(self.test_json_path):
            try:
                os.remove(self.test_json_path)
            except OSError:
                pass

    def test_01_import_modules(self):
        """Valida que todos los módulos se importan correctamente sin dependencias circulares."""
        import huesped
        import reserva
        import nexopms
        import main

        self.assertTrue(hasattr(huesped, "Huesped"))
        self.assertTrue(hasattr(reserva, "Reserva"))
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

        d = r.to_dict()
        self.assertEqual(d["huesped"]["rut"], "12.345.678-9")
        self.assertEqual(d["habitacion_idx"], 1)
        self.assertEqual(d["total"], 135000)
        self.assertTrue(d["incluye_desayuno"])
        self.assertFalse(d["incluye_estacionamiento"])

    def test_04_nexopms_initialization(self):
        """Valida inicialización correcta de NexoPMS, vectores paralelos y matriz de 30 días."""
        from nexopms import NexoPMS

        sistema = NexoPMS(archivo_datos=self.test_json_path)
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

        sistema = NexoPMS(archivo_datos=self.test_json_path)
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
        """Valida doble validación, marcado de matriz, guardado y posterior carga en JSON."""
        from huesped import Huesped
        from reserva import Reserva
        from nexopms import NexoPMS

        sistema = NexoPMS(archivo_datos=self.test_json_path)
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

        # Confirmación exitosa con stdout silenciado
        buffer = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buffer
            exito = sistema.confirmar_y_guardar_reserva(nueva_reserva, 2, 10, 4)
        finally:
            sys.stdout = old_stdout

        self.assertTrue(exito)
        self.assertEqual(len(sistema.reservas), 1)

        # Validar celdas ocupadas en la matriz
        for d in range(10, 14):
            self.assertEqual(sistema.matriz_disponibilidad[2][d], 1)
        self.assertEqual(sistema.matriz_disponibilidad[2][9], 0)
        self.assertEqual(sistema.matriz_disponibilidad[2][14], 0)

        # Intento de reserva solapada debe fallar
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

        # Validar persistencia recargando desde archivo
        sistema2 = NexoPMS(archivo_datos=self.test_json_path)
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

        sistema = NexoPMS(archivo_datos=self.test_json_path)
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

        self.assertIn("=== SISTEMA NEXOPMS ===", output)
        self.assertIn("Cerrando NexoPMS... ¡Hasta pronto!", output)

    def test_08_registrar_reserva_interactivo_y_ver_activas(self):
        """Valida el flujo interactivo de registrar_reserva() con cotización y ver_reservas_activas()."""
        from nexopms import NexoPMS

        sistema = NexoPMS(archivo_datos=self.test_json_path)
        # Entradas: Hab 103, Día 1, 2 noches, RUT 1-9, Nombre Pedro, Fono 1234, Desayuno s, Estacionamiento s, Confirmar s
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
        self.assertIn("¡Reserva confirmada y guardada exitosamente!", output)
        # Habitación 103 cuesta 60000 + 5000 (desayuno) + 8000 (estacionamiento) = 73000 * 2 = 146000
        self.assertEqual(len(sistema.reservas), 1)
        self.assertEqual(sistema.reservas[0].total, 146000)
        self.assertTrue(sistema.reservas[0].incluye_desayuno)
        self.assertTrue(sistema.reservas[0].incluye_estacionamiento)

        # Probar ver_reservas_activas()
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
