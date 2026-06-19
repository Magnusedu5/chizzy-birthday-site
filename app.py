import os
import requests as req
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

PHOTOS_DIR = os.path.join(app.static_folder, 'photos')
os.makedirs(PHOTOS_DIR, exist_ok=True)


def _turso(statements):
    """Run one or more SQL statements via Turso HTTP pipeline API."""
    db_url = os.environ.get('TURSO_DATABASE_URL', '')
    if not db_url:
        raise RuntimeError('TURSO_DATABASE_URL not set')
    token = os.environ.get('TURSO_AUTH_TOKEN', '')
    endpoint = db_url.replace('libsql://', 'https://') + '/v2/pipeline'

    pipeline = []
    for s in statements:
        entry = {'type': 'execute', 'stmt': {'sql': s['sql']}}
        if s.get('args'):
            entry['stmt']['args'] = [_enc(a) for a in s['args']]
        pipeline.append(entry)
    pipeline.append({'type': 'close'})

    r = req.post(
        endpoint,
        json={'requests': pipeline},
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        timeout=10,
    )
    r.raise_for_status()

    results = []
    for item in r.json()['results'][:-1]:
        if item['type'] == 'error':
            raise RuntimeError(item['error']['message'])
        res = item['response']['result']
        cols = [c['name'] for c in res['cols']]
        rows = [_dec(cols, row) for row in res['rows']]
        results.append({'rows': rows, 'last_insert_rowid': res.get('last_insert_rowid')})
    return results


def _enc(v):
    if v is None:
        return {'type': 'null', 'value': None}
    if isinstance(v, int):
        return {'type': 'integer', 'value': str(v)}
    if isinstance(v, float):
        return {'type': 'float', 'value': str(v)}
    return {'type': 'text', 'value': str(v)}


def _dec(cols, row):
    d = {}
    for i, col in enumerate(cols):
        cell = row[i]
        if cell['type'] == 'null':
            d[col] = None
        elif cell['type'] == 'integer':
            d[col] = int(cell['value'])
        elif cell['type'] == 'float':
            d[col] = float(cell['value'])
        else:
            d[col] = cell['value']
    return d


def db(sql, args=None):
    return _turso([{'sql': sql, 'args': args or []}])[0]


def init_db():
    try:
        _turso([
            {'sql': '''CREATE TABLE IF NOT EXISTS chizzy_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                city TEXT,
                message TEXT NOT NULL,
                reactions INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''},
            {'sql': '''CREATE TABLE IF NOT EXISTS chizzy_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER REFERENCES chizzy_messages(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )'''},
        ])
    except Exception as e:
        print(f"DB init skipped: {e}")


with app.app_context():
    init_db()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/photos', methods=['GET'])
def get_photos():
    try:
        media_files = []
        valid_image_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        valid_video_extensions = ('.mp4', '.webm', '.mov')

        for filename in sorted(os.listdir(PHOTOS_DIR)):
            lower_filename = filename.lower()

            if lower_filename in ('bg-video.mp4', 'introvid.mp4'):
                continue

            if lower_filename.endswith(valid_image_extensions):
                media_files.append({'filename': filename, 'type': 'image'})
            elif lower_filename.endswith(valid_video_extensions):
                media_files.append({'filename': filename, 'type': 'video'})

        return jsonify(media_files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/messages', methods=['GET', 'POST'])
def handle_messages():
    try:
        if request.method == 'POST':
            data = request.json
            name = data.get('name')
            city = data.get('city', '')
            message = data.get('message')

            if not name or not message:
                return jsonify({"error": "Name and message are required"}), 400

            result = db(
                "INSERT INTO chizzy_messages (name, city, message) VALUES (?, ?, ?) RETURNING *;",
                [name, city, message]
            )
            return jsonify(result['rows'][0]), 201

        messages = db("SELECT * FROM chizzy_messages ORDER BY created_at DESC;")['rows']
        for msg in messages:
            msg['replies'] = db(
                "SELECT * FROM chizzy_replies WHERE message_id = ? ORDER BY created_at ASC;",
                [msg['id']]
            )['rows']
        return jsonify(messages)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/messages/<int:message_id>/react', methods=['POST'])
def react_to_message(message_id):
    try:
        result = db(
            "UPDATE chizzy_messages SET reactions = reactions + 1 WHERE id = ? RETURNING reactions;",
            [message_id]
        )
        if not result['rows']:
            return jsonify({"error": "Message not found"}), 404
        return jsonify({"reactions": result['rows'][0]['reactions']})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/messages/<int:message_id>/replies', methods=['POST'])
def add_reply(message_id):
    try:
        data = request.json
        content = data.get('content', '').strip()
        if not content:
            return jsonify({"error": "Content is required"}), 400
        result = db(
            "INSERT INTO chizzy_replies (message_id, content) VALUES (?, ?) RETURNING *;",
            [message_id, content]
        )
        return jsonify(result['rows'][0]), 201
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
