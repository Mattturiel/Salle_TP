## API Gestion config

| méthode | endpoint | description | body / params | réponse succès |
|---|---|---|---|---|
| POST | `/api/auth/login` | authentification | `email`, `mot_de_passe` | 200 + infos utilisateur |
| GET | `/api/salles` | liste des salles | — | 200 + `[{id_salle, nom, capacite, id_vlan}]` |
| GET | `/api/urls` | liste des URLs disponibles | — | 200 + `[{id_url, lien, description}]` |
| POST | `/api/configs` | création config (statut `pending`) | `id_salle`, `id_utilisateur`, `date_config`, `heure_debut`, `heure_fin`, `url_ids[]` | 201 + config créée |
| GET | `/api/configs` | liste toutes les configs | `?statut=pending\|active\|failed` (optionnel) | 200 + `[config]` |
| GET | `/api/configs/active` | configs actives avec détail JOIN | — | 200 + `[config+urls+salle+enseignant]` |
| GET | `/api/configs/<id>` | détail d'une config | — | 200 + config |
| DELETE | `/api/configs/<id>` | suppression (interdit si `active`) | — | 200 ou 409 |
| POST | `/api/configs/<id>/activate` | validation conflits + push API2 | — | 200 / 409 conflit / 502 API2 KO |

```
# ── salles ────────────────────────────────────────────────────────────────
curl -s http://localhost:5000/api/salles

# ── urls ──────────────────────────────────────────────────────────────────
curl -s http://localhost:5000/api/urls

# ── créer une config (statut pending) ────────────────────────────────────
curl -s -X POST http://localhost:5000/api/configs \
  -H "Content-Type: application/json" \
  -d '{
    "id_salle": 3,
    "id_utilisateur": 1,
    "date_config": "2026-06-10",
    "heure_debut": "09:00",
    "heure_fin": "11:00",
    "url_ids": [1, 2]
  }'

# ── lister toutes les configs ─────────────────────────────────────────────
curl -s http://localhost:5000/api/configs

# ── filtrer par statut ────────────────────────────────────────────────────
curl -s "http://localhost:5000/api/configs?statut=pending"
curl -s "http://localhost:5000/api/configs?statut=active"

# ── configs actives (endpoint appelé par API2) ────────────────────────────
curl -s http://localhost:5000/api/configs/active

# ── détail d'une config ───────────────────────────────────────────────────
curl -s http://localhost:5000/api/configs/1

# ── activer une config (push vers API2) ───────────────────────────────────
curl -s -X POST http://localhost:5000/api/configs/4/activate

# ── supprimer une config pending ──────────────────────────────────────────
curl -s -X DELETE http://localhost:5000/api/configs/4
```

## API FW

| méthode | endpoint | description | params | réponse succès |
|---|---|---|---|---|
| POST | `/fw/trigger` | pull les configs actives depuis API 'Gestion config' puis stocke en mémoire + dump fichier JSON local| — | 201 + nb règles chargées + chemin fichier |
| GET | `/fw/rules` | liste toutes les règles en mémoire avec flag `en_cours` | `?active=1` filtre uniquement les règles actuellement valides par rapport à l'heure du FW| 200 + `[rule + en_cours]` |
| GET | `/fw/status` | santé de l'API + compteurs | — | 200 + `regles_en_memoire`, `regles_actives`, `heure_courante` |

```
# ── trigger le pull des règles générées depuis l'API1  ──────────────────────
curl -s -X POST http://localhost:5001/fw/trigger
# ── Afficher le status du FW  ───────────────────────────────────────────────
curl -s http://localhost:5001/fw/status
# ── Afficher les régles actuellement 'enforced'  ────────────────────────────
curl -s http://localhost:5001/fw/rules?active=1
```
