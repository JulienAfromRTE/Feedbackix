# Feedbackix

Application Flask de collecte et gestion de feedbacks sur les applications internes de la DSIT, déployée via **Projectix** (plateforme interne qui héberge des apps Flask sur des VMs d'entreprise, derrière Nginx avec un préfixe `/feedbackix/`).

## Stack

- **Backend** : Python 3 + Flask (uniquement, pas d'ORM ni de blueprint)
- **DB** : SQLite, fichier `data/app.db`, mode WAL, `foreign_keys=ON`
- **Front** : templates Jinja2 + CSS custom (design system DSIT) + JS inline
- **Libs externes (CDN)** : Quill.js 1.3.7 (éditeur riche), Chart.js 3.9.1 (graphe note mensuelle)
- **Aucune dépendance npm** — tout est servi via CDN ou en static

## Métadonnées Projectix

Définies en haut de [app.py](app.py) (ne pas supprimer, lues par la plateforme) :

- `APP_NAME = "Feedbackix"`
- `APP_SLUG = "feedbackix"`
- `APP_RELEASE = "v1.0"`
- `APP_ICON = "💬"`, `APP_COLOR = "#3b82f6"`
- Endpoint `/health` obligatoire (renvoie status, uptime, request_count)

## Structure

```
app.py                       # Toute la logique : config, DB, routes, helpers
requirements.txt             # flask
data/app.db                  # SQLite (créé au boot)
static/
  css/style.css
  js/app.js
  uploads/<slug>/...         # Images uploadées via Quill, par app
templates/
  base.html                  # Layout + nav + flash + Quill/Chart conditionnels
  index.html                 # Grille des apps
  app_detail.html            # Dashboard app (note + chart + versions + feedbacks)
  feedback_new.html          # Formulaire avec Quill
  feedback_detail.html       # Détail + commentaires + workflow statut
  settings.html              # Paramétrage : apps / catégories / versions / admins
```

## Modèle de données

7 tables, toutes avec `ON DELETE CASCADE` depuis `apps` :

- `apps` (id, name, slug unique, description, icon, color)
- `app_admins` (app_id, name, service) — autorisés à changer un statut
- `categories` (app_id NULL = catégorie par défaut globale, sinon spécifique app)
- `versions` (app_id, version_name, release_date, description)
- `feedbacks` (app_id, category_id, version_id, title, content_html, author_name/service, is_anonymous, priority, status, vote_count)
- `feedback_votes` (feedback_id, voter_ip) — déduplication par IP
- `comments` (feedback_id, author_name, author_service, content)
- `ratings` (app_id, rating 1-5, rater_name, rater_service)

Catégories par défaut (auto-créées au premier boot) : Bug / Amélioration / Nouvelle fonctionnalité / Question / Performance / Interface UX.

## Constantes métier

```python
STATUS_LABELS   = nouveau, en_cours, traite, en_attente, abandonne
PRIORITY_LABELS = basse, normale, haute, critique
```

Toujours passer ces dicts au template — les badges (label + couleur) en dépendent.

## Routes

**Pages** :
- `/` — liste apps
- `/app/<slug>` — dashboard (filtres `status`/`category`/`priority` + `sort` votes/date/priority)
- `/app/<slug>/feedback/new` — formulaire (GET + POST)
- `/app/<slug>/feedback/<fid>` — détail + commentaires
- `/settings` — paramétrage global (accordéon par app)

**AJAX (JSON)** :
- `POST /app/<slug>/feedback/<fid>/vote` — dédup IP
- `POST /app/<slug>/feedback/<fid>/comment` — body : `author_name`, `author_service`, `content`
- `POST /app/<slug>/feedback/<fid>/status` — body : `admin_name`, `admin_service`, `status` (vérif contre `app_admins`, comparaison case-insensitive trim)
- `POST /app/<slug>/rate` — body : `rating` (1-5), `rater_name?`, `rater_service?`
- `POST /app/<slug>/feedback/upload-image` — multipart `image`, retourne `{url}` via `url_for('static', ...)`

**Settings** : `/settings/apps/{new,<aid>/edit,<aid>/delete}` + sous-routes pour `categories`, `versions`, `admins`.

**Système** : `/health`

## Décisions produit (validées avec l'utilisateur)

Conserver ces choix, pas les redébattre sans raison :

- **Pas d'auth** : consultation libre. Pour un feedback nominatif → saisie libre nom + service à chaque fois (aucun login, aucun cookie de session pour identité).
- **Anonymat** : case à cocher dans le formulaire ; si cochée, name/service sont stockés `NULL`.
- **Commentaires** : ouverts à tous, nom + service saisis à chaque post.
- **Changement de statut** : réservé aux admins de l'app, vérifiés par couple (nom, service) **trim + lowercase**, définis dans Settings.
- **Vote** : dédupliqué par `request.remote_addr` (l'app tourne derrière Nginx — `X-Forwarded-For` n'est pas géré, on s'en contente pour v1.0).
- **Note** : chaque utilisateur peut noter ; le dashboard affiche la moyenne. Graphe mois par mois sur 12 mois (`strftime('%Y-%m', ...)`).
- **Catégories** : 6 par défaut globales (`app_id IS NULL`) + catégories spécifiques par app, créées dans Settings.
- **Settings** : accessible à tout le monde en v1.0 (à durcir si besoin).
- **Images** : uploadées vers `static/uploads/<slug>/<uuid>.<ext>`, URL retournée via `url_for('static', ...)` pour rester correcte derrière le préfixe Nginx `/feedbackix/`.

## Gotchas / pièges déjà rencontrés

- **Préfixe Nginx `/feedbackix/`** : utiliser exclusivement `url_for(...)` côté serveur. Côté JS, les `fetch()` utilisent des chemins **relatifs** (`fetch('upload-image')`, `fetch('vote')`...) qui se résolvent correctement depuis l'URL courante.
- **`{templates,static/...}`** : si tu vois ce dossier réapparaître, c'est un `mkdir` lancé sans brace expansion (zsh sans `setopt`, ou guillemets autour des accolades). Le supprimer.
- **`db.close()` partout** : pas de `g` ni de pool, chaque vue ouvre/ferme. Ne pas oublier le `close()` sur les chemins d'erreur, surtout `abort(404)` dans `feedback_detail`.
- **`content_html` est rendu avec `| safe`** dans `feedback_detail.html` — Quill produit du HTML qu'on fait confiance. Acceptable pour outil interne, mais à ne pas relâcher sur un endpoint public.
- **`SECRET_KEY`** : en dev, valeur en dur ; en prod Projectix, lue depuis `os.environ['SECRET_KEY']`.

## Lancer en local

```bash
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

La base est créée automatiquement au premier démarrage (`init_db()` est appelé au chargement du module).

## État / TODO connus

- v1.0 livré : tout le périmètre demandé est en place (cf. liste validée dans l'historique de conception).
- Pas de tests automatisés.
- Pas de pagination sur la liste des feedbacks (OK tant que volume reste raisonnable par app).
- Pas de gestion fine des permissions sur `/settings` (volontaire pour v1.0).
