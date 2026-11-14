CREATE DATABASE IF NOT EXISTS nexopms_db CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

USE nexopms_db;

CREATE TABLE huespedes (
    id_huesped INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    rut VARCHAR(12) NOT NULL UNIQUE,
    nombre VARCHAR(100) NOT NULL,
    telefono VARCHAR(20) NOT NULL,
    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE = InnoDB;

CREATE TABLE habitaciones (
    id_habitacion INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    numero_habitacion VARCHAR(10) NOT NULL UNIQUE,
    tarifa_base_noche INT UNSIGNED NOT NULL,
    activa TINYINT(1) NOT NULL DEFAULT 1
) ENGINE = InnoDB;

-- Poblar las 4 habitaciones del Hotel Los Arrayanes
INSERT INTO
    habitaciones (
        numero_habitacion,
        tarifa_base_noche,
        activa
    )
VALUES ('101', 45000, 1),
    ('102', 45000, 1),
    ('103', 60000, 1),
    ('104', 70000, 1);

CREATE TABLE reservas (
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
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reserva_huesped FOREIGN KEY (id_huesped) REFERENCES huespedes (id_huesped) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_reserva_habitacion FOREIGN KEY (id_habitacion) REFERENCES habitaciones (id_habitacion) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_dias_validos CHECK (
        dia_inicio BETWEEN 1 AND 30
        AND dias_estadia >= 1
        AND (dia_inicio + dias_estadia - 1) <= 30
    )
) ENGINE = InnoDB;

CREATE TABLE ocupacion_diaria (
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

