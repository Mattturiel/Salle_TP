## API FW:
- [ ] Ajouter fetch règles actives au demarrage => GET /api/configs/active
- [ ] Tester ert ajouter GUI FW

## API MGMT:

### Bug
#### activation règle
  - [x]  => ajout nouveau statut 'PREACTIVE' ds le schema de la DB.
  - [x]  => ajout update status règle 'PREACTIVE' si OK (aprés la verif 8b).
  - [x]  => modifier requète SQL de la route '/api/configs/activate' (et autres) pour ajouter les régles en statut 'PREACTIVE'.

#### Autres

  - [ ]  => Empécher création config sans URLs
  - [ ]  => Empécher création config si date < now()


### Features
### Ajout support status FW:
  - [ ]  => ajout route /fw/status qui renvoie le resultat  de la requete vers API2/fw/status
  - [ ]  =>
  - [ ]  =>
  - [ ]  =>
  - [ ]  =>


