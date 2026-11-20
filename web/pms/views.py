"""
Vistas Django de NexoPMS Web (Opción 1).
Reutiliza directamente el núcleo POO (NexoPMS, Huesped, Reserva) y ConexionDB (MySQL).
"""

from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect, render

from conexion import ConexionDB
from huesped import Huesped
from nexopms import NexoPMS
from reserva import Reserva


def _obtener_db():
    """Retorna una instancia de ConexionDB (puede ser mockeada en tests)."""
    return ConexionDB()


def _obtener_mes_anio(request):
    """Lee mes (1..12) y año (2000..2100) desde query string o sesión (por defecto Noviembre 2026)."""
    raw_mes = request.GET.get("mes") or request.POST.get("mes") or request.session.get("mes_actual", 11)
    raw_anio = request.GET.get("anio") or request.POST.get("anio") or request.session.get("anio_actual", 2026)
    try:
        mes = int(raw_mes)
        if not (1 <= mes <= 12):
            mes = 11
    except (TypeError, ValueError):
        mes = 11
    try:
        anio = int(raw_anio)
        if not (2000 <= anio <= 2100):
            anio = 2026
    except (TypeError, ValueError):
        anio = 2026
    request.session["mes_actual"] = mes
    request.session["anio_actual"] = anio
    return mes, anio


def _obtener_sistema(request):
    """Inicializa NexoPMS sincronizado con MySQL para el mes/año y usuario activos."""
    mes, anio = _obtener_mes_anio(request)
    sistema = NexoPMS(db=_obtener_db(), mes=mes, anio=anio)
    usuario = request.session.get("usuario")
    if usuario:
        sistema.usuario_actual = usuario
    return sistema


def requiere_login(view_func):
    """Decorador que exige sesión autenticada para acceder a la vista."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.session.get("usuario"):
            return redirect("login")
        return view_func(request, *args, **kwargs)
    return _wrapped


def requiere_roles(*roles_permitidos):
    """Decorador RBAC que restringe el acceso según el rol del usuario autenticado."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            usuario = request.session.get("usuario")
            if not usuario:
                return redirect("login")
            if usuario.get("rol") not in roles_permitidos:
                messages.error(
                    request,
                    f"Acceso denegado: tu rol ({usuario.get('rol')}) no tiene permisos para este módulo.",
                )
                return redirect("dashboard")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def login_view(request):
    """Autenticación de usuarios (admin, gerente, recepcionista) contra MySQL (PBKDF2)."""
    if request.session.get("usuario"):
        return redirect("dashboard")

    nombre_hotel = "Hotel Los Arrayanes"
    db = _obtener_db()
    try:
        if hasattr(db, "asegurar_esquema"):
            db.asegurar_esquema()
        if hasattr(db, "obtener_nombre_hotel"):
            nombre_hotel = db.obtener_nombre_hotel()
    except Exception:
        pass

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        try:
            usuario = db.autenticar_usuario(username, password)
        except Exception as e:
            messages.error(request, f"No se pudo conectar a MySQL (¿está encendido XAMPP?): {e}")
            return render(request, "pms/login.html", {"nombre_hotel": nombre_hotel})

        if usuario:
            request.session["usuario"] = usuario
            messages.success(request, f"Bienvenido/a, {usuario['username']} ({usuario['rol']}).")
            return redirect("dashboard")
        messages.error(request, "Credenciales inválidas. Verifica usuario y contraseña.")

    return render(request, "pms/login.html", {"nombre_hotel": nombre_hotel})


def logout_view(request):
    """Cierra la sesión actual y permite iniciar sesión con otro usuario/rol."""
    request.session.flush()
    messages.info(request, "Sesión cerrada correctamente.")
    return redirect("login")


@requiere_login
def dashboard_view(request):
    """
    Panel principal con accesos según rol (Admin ve los 3 módulos:
    Administración, Gerencia y Recepción) + matriz visual de 30 días.
    """
    usuario = request.session["usuario"]
    sistema = _obtener_sistema(request)

    alojamientos_matriz = []
    for i, hab in enumerate(sistema.habitaciones):
        tipo = sistema.tipos_habitaciones[i] if i < len(sistema.tipos_habitaciones) else "Habitación"
        tarifa = sistema.tarifas[i]
        fila = sistema.matriz_disponibilidad[i]
        dias_ocupados = sum(1 for c in fila if c == 1)
        alojamientos_matriz.append({
            "id": sistema.ids_habitaciones[i],
            "tipo": tipo,
            "numero": hab,
            "tarifa": tarifa,
            "fila": fila,
            "dias_ocupados": dias_ocupados,
        })

    servicios_activos = [
        {"id": sid, "nombre": nom, "costo": cos}
        for sid, nom, cos, disp in zip(
            sistema.servicios_ids,
            sistema.servicios_nombres,
            sistema.servicios_costos,
            sistema.servicios_disponibles,
        )
        if disp
    ]

    meses_lista = [
        {"numero": idx, "nombre": nombre}
        for idx, nombre in enumerate(NexoPMS.MESES_ANIO, start=1)
    ]

    contexto = {
        "usuario": usuario,
        "nombre_hotel": sistema.nombre_hotel,
        "mes_actual": sistema.mes_actual,
        "anio_actual": sistema.anio_actual,
        "nombre_mes_actual": sistema.nombre_mes_actual,
        "dias_mes": sistema.dias_mes,
        "meses_lista": meses_lista,
        "anios_lista": [2025, 2026, 2027, 2028],
        "dias_header": list(range(1, sistema.dias_mes + 1)),
        "alojamientos_matriz": alojamientos_matriz,
        "servicios_activos": servicios_activos,
        "total_reservas_activas": len(sistema.reservas),
        "total_alojamientos": len(sistema.habitaciones),
    }
    return render(request, "pms/dashboard.html", contexto)


@requiere_login
def reservas_view(request):
    """Vista del Módulo Recepción / Gestión de Reservas."""
    usuario = request.session["usuario"]
    sistema = _obtener_sistema(request)

    alojamientos = [
        {
            "idx": i,
            "id": sistema.ids_habitaciones[i],
            "tipo": sistema.tipos_habitaciones[i],
            "numero": sistema.habitaciones[i],
            "tarifa": sistema.tarifas[i],
        }
        for i in range(len(sistema.habitaciones))
    ]
    servicios_disponibles = [
        {"id": sid, "nombre": nom, "costo": cos}
        for sid, nom, cos, disp in zip(
            sistema.servicios_ids,
            sistema.servicios_nombres,
            sistema.servicios_costos,
            sistema.servicios_disponibles,
        )
        if disp
    ]

    reservas_render = []
    for r in sistema.reservas:
        hab_nombre = (
            r.habitacion_nombre
            if r.habitacion_nombre is not None
            else (
                sistema.habitaciones[r.habitacion_idx]
                if 0 <= r.habitacion_idx < len(sistema.habitaciones)
                else f"ID#{r.habitacion_idx}"
            )
        )
        tipo_aloj = (
            r.tipo_alojamiento
            if r.tipo_alojamiento is not None
            else (
                sistema.tipos_habitaciones[r.habitacion_idx]
                if 0 <= r.habitacion_idx < len(sistema.tipos_habitaciones)
                else "Habitación"
            )
        )
        mes_res = r.mes if getattr(r, "mes", None) else sistema.mes_actual
        anio_res = r.anio if getattr(r, "anio", None) else sistema.anio_actual
        reservas_render.append({
            "id_reserva": r.id_reserva,
            "huesped": r.huesped,
            "habitacion_idx": r.habitacion_idx,
            "habitacion_nombre": hab_nombre,
            "tipo_alojamiento": tipo_aloj,
            "mes": mes_res,
            "mes_nombre": NexoPMS.MESES_ANIO[mes_res - 1],
            "anio": anio_res,
            "dia_inicio_ui": r.dia_inicio + 1,
            "dias_estadia": r.dias_estadia,
            "servicios_texto": sistema._formatear_servicios_reserva(r),
            "servicios_ids": [s["id_servicio"] for s in r.servicios if s.get("id_servicio")],
            "total": r.total,
            "estado": r.estado,
        })

    meses_lista = [
        {"numero": idx, "nombre": nombre}
        for idx, nombre in enumerate(NexoPMS.MESES_ANIO, start=1)
    ]

    contexto = {
        "usuario": usuario,
        "nombre_hotel": sistema.nombre_hotel,
        "mes_actual": sistema.mes_actual,
        "anio_actual": sistema.anio_actual,
        "nombre_mes_actual": sistema.nombre_mes_actual,
        "meses_lista": meses_lista,
        "puede_registrar": usuario["rol"] in ("admin", "recepcionista"),
        "alojamientos": alojamientos,
        "servicios_disponibles": servicios_disponibles,
        "reservas": reservas_render,
        "dias_mes": sistema.dias_mes,
    }
    return render(request, "pms/reservas.html", contexto)


@requiere_roles("admin", "recepcionista")
def registrar_reserva_view(request):
    """Registra una nueva reserva con servicios dinámicos y doble validación TO-BE."""
    if request.method != "POST":
        return redirect("reservas")

    sistema = _obtener_sistema(request)
    try:
        hab_idx = int(request.POST.get("habitacion_idx", "-1"))
        dia_inicio_ui = int(request.POST.get("dia_inicio", "0"))
        dias_estadia = int(request.POST.get("dias_estadia", "0"))
    except ValueError:
        messages.error(request, "Los valores de habitación, día de ingreso y noches deben ser numéricos.")
        return redirect("reservas")

    rut = request.POST.get("rut", "").strip()
    nombre = request.POST.get("nombre", "").strip()
    telefono = request.POST.get("telefono", "").strip()

    if not (rut and nombre and telefono):
        messages.error(request, "Debe completar RUT, nombre y teléfono del huésped.")
        return redirect("reservas")

    if not (0 <= hab_idx < len(sistema.habitaciones)):
        messages.error(request, "Alojamiento seleccionado inválido.")
        return redirect("reservas")

    dia_inicio = dia_inicio_ui - 1
    if dia_inicio < 0 or dias_estadia < 1 or dia_inicio + dias_estadia > sistema.dias_mes:
        messages.error(request, "Las fechas seleccionadas exceden el calendario de 30 días.")
        return redirect("reservas")

    ids_srv_sel = []
    for raw_id in request.POST.getlist("servicios"):
        try:
            ids_srv_sel.append(int(raw_id))
        except ValueError:
            pass

    servicios_seleccionados = []
    for i, sid in enumerate(sistema.servicios_ids):
        if sid in ids_srv_sel and sistema.servicios_disponibles[i]:
            costo_u = sistema.servicios_costos[i]
            servicios_seleccionados.append({
                "id_servicio": sid,
                "nombre": sistema.servicios_nombres[i],
                "costo_unitario": costo_u,
                "subtotal": costo_u * dias_estadia,
            })

    tarifa_base = sistema.tarifas[hab_idx]
    costo_srv_noche = sum(s["costo_unitario"] for s in servicios_seleccionados)
    costo_total = (tarifa_base + costo_srv_noche) * dias_estadia

    nueva_reserva = Reserva(
        huesped=Huesped(rut, nombre, telefono),
        habitacion_idx=hab_idx,
        dia_inicio=dia_inicio,
        dias_estadia=dias_estadia,
        total=costo_total,
        estado="Confirmada",
        habitacion_nombre=sistema.habitaciones[hab_idx],
        tipo_alojamiento=sistema.tipos_habitaciones[hab_idx],
        tarifa_base_snapshot=tarifa_base,
        servicios=servicios_seleccionados,
    )

    if sistema.confirmar_y_guardar_reserva(nueva_reserva, hab_idx, dia_inicio, dias_estadia):
        messages.success(
            request,
            f"Reserva confirmada para {nombre} en {sistema.tipos_habitaciones[hab_idx]} "
            f"{sistema.habitaciones[hab_idx]} (Total: ${costo_total:,}).",
        )
    else:
        messages.error(
            request,
            "No se pudo confirmar la reserva: el alojamiento ya se encuentra ocupado en esas fechas.",
        )

    return redirect("reservas")


@requiere_login
def editar_reserva_view(request, id_reserva):
    """Edita una reserva activa (recalcula total y valida disponibilidad en matriz y BD)."""
    if request.method != "POST":
        return redirect("reservas")

    sistema = _obtener_sistema(request)
    try:
        nuevo_hab_idx = int(request.POST.get("habitacion_idx", "-1"))
        nuevo_dia_ui = int(request.POST.get("dia_inicio", "0"))
        nuevos_dias = int(request.POST.get("dias_estadia", "0"))
    except ValueError:
        messages.error(request, "Datos numéricos inválidos al editar la reserva.")
        return redirect("reservas")

    ids_srv_sel = []
    for raw_id in request.POST.getlist("servicios"):
        try:
            ids_srv_sel.append(int(raw_id))
        except ValueError:
            pass

    exito, msg = sistema.editar_reserva_por_id(
        id_reserva=id_reserva,
        nuevo_habitacion_idx=nuevo_hab_idx,
        nuevo_dia_inicio=nuevo_dia_ui - 1,
        nuevos_dias_estadia=nuevos_dias,
        nuevos_servicios=ids_srv_sel,
    )
    if exito:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect("reservas")


@requiere_login
def cancelar_reserva_view(request, id_reserva):
    """Cancela lógicamente una reserva (soft-delete) y libera sus días en la matriz."""
    if request.method != "POST":
        return redirect("reservas")

    sistema = _obtener_sistema(request)
    exito, msg = sistema.cancelar_reserva_por_id(id_reserva)
    if exito:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect("reservas")


@requiere_roles("admin", "gerente")
def reportes_view(request):
    """Módulo Gerencia: Los 4 informes (Resumen, Ingresos, Ocupación y Rendimiento de Servicios)."""
    usuario = request.session["usuario"]
    sistema = _obtener_sistema(request)
    reportes = sistema.generar_todos_los_reportes()

    return render(request, "pms/reportes.html", {
        "usuario": usuario,
        "nombre_hotel": sistema.nombre_hotel,
        "nombre_mes_actual": sistema.nombre_mes_actual,
        "anio_actual": sistema.anio_actual,
        "resumen": reportes["resumen_reservas"],
        "ingresos": reportes["ingresos"],
        "ocupacion": reportes["ocupacion"],
        "servicios_ranking": reportes["rendimiento_servicios"],
    })


@requiere_roles("admin")
def administracion_view(request):
    """Módulo Administración (exclusivo Admin): Hotel, Habitaciones/Cabañas y Servicios."""
    usuario = request.session["usuario"]
    sistema = _obtener_sistema(request)

    alojamientos = [
        {
            "id": sistema.ids_habitaciones[i],
            "tipo": sistema.tipos_habitaciones[i],
            "numero": sistema.habitaciones[i],
            "tarifa": sistema.tarifas[i],
            "ocupados": sum(1 for c in sistema.matriz_disponibilidad[i] if c == 1),
        }
        for i in range(len(sistema.habitaciones))
    ]
    servicios = [
        {
            "id": sid,
            "nombre": nom,
            "costo": cos,
            "disponible": disp,
        }
        for sid, nom, cos, disp in zip(
            sistema.servicios_ids,
            sistema.servicios_nombres,
            sistema.servicios_costos,
            sistema.servicios_disponibles,
        )
    ]

    return render(request, "pms/administracion.html", {
        "usuario": usuario,
        "nombre_hotel": sistema.nombre_hotel,
        "dias_mes": sistema.dias_mes,
        "nombre_mes_actual": sistema.nombre_mes_actual,
        "anio_actual": sistema.anio_actual,
        "alojamientos": alojamientos,
        "servicios": servicios,
    })


@requiere_roles("admin")
def editar_hotel_view(request):
    """Actualiza el nombre del hotel en MySQL (exclusivo Admin)."""
    if request.method == "POST":
        sistema = _obtener_sistema(request)
        nuevo_nombre = request.POST.get("nombre_hotel", "").strip()
        exito, msg = sistema.actualizar_nombre_hotel(nuevo_nombre)
        if exito:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
    return redirect("administracion")


@requiere_roles("admin")
def agregar_alojamiento_view(request):
    if request.method == "POST":
        sistema = _obtener_sistema(request)
        tipo_local = request.POST.get("tipo_local", "").strip()
        tarifa = request.POST.get("tarifa_base_noche", "").strip()

        if tipo_local in ("Hotel", "Cabaña"):
            if tipo_local == "Hotel":
                cantidad = request.POST.get("cantidad_habitaciones", "1").strip()
            else:
                cantidad = request.POST.get("cantidad_cabanas", "1").strip()
            exito, _, msg = sistema.db.agregar_alojamientos_por_secuencia(
                tipo_local, cantidad, tarifa
            )
            if exito:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        else:
            # Compatibilidad con envío individual clásico (tipo + numero_habitacion)
            tipo = request.POST.get("tipo", "Habitación").strip()
            numero = request.POST.get("numero_habitacion", "").strip()
            exito, _, msg = sistema.db.agregar_habitacion(tipo, numero, tarifa)
            if exito:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
    return redirect("administracion")


@requiere_roles("admin")
def editar_alojamiento_view(request, id_habitacion):
    if request.method == "POST":
        sistema = _obtener_sistema(request)
        tipo = request.POST.get("tipo", "Habitación").strip()
        numero = request.POST.get("numero_habitacion", "").strip()
        tarifa = request.POST.get("tarifa_base_noche", "").strip()
        exito, msg = sistema.db.editar_habitacion(id_habitacion, tipo, numero, tarifa)
        if exito:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
    return redirect("administracion")


@requiere_roles("admin")
def eliminar_alojamiento_view(request, id_habitacion):
    if request.method == "POST":
        sistema = _obtener_sistema(request)
        exito, msg = sistema.db.eliminar_habitacion(id_habitacion)
        if exito:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
    return redirect("administracion")


@requiere_roles("admin")
def crear_servicio_view(request):
    if request.method == "POST":
        sistema = _obtener_sistema(request)
        nombre = request.POST.get("nombre", "").strip()
        costo = request.POST.get("costo", "").strip()
        exito, _, msg = sistema.crear_servicio(nombre, costo, disponible=True)
        if exito:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
    return redirect("administracion")


@requiere_roles("admin")
def editar_servicio_view(request, id_servicio):
    if request.method == "POST":
        sistema = _obtener_sistema(request)
        nombre = request.POST.get("nombre", "").strip()
        costo = request.POST.get("costo", "").strip()
        exito, msg = sistema.editar_servicio(id_servicio, nombre, costo)
        if exito:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
    return redirect("administracion")


@requiere_roles("admin")
def toggle_servicio_view(request, id_servicio):
    if request.method == "POST":
        sistema = _obtener_sistema(request)
        exito, _, msg = sistema.cambiar_disponibilidad_servicio(id_servicio)
        if exito:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
    return redirect("administracion")
