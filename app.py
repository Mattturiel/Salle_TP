"""
API1 - SalleTP : gestion des configurations firewall
BTS CIEL E6IR 2026

Dépendances : flask, flask-bcrypt, pymysql

Variables d'environnement :
  DB_HOST      (défaut: localhost)
  DB_USER      (défaut: salle_tp_user)
  DB_PASSWORD
  DB_NAME      (défaut: salle_tp)
  FW_API_URL   (défaut: http://127.0.0.1:5001)

Routes :
  
  IHM =>

    GET  /login             => page de connexion
    GET  /logout            => déconnexion
    GET  /              => redirect /ui/
    GET  /ui/           => tableau de bord
    GET  /ui/configs    => gestion des configurations
    GET  /ui/salles     => liste salles / VLAN
    GET  /ui/users      => gestion des utilisateurs

  API REST =>

    POST /api/auth/login
    POST /api/auth/logout
    GET  /api/auth/me
    GET  /api/salles
    GET  /api/urls
    GET  /api/users
    POST /api/users
    GET  /api/users/<id>
    PUT  /api/users/<id>
    DELETE /api/users/<id>
    POST /api/configs
    GET  /api/configs              ?statut=pending|active|failed
    GET  /api/configs/active       (consommé par API FW)
    GET  /api/configs/<id>
    PUT  /api/configs/<id>          (statut pending uniquement)
    DELETE /api/configs/<id>
    POST /api/configs/<id>/activate
"""

import os
import datetime
import pymysql
import pymysql.cursors
import requests
from flask import Flask, jsonify, request, g, abort, session, redirect, url_for, render_template
from flask_bcrypt import Bcrypt

app = Flask(__name__)
app.json.ensure_ascii = False
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me-in-production")

bcrypt = Bcrypt(app)

# Import du Blueprint IHM (ui_blueprint.py)
from ui_blueprint import ui_bp
app.register_blueprint(ui_bp)


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------

_PUBLIC_PATHS = {"/login", "/api/auth/login"}

@app.before_request
def require_login():
    if request.path in _PUBLIC_PATHS or request.path.startswith("/static"):
        return
    if "user" not in session:
        if request.path.startswith("/api/"):
            return jsonify({"error": "non authentifié"}), 401
        return redirect(url_for("login_page"))

@app.context_processor
def inject_current_user():
    return {"current_user": session.get("user")}

def _is_admin():
    return session.get("user", {}).get("droit") == 2

def _current_uid():
    return session.get("user", {}).get("id_utilisateur")

@app.get("/")
def root():
    return redirect(url_for("ui.index"))

@app.get("/login")
def login_page():
    if "user" in session:
        return redirect(url_for("ui.index"))
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


DB_CONF = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "user":     os.getenv("DB_USER",     "salle_tp_user"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME",     "salle_tp"),
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}
FW_API_URL = os.getenv("FW_API_URL", "http://127.0.0.1:5001")


# ---------------------------------------------------------------------------
# Connexion DB par requête Flask
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = pymysql.connect(**DB_CONF)
    return g.db

@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def serialize_row(row):
    """
    Convertit les types non-JSON-sérialisables retournés par pymysql :
      timedelta (colonnes TIME)  => 'HH:MM:SS'
      date                       => 'YYYY-MM-DD'
      datetime                   => 'YYYY-MM-DD HH:MM:SS'
    """
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime.timedelta):
            total = int(v.total_seconds())
            h, rem = divmod(abs(total), 3600)
            m, s   = divmod(rem, 60)
            out[k] = f"{h:02d}:{m:02d}:{s:02d}"
        elif isinstance(v, datetime.datetime):
            out[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, datetime.date):
            out[k] = v.strftime("%Y-%m-%d")
        else:
            out[k] = v
    return out

def query(sql, params=(), one=False):
    """SELECT => liste de dict, ou un seul dict si one=True."""
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        rows = [serialize_row(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows

def execute(sql, params=()):
    """INSERT / UPDATE / DELETE => lastrowid."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_time(s):
    """'HH:MM' ou 'HH:MM:SS' => 'HH:MM:SS'"""
    parts = s.split(":")
    h, m  = int(parts[0]), int(parts[1])
    sec   = int(parts[2]) if len(parts) > 2 else 0
    return f"{h:02d}:{m:02d}:{sec:02d}"

def has_conflict(id_salle, date_cfg, h_debut, h_fin, exclude_id=None):
    """True si une config active ou preactive chevauche la plage sur la même salle."""
    sql = """
        SELECT id_config FROM configuration
        WHERE id_salle    = %s
          AND date_config = %s
          AND statut      IN ('active', 'preactive')
          AND heure_debut < %s
          AND heure_fin   > %s
    """
    params = (id_salle, date_cfg, h_fin, h_debut)
    if exclude_id:
        sql += " AND id_config != %s"
        params += (exclude_id,)
    return query(sql, params, one=True) is not None

def config_with_urls(row):
    """Ajoute la liste des URLs à un dict config."""
    urls = query(
        """SELECT u.id_url, u.lien, u.description
           FROM url u
           JOIN configuration_url cu ON cu.id_url = u.id_url
           WHERE cu.id_config = %s""",
        (row["id_config"],)
    )
    row["urls"] = urls
    return row


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
def login():
    data = request.get_json(force=True)
    user = query("SELECT * FROM utilisateur WHERE email = %s",
                 (data.get("email", ""),), one=True)
    if not user or not bcrypt.check_password_hash(user["mot_de_passe"],
                                                   data.get("mot_de_passe", "")):
        return jsonify({"error": "identifiants invalides"}), 401
    session.permanent = False
    session["user"] = {
        "id_utilisateur": user["id_utilisateur"],
        "nom":    user["nom"],
        "prenom": user["prenom"],
        "email":  user["email"],
        "droit":  user["droit"],
    }
    return jsonify({"message": "ok", "utilisateur": session["user"]}), 200

@app.post("/api/auth/logout")
def api_logout():
    session.clear()
    return jsonify({"message": "déconnecté"}), 200

@app.get("/api/auth/me")
def me():
    return jsonify({"utilisateur": session["user"]}), 200


# ---------------------------------------------------------------------------
# Salles / URLs / Users
# ---------------------------------------------------------------------------

@app.get("/api/salles")
def list_salles():
    return jsonify(query("SELECT id_salle, nom, capacite, id_vlan FROM salle ORDER BY id_salle"))

@app.get("/api/urls")
def list_urls():
    return jsonify(query("SELECT id_url, lien, description FROM url ORDER BY id_url"))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

USER_FIELDS = "id_utilisateur, nom, prenom, email, droit"

@app.get("/api/users")
def list_users():
    return jsonify(query(f"SELECT {USER_FIELDS} FROM utilisateur ORDER BY id_utilisateur"))

@app.get("/api/users/<int:id_utilisateur>")
def get_user(id_utilisateur):
    row = query(f"SELECT {USER_FIELDS} FROM utilisateur WHERE id_utilisateur = %s",
                (id_utilisateur,), one=True)
    if not row:
        abort(404)
    return jsonify(row)

@app.post("/api/users")
def create_user():
    data = request.get_json(force=True)
    required = ["nom", "prenom", "email", "mot_de_passe", "droit"]
    missing  = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"champs manquants: {missing}"}), 400
    if data["droit"] not in (1, 2):
        return jsonify({"error": "droit doit être 1 (enseignant) ou 2 (administrateur)"}), 400
    if query("SELECT id_utilisateur FROM utilisateur WHERE email = %s",
             (data["email"],), one=True):
        return jsonify({"error": "email déjà utilisé"}), 409

    pwd_hash = bcrypt.generate_password_hash(data["mot_de_passe"]).decode()
    new_id = execute(
        "INSERT INTO utilisateur (nom, prenom, email, mot_de_passe, droit) VALUES (%s,%s,%s,%s,%s)",
        (data["nom"], data["prenom"], data["email"], pwd_hash, data["droit"])
    )
    row = query(f"SELECT {USER_FIELDS} FROM utilisateur WHERE id_utilisateur = %s",
                (new_id,), one=True)
    return jsonify({"message": "utilisateur créé", "utilisateur": row}), 201

@app.put("/api/users/<int:id_utilisateur>")
def update_user(id_utilisateur):
    if not query("SELECT id_utilisateur FROM utilisateur WHERE id_utilisateur = %s",
                 (id_utilisateur,), one=True):
        abort(404)
    if not _is_admin() and id_utilisateur != _current_uid():
        return jsonify({"error": "accès refusé : vous ne pouvez modifier que votre propre compte"}), 403
    data = request.get_json(force=True)

    if "email" in data:
        conflict = query("SELECT id_utilisateur FROM utilisateur WHERE email = %s",
                         (data["email"],), one=True)
        if conflict and conflict["id_utilisateur"] != id_utilisateur:
            return jsonify({"error": "email déjà utilisé"}), 409
    if "droit" in data and data["droit"] not in (1, 2):
        return jsonify({"error": "droit doit être 1 (enseignant) ou 2 (administrateur)"}), 400

    fields, params = [], []
    for col in ("nom", "prenom", "email", "droit"):
        if col in data:
            fields.append(f"{col} = %s")
            params.append(data[col])
    if "mot_de_passe" in data and data["mot_de_passe"]:
        fields.append("mot_de_passe = %s")
        params.append(bcrypt.generate_password_hash(data["mot_de_passe"]).decode())

    if not fields:
        return jsonify({"error": "aucun champ à modifier"}), 400

    params.append(id_utilisateur)
    execute(f"UPDATE utilisateur SET {', '.join(fields)} WHERE id_utilisateur = %s", params)
    row = query(f"SELECT {USER_FIELDS} FROM utilisateur WHERE id_utilisateur = %s",
                (id_utilisateur,), one=True)
    return jsonify({"message": "utilisateur mis à jour", "utilisateur": row}), 200

@app.delete("/api/users/<int:id_utilisateur>")
def delete_user(id_utilisateur):
    if not query("SELECT id_utilisateur FROM utilisateur WHERE id_utilisateur = %s",
                 (id_utilisateur,), one=True):
        abort(404)
    if not _is_admin() and id_utilisateur != _current_uid():
        return jsonify({"error": "accès refusé : vous ne pouvez supprimer que votre propre compte"}), 403
    if query("SELECT id_config FROM configuration WHERE id_utilisateur = %s LIMIT 1",
             (id_utilisateur,), one=True):
        return jsonify({"error": "impossible de supprimer : cet utilisateur a des configurations"}), 409
    execute("DELETE FROM utilisateur WHERE id_utilisateur = %s", (id_utilisateur,))
    return jsonify({"message": f"utilisateur {id_utilisateur} supprimé"}), 200

# ---------------------------------------------------------------------------
# Configurations
# ---------------------------------------------------------------------------

@app.post("/api/configs")
def create_config():
    data = request.get_json(force=True)
    required = ["id_salle", "id_utilisateur", "date_config", "heure_debut", "heure_fin"]
    missing  = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"champs manquants: {missing}"}), 400

    url_ids = data.get("url_ids", [])
    if not url_ids:
        return jsonify({"error": "au moins une URL doit être fournie"}), 400

    try:
        date_cfg = datetime.date.fromisoformat(data["date_config"])
    except ValueError:
        return jsonify({"error": "date_config invalide, format attendu: YYYY-MM-DD"}), 400
    if date_cfg < datetime.date.today():
        return jsonify({"error": "date_config ne peut pas être dans le passé"}), 400

    h_debut = parse_time(data["heure_debut"])
    h_fin   = parse_time(data["heure_fin"])
    if h_fin <= h_debut:
        return jsonify({"error": "heure_fin doit être > heure_debut"}), 400

    if date_cfg == datetime.date.today():
        now_hms = datetime.datetime.now().strftime("%H:%M:%S")
        if h_fin <= now_hms:
            return jsonify({"error": "heure_fin est déjà passée pour aujourd'hui"}), 400

    new_id = execute(
        """INSERT INTO configuration
               (id_salle, id_utilisateur, date_config, heure_debut, heure_fin, statut)
           VALUES (%s, %s, %s, %s, %s, 'pending')""",
        (data["id_salle"], data["id_utilisateur"],
         data["date_config"], h_debut, h_fin)
    )
    for uid in url_ids:
        execute("INSERT INTO configuration_url (id_config, id_url) VALUES (%s, %s)",
                (new_id, uid))

    row = query("SELECT * FROM configuration WHERE id_config = %s", (new_id,), one=True)
    return jsonify({"message": "config créée", "config": config_with_urls(row)}), 201


@app.get("/api/configs")
def list_configs():
    statut = request.args.get("statut")
    if statut:
        rows = query("SELECT * FROM configuration WHERE statut = %s ORDER BY id_config",
                     (statut,))
    else:
        rows = query("SELECT * FROM configuration ORDER BY id_config")
    return jsonify([config_with_urls(r) for r in rows])


@app.get("/api/configs/active")
def list_active_configs():
    """Endpoint appelé par API2 pour récupérer les configs actives avec détail."""
    rows = query("""
        SELECT c.id_config, c.id_salle, s.nom AS salle, s.id_vlan,
               c.id_utilisateur,
               CONCAT(u.prenom, ' ', u.nom) AS enseignant,
               c.date_config, c.heure_debut, c.heure_fin,
               c.statut, c.fw_response
        FROM configuration c
        JOIN salle       s ON s.id_salle       = c.id_salle
        JOIN utilisateur u ON u.id_utilisateur = c.id_utilisateur
        WHERE c.statut IN ('active', 'preactive')
        ORDER BY c.id_config
    """)
    return jsonify([config_with_urls(r) for r in rows])


@app.get("/api/configs/<int:id_config>")
def get_config(id_config):
    row = query("SELECT * FROM configuration WHERE id_config = %s",(id_config,), one=True)
    if not row:
        abort(404)
    return jsonify(config_with_urls(row))


@app.put("/api/configs/<int:id_config>")
def update_config(id_config):
    cfg = query("SELECT statut, id_utilisateur FROM configuration WHERE id_config = %s", (id_config,), one=True)
    if not cfg:
        abort(404)
    if not _is_admin() and cfg["id_utilisateur"] != _current_uid():
        return jsonify({"error": "accès refusé : vous ne pouvez modifier que vos propres configurations"}), 403
    if cfg["statut"] != "pending":
        return jsonify({"error": "seules les configurations en statut 'pending' peuvent être modifiées"}), 409

    data = request.get_json(force=True)

    url_ids = data.get("url_ids", [])
    if not url_ids:
        return jsonify({"error": "au moins une URL doit être fournie"}), 400

    try:
        date_cfg = datetime.date.fromisoformat(data["date_config"])
    except (KeyError, ValueError):
        return jsonify({"error": "date_config invalide, format attendu: YYYY-MM-DD"}), 400
    if date_cfg < datetime.date.today():
        return jsonify({"error": "date_config ne peut pas être dans le passé"}), 400

    try:
        h_debut = parse_time(data["heure_debut"])
        h_fin   = parse_time(data["heure_fin"])
    except (KeyError, ValueError):
        return jsonify({"error": "heure_debut et heure_fin sont requis (format HH:MM)"}), 400
    if h_fin <= h_debut:
        return jsonify({"error": "heure_fin doit être > heure_debut"}), 400

    if date_cfg == datetime.date.today():
        if h_fin <= datetime.datetime.now().strftime("%H:%M:%S"):
            return jsonify({"error": "heure_fin est déjà passée pour aujourd'hui"}), 400

    execute("""UPDATE configuration
               SET id_salle=%s, id_utilisateur=%s, date_config=%s,
                   heure_debut=%s, heure_fin=%s
               WHERE id_config=%s""",
            (data["id_salle"], data["id_utilisateur"],
             data["date_config"], h_debut, h_fin, id_config))

    execute("DELETE FROM configuration_url WHERE id_config = %s", (id_config,))
    for uid in url_ids:
        execute("INSERT INTO configuration_url (id_config, id_url) VALUES (%s, %s)",
                (id_config, uid))

    row = query("SELECT * FROM configuration WHERE id_config = %s", (id_config,), one=True)
    return jsonify({"message": "config mise à jour", "config": config_with_urls(row)}), 200


@app.delete("/api/configs/<int:id_config>")
def delete_config(id_config):
    row = query("SELECT statut, id_utilisateur FROM configuration WHERE id_config = %s",
                (id_config,), one=True)
    if not row:
        abort(404)
    if not _is_admin() and row["id_utilisateur"] != _current_uid():
        return jsonify({"error": "accès refusé : vous ne pouvez supprimer que vos propres configurations"}), 403
    if row["statut"] == "active":
        return jsonify({"error": "impossible de supprimer une config active"}), 409
    execute("DELETE FROM configuration WHERE id_config = %s", (id_config,))
    return jsonify({"message": f"supression config {id_config} OK"}), 200


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

@app.post("/api/configs/<int:id_config>/activate")
def activate_config(id_config):
    cfg = query("SELECT * FROM configuration WHERE id_config = %s", (id_config,), one=True)
    if not cfg:
        abort(404)

    if cfg["statut"] in ("active", "preactive"):
        return jsonify({"message": "config deja active", "config": config_with_urls(cfg)}), 200
    if cfg["statut"] == "failed":
        return jsonify({"error": "config en échec, recréer ou corriger"}), 409

    if has_conflict(cfg["id_salle"], cfg["date_config"],
                    cfg["heure_debut"], cfg["heure_fin"], exclude_id=id_config):
        return jsonify({
            "error": "conflit horaire : une config active existe sur cette salle/plage !"
        }), 409

    # Marque preactive avant d'appeler API2 pour que /api/configs/active l'inclue
    execute("UPDATE configuration SET statut = 'preactive' WHERE id_config = %s",
            (id_config,))

    # push vers API2
    try:
        resp    = requests.post(f"{FW_API_URL}/fw/trigger",
                                json={"id_config": id_config}, timeout=5)
        fw_code = resp.status_code
        fw_msg  = resp.text[:500]
    except requests.exceptions.ConnectionError:
        fw_code = 0
        fw_msg  = "API2 injoignable"

    nouveau_statut = "active" if fw_code == 201 else "failed"
    execute("""UPDATE configuration
               SET statut = %s, fw_response = %s, fw_message = %s
               WHERE id_config = %s""",
            (nouveau_statut, fw_code, fw_msg, id_config))

    cfg = query("SELECT * FROM configuration WHERE id_config = %s",
                (id_config,), one=True)

    if nouveau_statut == "active":
        return jsonify({"message": "activation config OK", "config": config_with_urls(cfg)}), 200
    return jsonify({
        "error": f"API2 a répondu {fw_code} — statut passé à failed",
        "fw_message": fw_msg,
        "config": config_with_urls(cfg),
    }), 502


# ---------------------------------------------------------------------------
# Proxy statut API2
# ---------------------------------------------------------------------------

@app.get("/fw/status")
def fw_status():
    try:
        resp = requests.get(f"{FW_API_URL}/fw/status", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "API2 injoignable"}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
