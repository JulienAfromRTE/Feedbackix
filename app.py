#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feedbackix — Collecte et gestion des feedbacks sur les applications internes DSIT
Module Flask deploye via Projectix
"""

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, flash, abort)
import os, time, logging, re, uuid, sqlite3
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'feedbackix-dev-key')

# ════════════════════════════════════════════
# CONFIGURATION — NE PAS SUPPRIMER
# ════════════════════════════════════════════
APP_NAME = "Feedbackix"
APP_SLUG = "feedbackix"
APP_RELEASE = "v1.0"
APP_DESCRIPTION = "Collecte et gestion des feedbacks sur les applications internes DSIT"
APP_ICON = "💬"
APP_COLOR = "#3b82f6"
APP_CATEGORY = ""

# ════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(APP_NAME)

# ════════════════════════════════════════════
# HEALTH / COMPTEUR
# ════════════════════════════════════════════
request_count = 0
start_time = time.time()

@app.before_request
def count_requests():
    global request_count
    request_count += 1

# ════════════════════════════════════════════
# BASE DE DONNEES
# ════════════════════════════════════════════
DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'app.db')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

DEFAULT_CATEGORIES = [
    ('Bug / Anomalie', '#ef4444'),
    ('Amelioration', '#3b82f6'),
    ('Nouvelle fonctionnalite', '#8b5cf6'),
    ('Question', '#f59e0b'),
    ('Performance', '#10b981'),
    ('Interface / UX', '#ec4899'),
]

def init_db():
    db = get_db()

    db.execute("""CREATE TABLE IF NOT EXISTS app_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        sort_order INTEGER DEFAULT 0
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '📱',
        color TEXT DEFAULT '#3b82f6',
        group_id INTEGER REFERENCES app_groups(id) ON DELETE SET NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS app_admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        service TEXT DEFAULT '',
        FOREIGN KEY (app_id) REFERENCES apps(id) ON DELETE CASCADE
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER,
        name TEXT NOT NULL,
        color TEXT DEFAULT '#3b82f6',
        is_default INTEGER DEFAULT 0
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER NOT NULL,
        version_name TEXT NOT NULL,
        release_date DATE,
        description TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (app_id) REFERENCES apps(id) ON DELETE CASCADE
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS feedbacks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER NOT NULL,
        category_id INTEGER,
        version_id INTEGER,
        title TEXT NOT NULL,
        content_html TEXT DEFAULT '',
        author_name TEXT,
        author_service TEXT,
        is_anonymous INTEGER DEFAULT 0,
        priority TEXT DEFAULT 'normale',
        status TEXT DEFAULT 'nouveau',
        vote_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (app_id) REFERENCES apps(id) ON DELETE CASCADE,
        FOREIGN KEY (category_id) REFERENCES categories(id),
        FOREIGN KEY (version_id) REFERENCES versions(id)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS feedback_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_id INTEGER NOT NULL,
        voter_ip TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (feedback_id) REFERENCES feedbacks(id) ON DELETE CASCADE
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_id INTEGER NOT NULL,
        author_name TEXT NOT NULL,
        author_service TEXT DEFAULT '',
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (feedback_id) REFERENCES feedbacks(id) ON DELETE CASCADE
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER NOT NULL,
        rating INTEGER NOT NULL,
        rater_name TEXT,
        rater_service TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (app_id) REFERENCES apps(id) ON DELETE CASCADE
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS feedback_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_id INTEGER NOT NULL,
        editor_name TEXT NOT NULL,
        editor_service TEXT DEFAULT '',
        edited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        changed_fields TEXT NOT NULL,
        FOREIGN KEY (feedback_id) REFERENCES feedbacks(id) ON DELETE CASCADE
    )""")

    existing = db.execute("SELECT COUNT(*) as c FROM categories WHERE is_default=1").fetchone()['c']
    if existing == 0:
        for (name, color) in DEFAULT_CATEGORIES:
            db.execute("INSERT INTO categories (app_id, name, color, is_default) VALUES (NULL, ?, ?, 1)",
                       (name, color))

    # Migrate: add group_id to apps if column doesn't exist yet
    cols = [r[1] for r in db.execute("PRAGMA table_info(apps)").fetchall()]
    if 'group_id' not in cols:
        db.execute("ALTER TABLE apps ADD COLUMN group_id INTEGER REFERENCES app_groups(id) ON DELETE SET NULL")

    existing_groups = db.execute("SELECT COUNT(*) as c FROM app_groups").fetchone()['c']
    if existing_groups == 0:
        for i, name in enumerate(['Finance', 'Industriel', 'Réseau', 'Marché']):
            db.execute("INSERT INTO app_groups (name, sort_order) VALUES (?, ?)", (name, i))

    db.commit()
    db.close()

init_db()

# ════════════════════════════════════════════
# CONSTANTES METIER
# ════════════════════════════════════════════
STATUS_LABELS = {
    'nouveau':    ('Nouveau',             '#3b82f6'),
    'en_cours':   ('En cours',            '#f59e0b'),
    'traite':     ('Traite',              '#10b981'),
    'en_attente': ("En attente d'info",   '#8b5cf6'),
    'abandonne':  ('Abandonne',           '#6b7280'),
}

PRIORITY_LABELS = {
    'basse':    ('Basse',    '#10b981'),
    'normale':  ('Normale',  '#3b82f6'),
    'haute':    ('Haute',    '#f59e0b'),
    'critique': ('Critique', '#ef4444'),
}

# ════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════
def get_app_by_slug(slug):
    db = get_db()
    row = db.execute("SELECT * FROM apps WHERE slug=?", (slug,)).fetchone()
    db.close()
    return row

def get_app_categories(app_id):
    db = get_db()
    cats = db.execute(
        "SELECT * FROM categories WHERE app_id IS NULL OR app_id=? ORDER BY is_default DESC, name",
        (app_id,)
    ).fetchall()
    db.close()
    return cats

def get_avg_rating(app_id):
    db = get_db()
    row = db.execute(
        "SELECT AVG(rating) as avg, COUNT(*) as cnt FROM ratings WHERE app_id=?", (app_id,)
    ).fetchone()
    db.close()
    avg = row['avg'] if row['avg'] else 0
    return round(avg, 1), row['cnt']

def get_rating_history(app_id):
    db = get_db()
    rows = db.execute("""
        SELECT strftime('%Y-%m', created_at) as month,
               ROUND(AVG(rating), 2) as avg_rating,
               COUNT(*) as cnt
        FROM ratings WHERE app_id=?
        GROUP BY month ORDER BY month DESC LIMIT 12
    """, (app_id,)).fetchall()
    db.close()
    return list(reversed(rows))

def slugify(text):
    text = text.lower().strip()
    for src, dst in [('à','a'),('â','a'),('ä','a'),('é','e'),('è','e'),('ê','e'),
                     ('ë','e'),('î','i'),('ï','i'),('ô','o'),('ö','o'),('û','u'),
                     ('ü','u'),('ù','u'),('ç','c')]:
        text = text.replace(src, dst)
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text

# ════════════════════════════════════════════
# ROUTES PRINCIPALES
# ════════════════════════════════════════════

@app.route('/')
def index():
    db = get_db()
    groups = db.execute("SELECT * FROM app_groups ORDER BY sort_order, name").fetchall()
    apps_raw = db.execute("SELECT * FROM apps ORDER BY name").fetchall()

    apps_data = []
    for a in apps_raw:
        avg, cnt = get_avg_rating(a['id'])
        fb_count = db.execute(
            "SELECT COUNT(*) as c FROM feedbacks WHERE app_id=?", (a['id'],)
        ).fetchone()['c']
        apps_data.append({
            'id': a['id'], 'name': a['name'], 'slug': a['slug'],
            'description': a['description'], 'icon': a['icon'], 'color': a['color'],
            'group_id': a['group_id'],
            'avg_rating': avg, 'rating_count': cnt, 'feedback_count': fb_count
        })

    grouped = []
    group_ids = {g['id']: g for g in groups}
    seen = set()
    for g in groups:
        apps_in_group = [a for a in apps_data if a['group_id'] == g['id']]
        if apps_in_group:
            grouped.append({'group': g, 'apps': apps_in_group})
        seen.update(a['id'] for a in apps_in_group)
    ungrouped = [a for a in apps_data if a['id'] not in seen]

    db.close()
    return render_template('index.html', grouped=grouped, ungrouped=ungrouped, apps=apps_data,
                           APP_NAME=APP_NAME, APP_RELEASE=APP_RELEASE, APP_ICON=APP_ICON)


@app.route('/app/<slug>')
def app_detail(slug):
    app_row = get_app_by_slug(slug)
    if not app_row:
        abort(404)

    db = get_db()
    avg_rating, rating_count = get_avg_rating(app_row['id'])
    rating_history = get_rating_history(app_row['id'])
    categories = get_app_categories(app_row['id'])

    versions = db.execute("""
        SELECT v.*, COUNT(f.id) as fb_count
        FROM versions v
        LEFT JOIN feedbacks f ON f.version_id = v.id
        WHERE v.app_id=? GROUP BY v.id ORDER BY v.release_date ASC
    """, (app_row['id'],)).fetchall()

    status_filter   = request.args.get('status', '')
    cat_filter      = request.args.get('category', '')
    priority_filter = request.args.get('priority', '')
    sort_by         = request.args.get('sort', 'votes')

    query = """SELECT f.*, c.name as cat_name, c.color as cat_color,
                      v.version_name as planned_version,
                      v.release_date as planned_release_date,
                      COUNT(cm.id) as comment_count
               FROM feedbacks f
               LEFT JOIN categories c ON c.id = f.category_id
               LEFT JOIN versions v ON v.id = f.version_id
               LEFT JOIN comments cm ON cm.feedback_id = f.id
               WHERE f.app_id=?"""
    params = [app_row['id']]

    if status_filter:
        query += " AND f.status=?"
        params.append(status_filter)
    if cat_filter:
        query += " AND f.category_id=?"
        params.append(cat_filter)
    if priority_filter:
        query += " AND f.priority=?"
        params.append(priority_filter)

    query += " GROUP BY f.id"
    sort_map = {
        'votes':    'f.vote_count DESC',
        'date':     'f.created_at DESC',
        'priority': "CASE f.priority WHEN 'critique' THEN 1 WHEN 'haute' THEN 2 WHEN 'normale' THEN 3 WHEN 'basse' THEN 4 END",
    }
    query += f" ORDER BY {sort_map.get(sort_by, 'f.vote_count DESC')}"

    feedbacks = db.execute(query, params).fetchall()

    version_feedbacks = {}
    for v in versions:
        version_feedbacks[v['id']] = db.execute("""
            SELECT id, title, status, priority, vote_count
            FROM feedbacks WHERE version_id=? AND app_id=?
        """, (v['id'], app_row['id'])).fetchall()

    voter_ip = request.remote_addr
    voted_ids = set(
        row['feedback_id'] for row in
        db.execute("SELECT feedback_id FROM feedback_votes WHERE voter_ip=?", (voter_ip,)).fetchall()
    )

    db.close()
    return render_template('app_detail.html',
        app=app_row, avg_rating=avg_rating, rating_count=rating_count,
        rating_history=rating_history, categories=categories,
        versions=versions, version_feedbacks=version_feedbacks,
        feedbacks=feedbacks, voted_ids=voted_ids,
        status_filter=status_filter, cat_filter=cat_filter,
        priority_filter=priority_filter, sort_by=sort_by,
        STATUS_LABELS=STATUS_LABELS, PRIORITY_LABELS=PRIORITY_LABELS,
        APP_NAME=APP_NAME, APP_RELEASE=APP_RELEASE, APP_ICON=APP_ICON)


@app.route('/app/<slug>/feedback/new', methods=['GET', 'POST'])
def feedback_new(slug):
    app_row = get_app_by_slug(slug)
    if not app_row:
        abort(404)

    categories = get_app_categories(app_row['id'])
    db = get_db()
    versions = db.execute(
        "SELECT * FROM versions WHERE app_id=? ORDER BY release_date", (app_row['id'],)
    ).fetchall()
    db.close()

    form_data = {}

    if request.method == 'POST':
        title        = request.form.get('title', '').strip()
        content_html = request.form.get('content_html', '')
        category_id  = request.form.get('category_id') or None
        version_id   = request.form.get('version_id') or None
        priority     = request.form.get('priority', 'normale')
        author_name    = request.form.get('author_name', '').strip()
        author_service = request.form.get('author_service', '').strip()

        form_data = {
            'title': title, 'content_html': content_html,
            'category_id': category_id, 'version_id': version_id,
            'priority': priority,
            'author_name': author_name, 'author_service': author_service,
        }

        if not title:
            flash('Le titre est obligatoire.', 'error')
        elif not author_name:
            flash('Le nom est obligatoire.', 'error')
        else:
            db = get_db()
            db.execute("""INSERT INTO feedbacks
                (app_id, category_id, version_id, title, content_html,
                 author_name, author_service, is_anonymous, priority, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'nouveau')""",
                (app_row['id'], category_id, version_id, title, content_html,
                 author_name, author_service, priority))
            db.commit()
            db.close()
            flash('Feedback soumis avec succes !', 'success')
            return redirect(url_for('app_detail', slug=slug))

    return render_template('feedback_new.html',
        app=app_row, categories=categories, versions=versions, form_data=form_data,
        APP_NAME=APP_NAME, APP_RELEASE=APP_RELEASE, APP_ICON=APP_ICON)


@app.route('/app/<slug>/feedback/upload-image', methods=['POST'])
def upload_image(slug):
    app_row = get_app_by_slug(slug)
    if not app_row:
        return jsonify({'error': 'App not found'}), 404
    if 'image' not in request.files:
        return jsonify({'error': 'No image'}), 400
    f = request.files['image']
    if not f or not allowed_file(f.filename):
        return jsonify({'error': 'Fichier invalide'}), 400

    ext = f.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    upload_dir = os.path.join(UPLOAD_FOLDER, slug)
    os.makedirs(upload_dir, exist_ok=True)
    f.save(os.path.join(upload_dir, filename))

    img_url = url_for('static', filename=f'uploads/{slug}/{filename}')
    return jsonify({'url': img_url})


@app.route('/app/<slug>/feedback/<int:fid>')
def feedback_detail(slug, fid):
    app_row = get_app_by_slug(slug)
    if not app_row:
        abort(404)

    db = get_db()
    feedback = db.execute("""
        SELECT f.*, c.name as cat_name, c.color as cat_color,
               v.version_name as planned_version
        FROM feedbacks f
        LEFT JOIN categories c ON c.id = f.category_id
        LEFT JOIN versions v ON v.id = f.version_id
        WHERE f.id=? AND f.app_id=?
    """, (fid, app_row['id'])).fetchone()

    if not feedback:
        db.close()
        abort(404)

    comments = db.execute(
        "SELECT * FROM comments WHERE feedback_id=? ORDER BY created_at ASC", (fid,)
    ).fetchall()

    edits = db.execute(
        "SELECT * FROM feedback_edits WHERE feedback_id=? ORDER BY edited_at ASC", (fid,)
    ).fetchall()

    voter_ip = request.remote_addr
    already_voted = db.execute(
        "SELECT id FROM feedback_votes WHERE feedback_id=? AND voter_ip=?",
        (fid, voter_ip)
    ).fetchone() is not None

    db.close()
    return render_template('feedback_detail.html',
        app=app_row, feedback=feedback, comments=comments, edits=edits,
        already_voted=already_voted,
        STATUS_LABELS=STATUS_LABELS, PRIORITY_LABELS=PRIORITY_LABELS,
        APP_NAME=APP_NAME, APP_RELEASE=APP_RELEASE, APP_ICON=APP_ICON)


@app.route('/app/<slug>/feedback/<int:fid>/edit', methods=['GET', 'POST'])
def feedback_edit(slug, fid):
    app_row = get_app_by_slug(slug)
    if not app_row:
        abort(404)

    db = get_db()
    feedback = db.execute(
        "SELECT * FROM feedbacks WHERE id=? AND app_id=?", (fid, app_row['id'])
    ).fetchone()
    if not feedback:
        db.close()
        abort(404)

    categories = get_app_categories(app_row['id'])
    versions = db.execute(
        "SELECT * FROM versions WHERE app_id=? ORDER BY release_date", (app_row['id'],)
    ).fetchall()

    if request.method == 'POST':
        title        = request.form.get('title', '').strip()
        content_html = request.form.get('content_html', '')
        category_id  = request.form.get('category_id') or None
        version_id   = request.form.get('version_id') or None
        priority     = request.form.get('priority', feedback['priority'])
        editor_name    = request.form.get('editor_name', '').strip()
        editor_service = request.form.get('editor_service', '').strip()

        if not title:
            flash('Le titre est obligatoire.', 'error')
        elif not editor_name:
            flash('Votre nom est obligatoire pour tracer la modification.', 'error')
        else:
            changed = []
            if title != feedback['title']:
                changed.append('titre')
            if content_html != feedback['content_html']:
                changed.append('contenu')
            if str(category_id or '') != str(feedback['category_id'] or ''):
                changed.append('catégorie')
            if priority != feedback['priority']:
                changed.append('priorité')
            if str(version_id or '') != str(feedback['version_id'] or ''):
                changed.append('version')

            db.execute("""UPDATE feedbacks
                SET title=?, content_html=?, category_id=?, version_id=?, priority=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?""",
                (title, content_html, category_id, version_id, priority, fid))

            if changed:
                db.execute("""INSERT INTO feedback_edits
                    (feedback_id, editor_name, editor_service, changed_fields)
                    VALUES (?, ?, ?, ?)""",
                    (fid, editor_name, editor_service, ', '.join(changed)))

            db.commit()
            db.close()
            flash('Feedback mis à jour.', 'success')
            return redirect(url_for('feedback_detail', slug=slug, fid=fid))

    db.close()
    return render_template('feedback_edit.html',
        app=app_row, feedback=feedback, categories=categories, versions=versions,
        APP_NAME=APP_NAME, APP_RELEASE=APP_RELEASE, APP_ICON=APP_ICON)


# ════════════════════════════════════════════
# ROUTES AJAX
# ════════════════════════════════════════════

@app.route('/app/<slug>/feedback/<int:fid>/vote', methods=['POST'])
def vote_feedback(slug, fid):
    voter_ip = request.remote_addr
    db = get_db()
    if db.execute("SELECT id FROM feedback_votes WHERE feedback_id=? AND voter_ip=?",
                  (fid, voter_ip)).fetchone():
        db.close()
        return jsonify({'error': 'Vous avez deja vote', 'already_voted': True})

    db.execute("INSERT INTO feedback_votes (feedback_id, voter_ip) VALUES (?, ?)", (fid, voter_ip))
    db.execute("UPDATE feedbacks SET vote_count = vote_count + 1 WHERE id=?", (fid,))
    db.commit()
    new_count = db.execute("SELECT vote_count FROM feedbacks WHERE id=?", (fid,)).fetchone()['vote_count']
    db.close()
    return jsonify({'success': True, 'vote_count': new_count})


@app.route('/app/<slug>/feedback/<int:fid>/comment', methods=['POST'])
def add_comment(slug, fid):
    data = request.get_json() or {}
    author_name    = data.get('author_name', '').strip()
    author_service = data.get('author_service', '').strip()
    content        = data.get('content', '').strip()

    if not author_name or not content:
        return jsonify({'error': 'Nom et contenu requis'}), 400

    db = get_db()
    db.execute("""INSERT INTO comments (feedback_id, author_name, author_service, content)
                  VALUES (?, ?, ?, ?)""", (fid, author_name, author_service, content))
    db.commit()
    cnt = db.execute("SELECT COUNT(*) as c FROM comments WHERE feedback_id=?", (fid,)).fetchone()['c']
    db.close()
    return jsonify({'success': True, 'comment_count': cnt})


@app.route('/app/<slug>/feedback/<int:fid>/status', methods=['POST'])
def change_status(slug, fid):
    data = request.get_json() or {}
    new_status = data.get('status', '')

    if new_status not in STATUS_LABELS:
        return jsonify({'error': 'Statut invalide'}), 400

    db = get_db()
    db.execute("UPDATE feedbacks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
               (new_status, fid))
    db.commit()
    db.close()
    label, color = STATUS_LABELS[new_status]
    return jsonify({'success': True, 'status': new_status, 'label': label, 'color': color})


@app.route('/app/<slug>/rate', methods=['POST'])
def rate_app(slug):
    app_row = get_app_by_slug(slug)
    if not app_row:
        return jsonify({'error': 'App non trouvee'}), 404

    data = request.get_json() or {}
    try:
        rating = int(data.get('rating'))
        if not 1 <= rating <= 5:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'Note invalide (1-5)'}), 400

    rater_name    = data.get('rater_name', '').strip() or None
    rater_service = data.get('rater_service', '').strip() or None

    db = get_db()
    db.execute("INSERT INTO ratings (app_id, rating, rater_name, rater_service) VALUES (?, ?, ?, ?)",
               (app_row['id'], rating, rater_name, rater_service))
    db.commit()
    row = db.execute("SELECT ROUND(AVG(rating),1) as avg, COUNT(*) as cnt FROM ratings WHERE app_id=?",
                     (app_row['id'],)).fetchone()
    db.close()
    return jsonify({'success': True, 'avg_rating': row['avg'], 'count': row['cnt']})


# ════════════════════════════════════════════
# ROUTES PARAMETRAGE
# ════════════════════════════════════════════

@app.route('/settings')
def settings():
    db = get_db()
    groups   = db.execute("SELECT * FROM app_groups ORDER BY sort_order, name").fetchall()
    apps_raw = db.execute("SELECT * FROM apps ORDER BY name").fetchall()
    apps_data = []
    for a in apps_raw:
        cats     = db.execute("SELECT * FROM categories WHERE app_id=? ORDER BY name", (a['id'],)).fetchall()
        versions = db.execute("SELECT * FROM versions WHERE app_id=? ORDER BY release_date", (a['id'],)).fetchall()
        apps_data.append({'app': a, 'categories': cats, 'versions': versions})
    default_cats = db.execute("SELECT * FROM categories WHERE app_id IS NULL ORDER BY name").fetchall()
    db.close()
    return render_template('settings.html',
        apps_data=apps_data, default_cats=default_cats, groups=groups,
        APP_NAME=APP_NAME, APP_RELEASE=APP_RELEASE, APP_ICON=APP_ICON)


@app.route('/settings/apps/new', methods=['POST'])
def settings_app_new():
    name        = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    icon        = request.form.get('icon', '📱').strip() or '📱'
    color       = request.form.get('color', '#3b82f6').strip()
    group_id    = request.form.get('group_id') or None
    if not name:
        flash('Le nom est obligatoire.', 'error')
        return redirect(url_for('settings'))
    slug = base = slugify(name) or 'app'
    db = get_db()
    i = 1
    while db.execute("SELECT id FROM apps WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{i}"; i += 1
    db.execute("INSERT INTO apps (name, slug, description, icon, color, group_id) VALUES (?, ?, ?, ?, ?, ?)",
               (name, slug, description, icon, color, group_id))
    db.commit(); db.close()
    flash(f'Application "{name}" creee !', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/apps/<int:aid>/edit', methods=['POST'])
def settings_app_edit(aid):
    name        = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    icon        = request.form.get('icon', '📱').strip() or '📱'
    color       = request.form.get('color', '#3b82f6').strip()
    group_id    = request.form.get('group_id') or None
    db = get_db()
    db.execute("UPDATE apps SET name=?, description=?, icon=?, color=?, group_id=? WHERE id=?",
               (name, description, icon, color, group_id, aid))
    db.commit(); db.close()
    flash('Application mise a jour.', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/apps/<int:aid>/delete', methods=['POST'])
def settings_app_delete(aid):
    db = get_db()
    row = db.execute("SELECT name FROM apps WHERE id=?", (aid,)).fetchone()
    if row:
        db.execute("DELETE FROM apps WHERE id=?", (aid,))
        db.commit()
        flash(f'Application "{row["name"]}" supprimee.', 'success')
    db.close()
    return redirect(url_for('settings'))


@app.route('/settings/apps/<int:aid>/categories/new', methods=['POST'])
def settings_category_new(aid):
    name  = request.form.get('name', '').strip()
    color = request.form.get('color', '#3b82f6').strip()
    if not name:
        flash('Le nom est obligatoire.', 'error')
        return redirect(url_for('settings'))
    db = get_db()
    db.execute("INSERT INTO categories (app_id, name, color) VALUES (?, ?, ?)", (aid, name, color))
    db.commit(); db.close()
    flash(f'Categorie "{name}" ajoutee.', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/apps/<int:aid>/categories/<int:cid>/delete', methods=['POST'])
def settings_category_delete(aid, cid):
    db = get_db()
    db.execute("DELETE FROM categories WHERE id=? AND app_id=?", (cid, aid))
    db.commit(); db.close()
    flash('Categorie supprimee.', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/apps/<int:aid>/versions/new', methods=['POST'])
def settings_version_new(aid):
    vname       = request.form.get('version_name', '').strip()
    release_date = request.form.get('release_date', '').strip() or None
    description  = request.form.get('description', '').strip()
    if not vname:
        flash('Le numero de version est obligatoire.', 'error')
        return redirect(url_for('settings'))
    db = get_db()
    db.execute("INSERT INTO versions (app_id, version_name, release_date, description) VALUES (?, ?, ?, ?)",
               (aid, vname, release_date, description))
    db.commit(); db.close()
    flash(f'Version "{vname}" ajoutee.', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/apps/<int:aid>/versions/<int:vid>/delete', methods=['POST'])
def settings_version_delete(aid, vid):
    db = get_db()
    db.execute("UPDATE feedbacks SET version_id=NULL WHERE version_id=? AND app_id=?", (vid, aid))
    db.execute("DELETE FROM versions WHERE id=? AND app_id=?", (vid, aid))
    db.commit(); db.close()
    flash('Version supprimee.', 'success')
    return redirect(url_for('settings'))



@app.route('/settings/groups/new', methods=['POST'])
def settings_group_new():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Le nom est obligatoire.', 'error')
        return redirect(url_for('settings'))
    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) as c FROM app_groups").fetchone()['c']
        db.execute("INSERT INTO app_groups (name, sort_order) VALUES (?, ?)", (name, count))
        db.commit()
        flash(f'Groupe "{name}" créé.', 'success')
    except Exception:
        flash(f'Un groupe "{name}" existe déjà.', 'error')
    db.close()
    return redirect(url_for('settings'))


@app.route('/settings/groups/<int:gid>/delete', methods=['POST'])
def settings_group_delete(gid):
    db = get_db()
    db.execute("UPDATE apps SET group_id=NULL WHERE group_id=?", (gid,))
    db.execute("DELETE FROM app_groups WHERE id=?", (gid,))
    db.commit(); db.close()
    flash('Groupe supprimé.', 'success')
    return redirect(url_for('settings'))


# ════════════════════════════════════════════
# HEALTH
# ════════════════════════════════════════════
@app.route('/health')
def health():
    return jsonify({
        "status": "ok", "app": APP_NAME, "slug": APP_SLUG,
        "release": APP_RELEASE, "icon": APP_ICON, "color": APP_COLOR,
        "description": APP_DESCRIPTION,
        "uptime_seconds": int(time.time() - start_time),
        "request_count": request_count
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
