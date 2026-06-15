"""
API2 - SalleTP : simulateur firewall Stormshield
BTS CIEL E6IR 2026

Dépendances : flask, requests

Variables d'environnement :
  API1_URL      URL de base de l'API1  (défaut: http://127.0.0.1:5000)
  FW_RULES_DIR  répertoire de dump JSON (défaut: ./fw_data)

Routes :
  POST  /fw/trigger        appelée par API1 pour déclencher le chargement
  GET   /fw/rules          affiche toutes les règles + détection config en cours
  GET   /fw/status         santé de l'API2
"""

import os
import json
import requests
from datetime import datetime
from flask import Flask, jsonify, request, redirect, render_template

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "fw_templates"))

API1_URL     = os.getenv("API1_URL",     "http://127.0.0.1:5000")
FW_RULES_DIR = os.getenv("FW_RULES_DIR", os.path.join(os.path.dirname(__file__), "fw_data"))

# stockage en mémoire des règles actives
_rules_cache = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_active_rules():
    """
    Appelle GET /api/configs/active sur API1.
    Normalise date_config et heure_* en str pour éviter les problèmes
    de types pymysql (datetime.date / datetime.timedelta).
    """
    resp = requests.get(f"{API1_URL}/api/configs/active", timeout=5)
    resp.raise_for_status()
    rules = resp.json()
    for rule in rules:
        rule["date_config"] = str(rule["date_config"])[:10]
        for field in ("heure_debut", "heure_fin"):
            parts = str(rule[field]).split(":")
            rule[field] = f"{int(parts[0]):02d}:{parts[1]}:{parts[2] if len(parts) > 2 else '00'}"
    return rules


def dump_rules_to_file(rules):
    """Écrit les règles en JSON dans FW_RULES_DIR/fw_rules.json."""
    os.makedirs(FW_RULES_DIR, exist_ok=True)
    path = os.path.join(FW_RULES_DIR, "fw_rules.json")
    with open(path, "w") as f:
        json.dump(rules, f, indent=2)
    return path


def is_active_now(rule):
    """
    Retourne True si la règle est en cours d'activation.
    date_config et heure_* sont garantis strings après fetch_active_rules.
    """
    now = datetime.now()

    if now.strftime("%Y-%m-%d") != rule["date_config"]:
        return False

    def to_dt(hms):
        h, m, s = hms.split(":")
        return now.replace(hour=int(h), minute=int(m), second=int(s), microsecond=0)

    return to_dt(rule["heure_debut"]) <= now <= to_dt(rule["heure_fin"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/fw/trigger")
def trigger():
    """
    Appelée par API1 après validation d'une config.
    1. Récupère toutes les configs actives depuis API1
    2. Stocke en mémoire + dump JSON local
    3. Répond 201 si tout s'est bien passé
    """
    global _rules_cache

    try:
        rules = fetch_active_rules()
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"impossible de joindre API1 : {e}"}), 502

    _rules_cache = rules

    try:
        path = dump_rules_to_file(rules)
    except OSError as e:
        return jsonify({"error": f"écriture JSON échouée : {e}"}), 500

    return jsonify({
        "message": f"{len(rules)} règle(s) chargée(s)",
        "fichier": path,
    }), 201


@app.get("/fw/rules")
def list_rules():
    """
    Affiche les règles en mémoire avec flag en_cours.
    ?active=1  => filtre uniquement les règles en cours d'activation.
    """
    only_active = request.args.get("active", "0") == "1"
    result = []
    for rule in _rules_cache:
        entry = dict(rule)
        entry["en_cours"] = is_active_now(rule)
        if only_active and not entry["en_cours"]:
            continue
        result.append(entry)
    return jsonify(result)


@app.get("/fw/status")
def status():
    actives = sum(1 for r in _rules_cache if is_active_now(r))
    return jsonify({
        "status":          "ok",
        "regles_en_memoire": len(_rules_cache),
        "regles_actives":    actives,
        "heure_courante":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }), 200


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return redirect("/ui/fw")

@app.get("/ui/fw")
def ui_fw():
    return render_template("fw.html")


# ---------------------------------------------------------------------------
# Chargement initial au démarrage
# ---------------------------------------------------------------------------

def _startup_load():
    global _rules_cache
    try:
        rules = fetch_active_rules()
        _rules_cache = rules
        dump_rules_to_file(rules)
        print(f"[startup] {len(rules)} règle(s) chargée(s) depuis API1")
    except Exception as e:
        print(f"[startup] impossible de joindre API1 : {e} — cache vide")

_startup_load()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
