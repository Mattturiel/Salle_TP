-- =============================================================
-- schema_salle_tp.sql
-- projet BTS CIEL IR 2026 - gestion firewall salles TP
-- version 1.1
-- =============================================================

CREATE DATABASE IF NOT EXISTS salle_tp
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE salle_tp;

-- -------------------------------------------------------------
-- table : salle
-- -------------------------------------------------------------
CREATE TABLE salle (
    id_salle    INT             NOT NULL AUTO_INCREMENT,
    nom         VARCHAR(50)     NOT NULL,
    capacite    INT             NOT NULL DEFAULT 20,
    id_vlan     SMALLINT        NOT NULL COMMENT 'VLAN ID 802.1Q associé à la salle (1-4094)',
    CONSTRAINT pk_salle     PRIMARY KEY (id_salle),
    CONSTRAINT uq_vlan      UNIQUE (id_vlan),
    CONSTRAINT chk_vlan_range CHECK (id_vlan BETWEEN 1 AND 4094)
) ENGINE=InnoDB;

-- -------------------------------------------------------------
-- table : utilisateur
-- -------------------------------------------------------------
CREATE TABLE utilisateur (
    id_utilisateur  INT             NOT NULL AUTO_INCREMENT,
    nom             VARCHAR(100)    NOT NULL,
    prenom          VARCHAR(100)    NOT NULL,
    email           VARCHAR(255)    NOT NULL,
    mot_de_passe    VARCHAR(255)    NOT NULL COMMENT 'hash bcrypt',
    droit           TINYINT         NOT NULL DEFAULT 1
                        COMMENT '1=enseignant, 2=administrateur',
    CONSTRAINT pk_utilisateur   PRIMARY KEY (id_utilisateur),
    CONSTRAINT uq_email         UNIQUE (email)
) ENGINE=InnoDB;

-- -------------------------------------------------------------
-- table : url
-- -------------------------------------------------------------
CREATE TABLE url (
    id_url      INT             NOT NULL AUTO_INCREMENT,
    lien        TEXT            NOT NULL,
    description VARCHAR(255)    NULL,
    CONSTRAINT pk_url PRIMARY KEY (id_url)
) ENGINE=InnoDB;

-- -------------------------------------------------------------
-- table : configuration
--
-- statut : cycle de vie du déploiement de la régle firewall
--   pending   => créée, envoi API non encore tenté
--   preactive => vérifications passées, appel POST /fw/trigger en cours
--   active    => API firewall a retourné HTTP 201
--   failed    => erreur API ou timeout
--
-- la fenêtre temporelle (date_config + heure_debut + heure_fin)
-- est transmise dans le JSON de config au firewall ;
-- c'est l'API FW qui filtre par rapport à son horloge locale
-- -------------------------------------------------------------
CREATE TABLE configuration (
    id_config       INT         NOT NULL AUTO_INCREMENT,
    id_salle        INT         NOT NULL,
    id_utilisateur  INT         NOT NULL,
    date_config     DATE        NOT NULL    COMMENT 'date d activation de la règle',
    heure_debut     TIME        NOT NULL,
    heure_fin       TIME        NOT NULL,
    statut          ENUM('pending','preactive','active','failed') NOT NULL DEFAULT 'pending' COMMENT 'état du déploiement firewall - preactive pendant appel API2, active sur réception HTTP 201',
    date_creation   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_maj        DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    fw_response     SMALLINT    NULL COMMENT 'dernier code HTTP retourné par l API Stormshield',
    fw_message      TEXT        NULL COMMENT 'corps de la réponse ou message d erreur',
    CONSTRAINT pk_configuration PRIMARY KEY (id_config),
    CONSTRAINT fk_config_salle
        FOREIGN KEY (id_salle)
        REFERENCES salle (id_salle)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_config_utilisateur
        FOREIGN KEY (id_utilisateur)
        REFERENCES utilisateur (id_utilisateur)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_horaire
        CHECK (heure_fin > heure_debut)
) ENGINE=InnoDB;

-- index utile pour le gestionnaire de config (filtrage sur statut)
CREATE INDEX idx_config_statut_date
    ON configuration (statut, date_config);

-- -------------------------------------------------------------
-- table : configuration_url  (association n-n)
-- -------------------------------------------------------------
CREATE TABLE configuration_url (
    id_config   INT NOT NULL,
    id_url      INT NOT NULL,
    CONSTRAINT pk_configuration_url PRIMARY KEY (id_config, id_url),
    CONSTRAINT fk_cu_config
        FOREIGN KEY (id_config)
        REFERENCES configuration (id_config)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_cu_url
        FOREIGN KEY (id_url)
        REFERENCES url (id_url)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

-- =============================================================
-- données de test
-- =============================================================

INSERT INTO salle (nom, capacite, id_vlan) VALUES
    ('Salle 21', 20, 21),
    ('Salle 22', 20, 22),
    ('Salle 23', 20, 23),
    ('Salle 24', 20, 24),
    ('Salle 25', 20, 25);

-- mot_de_passe = 'changeme' (bcrypt cost=4, usage test uniquement)
INSERT INTO utilisateur (nom, prenom, email, mot_de_passe, droit) VALUES
    ('Turiel', 'Matthieu', 'matt@labmatt.local',        '$2b$04$lI6jy9DUW1oWtu1SMvu2.ucnsjEIOpJbANhgPmsbCG2YRqJBxjvgy', 2),
    ('Dupont', 'Toto',     'toto.dupont@labmatt.local', '$2b$04$lI6jy9DUW1oWtu1SMvu2.ucnsjEIOpJbANhgPmsbCG2YRqJBxjvgy',  1),
    ('System',    'Admin',    'admin@labmatt.local',       '$2b$04$lI6jy9DUW1oWtu1SMvu2.ucnsjEIOpJbANhgPmsbCG2YRqJBxjvgy',  2);

INSERT INTO url (lien, description) VALUES
    ('www.netacad.com',        'Cisco Netacad'),
    ('www.pronote.fr',         'ENT Pronote'),
    ('www.wikipedia.org',      'Wikipedia'),
    ('www.openclassrooms.com', 'OpenClassrooms'),
    ('docs.python.org',        'Documentation Python officielle');

-- configuration 1 : active (HTTP 201 reçu)
INSERT INTO configuration
    (id_salle, id_utilisateur, date_config, heure_debut, heure_fin, statut, fw_response)
VALUES (2, 1, '2026-04-10', '10:00:00', '12:00:00', 'active', 201);

INSERT INTO configuration_url (id_config, id_url) VALUES (1, 1), (1, 2);

-- configuration 2 : active (HTTP 201 reçu)
INSERT INTO configuration
    (id_salle, id_utilisateur, date_config, heure_debut, heure_fin, statut, fw_response)
VALUES (1, 2, '2026-04-11', '14:00:00', '16:00:00', 'active', 201);

INSERT INTO configuration_url (id_config, id_url) VALUES (2, 3), (2, 4);

-- configuration 3 : pending (déploiement non encore confirmé)
INSERT INTO configuration
    (id_salle, id_utilisateur, date_config, heure_debut, heure_fin, statut)
VALUES (3, 1, '2026-04-12', '08:00:00', '10:00:00', 'pending');

INSERT INTO configuration_url (id_config, id_url) VALUES (3, 5);

-- créer l'user avec mot de passe
CREATE USER 'salle_tp_user'@'localhost' IDENTIFIED BY 'moto2015';

-- droits minimum sur la DB du projet
GRANT SELECT, INSERT, UPDATE, DELETE ON salle_tp.* TO 'salle_tp_user'@'localhost';

FLUSH PRIVILEGES;
