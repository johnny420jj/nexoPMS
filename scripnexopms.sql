CREATE DATABASE IF NOT EXISTS nexopms_db CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

USE nexopms_db;

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    rol ENUM('admin', 'gerente', 'recepcionista') NOT NULL,
    activo TINYINT(1) NOT NULL DEFAULT 1,
    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB;

-- Usuarios semilla por defecto (contraseñas almacenadas con hash PBKDF2-HMAC-SHA256)
INSERT IGNORE INTO
    usuarios (username, password, rol, activo)
VALUES (
        'admin',
        'pbkdf2_sha256$100000$d76f3951aa0aa635d61a42fcdb4f00cd$eb697afe724326af0437de2dc86852017552ce955df8b31b728b6bec428285f1',
        'admin',
        1
    ),
    (
        'gerente',
        'pbkdf2_sha256$100000$a53c3edb2669347d91524bb1ada4b18b$bf932a312a0b39a041b0def3555777f7baad40f517326935c97b2598c35c96e6',
        'gerente',
        1
    ),
    (
        'recepcion',
        'pbkdf2_sha256$100000$552258e3ee908896bce7018cec99ebf7$43e6590424acd03bca3b50013497f16a379dc00f7ae29fde4f72f15e13fcb808',
        'recepcionista',
        1
    );

CREATE TABLE IF NOT EXISTS huespedes (
    id_huesped INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    rut VARCHAR(12) NOT NULL UNIQUE,
    nombre VARCHAR(100) NOT NULL,
    telefono VARCHAR(20) NOT NULL,
    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS habitaciones (
    id_habitacion INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tipo ENUM('Habitación', 'Cabaña') NOT NULL DEFAULT 'Habitación',
    numero_habitacion VARCHAR(50) NOT NULL UNIQUE,
    tarifa_base_noche INT UNSIGNED NOT NULL,
    activa TINYINT(1) NOT NULL DEFAULT 1
) ENGINE = InnoDB;

-- Poblar las 4 habitaciones iniciales del Hotel Los Arrayanes
INSERT IGNORE INTO
    habitaciones (
        tipo,
        numero_habitacion,
        tarifa_base_noche,
        activa
    )
VALUES ('Habitación', '101', 45000, 1),
    ('Habitación', '102', 45000, 1),
    ('Habitación', '103', 60000, 1),
    ('Habitación', '104', 70000, 1);

CREATE TABLE IF NOT EXISTS servicios (
    id_servicio INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    costo INT UNSIGNED NOT NULL,
    disponible TINYINT(1) NOT NULL DEFAULT 1
) ENGINE = InnoDB;

-- Poblar servicios adicionales iniciales
INSERT IGNORE INTO
    servicios (nombre, costo, disponible)
VALUES ('Desayuno', 5000, 1),
    ('Estacionamiento', 8000, 1);

CREATE TABLE IF NOT EXISTS reservas (
    id_reserva INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_huesped INT UNSIGNED NOT NULL,
    id_habitacion INT UNSIGNED NOT NULL,
    dia_inicio TINYINT UNSIGNED NOT NULL,
    dias_estadia TINYINT UNSIGNED NOT NULL,
    incluye_desayuno TINYINT(1) NOT NULL DEFAULT 0,
    incluye_estacionamiento TINYINT(1) NOT NULL DEFAULT 0,
    monto_total INT UNSIGNED NOT NULL,
    estado ENUM(
        'Confirmada',
        'Cancelada',
        'Finalizada'
    ) NOT NULL DEFAULT 'Confirmada',
    habitacion_nombre VARCHAR(50) NULL,
    tipo_alojamiento VARCHAR(20) NULL,
    tarifa_base_snapshot INT UNSIGNED NULL,
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reserva_huesped FOREIGN KEY (id_huesped) REFERENCES huespedes (id_huesped) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_reserva_habitacion FOREIGN KEY (id_habitacion) REFERENCES habitaciones (id_habitacion) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_dias_validos CHECK (
        dia_inicio BETWEEN 1 AND 30
        AND dias_estadia >= 1
        AND (dia_inicio + dias_estadia - 1) <= 30
    )
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS ocupacion_diaria (
    id_ocupacion INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_habitacion INT UNSIGNED NOT NULL,
    dia_mes TINYINT UNSIGNED NOT NULL,
    ocupada TINYINT(1) NOT NULL DEFAULT 1,
    id_reserva INT UNSIGNED NULL,
    CONSTRAINT uq_habitacion_dia UNIQUE (id_habitacion, dia_mes),
    CONSTRAINT fk_ocupacion_habitacion FOREIGN KEY (id_habitacion) REFERENCES habitaciones (id_habitacion) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_ocupacion_reserva FOREIGN KEY (id_reserva) REFERENCES reservas (id_reserva) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT chk_dia_mes CHECK (dia_mes BETWEEN 1 AND 30)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS reserva_servicios (
    id_reserva_servicio INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_reserva INT UNSIGNED NOT NULL,
    id_servicio INT UNSIGNED NOT NULL,
    nombre_snapshot VARCHAR(100) NOT NULL,
    costo_unitario_snapshot INT UNSIGNED NOT NULL,
    subtotal INT UNSIGNED NOT NULL,
    CONSTRAINT uq_reserva_servicio UNIQUE (id_reserva, id_servicio),
    CONSTRAINT fk_res_serv_reserva FOREIGN KEY (id_reserva) REFERENCES reservas (id_reserva) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_res_serv_servicio FOREIGN KEY (id_servicio) REFERENCES servicios (id_servicio) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE = InnoDB;

