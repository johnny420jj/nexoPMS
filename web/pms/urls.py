from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard_view, name="dashboard"),
    path("recepcion/reservas/", views.reservas_view, name="reservas"),
    path("recepcion/reservas/registrar/", views.registrar_reserva_view, name="registrar_reserva"),
    path("recepcion/reservas/<int:id_reserva>/editar/", views.editar_reserva_view, name="editar_reserva"),
    path("recepcion/reservas/<int:id_reserva>/cancelar/", views.cancelar_reserva_view, name="cancelar_reserva"),
    path("gerencia/reportes/", views.reportes_view, name="reportes"),
    path("administracion/", views.administracion_view, name="administracion"),
    path("administracion/hotel/editar/", views.editar_hotel_view, name="editar_hotel"),
    path("administracion/alojamientos/agregar/", views.agregar_alojamiento_view, name="agregar_alojamiento"),
    path("administracion/alojamientos/<int:id_habitacion>/editar/", views.editar_alojamiento_view, name="editar_alojamiento"),
    path("administracion/alojamientos/<int:id_habitacion>/eliminar/", views.eliminar_alojamiento_view, name="eliminar_alojamiento"),
    path("administracion/servicios/crear/", views.crear_servicio_view, name="crear_servicio"),
    path("administracion/servicios/<int:id_servicio>/editar/", views.editar_servicio_view, name="editar_servicio"),
    path("administracion/servicios/<int:id_servicio>/toggle/", views.toggle_servicio_view, name="toggle_servicio"),
]
