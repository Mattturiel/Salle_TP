"""
ui_blueprint.py
SalleTP - IHM web
BTS CIEL E6IR 2026

Blueprint Flask dédié aux routes de rendu HTML.
Aucun accès direct à la BDD - toute la logique passe par les routes /api/*.

Enregistrement dans app.py :
    from ui_blueprint import ui_bp
    app.register_blueprint(ui_bp)
"""

from flask import Blueprint, render_template

ui_bp = Blueprint(
    "ui",
    __name__,
    url_prefix="/ui",
    template_folder="templates",
    static_folder="static",
)


@ui_bp.get("/")
def index():
    """Tableau de bord principal."""
    return render_template("index.html")


@ui_bp.get("/configs")
def page_configs():
    """Liste et gestion des configurations firewall."""
    return render_template("configs.html")


@ui_bp.get("/salles")
def page_salles():
    """Liste des salles et leurs VLAN."""
    return render_template("salles.html")


@ui_bp.get("/fw")
def page_fw():
    """Interface du simulateur firewall (API2)."""
    return render_template("fw.html")
