"""
Pruebas de verificación automatizadas (smoke tests) para NexoPMS con arquitectura MySQL.
Valida la importación modular, inicialización, lógica de negocio y persistencia
sin requerir interacción manual en consola.
"""

import io
import sys
import unittest
from unittest.mock import MagicMock, patch

from conexion import (
    ConexionDB,
    MAX_INT_UNSIGNED,
    SERVICIOS_SEMILLA,
    USUARIOS_SEMILLA,
    _parsear_entero,
    hashear_password,
    verificar_password,
)


class FakeConexionDB:
    """Simulador de ConexionDB en memoria para pruebas aisladas sin alterar la BD real."""

    def __init__(self):
        self.nombre_hotel = "Hotel Los Arrayanes"
        self.usuarios = []
        self.habitaciones = [
            {"id_habitacion": 1, "tipo": "Habitación", "numero_habitacion": "101", "tarifa_base_noche": 45000, "activa": 1},
            {"id_habitacion": 2, "tipo": "Habitación", "numero_habitacion": "102", "tarifa_base_noche": 45000, "activa": 1},
            {"id_habitacion": 3, "tipo": "Habitación", "numero_habitacion": "103", "tarifa_base_noche": 60000, "activa": 1},
            {"id_habitacion": 4, "tipo": "Habitación", "numero_habitacion": "104", "tarifa_base_noche": 70000, "activa": 1},
        ]
        self.servicios = []
        self.reserva_servicios = []
        self.ocupacion = []
        self.reservas = []
        self._next_id = 1
        self._next_hab_id = 5
        self._next_user_id = 1
        self._next_servicio_id = 1
        self._seq_habitacion = 104
        self._seq_cabana = 0
        self.asegurar_esquema()

    def asegurar_esquema(self):
        existentes = {u["username"] for u in self.usuarios}
        for username, raw_pwd, rol in USUARIOS_SEMILLA:
            if username not in existentes:
                self.usuarios.append({
                    "id_usuario": self._next_user_id,
                    "username": username,
                    "password": hashear_password(raw_pwd),
                    "rol": rol,
                    "activo": 1,
                })
                self._next_user_id += 1
                existentes.add(username)

        servicios_existentes = {s["nombre"].strip().lower() for s in self.servicios}
        for nombre, costo, disponible in SERVICIOS_SEMILLA:
            if nombre.strip().lower() not in servicios_existentes:
                self.servicios.append({
                    "id_servicio": self._next_servicio_id,
                    "nombre": nombre,
                    "costo": int(costo),
                    "disponible": bool(disponible),
                })
                self._next_servicio_id += 1
                servicios_existentes.add(nombre.strip().lower())
        return True

    def autenticar_usuario(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        username_limpio = username.strip()
        if not username_limpio or not password:
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

    def obtener_nombre_hotel(self):
        return self.nombre_hotel

    def actualizar_nombre_hotel(self, nuevo_nombre):
        if not isinstance(nuevo_nombre, str) or not nuevo_nombre.strip() or len(nuevo_nombre.strip()) > 150:
            return False, "Nombre de hotel inválido."
        self.nombre_hotel = nuevo_nombre.strip()
        return True, f"Nombre del hotel actualizado a '{self.nombre_hotel}'."

    def obtener_ocupacion_diaria(self, mes=None, anio=None):
        resultado = []
        for o in self.ocupacion:
            if o.get("ocupada") != 1:
                continue
            if mes is not None and o.get("mes", 11) != int(mes):
                continue
            if anio is not None and o.get("anio", 2026) != int(anio):
                continue
            resultado.append(dict(o))
        return resultado

    def _obtener_servicios_de_reserva(self, id_reserva):
        return [
            {
                "id_servicio": int(s["id_servicio"]),
                "nombre": str(s["nombre_snapshot"]),
                "costo_unitario": int(s["costo_unitario_snapshot"]),
                "subtotal": int(s["subtotal"]),
            }
            for s in self.reserva_servicios
            if s["id_reserva"] == id_reserva
        ]

    def obtener_reservas_activas(self):
        resultado = []
        for r in sorted(self.reservas, key=lambda x: x["id_reserva"]):
            if r.get("estado") == "Confirmada":
                copia = dict(r)
                copia["servicios"] = self._obtener_servicios_de_reserva(r["id_reserva"])
                resultado.append(copia)
        return resultado

    def obtener_todas_las_reservas(self):
        resultado = []
        for r in sorted(self.reservas, key=lambda x: x["id_reserva"]):
            copia = dict(r)
            copia["servicios"] = self._obtener_servicios_de_reserva(r["id_reserva"])
            resultado.append(copia)
        return resultado

    def agregar_habitacion(self, tipo, numero_habitacion, tarifa_base_noche):
        if tipo not in ("Habitación", "Cabaña"):
            return False, None, "Tipo de alojamiento inválido."
        ident = (
            numero_habitacion.strip()
            if isinstance(numero_habitacion, str)
            else (str(numero_habitacion).strip() if numero_habitacion is not None else "")
        )
        if not ident or len(ident) > 50:
            return False, None, "Identificador inválido."
        tarifa = _parsear_entero(tarifa_base_noche, minimo=1, maximo=MAX_INT_UNSIGNED)
        if tarifa is None:
            return False, None, "La tarifa base debe ser un número entero entre 1 y 4294967295."

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

    def agregar_alojamientos_por_secuencia(self, tipo_local, cantidad, tarifa_base_noche):
        if tipo_local not in ("Hotel", "Cabaña"):
            return False, [], "Tipo de local inválido."
        cant = _parsear_entero(cantidad, minimo=1, maximo=100)
        if cant is None:
            return False, [], "Cantidad inválida."
        tarifa = _parsear_entero(tarifa_base_noche, minimo=1, maximo=MAX_INT_UNSIGNED)
        if tarifa is None:
            return False, [], "Tarifa inválida."
        es_hotel = (tipo_local == "Hotel")
        tipo_unidad = "Habitación" if es_hotel else "Cabaña"
        creados = []
        for _ in range(cant):
            while True:
                if es_hotel:
                    self._seq_habitacion += 1
                    ident = str(self._seq_habitacion)
                else:
                    self._seq_cabana += 1
                    ident = f"Cabaña {self._seq_cabana}"
                ok, _, _ = self.agregar_habitacion(tipo_unidad, ident, tarifa)
                if ok:
                    creados.append(ident)
                    break
        etiqueta = "habitación(es)" if es_hotel else "cabaña(s)"
        return True, creados, f"Se generaron {len(creados)} {etiqueta} por secuencia SQL: {', '.join(creados)}."

    def editar_habitacion(self, id_habitacion, tipo, numero_habitacion, tarifa_base_noche):
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_hab is None:
            return False, "Identificador de alojamiento inválido."
        if tipo not in ("Habitación", "Cabaña"):
            return False, "Tipo de alojamiento inválido."
        ident = (
            numero_habitacion.strip()
            if isinstance(numero_habitacion, str)
            else (str(numero_habitacion).strip() if numero_habitacion is not None else "")
        )
        if not ident or len(ident) > 50:
            return False, "Identificador inválido."
        tarifa = _parsear_entero(tarifa_base_noche, minimo=1, maximo=MAX_INT_UNSIGNED)
        if tarifa is None:
            return False, "La tarifa base debe ser un número entero entre 1 y 4294967295."

        objetivo = next(
            (h for h in self.habitaciones if h["id_habitacion"] == id_hab and h.get("activa", 1) == 1),
            None,
        )
        if objetivo is None:
            return False, "El alojamiento seleccionado no existe o no está activo."

        if any(
            h["id_habitacion"] != id_hab and h["numero_habitacion"].strip().lower() == ident.lower()
            for h in self.habitaciones
        ):
            return False, f"Ya existe otro alojamiento con el identificador '{ident}'."

        objetivo["tipo"] = tipo
        objetivo["numero_habitacion"] = ident
        objetivo["tarifa_base_noche"] = tarifa
        return True, f"{tipo} '{ident}' actualizada exitosamente."

    def eliminar_habitacion(self, id_habitacion):
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_hab is None:
            return False, "Identificador de alojamiento inválido."
        if any(o["id_habitacion"] == id_hab and o.get("ocupada") == 1 for o in self.ocupacion):
            return False, "No se puede eliminar: el alojamiento tiene días ocupados registrados."
        if any(r["id_habitacion"] == id_hab and r.get("estado") == "Confirmada" for r in self.reservas):
            return False, "No se puede eliminar: el alojamiento tiene reservas activas."

        tiene_historicas = any(r["id_habitacion"] == id_hab for r in self.reservas)
        if tiene_historicas:
            for h in self.habitaciones:
                if h["id_habitacion"] == id_hab:
                    h["activa"] = 0
                    return True, "Alojamiento eliminado exitosamente."
            return False, "El alojamiento seleccionado no existe."
        antes = len(self.habitaciones)
        self.habitaciones = [h for h in self.habitaciones if h["id_habitacion"] != id_hab]
        if len(self.habitaciones) == antes:
            return False, "El alojamiento seleccionado no existe."
        return True, "Alojamiento eliminado exitosamente."

    def obtener_servicios(self, solo_disponibles=False):
        return [
            {
                "id_servicio": int(s["id_servicio"]),
                "nombre": str(s["nombre"]),
                "costo": int(s["costo"]),
                "disponible": bool(s["disponible"]),
            }
            for s in sorted(self.servicios, key=lambda x: x["id_servicio"])
            if not solo_disponibles or bool(s["disponible"])
        ]

    def crear_servicio(self, nombre, costo, disponible=True):
        if not isinstance(nombre, str):
            return False, None, "El nombre del servicio debe ser una cadena de texto."
        nombre_limpio = nombre.strip()
        if not nombre_limpio or len(nombre_limpio) > 100:
            return False, None, "El nombre del servicio debe tener entre 1 y 100 caracteres."
        costo_val = _parsear_entero(costo, minimo=1, maximo=MAX_INT_UNSIGNED)
        if costo_val is None:
            return False, None, "El costo del servicio debe ser un entero entre 1 y 4294967295."
        if any(s["nombre"].strip().lower() == nombre_limpio.lower() for s in self.servicios):
            return False, None, f"Ya existe un servicio con el nombre '{nombre_limpio}'."

        nuevo_id = self._next_servicio_id
        self._next_servicio_id += 1
        self.servicios.append({
            "id_servicio": nuevo_id,
            "nombre": nombre_limpio,
            "costo": costo_val,
            "disponible": bool(disponible),
        })
        return True, nuevo_id, f"Servicio '{nombre_limpio}' creado exitosamente."

    def editar_servicio(self, id_servicio, nombre, costo):
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

        objetivo = next((s for s in self.servicios if s["id_servicio"] == id_srv), None)
        if objetivo is None:
            return False, "El servicio seleccionado no existe."
        if any(
            s["id_servicio"] != id_srv and s["nombre"].strip().lower() == nombre_limpio.lower()
            for s in self.servicios
        ):
            return False, f"Ya existe otro servicio con el nombre '{nombre_limpio}'."

        objetivo["nombre"] = nombre_limpio
        objetivo["costo"] = costo_val
        return True, f"Servicio '{nombre_limpio}' actualizado exitosamente."

    def cambiar_disponibilidad_servicio(self, id_servicio, disponible=None):
        id_srv = _parsear_entero(id_servicio, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_srv is None:
            return False, None, "Identificador de servicio inválido."
        for s in self.servicios:
            if s["id_servicio"] == id_srv:
                nuevo_estado = (not bool(s["disponible"])) if disponible is None else bool(disponible)
                s["disponible"] = nuevo_estado
                estado_txt = "habilitado" if nuevo_estado else "deshabilitado"
                return True, nuevo_estado, f"Servicio '{s['nombre']}' {estado_txt} exitosamente."
        return False, None, "El servicio seleccionado no existe."

    def verificar_disponibilidad_db(self, id_habitacion, dia_inicio_bd, dias_estadia, excluir_id_reserva=None, mes=None, anio=None):
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

        dia_fin_bd = dia_ini + dias - 1
        for reg in self.ocupacion:
            if mes is not None and reg.get("mes", 11) != int(mes):
                continue
            if anio is not None and reg.get("anio", 2026) != int(anio):
                continue
            if (
                reg["id_habitacion"] == id_hab
                and dia_ini <= reg["dia_mes"] <= dia_fin_bd
                and reg["ocupada"] == 1
            ):
                if excluir_id is not None and reg.get("id_reserva") == excluir_id:
                    continue
                return False
        return True

    def _resolver_servicios_fake(self, servicios, dias_estadia, incluye_desayuno=False, incluye_estacionamiento=False):
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
                    match = next(
                        (s for s in self.servicios if s["nombre"].strip().lower() == nombre.lower()),
                        None,
                    )
                    if match is None:
                        raise ValueError(f"El servicio '{nombre}' no existe en el catálogo.")
                    id_srv = int(match["id_servicio"])
                    if not nombre:
                        nombre = str(match["nombre"])
                    if raw_costo is None:
                        raw_costo = match["costo"]
                else:
                    match = next((s for s in self.servicios if s["id_servicio"] == id_srv), None)
                    if match is None:
                        raise ValueError(f"El servicio con ID {id_srv} no existe en el catálogo.")

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
            for s in sorted(self.servicios, key=lambda x: x["id_servicio"]):
                nl = s["nombre"].strip().lower()
                incluir = (
                    (incluye_desayuno and "desayuno" in nl)
                    or (incluye_estacionamiento and "estacionamiento" in nl)
                )
                if incluir and s["id_servicio"] not in vistos:
                    vistos.add(s["id_servicio"])
                    resueltos.append({
                        "id_servicio": int(s["id_servicio"]),
                        "nombre": str(s["nombre"]),
                        "costo_unitario": int(s["costo"]),
                        "subtotal": int(s["costo"]) * dias_estadia,
                    })
        return resueltos

    def _upsert_ocupacion_fake(self, id_habitacion, dia_mes, id_reserva, mes=11, anio=2026):
        for reg in self.ocupacion:
            if (
                reg["id_habitacion"] == id_habitacion
                and reg.get("mes", 11) == mes
                and reg.get("anio", 2026) == anio
                and reg["dia_mes"] == dia_mes
            ):
                reg["ocupada"] = 1
                reg["id_reserva"] = id_reserva
                return
        self.ocupacion.append({
            "id_habitacion": id_habitacion,
            "anio": anio,
            "mes": mes,
            "dia_mes": dia_mes,
            "ocupada": 1,
            "id_reserva": id_reserva,
        })

    def guardar_reserva_transaccional(self, nueva_reserva, id_habitacion, mes=None, anio=None):
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
        if not any(h["id_habitacion"] == id_hab for h in self.habitaciones):
            return False
        if not self.verificar_disponibilidad_db(id_hab, dia_inicio_bd, dias, mes=mes_val, anio=anio_val):
            return False

        servicios_actuales = list(getattr(nueva_reserva, "servicios", []) or [])
        try:
            servicios_resueltos = self._resolver_servicios_fake(
                servicios_actuales,
                dias,
                incluye_desayuno=bool(nueva_reserva.incluye_desayuno),
                incluye_estacionamiento=bool(nueva_reserva.incluye_estacionamiento),
            )
        except ValueError:
            return False

        id_reserva = self._next_id
        self._next_id += 1
        self.reservas.append({
            "id_reserva": id_reserva,
            "id_habitacion": id_hab,
            "anio": anio_val,
            "mes": mes_val,
            "dia_inicio": dia_inicio_bd,
            "dias_estadia": dias,
            "incluye_desayuno": 1 if nueva_reserva.incluye_desayuno else 0,
            "incluye_estacionamiento": 1 if nueva_reserva.incluye_estacionamiento else 0,
            "monto_total": total_val,
            "estado": nueva_reserva.estado,
            "habitacion_nombre": getattr(nueva_reserva, "habitacion_nombre", None),
            "tipo_alojamiento": getattr(nueva_reserva, "tipo_alojamiento", None),
            "tarifa_base_snapshot": getattr(nueva_reserva, "tarifa_base_snapshot", None),
            "rut": nueva_reserva.huesped.rut,
            "nombre": nueva_reserva.huesped.nombre,
            "telefono": nueva_reserva.huesped.telefono,
        })
        for srv in servicios_resueltos:
            self.reserva_servicios.append({
                "id_reserva": id_reserva,
                "id_servicio": srv["id_servicio"],
                "nombre_snapshot": srv["nombre"],
                "costo_unitario_snapshot": srv["costo_unitario"],
                "subtotal": srv["subtotal"],
            })
        for d_offset in range(dias):
            self._upsert_ocupacion_fake(id_hab, dia_inicio_bd + d_offset, id_reserva, mes=mes_val, anio=anio_val)
        nueva_reserva.id_reserva = id_reserva
        if not servicios_actuales and servicios_resueltos:
            nueva_reserva.servicios = [dict(s) for s in servicios_resueltos]
        return True

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
    ):
        id_res = _parsear_entero(id_reserva, minimo=1, maximo=MAX_INT_UNSIGNED)
        id_hab = _parsear_entero(id_habitacion, minimo=1, maximo=MAX_INT_UNSIGNED)
        dia_ini = _parsear_entero(dia_inicio_bd, minimo=1, maximo=30)
        dias = _parsear_entero(dias_estadia, minimo=1, maximo=30)
        total_val = _parsear_entero(monto_total, minimo=0, maximo=MAX_INT_UNSIGNED)

        if id_res is None or id_hab is None or dia_ini is None or dias is None or total_val is None:
            return False, "Parámetros inválidos para editar la reserva."
        dia_fin = dia_ini + dias - 1
        if dia_fin > 30:
            return False, "El rango de días excede el límite del mes (1..30)."

        res = next((r for r in self.reservas if r["id_reserva"] == id_res), None)
        if res is None:
            return False, "La reserva seleccionada no existe."
        if res.get("estado") != "Confirmada":
            return False, "Solo se pueden editar reservas en estado 'Confirmada'."

        hab = next(
            (h for h in self.habitaciones if h["id_habitacion"] == id_hab and h.get("activa", 1) == 1),
            None,
        )
        if hab is None:
            return False, "El alojamiento seleccionado no existe o no está activo."

        if not self.verificar_disponibilidad_db(id_hab, dia_ini, dias, excluir_id_reserva=id_res):
            return False, "El alojamiento no está disponible para las fechas seleccionadas."

        try:
            servicios_norm = self._resolver_servicios_fake(servicios or [], dias)
        except ValueError as e:
            return False, str(e)

        nombres_lower = [s["nombre"].strip().lower() for s in servicios_norm]
        res["id_habitacion"] = id_hab
        res["dia_inicio"] = dia_ini
        res["dias_estadia"] = dias
        res["monto_total"] = total_val
        res["incluye_desayuno"] = 1 if any("desayuno" in n for n in nombres_lower) else 0
        res["incluye_estacionamiento"] = 1 if any("estacionamiento" in n for n in nombres_lower) else 0
        res["habitacion_nombre"] = habitacion_nombre if habitacion_nombre is not None else hab["numero_habitacion"]
        res["tipo_alojamiento"] = tipo_alojamiento if tipo_alojamiento is not None else hab["tipo"]
        res["tarifa_base_snapshot"] = (
            tarifa_base_snapshot if tarifa_base_snapshot is not None else int(hab["tarifa_base_noche"])
        )

        self.ocupacion = [o for o in self.ocupacion if o.get("id_reserva") != id_res]
        for d_offset in range(dias):
            self._upsert_ocupacion_fake(id_hab, dia_ini + d_offset, id_res)

        self.reserva_servicios = [s for s in self.reserva_servicios if s["id_reserva"] != id_res]
        for srv in servicios_norm:
            self.reserva_servicios.append({
                "id_reserva": id_res,
                "id_servicio": srv["id_servicio"],
                "nombre_snapshot": srv["nombre"],
                "costo_unitario_snapshot": srv["costo_unitario"],
                "subtotal": srv["subtotal"],
            })
        return True, "Reserva actualizada exitosamente."

    def cancelar_reserva_transaccional(self, id_reserva):
        id_res = _parsear_entero(id_reserva, minimo=1, maximo=MAX_INT_UNSIGNED)
        if id_res is None:
            return False, "Identificador de reserva inválido."
        res = next((r for r in self.reservas if r["id_reserva"] == id_res), None)
        if res is None:
            return False, "La reserva seleccionada no existe."
        if res.get("estado") != "Confirmada":
            return False, "Solo se pueden cancelar reservas en estado 'Confirmada'."

        res["estado"] = "Cancelada"
        self.ocupacion = [o for o in self.ocupacion if o.get("id_reserva") != id_res]
        return True, "Reserva cancelada exitosamente."


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
        """R1/AC1: Verifica usuarios semilla admin, gerente y recepcion con contraseñas hasheadas e idempotencia."""
        usernames = {u["username"]: u for u in self.fake_db.usuarios}
        self.assertIn("admin", usernames)
        self.assertIn("gerente", usernames)
        self.assertIn("recepcion", usernames)
        self.assertEqual(usernames["admin"]["rol"], "admin")
        self.assertEqual(usernames["gerente"]["rol"], "gerente")
        self.assertEqual(usernames["recepcion"]["rol"], "recepcionista")

        self.assertNotEqual(usernames["admin"]["password"], "admin123")
        self.assertNotEqual(usernames["gerente"]["password"], "gerente123")
        self.assertNotEqual(usernames["recepcion"]["password"], "recep123")
        self.assertTrue(usernames["admin"]["password"].startswith("pbkdf2_sha256$"))
        self.assertTrue(usernames["gerente"]["password"].startswith("pbkdf2_sha256$"))
        self.assertTrue(usernames["recepcion"]["password"].startswith("pbkdf2_sha256$"))

        self.fake_db.asegurar_esquema()
        self.assertEqual(len(self.fake_db.usuarios), 3)

        auth_admin = self.fake_db.autenticar_usuario("admin", "admin123")
        auth_gerente = self.fake_db.autenticar_usuario("gerente", "gerente123")
        auth_recep = self.fake_db.autenticar_usuario("recepcion", "recep123")
        self.assertIsNotNone(auth_admin)
        self.assertEqual(auth_admin["rol"], "admin")
        self.assertIsNotNone(auth_gerente)
        self.assertEqual(auth_gerente["rol"], "gerente")
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
            "admin\nmal\nadmin\nadmin123\n5\n"
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
        # Inicia como recepcionista, intenta opción 9 (inválida para recepcionista),
        # luego elige 5 (Cerrar sesión / Cambiar de usuario), inicia como admin, ve los 3 módulos y sale con 5.
        script = (
            "recepcion\nrecep123\n"
            "9\n"
            "5\n"
            "admin\nadmin123\n"
            "5\n"
        )
        buffer = io.StringIO()
        with patch("sys.stdout", buffer), patch("sys.stdin", io.StringIO(script)):
            sistema.iniciar()
        output = buffer.getvalue()

        parte_recep, parte_admin = output.split("Cerrando sesión de 'recepcion'...")
        self.assertNotIn("Módulo Administración", parte_recep)
        self.assertIn("Opción inválida", parte_recep)
        self.assertIn("1. Módulo Administración", parte_admin)
        self.assertIn("2. Módulo Gerencia", parte_admin)
        self.assertIn("3. Módulo Recepción", parte_admin)

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
            "1\n"            # Módulo Administración
            "2\n"            # Agregar alojamiento
            "2\n"            # Cabaña
            "Cabaña 1\n"     # Identificador
            "85000\n"        # Tarifa
            "2\n"            # Intentar duplicado insensible a mayúsculas
            "2\n"
            "cabaña 1\n"
            "7\n"            # Volver al menú principal
            "3\n"            # Módulo Recepción
            "2\n"            # Consultar tarifas
            "1\n"            # Consultar matriz de disponibilidad
            "8\n"            # Volver al menú principal
            "5\n"            # Salir
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
            "1\n"           # Módulo Administración
            "3\n"           # Editar
            "3\n"           # Lista #3 (103)
            "2\n"           # Cabaña
            "Cabaña 3\n"    # Nuevo identificador
            "90000\n"       # Nueva tarifa
            "7\n"           # Volver al menú principal
            "3\n"           # Módulo Recepción
            "3\n"           # Nueva reserva con tarifa actualizada
            "Cabaña 3\n10\n2\n22.222.222-2\nLuis\n8888\nn\nn\ns\n"
            "6\n"           # Ver reservas activas
            "8\n"           # Volver al menú principal
            "5\n"           # Salir
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

            # Simular asegurar_esquema usando INSERT IGNORE atómico para usuarios y servicios semilla
            mock_cursor.fetchone.side_effect = None
            mock_cursor.fetchone.return_value = None
            mock_cursor.fetchall.side_effect = None
            mock_cursor.fetchall.return_value = []
            self.assertTrue(db.asegurar_esquema())
            sql_ejecutado = " ".join(
                call.args[0] for call in mock_cursor.execute.call_args_list if call.args
            )
            self.assertIn("INSERT IGNORE INTO usuarios (username, password, rol)", sql_ejecutado)
            self.assertIn("CREATE TABLE IF NOT EXISTS servicios", sql_ejecutado)
            self.assertIn("INSERT IGNORE INTO servicios (nombre, costo, disponible)", sql_ejecutado)

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

    def test_18_reserva_model_m1_id_y_servicios(self):
        """M1/F4: Reserva soporta id_reserva, servicios normalizados, auto-sync y retrocompatibilidad."""
        from huesped import Huesped
        from reserva import Reserva

        h = Huesped("15.111.222-3", "Camila Rojas", "+56977778888")

        # Llamada heredada sin servicios conserva booleanos
        r_legacy = Reserva(h, 0, 2, 3, 150000, incluye_desayuno=True, incluye_estacionamiento=False)
        self.assertIsNone(r_legacy.id_reserva)
        self.assertEqual(r_legacy.servicios, [])
        self.assertTrue(r_legacy.incluye_desayuno)
        self.assertFalse(r_legacy.incluye_estacionamiento)
        d_legacy = r_legacy.to_dict()
        self.assertIsNone(d_legacy["id_reserva"])
        self.assertEqual(d_legacy["servicios"], [])

        # Llamada con servicios (incluyendo claves snapshot y sin subtotal) normaliza y sincroniza flags
        entrada_servicios = [
            {"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": 5000},
            {"id_servicio": 2, "nombre_snapshot": "ESTACIONAMIENTO VIP", "costo_unitario_snapshot": 8000, "subtotal": 16000},
        ]
        r_m1 = Reserva(
            h,
            1,
            4,
            2,
            116000,
            incluye_desayuno=False,
            incluye_estacionamiento=False,
            id_reserva=42,
            servicios=entrada_servicios,
        )
        self.assertEqual(r_m1.id_reserva, 42)
        self.assertTrue(r_m1.incluye_desayuno)
        self.assertTrue(r_m1.incluye_estacionamiento)
        self.assertEqual(len(r_m1.servicios), 2)
        self.assertEqual(r_m1.servicios[0], {
            "id_servicio": 1,
            "nombre": "Desayuno",
            "costo_unitario": 5000,
            "subtotal": 10000,
        })
        self.assertEqual(r_m1.servicios[1], {
            "id_servicio": 2,
            "nombre": "ESTACIONAMIENTO VIP",
            "costo_unitario": 8000,
            "subtotal": 16000,
        })

        # Copia defensiva en constructor y to_dict()
        entrada_servicios[0]["costo_unitario"] = 999999
        self.assertEqual(r_m1.servicios[0]["costo_unitario"], 5000)
        d_m1 = r_m1.to_dict()
        d_m1["servicios"][0]["nombre"] = "Mutado"
        self.assertEqual(r_m1.servicios[0]["nombre"], "Desayuno")

    def test_19_autenticacion_tres_roles_e_inactivos(self):
        """M1/F1: Autenticación de admin, gerente, recepcionista y rechazo de usuarios inactivos."""
        for username, pwd, rol_esp in USUARIOS_SEMILLA:
            res = self.fake_db.autenticar_usuario(f"  {username}  ", pwd)
            self.assertIsNotNone(res)
            self.assertEqual(res["username"], username)
            self.assertEqual(res["rol"], rol_esp)

        # Usuario inactivo no puede autenticarse
        for u in self.fake_db.usuarios:
            if u["username"] == "gerente":
                u["activo"] = 0
        self.assertIsNone(self.fake_db.autenticar_usuario("gerente", "gerente123"))

    def test_20_servicios_crud_y_disponibilidad(self):
        """M1/F3: CRUD de servicios escalables, validaciones, unicidad y toggle de disponibilidad."""
        servicios_iniciales = self.fake_db.obtener_servicios()
        self.assertEqual(len(servicios_iniciales), 2)
        self.assertEqual(servicios_iniciales[0]["nombre"], "Desayuno")
        self.assertEqual(servicios_iniciales[0]["costo"], 5000)
        self.assertTrue(servicios_iniciales[0]["disponible"])
        self.assertEqual(servicios_iniciales[1]["nombre"], "Estacionamiento")
        self.assertEqual(servicios_iniciales[1]["costo"], 8000)

        # Validaciones de rechazo (duplicado, booleano, vacío, overflow)
        ok_dup, id_dup, _ = self.fake_db.crear_servicio("desayuno", 6000)
        self.assertFalse(ok_dup)
        self.assertIsNone(id_dup)
        self.assertFalse(self.fake_db.crear_servicio("Spa", True)[0])
        self.assertFalse(self.fake_db.crear_servicio("   ", 5000)[0])
        self.assertFalse(self.fake_db.crear_servicio("Spa", 5000000000)[0])

        # Crear servicio válido
        ok_crea, id_spa, _ = self.fake_db.crear_servicio("Spa Termal", 15000)
        self.assertTrue(ok_crea)
        self.assertEqual(id_spa, 3)

        # Editar servicio válido y rechazo de nombre duplicado
        ok_ed, _ = self.fake_db.editar_servicio(id_spa, "Spa Premium", 18000)
        self.assertTrue(ok_ed)
        self.assertFalse(self.fake_db.editar_servicio(id_spa, "Desayuno", 18000)[0])

        # Toggle de disponibilidad y filtro solo_disponibles
        ok_tog, nuevo_est, _ = self.fake_db.cambiar_disponibilidad_servicio(id_spa)
        self.assertTrue(ok_tog)
        self.assertFalse(nuevo_est)
        self.assertEqual(len(self.fake_db.obtener_servicios(solo_disponibles=True)), 2)
        self.assertEqual(len(self.fake_db.obtener_servicios(solo_disponibles=False)), 3)

        ok_set, est_set, _ = self.fake_db.cambiar_disponibilidad_servicio(id_spa, disponible=True)
        self.assertTrue(ok_set)
        self.assertTrue(est_set)
        self.assertEqual(len(self.fake_db.obtener_servicios(solo_disponibles=True)), 3)

    def test_21_guardar_reserva_con_servicios_y_snapshots(self):
        """M1/F3/F4: guardar_reserva_transaccional asigna id_reserva y congela snapshots ante ediciones."""
        from huesped import Huesped
        from reserva import Reserva

        _, id_spa, _ = self.fake_db.crear_servicio("Spa", 15000)
        h = Huesped("16.555.666-7", "Sofía Pérez", "+56944445555")
        r = Reserva(
            h,
            habitacion_idx=0,
            dia_inicio=2,
            dias_estadia=2,
            total=120000,
            habitacion_nombre="101",
            tipo_alojamiento="Habitación",
            tarifa_base_snapshot=45000,
            servicios=[{"id_servicio": id_spa, "nombre": "Spa", "costo_unitario": 15000, "subtotal": 30000}],
        )
        self.assertTrue(self.fake_db.guardar_reserva_transaccional(r, id_habitacion=1))
        self.assertEqual(r.id_reserva, 1)

        # Editar catálogo de Spa después de guardar la reserva no debe alterar el snapshot guardado
        self.fake_db.editar_servicio(id_spa, "Spa Deluxe", 25000)
        activas = self.fake_db.obtener_reservas_activas()
        self.assertEqual(len(activas), 1)
        self.assertEqual(activas[0]["servicios"], [{
            "id_servicio": id_spa,
            "nombre": "Spa",
            "costo_unitario": 15000,
            "subtotal": 30000,
        }])

    def test_22_disponibilidad_excluir_reserva_y_editar_reserva(self):
        """M1/F4: verificar_disponibilidad_db(excluir_id_reserva) y editar_reserva_transaccional con rollback."""
        from huesped import Huesped
        from reserva import Reserva

        h1 = Huesped("11.111.111-1", "Huesped Uno", "+56911111111")
        h2 = Huesped("22.222.222-2", "Huesped Dos", "+56922222222")
        r1 = Reserva(h1, 0, 1, 3, 135000, servicios=[{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": 5000, "subtotal": 15000}])
        r2 = Reserva(h2, 0, 6, 2, 90000, servicios=[])
        self.assertTrue(self.fake_db.guardar_reserva_transaccional(r1, id_habitacion=1))
        self.assertTrue(self.fake_db.guardar_reserva_transaccional(r2, id_habitacion=1))

        # Días 2..4 (1-based) pertenecen a r1: conflicto sin excluir, disponible si se excluye r1
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1, 2, 3))
        self.assertTrue(self.fake_db.verificar_disponibilidad_db(1, 2, 3, excluir_id_reserva=r1.id_reserva))
        # Días 6..8 chocan con r2 (días 7..8 en 1-based) incluso excluyendo r1
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1, 6, 3, excluir_id_reserva=r1.id_reserva))

        # Intento fallido de editar r1 hacia días de r2 deja estado intacto
        ok_fail, _ = self.fake_db.editar_reserva_transaccional(
            r1.id_reserva, 1, 7, 2, 90000, []
        )
        self.assertFalse(ok_fail)
        r1_actual = next(r for r in self.fake_db.obtener_reservas_activas() if r["id_reserva"] == r1.id_reserva)
        self.assertEqual(r1_actual["dia_inicio"], 2)
        self.assertEqual(r1_actual["dias_estadia"], 3)

        # Edición exitosa cambiando de habitación 101 -> 102 y servicios -> Estacionamiento
        ok_edit, _ = self.fake_db.editar_reserva_transaccional(
            r1.id_reserva,
            2,
            10,
            2,
            106000,
            [{"id_servicio": 2, "nombre": "Estacionamiento", "costo_unitario": 8000, "subtotal": 16000}],
        )
        self.assertTrue(ok_edit)
        self.assertTrue(self.fake_db.verificar_disponibilidad_db(1, 2, 3))
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(2, 10, 2))
        r1_editada = next(r for r in self.fake_db.obtener_reservas_activas() if r["id_reserva"] == r1.id_reserva)
        self.assertEqual(r1_editada["id_habitacion"], 2)
        self.assertEqual(r1_editada["habitacion_nombre"], "102")
        self.assertEqual(r1_editada["incluye_desayuno"], 0)
        self.assertEqual(r1_editada["incluye_estacionamiento"], 1)
        self.assertEqual(len(r1_editada["servicios"]), 1)
        self.assertEqual(r1_editada["servicios"][0]["nombre"], "Estacionamiento")

    def test_23_cancelar_reserva_soft_delete_y_historial(self):
        """M1/F4: cancelar_reserva_transaccional marca Cancelada, libera ocupación y preserva historial."""
        from huesped import Huesped
        from reserva import Reserva

        h = Huesped("19.999.888-7", "Cliente Cancelar", "+56999998888")
        r = Reserva(
            h,
            habitacion_idx=0,
            dia_inicio=4,
            dias_estadia=2,
            total=100000,
            servicios=[{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": 5000, "subtotal": 10000}],
        )
        self.assertTrue(self.fake_db.guardar_reserva_transaccional(r, id_habitacion=1))
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1, 5, 2))

        ok_can, _ = self.fake_db.cancelar_reserva_transaccional(r.id_reserva)
        self.assertTrue(ok_can)
        self.assertTrue(self.fake_db.verificar_disponibilidad_db(1, 5, 2))
        self.assertEqual(self.fake_db.obtener_reservas_activas(), [])

        # Re-cancelar o editar una reserva cancelada debe fallar
        self.assertFalse(self.fake_db.cancelar_reserva_transaccional(r.id_reserva)[0])
        self.assertFalse(self.fake_db.editar_reserva_transaccional(r.id_reserva, 1, 5, 2, 100000, [])[0])

        # Historial completo conserva el registro y sus servicios
        historial = self.fake_db.obtener_todas_las_reservas()
        self.assertEqual(len(historial), 1)
        self.assertEqual(historial[0]["estado"], "Cancelada")
        self.assertEqual(historial[0]["monto_total"], 100000)
        self.assertEqual(len(historial[0]["servicios"]), 1)

    def test_24_conexion_db_m1_sql_unit(self):
        """M1/F1-F4: Pruebas unitarias SQL de ConexionDB (migración ENUM, servicios, editar, soft-delete)."""
        import re
        from mysql.connector import Error as MySQLError
        from huesped import Huesped
        from reserva import Reserva

        db = ConexionDB()
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(db, "conectar", return_value=mock_conn):
            # 1. asegurar_esquema migra usuarios.rol si falta 'gerente' y crea reserva_servicios
            mock_cursor.fetchone.side_effect = [{"COLUMN_TYPE": "enum('admin','recepcionista')"}]
            mock_cursor.fetchall.side_effect = [
                [],
                [{"COLUMN_NAME": "id_reserva", "COLUMN_TYPE": "int unsigned"}],
                [],
                [],
            ]
            self.assertTrue(db.asegurar_esquema())
            sql_mig = " ".join(
                c.args[0] for c in mock_cursor.execute.call_args_list if c.args
            )
            self.assertIn("ALTER TABLE usuarios", sql_mig)
            self.assertIn("MODIFY COLUMN rol ENUM('admin', 'gerente', 'recepcionista') NOT NULL", sql_mig)
            self.assertIn("CREATE TABLE IF NOT EXISTS servicios", sql_mig)
            self.assertIn("CREATE TABLE IF NOT EXISTS reserva_servicios", sql_mig)

            # 2. CRUD de servicios en ConexionDB
            db._esquema_asegurado = True
            mock_cursor.execute.reset_mock()
            mock_cursor.fetchone.side_effect = None
            mock_cursor.fetchall.side_effect = None
            mock_cursor.fetchall.return_value = [
                {"id_servicio": 1, "nombre": "Desayuno", "costo": 5000, "disponible": 1},
            ]
            srvs = db.obtener_servicios(solo_disponibles=True)
            self.assertEqual(srvs, [{"id_servicio": 1, "nombre": "Desayuno", "costo": 5000, "disponible": True}])

            mock_cursor.fetchone.return_value = None
            mock_cursor.lastrowid = 3
            ok_cs, id_cs, _ = db.crear_servicio("Spa", 15000)
            self.assertTrue(ok_cs)
            self.assertEqual(id_cs, 3)

            mock_cursor.fetchone.side_effect = [{"id_servicio": 3}, None]
            self.assertTrue(db.editar_servicio(3, "Spa VIP", 20000)[0])

            mock_cursor.fetchone.side_effect = None
            mock_cursor.fetchone.return_value = {"id_servicio": 3, "nombre": "Spa VIP", "disponible": 1}
            ok_td, est_td, _ = db.cambiar_disponibilidad_servicio(3)
            self.assertTrue(ok_td)
            self.assertFalse(est_td)

            # 3. verificar_disponibilidad_db con excluir_id_reserva
            mock_cursor.execute.reset_mock()
            mock_cursor.fetchone.return_value = (0,)
            self.assertTrue(db.verificar_disponibilidad_db(1, 5, 3, excluir_id_reserva=7))
            sql_disp, params_disp = mock_cursor.execute.call_args[0]
            self.assertIn("(id_reserva IS NULL OR id_reserva != %s)", sql_disp)
            self.assertEqual(params_disp, (1, 5, 7, 7))

            # 4. guardar_reserva_transaccional asigna id_reserva y escribe reserva_servicios + upsert
            mock_cursor.execute.reset_mock()
            mock_conn.commit.reset_mock()
            mock_cursor.fetchone.return_value = (0,)
            mock_cursor.lastrowid = 55
            res_obj = Reserva(
                Huesped("12.345.678-9", "Juan", "+56912345678"),
                0,
                1,
                2,
                100000,
                servicios=[{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": 5000, "subtotal": 10000}],
            )
            self.assertTrue(db.guardar_reserva_transaccional(res_obj, id_habitacion=1))
            self.assertEqual(res_obj.id_reserva, 55)
            sql_save = " ".join(c.args[0] for c in mock_cursor.execute.call_args_list if c.args)
            self.assertIn("FOR UPDATE", sql_save)
            self.assertIn("INSERT INTO reserva_servicios", sql_save)
            self.assertIn("ON DUPLICATE KEY UPDATE", sql_save)
            mock_conn.commit.assert_called()

            # 5. editar_reserva_transaccional éxito y rollback ante Error SQL
            mock_cursor.execute.reset_mock()
            mock_conn.commit.reset_mock()
            mock_cursor.fetchone.side_effect = [
                {"id_reserva": 55, "estado": "Confirmada"},
                {"id_habitacion": 2, "tipo": "Cabaña", "numero_habitacion": "C1", "tarifa_base_noche": 80000, "activa": 1},
                {"ocupadas": 0},
            ]
            ok_ed_tx, _ = db.editar_reserva_transaccional(
                55, 2, 10, 2, 170000,
                [{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": 5000, "subtotal": 10000}],
            )
            self.assertTrue(ok_ed_tx)
            mock_conn.commit.assert_called()

            mock_conn.rollback.reset_mock()
            mock_cursor.execute.side_effect = MySQLError("fallo simulado")
            ok_ed_err, _ = db.editar_reserva_transaccional(55, 2, 10, 2, 170000, [])
            self.assertFalse(ok_ed_err)
            mock_conn.rollback.assert_called()
            mock_cursor.execute.side_effect = None

            # 6. cancelar_reserva_transaccional: UPDATE estado='Cancelada' y CERO DELETE FROM reservas
            mock_cursor.execute.reset_mock()
            mock_cursor.fetchone.side_effect = [{"id_reserva": 55, "estado": "Confirmada"}]
            ok_can_tx, _ = db.cancelar_reserva_transaccional(55)
            self.assertTrue(ok_can_tx)
            sql_can = " ".join(c.args[0] for c in mock_cursor.execute.call_args_list if c.args)
            self.assertIn("UPDATE reservas SET estado = 'Cancelada'", sql_can)
            self.assertIn("DELETE FROM ocupacion_diaria WHERE id_reserva = %s", sql_can)
            self.assertIsNone(re.search(r"DELETE\s+FROM\s+reservas", sql_can, re.IGNORECASE))

            # 7. obtener_todas_las_reservas fusiona servicios desde reserva_servicios
            mock_cursor.fetchall.side_effect = [
                [
                    {"id_reserva": 1, "estado": "Confirmada"},
                    {"id_reserva": 2, "estado": "Cancelada"},
                ],
                [
                    {
                        "id_reserva": 2,
                        "id_servicio": 1,
                        "nombre_snapshot": "Desayuno",
                        "costo_unitario_snapshot": 5000,
                        "subtotal": 10000,
                    }
                ],
            ]
            todas = db.obtener_todas_las_reservas()
            self.assertEqual(len(todas), 2)
            self.assertEqual(todas[0]["servicios"], [])
            self.assertEqual(todas[1]["estado"], "Cancelada")
            self.assertEqual(todas[1]["servicios"], [{
                "id_servicio": 1,
                "nombre": "Desayuno",
                "costo_unitario": 5000,
                "subtotal": 10000,
            }])

    def test_25_scripnexopms_sql_contract(self):
        """M1/F1/F3: Verifica esquema SQL, tablas servicios/reserva_servicios y hashes PBKDF2 semilla."""
        import os
        import re

        ruta_sql = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripnexopms.sql")
        with open(ruta_sql, "r", encoding="utf-8") as fh:
            contenido = fh.read()

        self.assertIn("ENUM('admin', 'gerente', 'recepcionista')", contenido)
        self.assertIn("CREATE TABLE IF NOT EXISTS servicios", contenido)
        self.assertIn("CREATE TABLE IF NOT EXISTS reserva_servicios", contenido)
        self.assertIn("'Desayuno'", contenido)
        self.assertIn("'Estacionamiento'", contenido)

        hashes = {}
        for username, pwd_hash, rol in re.findall(
            r"\(\s*'([^']+)',\s*'(pbkdf2_sha256\$[^']+)',\s*'([^']+)'", contenido
        ):
            hashes[username] = (pwd_hash, rol)

        self.assertEqual(set(hashes.keys()), {"admin", "gerente", "recepcion"})
        self.assertEqual(hashes["admin"][1], "admin")
        self.assertEqual(hashes["gerente"][1], "gerente")
        self.assertEqual(hashes["recepcion"][1], "recepcionista")
        self.assertTrue(verificar_password("admin123", hashes["admin"][0]))
        self.assertTrue(verificar_password("gerente123", hashes["gerente"][0]))
        self.assertTrue(verificar_password("recep123", hashes["recepcion"][0]))

    def test_26_fake_db_paridad_validacion_ids_y_reserva(self):
        """M1-QA: FakeConexionDB rechaza bool/float/inválidos igual que ConexionDB y Reserva sanea IDs."""
        from huesped import Huesped
        from reserva import Reserva

        # 1. Reserva: IDs inválidos (bool, float, texto no numérico, <=0, overflow) se normalizan a None sin lanzar excepción
        h = Huesped("12.345.678-9", "Prueba IDs", "+56912345678")
        for id_invalido in (True, False, 1.5, 1.0, "abc", "", 0, -5, MAX_INT_UNSIGNED + 1):
            r_inv = Reserva(
                h,
                0,
                1,
                2,
                90000,
                id_reserva=id_invalido,
                servicios=[{"id_servicio": id_invalido, "nombre": "Desayuno", "costo_unitario": 5000}],
            )
            self.assertIsNone(r_inv.id_reserva)
            self.assertIsNone(r_inv.servicios[0]["id_servicio"])

        r_str = Reserva(
            h,
            0,
            1,
            2,
            90000,
            id_reserva=" 42 ",
            servicios=[{"id_servicio": "7", "nombre": "Spa", "costo_unitario": 10000}],
        )
        self.assertEqual(r_str.id_reserva, 42)
        self.assertEqual(r_str.servicios[0]["id_servicio"], 7)

        # 2. Habitaciones y Servicios en FakeConexionDB: rechazo de bool/float/None y aceptación de strings numéricos
        for bad_id in (True, False, 1.0, 1.5, "abc", 0, -1, None):
            self.assertFalse(self.fake_db.editar_habitacion(bad_id, "Cabaña", "C1", 50000)[0])
            self.assertFalse(self.fake_db.eliminar_habitacion(bad_id)[0])
            self.assertFalse(self.fake_db.editar_servicio(bad_id, "Nuevo", 5000)[0])
            self.assertFalse(self.fake_db.cambiar_disponibilidad_servicio(bad_id)[0])
            self.assertFalse(self.fake_db.cancelar_reserva_transaccional(bad_id)[0])

        # Verificar que habitación #1 y servicio #1 siguen intactos tras intentos con True/1.0
        self.assertEqual(self.fake_db.obtener_habitaciones_y_tarifas()[0]["numero_habitacion"], "101")
        self.assertTrue(self.fake_db.obtener_servicios()[0]["disponible"])

        # Coerción de numero_habitacion no-str y strings numéricos de IDs
        ok_num, id_hab_num, _ = self.fake_db.agregar_habitacion("Cabaña", 202, 55000)
        self.assertTrue(ok_num)
        self.assertTrue(self.fake_db.editar_habitacion(str(id_hab_num), "Cabaña", 203, "60000")[0])
        self.assertTrue(self.fake_db.editar_servicio("1", "Desayuno", "5500")[0])
        self.assertTrue(self.fake_db.cambiar_disponibilidad_servicio("1", disponible=False)[0])
        self.assertFalse(self.fake_db.obtener_servicios()[0]["disponible"])
        self.assertTrue(self.fake_db.cambiar_disponibilidad_servicio("1", disponible=True)[0])

        # 3. verificar_disponibilidad_db: rechazo de bool/float/None/str-no-numérico, aceptación de strings numéricos
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(True, 1, 2))
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1.0, 1, 2))
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1, 1.5, 2))
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1, "abc", 2))
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1, None, 2))
        self.assertFalse(self.fake_db.verificar_disponibilidad_db(1, 1, 2, excluir_id_reserva=True))
        self.assertTrue(self.fake_db.verificar_disponibilidad_db("1", "1", "2"))

    def test_27_fake_db_servicios_payload_y_transacciones_edge_cases(self):
        """M1-QA: FakeConexionDB valida FK de servicios, costos/subtotales y parámetros transaccionales."""
        from huesped import Huesped
        from reserva import Reserva

        h = Huesped("18.111.222-3", "Cliente Edge", "+56911112222")
        r_ok = Reserva(h, 0, 2, 2, 100000, servicios=[{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": 5000}])
        self.assertTrue(self.fake_db.guardar_reserva_transaccional(r_ok, id_habitacion=1))
        self.assertEqual(r_ok.id_reserva, 1)

        # cancelar_reserva_transaccional con True / 1.0 NO debe cancelar la reserva #1
        self.assertFalse(self.fake_db.cancelar_reserva_transaccional(True)[0])
        self.assertFalse(self.fake_db.cancelar_reserva_transaccional(1.0)[0])
        self.assertEqual(len(self.fake_db.obtener_reservas_activas()), 1)

        # Parámetros inválidos en editar_reserva_transaccional y guardar_reserva_transaccional sin TypeError
        self.assertFalse(self.fake_db.editar_reserva_transaccional(1, 1, 3, 2, None, [])[0])
        self.assertFalse(self.fake_db.editar_reserva_transaccional(1, 1, "abc", 2, 90000, [])[0])
        self.assertFalse(self.fake_db.editar_reserva_transaccional(1, 1, 3, 2, -100, [])[0])
        self.assertFalse(self.fake_db.editar_reserva_transaccional(True, 1, 3, 2, 90000, [])[0])

        r_bad_total = Reserva(h, 0, 10, 2, None)
        self.assertFalse(self.fake_db.guardar_reserva_transaccional(r_bad_total, id_habitacion=1))
        r_bad_dia = Reserva(h, 0, "abc", 2, 90000)
        self.assertFalse(self.fake_db.guardar_reserva_transaccional(r_bad_dia, id_habitacion=1))

        # Payloads inválidos en servicios (sin costo_unitario, costo negativo/bool, FK inexistente 9999)
        self.assertFalse(
            self.fake_db.editar_reserva_transaccional(
                1, 1, 3, 2, 90000, [{"id_servicio": 1, "nombre": "Desayuno"}]
            )[0]
        )
        self.assertFalse(
            self.fake_db.editar_reserva_transaccional(
                1, 1, 3, 2, 90000, [{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": -500}]
            )[0]
        )
        self.assertFalse(
            self.fake_db.editar_reserva_transaccional(
                1, 1, 3, 2, 90000, [{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": True}]
            )[0]
        )
        self.assertFalse(
            self.fake_db.editar_reserva_transaccional(
                1, 1, 3, 2, 90000, [{"id_servicio": 1, "nombre": "Desayuno", "costo_unitario": 5000, "subtotal": -10}]
            )[0]
        )
        self.assertFalse(
            self.fake_db.editar_reserva_transaccional(
                1, 1, 3, 2, 90000, [{"id_servicio": 9999, "nombre": "Fantasma", "costo_unitario": 5000}]
            )[0]
        )
        self.assertFalse(
            self.fake_db.editar_reserva_transaccional(
                1, 1, 3, 2, 90000, [{"id_servicio": True, "costo_unitario": 5000}]
            )[0]
        )

        # id_servicio=True con nombre válido ("Desayuno") resuelve por nombre igual que ConexionDB, y strings numéricos funcionan
        ok_bool_name, _ = self.fake_db.editar_reserva_transaccional(
            "1",
            "1",
            "3",
            "2",
            "90000",
            [{"id_servicio": True, "nombre": "Desayuno", "costo_unitario": 5000}],
        )
        self.assertTrue(ok_bool_name)
        self.assertTrue(self.fake_db.cancelar_reserva_transaccional("1")[0])

    def test_28_guardar_reserva_transaccional_validacion_paridad(self):
        """M1-QA: Paridad entre ConexionDB (mock) y FakeConexionDB al rechazar nueva_reserva/huesped/total inválidos."""
        from types import SimpleNamespace
        from huesped import Huesped
        from reserva import Reserva

        h = Huesped("15.555.666-7", "Cliente Paridad", "+56955556666")
        db = ConexionDB()
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(db, "conectar", return_value=mock_conn) as mock_conectar:
            # 1. nueva_reserva is None y huesped faltante/incompleto
            casos_invalidos = [
                None,
                Reserva(None, 0, 1, 2, 100000),
                SimpleNamespace(
                    huesped=SimpleNamespace(rut="15.555.666-7"),
                    dia_inicio=1,
                    dias_estadia=2,
                    total=100000,
                ),
            ]
            # 2. Valores de total inválidos (None, negativo, bool, float, texto, overflow)
            for bad_total in (None, -100, True, False, 123.45, "abc", MAX_INT_UNSIGNED + 1):
                casos_invalidos.append(Reserva(h, 0, 1, 2, bad_total))

            for caso in casos_invalidos:
                self.assertFalse(self.fake_db.guardar_reserva_transaccional(caso, 1))
                self.assertFalse(db.guardar_reserva_transaccional(caso, 1))
                if caso is not None and hasattr(caso, "id_reserva"):
                    self.assertIsNone(caso.id_reserva)
                mock_conectar.assert_not_called()
                mock_conn.start_transaction.assert_not_called()
                mock_conn.commit.assert_not_called()

            # 3. total como string numérico válido se normaliza a int (total_val) al persistir en SQL
            mock_cursor.fetchone.return_value = (0,)
            mock_cursor.lastrowid = 88
            r_str_total = Reserva(h, 0, 1, 2, "100000")
            self.assertTrue(db.guardar_reserva_transaccional(r_str_total, 1))
            self.assertEqual(r_str_total.id_reserva, 88)
            mock_conn.start_transaction.assert_called_once()
            mock_conn.commit.assert_called_once()

            insert_reservas_calls = [
                c for c in mock_cursor.execute.call_args_list
                if c.args and "INSERT INTO reservas" in c.args[0]
            ]
            self.assertEqual(len(insert_reservas_calls), 1)
            params_insert = insert_reservas_calls[0].args[1]
            self.assertEqual(params_insert[6], 100000)
            self.assertIs(type(params_insert[6]), int)

    def test_29_rbac_tres_roles_menus_y_permisos(self):
        """F3: Verifica login y permisos RBAC de los 3 roles (recepcionista, gerente, admin)."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        # 1. Inicia como recepcionista -> ve opciones operativas, cambia a gerente -> ve reportes y gestión,
        # cambia a admin -> entra a submenús jerárquicos y sale.
        script = (
            "recepcion\nrecep123\n"
            "5\n"                   # Cerrar sesión / Cambiar de usuario
            "gerente\ngerente123\n"
            "1\n"                   # Consultar habitaciones/cabañas, disponibilidad y tarifas
            "2\n"                   # Gestionar reservas existentes (submenú gerencia)
            "1\n"                   # Ver reservas activas
            "5\n"                   # Volver al menú principal
            "3\n"                   # Módulo de Informes y Reportes
            "5\n"                   # Ver todos los informes completos
            "6\n"                   # Cerrar sesión / Cambiar de usuario desde reportes
            "admin\nadmin123\n"
            "2\n"                   # Módulo Gerencia (Admin)
            "5\n"                   # Volver
            "3\n"                   # Módulo Recepción (Admin)
            "8\n"                   # Volver
            "5\n"                   # Salir
        )
        buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.stdin", io.StringIO(script)):
            sistema.iniciar()
        out = buf.getvalue()

        self.assertIn("Bienvenido/a, recepcion (Rol: recepcionista)", out)
        self.assertIn("Bienvenido/a, gerente (Rol: gerente)", out)
        self.assertIn("Bienvenido/a, admin (Rol: admin)", out)
        self.assertIn("GESTIÓN DE RESERVAS EXISTENTES (GERENCIA)", out)
        self.assertIn("MÓDULO DE INFORMES Y REPORTES", out)
        self.assertIn("MÓDULO GERENCIA", out)
        self.assertIn("MÓDULO RECEPCIÓN", out)

        # 2. Gerente NO puede registrar nuevas reservas ni acceder a administración
        sistema.usuario_actual = {"id_usuario": 2, "username": "gerente", "rol": "gerente"}
        buf_ger = io.StringIO()
        with patch("sys.stdout", buf_ger):
            sistema.registrar_reserva()
            sistema.menu_administracion()
        self.assertIn("el rol gerente no está autorizado para registrar nuevas reservas", buf_ger.getvalue())
        self.assertIn("Acceso denegado: función exclusiva para administradores", buf_ger.getvalue())

        # 3. Recepcionista NO puede acceder a reportes ni administración
        sistema.usuario_actual = {"id_usuario": 3, "username": "recepcion", "rol": "recepcionista"}
        buf_rec = io.StringIO()
        with patch("sys.stdout", buf_rec):
            self.assertIsNone(sistema.reporte_resumen_reservas())
            self.assertIsNone(sistema.reporte_ingresos())
            self.assertIsNone(sistema.reporte_ocupacion())
            self.assertIsNone(sistema.reporte_rendimiento_servicios())
            sistema.menu_informes_y_reportes()
        self.assertIn("Acceso denegado: función exclusiva para administradores y gerentes", buf_rec.getvalue())

    def test_30_flujo_e2e_cabana_servicio_dinamico_edicion_y_cancelacion_logica(self):
        """F2/F4: Creación de cabaña y servicio dinámico, reserva con ese servicio, edición y soft-delete."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        sistema.usuario_actual = {"id_usuario": 1, "username": "admin", "rol": "admin"}

        # 1. Crear Cabaña Bosque ($80,000/noche) y servicio dinámico 'Tour Guiado' ($12,000/noche) desde CLI Admin
        script_admin = (
            "2\n"               # Agregar habitación o cabaña
            "2\n"               # Cabaña
            "Cabaña Bosque\n"
            "80000\n"
            "5\n"               # Gestionar Servicios Adicionales + Costos
            "2\n"               # Crear nuevo servicio adicional
            "Tour Guiado\n"
            "12000\n"
            "6\n"               # Volver a Administración
            "7\n"               # Volver al menú principal
        )
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(script_admin)):
            sistema.menu_administracion()

        self.assertIn("Cabaña Bosque", sistema.habitaciones)
        self.assertIn("Tour Guiado", sistema.servicios_nombres)
        idx_cab = sistema.habitaciones.index("Cabaña Bosque")

        # 2. Registrar reserva en 'Cabaña Bosque', Día 5, 2 noches, con Desayuno (n), Estacionamiento (n), Tour Guiado (s)
        # Total esperado: (80,000 + 12,000) * 2 = $184,000
        entradas_reserva = "Cabaña Bosque\n5\n2\n14.555.666-7\nMartín Soto\n+56944445555\nn\nn\ns\ns\n"
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(entradas_reserva)):
            sistema.registrar_reserva()

        self.assertEqual(len(sistema.reservas), 1)
        res = sistema.reservas[0]
        self.assertEqual(res.total, 184000)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][4], 1)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][5], 1)

        # 3. Editar reserva: mover a Día 10 por 3 noches y agregar también Desayuno ($5,000) + Tour Guiado ($12,000)
        # Nuevo total esperado: (80,000 + 5,000 + 12,000) * 3 = $291,000
        entradas_edicion = "1\n\n10\n3\ns\ns\nn\ns\ns\n"
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(entradas_edicion)):
            sistema.editar_reserva()

        res = sistema.reservas[0]
        self.assertEqual(res.dia_inicio, 9)
        self.assertEqual(res.dias_estadia, 3)
        self.assertEqual(res.total, 291000)
        # Días antiguos (5 y 6 -> idx 4 y 5) liberados en matriz
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][4], 0)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][5], 0)
        # Días nuevos (10, 11, 12 -> idx 9, 10, 11) ocupados en matriz
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][9], 1)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][10], 1)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][11], 1)

        # 4. Cancelación lógica (Soft Delete): libera matriz a 0 pero persiste en BD como 'Cancelada'
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO("1\ns\n")):
            sistema.cancelar_reserva()

        self.assertEqual(len(sistema.reservas), 0)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][9], 0)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][10], 0)
        self.assertEqual(sistema.matriz_disponibilidad[idx_cab][11], 0)

        historial_bd = self.fake_db.obtener_todas_las_reservas()
        self.assertEqual(len(historial_bd), 1)
        self.assertEqual(historial_bd[0]["estado"], "Cancelada")
        self.assertEqual(historial_bd[0]["monto_total"], 291000)

    def test_31_modulo_informes_y_reportes_exactitud(self):
        """F4: Verifica los 4 informes (Resumen, Ingresos, Ocupación y Rendimiento de Servicios)."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        sistema.usuario_actual = {"id_usuario": 1, "username": "admin", "rol": "admin"}

        # Crear servicio adicional dinámico 'Spa' ($15,000/noche)
        sistema.crear_servicio("Spa", 15000, disponible=True)

        # Reserva 1 (Confirmada): Hab 101 ($45,000), Día 1, 2 noches, con Desayuno ($5,000) y Spa ($15,000)
        # Total R1 = (45,000 + 5,000 + 15,000) * 2 = $130,000
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(
            "101\n1\n2\n11.111.111-1\nAna\n1111\ns\nn\ns\ns\n"
        )):
            sistema.registrar_reserva()

        # Reserva 2 (Confirmada): Hab 103 ($60,000), Día 5, 4 noches, con Estacionamiento ($8,000) y Spa ($15,000)
        # Total R2 = (60,000 + 8,000 + 15,000) * 4 = $332,000
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(
            "103\n5\n4\n22.222.222-2\nLuis\n2222\nn\ns\ns\ns\n"
        )):
            sistema.registrar_reserva()

        # Reserva 3 (Luego Cancelada): Hab 104 ($70,000), Día 15, 2 noches, sin servicios -> Total R3 = $140,000
        with patch("sys.stdout", io.StringIO()), patch("sys.stdin", io.StringIO(
            "104\n15\n2\n33.333.333-3\nEva\n3333\nn\nn\nn\ns\n"
        )):
            sistema.registrar_reserva()
        id_r3 = sistema.reservas[-1].id_reserva
        sistema.cancelar_reserva_por_id(id_r3)

        # Ejecutar los 4 reportes como Gerente
        sistema.usuario_actual = {"id_usuario": 2, "username": "gerente", "rol": "gerente"}
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rep = sistema.generar_todos_los_reportes()
        out = buf.getvalue()

        # 1. Resumen de Reservas: 3 históricas (2 Confirmadas, 1 Cancelada -> 33.33%)
        self.assertEqual(rep["resumen_reservas"]["total_historico"], 3)
        self.assertEqual(rep["resumen_reservas"]["confirmadas"], 2)
        self.assertEqual(rep["resumen_reservas"]["canceladas"], 1)
        self.assertAlmostEqual(rep["resumen_reservas"]["tasa_cancelacion"], 33.33, places=2)

        # 2. Informe de Ingresos: Confirmados = 130,000 + 332,000 = 462,000; Canceladas = 140,000; Ticket = 231,000
        self.assertEqual(rep["ingresos"]["ingresos_confirmados"], 462000)
        self.assertEqual(rep["ingresos"]["monto_canceladas"], 140000)
        self.assertEqual(rep["ingresos"]["ticket_promedio"], 231000.0)

        # 3. Informe de Ocupación: 6 días ocupados sobre 120 (4 hab * 30 días) = 5.0%
        self.assertEqual(rep["ocupacion"]["dias_ocupados_total"], 6)
        self.assertEqual(rep["ocupacion"]["capacidad_total_dias"], 120)
        self.assertEqual(rep["ocupacion"]["porcentaje_general"], 5.0)

        # 4. Rendimiento de Servicios:
        # Spa: 2 contrataciones, ingresos = (15,000*2) + (15,000*4) = 90,000 (#1)
        # Estacionamiento: 1 contratación, ingresos = 8,000*4 = 32,000 (#2)
        # Desayuno: 1 contratación, ingresos = 5,000*2 = 10,000 (#3)
        ranking = rep["rendimiento_servicios"]
        self.assertEqual(ranking[0]["nombre"], "Spa")
        self.assertEqual(ranking[0]["contrataciones"], 2)
        self.assertEqual(ranking[0]["ingresos"], 90000)
        self.assertEqual(ranking[1]["nombre"], "Estacionamiento")
        self.assertEqual(ranking[1]["ingresos"], 32000)
        self.assertEqual(ranking[2]["nombre"], "Desayuno")
        self.assertEqual(ranking[2]["ingresos"], 10000)

        self.assertIn("INFORME 1: RESUMEN DE RESERVAS", out)
        self.assertIn("INFORME 2: INFORME DE INGRESOS", out)
        self.assertIn("INFORME 3: INFORME DE OCUPACIÓN", out)
        self.assertIn("INFORME 4: RENDIMIENTO DE SERVICIOS ADICIONALES", out)

    def test_32_meses_calendario_y_editar_nombre_hotel(self):
        """Valida cambio de meses (Enero 31 días, Febrero 28 días) y edición de nombre del hotel."""
        from nexopms import NexoPMS

        sistema = NexoPMS(db=self.fake_db)
        sistema.usuario_actual = {"id_usuario": 1, "username": "admin", "rol": "admin"}

        # 1. Editar nombre del hotel
        self.assertEqual(sistema.nombre_hotel, "Hotel Los Arrayanes")
        ok, msg = sistema.actualizar_nombre_hotel("Cabañas del Sur")
        self.assertTrue(ok)
        self.assertEqual(sistema.nombre_hotel, "Cabañas del Sur")
        self.assertEqual(self.fake_db.obtener_nombre_hotel(), "Cabañas del Sur")

        # 2. Cambiar a Enero 2026 (31 días) y Febrero 2026 (28 días)
        ok_ene, _ = sistema.cambiar_mes(1, 2026)
        self.assertTrue(ok_ene)
        self.assertEqual(sistema.nombre_mes_actual, "Enero")
        self.assertEqual(sistema.dias_mes, 31)
        self.assertEqual(len(sistema.matriz_disponibilidad[0]), 31)

        ok_feb, _ = sistema.cambiar_mes(2, 2026)
        self.assertTrue(ok_feb)
        self.assertEqual(sistema.nombre_mes_actual, "Febrero")
        self.assertEqual(sistema.dias_mes, 28)
        self.assertEqual(len(sistema.matriz_disponibilidad[0]), 28)

        # 3. Verificar render en consola incluye nombre del hotel y mes
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            sistema.mostrar_matriz_disponibilidad()
        out = buf.getvalue()
        self.assertIn("Febrero 2026", out)
        self.assertIn("Cabañas del Sur", out)


if __name__ == "__main__":
    unittest.main()
