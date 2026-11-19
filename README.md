# NexoPMS — Sistema de Gestión Hotelera (Hotel Los Arrayanes)

**NexoPMS** es un Producto Mínimo Viable (MVP) por consola desarrollado en **Python 3** bajo el paradigma de **Programación Orientada a Objetos (POO)** y con persistencia relacional en **MySQL**. El sistema permite administrar la disponibilidad mensual, cotización de estadías con servicios adicionales y registro transaccional de reservas para el *Hotel Los Arrayanes*, alineado con el modelo de procesos de negocio **TO-BE (Bizagi)**.

---

## Arquitectura del Proyecto

El código está modularizado según responsabilidades:

| Archivo | Descripción |
| :--- | :--- |
| `main.py` | Punto de entrada principal que inicializa y ejecuta la aplicación. |
| `nexopms.py` | Controlador principal (`NexoPMS`): gestiona el menú interactivo, los vectores paralelos (`habitaciones` y `tarifas`), la matriz de disponibilidad ($4 \times 30$) y las reglas de negocio del flujo TO-BE. |
| `huesped.py` | Clase de dominio `Huesped` (`rut`, `nombre`, `telefono`). |
| `reserva.py` | Clase de dominio `Reserva` con soporte para servicios adicionales (`incluye_desayuno`, `incluye_estacionamiento`) y estado de reserva. |
| `conexion.py` | Capa de acceso a datos (`ConexionDB`): administra la conexión a MySQL y las transacciones SQL sobre `nexopms_db`. |
| `scripnexopms.sql` | Script DDL/DML para crear la base de datos `nexopms_db`, sus 4 tablas relacionales y poblar las habitaciones iniciales. |
| `test_smoke.py` | Suite de pruebas automatizadas (`unittest`) para verificar la integridad de los módulos y la lógica de negocio. |

---

## Requisitos Previos

1. **Python 3.10 o superior** instalado.
2. **Servidor MySQL activo** (por ejemplo, mediante **XAMPP** en el puerto `3306`, usuario `root` sin contraseña).
3. Conector oficial de MySQL para Python (`mysql-connector-python`).

---

## Guía de Instalación y Ejecución Paso a Paso

### 1. Clonar el repositorio
```bash
git clone https://github.com/johnny420jj/nexoPMS.git
cd nexoPMS
```

### 2. Instalar la dependencia de conexión a MySQL
```bash
pip install mysql-connector-python
```

### 3. Preparar la Base de Datos en MySQL
1. Abre el panel de control de **XAMPP** e inicia el módulo **MySQL** (*Start*).
2. Ejecuta el contenido del archivo `scripnexopms.sql` desde tu cliente SQL (extensión MySQL de VS Code/Antigravity, phpMyAdmin o consola MySQL).
   - Esto creará automáticamente la base de datos **`nexopms_db`**, las 4 tablas (`huespedes`, `habitaciones`, `reservas` y `ocupacion_diaria`) y cargará las habitaciones **101, 102, 103 y 104**.

### 4. Ejecutar el sistema
```bash
python main.py
```

---

## Modelo de Negocio (Proceso TO-BE)

- **Tarifario Base (Vectores Paralelos):**
  - Habitación `101`: $45.000 / noche
  - Habitación `102`: $45.000 / noche
  - Habitación `103`: $60.000 / noche
  - Habitación `104`: $70.000 / noche
- **Servicios Adicionales (Compuerta Inclusiva OR):**
  - **Desayuno:** $5.000 / noche
  - **Estacionamiento:** $8.000 / noche
  - **Fórmula de cobro:** `(Tarifa_Base + Costo_Desayuno + Costo_Estacionamiento) * Noches_Estadia`
- **Doble Validación de Disponibilidad:**
  - Antes de confirmar cualquier reserva, el sistema verifica la disponibilidad tanto en la matriz en memoria ($4 \times 30$) como directamente en la tabla `ocupacion_diaria` de MySQL mediante una transacción atómica, evitando cualquier colisión o sobreventa (*overbooking*).

---

## Ejecución de Pruebas Automatizadas

Para validar que todos los módulos y reglas de negocio funcionen correctamente sin requerir interacción manual:

```bash
python -m unittest test_smoke.py -v
```

