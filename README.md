## Introduction

## Lancement des daemons

> [!NOTE]
> - TODO Creer services systemd pour lancer chaque API sur sa VM.

### API Configuration (port 5000)


> [!IMPORTANT]
> Les variables d'environnement ci-dessous doivent être déclarées (une fois par shell) AVANT le lancement de l'appli.

```bash
# Adresse de la DB MySQL
export DB_HOST='localhost'
# Identifiants connection DB MySQL
export DB_USER='salle_tp_user'
export DB_PASSWORD='moto2015'
# Nom de la DB à utiliser
export DB_NAME='salle_tp'
```

```bash
# Lancement de l'appli ds le framework Flask
python3 app.py
```

---

### API Firewall (port 5001)

Les variables d'environnement ci-dessous doivent être déclarées:
```bash
# URL de l'API1 (Configuration) utilisé pour tirer la config
export API1_URL=http://localhost:5000
# Chemin pour le stockage du fichier de config JSON des régles FW
export FW_RULES_DIR=/opt/salle_tp/fw_data
```

```bash
# Lancement de l'appli ds le framework Flask
python3 fw_api.py
```
---


## Diagrammes de séquence de l'application

### Diagramme original du CDC

```mermaid
sequenceDiagram
    actor Ens as Enseignant
    participant Web as Interface Web
    participant DB as Base MariaDB
    participant Gest as Gestionnaire Configuration
    participant FW as Firewall Stormshield

    Ens->>Web: 1 Se connecter
    Web->>DB: 2 Vérifier identifiants
    DB-->>Web: 3 Résultat authentification
    Ens->>Web: 4 Sélectionner sites autorisés et durée d'accès
    Web->>DB: 5 Enregistrer règles d'accès (et durée)
    Web->>Gest: 6 Demande de génération configuration firewall
    Gest->>DB: 7 Lire paramètres et profils
    DB-->>Gest: 8 Paramètres et profils
    Gest->>Gest: 9 Génération fichier configuration (VLAN, ACL, filtrage temporel...)
    Gest->>FW: 10 Charger configuration
    FW-->>Gest: 11 Accusé de réception
    Gest-->>Web: 12 Configuration appliquée
    Web-->>Ens: 13 Confirmation
```
### Diagramme de l'implementation

#### Détail du cycle de vie d'une régle FW (étapes 4 à 6)

sélection puis enregistrement de la configuration

```mermaid
sequenceDiagram
    actor Ens as Enseignant
    participant Web as Interface Web
    participant API1 as API1 app.py
    participant DB as MariaDB

    Note over Ens,DB: Étapes 4 à 6 - sélection puis enregistrement de la configuration

    Note over Ens,Web: 4 Sélection des sites autorisés et de la durée
    Ens->>Web: choix salle, date, heure_debut/fin, URLs
    opt chargement des listes de référence
        Web->>API1: GET /api/salles
        API1->>DB: SELECT id_salle, nom, capacite, id_vlan FROM salle
        DB-->>API1: liste salles
        API1-->>Web: JSON salles
        Web->>API1: GET /api/urls
        API1->>DB: SELECT id_url, lien, description FROM url
        DB-->>API1: liste URLs
        API1-->>Web: JSON URLs
    end

    Note over Web,DB: 5 Enregistrement des règles d'accès
    Ens->>Web: 5 Valider la configuration
    Web->>API1: POST /api/configs {id_salle, id_utilisateur, date_config, heure_debut, heure_fin, url_ids}

    Note over API1: validation applicative
    API1->>API1: champs requis présents ? sinon 400
    API1->>API1: parse_time() + heure_fin > heure_debut ? sinon 400

    API1->>DB: INSERT INTO configuration (...) statut='pending'
    DB-->>API1: lastrowid = new_id
    loop pour chaque url_id
        API1->>DB: INSERT INTO configuration_url (id_config, id_url)
        DB-->>API1: ok
    end
    API1->>DB: SELECT config + config_with_urls(new_id)
    DB-->>API1: config + URLs associées
    API1-->>Web: 201 {message: config créée, config}

    Note over Ens,DB: 6 La demande de génération suit (=> POST /api/configs/{id}/activate)
    Web-->>Ens: config enregistrée (statut pending)
```

**Analyse:**

**Étape 4 (sélection)** => ne touche pas en écriture la base.

Cette étape s'appuie sur deux routes de lecture pour construire les listes déroulantes de l'IHM : `GET /api/salles` (`list_salles`) et `GET /api/urls` (`list_urls`), ces deux endpoints font de simples `SELECT ... ORDER BY` sans jointure.


| Action            | Type    | Appel API       | Appel DB                                             |
| ----------------- | ------- | --------------- | ---------------------------------------------------- |
| Lister salles | Lecture | GET /api/salles | `SELECT id_salle, nom, capacite, id_vlan FROM salle` |
| Lister urls | Lecture | GET /api/urls | `SELECT ...` |

Exemple de résultat:

```json=
[
  {
    "id_salle": 1,
    "nom": "Salle 21",
    "capacite": 20,
    "id_vlan": 21
  },
  {
    "id_salle": 2,
    "nom": "Salle 22",
    "capacite": 25,
    "id_vlan": 22
  }
]
```

**Étape 5 → route `POST /api/configs`** (`create_config`). C'est ici que se fait l'enregistrement.

Plusieurs contrôles applicatifs précèdent l'`INSERT` :

- présence des champs obligatoires (`id_salle`, `id_utilisateur`, `date_config`, `heure_debut`, `heure_fin`) sinon `400`.
- `parse_time()` normalise `HH:MM` ou `HH:MM:SS` en `HH:MM:SS`, puis vérification `heure_fin > heure_debut` sinon `400` avant même de tenter d'inserer la régle en base.

> [!NOTE]
> Par sécurité une contrainte du schema de la DB `chk_horaire CHECK (heure_fin > heure_debut)` empêche également de créer une régle .

**L'insertion est en deux temps** : 
- d'abord `INSERT` dans `configuration` avec `statut='pending'` forcé (l'enseignant ne choisit jamais le statut), récupération du `lastrowid` (l'id de la régle créé).
- puis une boucle d'`INSERT` dans la table d'association `configuration_url` pour chaque `url_id` => *(relation n-n)*.

> [!IMPORTANT]
> à l'étape 5, **aucun contrôle de conflit horaire** (fonction `has_conflict()`) n'est fait il est volontairement reporté à l'activation.
> Une config peut donc être créée en `pending` même si elle chevauchera une autre, **le conflit n'est bloquant qu'à l'étape du controle de config** `POST .../activate` (étape 7b) executé avant de générer la config.

---

#### Détail du cycle de vie d'une régle FW (étapes 6 à 13)

activation d'une configuration dans le FW

```mermaid
sequenceDiagram
    actor Ens as Enseignant
    participant Web as Interface Web
    participant API1 as API1 app.py
    participant DB as MariaDB
    participant API2 as API2 fw_api.py
    participant FS as Stockage JSON fw_data

    Note over Ens,FS: Étapes 6 à 13 - activation d'une configuration

    Ens->>Web: 6 Demande d'activation config
    Web->>API1: POST /api/configs/{id}/activate

    Note over API1: lecture config + contrôles
    API1->>DB: 7a SELECT configuration WHERE id_config
    DB-->>API1: 8a ligne config (statut, salle, plage)
    API1->>DB: 7b SELECT has_conflict (chevauchement salle/plage)
    DB-->>API1: 8b conflit ou non

    Note over API1: si OK => push vers API2
    API1->>API2: 10 POST /fw/trigger {id_config}

    Note over API2: récupération des règles actives
    API2->>API1: GET /api/configs/active
    API1->>DB: SELECT configs JOIN salle JOIN utilisateur WHERE statut=active
    DB-->>API1: lignes actives + URLs
    API1-->>API2: 8c JSON configs actives

    Note over API2: 9 normalisation dates/heures + dump
    API2->>FS: dump_rules_to_file fw_rules.json
    FS-->>API2: chemin fichier
    API2-->>API1: 11 HTTP 201 {message, fichier}

    Note over API1: maj statut selon code FW
    API1->>DB: 12 UPDATE statut=active fw_response=201
    DB-->>API1: ok
    API1-->>Web: 13 200 {message: config activée}
    Web-->>Ens: Confirmation
```

**Étape 6 → route `POST /api/configs/<id>/activate`** (`activate_config`). C'est le point d'entrée de l'activation, distinct de `POST /api/configs` qui ne fait que créer en statut `pending`.

**Étapes 7-8 (côté API1)** se décomposent en deux lectures DB avant tout appel réseau: le `SELECT` initial sur `configuration`, puis le contrôle `has_conflict()` qui détecte un chevauchement horaire sur la même salle (`heure_debut < %s AND heure_fin > %s`, statut `active`). En cas de conflit => `409`, pas d'appel à API2.

**Étape 10 → `POST /fw/trigger`** : c'est API1 qui appelle API2, avec un `timeout=5`. Si API2 est injoignable => `ConnectionError`, `fw_code=0`, statut `failed`.

**Étapes 7-8 (côté API2)** : `/fw/trigger` rappelle API1 via `GET /api/configs/active` => **API2 ne lit pas la base directement, elle repasse par l'API1 (API2 n'a aucun accès DB). `fetch_active_rules()` transforme ensuite `date_config` et `heure_*` en chaînes pour éviter les soucis de types `datetime.date` / `timedelta` de pymysql.

**Étape 9 → `dump_rules_to_file()`** : écriture du JSON dans `fw_data/fw_rules.json` + cache mémoire `_rules_cache`.

**Étape 11** : API2 répond `201` seulement si fetch configs + dump réussissent.

**Étape 12 → `UPDATE`** : `nouveau_statut = "active" if fw_code == 201 else "failed"`. Le passage à `active` est donc conditionné au code HTTP retourné par API2, comme demandé dans le schéma.

**Étape 13** : `200` si activée, sinon `502` avec le `fw_message`.

NB: la détection « config en cours » (`is_active_now` / route `GET /fw/rules?active=1` etc...) n'intervient pas ici => c'est de l'affichage côté pare-feu, postérieur à l'activation .

---

