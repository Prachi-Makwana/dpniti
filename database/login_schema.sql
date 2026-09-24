CREATE DATABASE IF NOT EXISTS auth_db;
USE auth_db;

CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(150) NOT NULL,
    role ENUM('student', 'faculty', 'admin') NOT NULL,
    semester TINYINT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT users_student_semester CHECK (
        (role = 'student' AND semester IN (5, 7)) OR
        (role IN ('faculty', 'admin') AND semester IS NULL)
    )
);

-- Student username convention enforced by the login API:
-- 23BCP... = semester 7, 24BCP... = semester 5.
-- The semester column must match the prefix when one is used.
