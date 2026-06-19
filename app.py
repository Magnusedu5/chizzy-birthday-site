import os
import libsql_experimental as libsql
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

PHOTOS_DIR = os.path.join(app.static_folder, 'photos')
os.makedirs(PHOTOS_DIR, exist_ok=True)


def get_db_connection():
    db_url = os.environ.get('TURSO_DATABASE_URL')
    auth_token = os.environ.get('TURSO_AUTH_TOKEN', '')
    if not db_url:
        print("Warning: TURSO_DATABASE_URL not set.")
        return None
    try:
        return libsql.connect(database=db_url, auth_token=auth_token)
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


def row_to_dict(cursor, row):
    if row is None:
        return None
    return {d[0]: v for d, v in zip(cursor.description, row)}


def rows_to_dicts(cursor, rows):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def init_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS chizzy_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    city TEXT,
                    message TEXT NOT NULL,
                    reactions INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS chizzy_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER REFERENCES chizzy_messages(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        finally:
            conn.close()


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
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database not configured"}), 500

    try:
        cur = conn.cursor()

        if request.method == 'POST':
            data = request.json
            name = data.get('name')
            city = data.get('city', '')
            message = data.get('message')

            if not name or not message:
                return jsonify({"error": "Name and message are required"}), 400

            cur.execute(
                "INSERT INTO chizzy_messages (name, city, message) VALUES (?, ?, ?) RETURNING *;",
                (name, city, message)
            )
            new_msg = row_to_dict(cur, cur.fetchone())
            conn.commit()
            return jsonify(new_msg), 201

        elif request.method == 'GET':
            cur.execute("SELECT * FROM chizzy_messages ORDER BY created_at DESC;")
            messages = rows_to_dicts(cur, cur.fetchall())
            for msg in messages:
                cur.execute(
                    "SELECT * FROM chizzy_replies WHERE message_id = ? ORDER BY created_at ASC;",
                    (msg['id'],)
                )
                msg['replies'] = rows_to_dicts(cur, cur.fetchall())
            return jsonify(messages)
    finally:
        conn.close()


@app.route('/api/messages/<int:message_id>/react', methods=['POST'])
def react_to_message(message_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database not configured"}), 500
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE chizzy_messages SET reactions = reactions + 1 WHERE id = ? RETURNING reactions;",
            (message_id,)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Message not found"}), 404
        conn.commit()
        return jsonify({"reactions": row[0]})
    finally:
        conn.close()


@app.route('/api/messages/<int:message_id>/replies', methods=['POST'])
def add_reply(message_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database not configured"}), 500
    try:
        data = request.json
        content = data.get('content', '').strip()
        if not content:
            return jsonify({"error": "Content is required"}), 400
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chizzy_replies (message_id, content) VALUES (?, ?) RETURNING *;",
            (message_id, content)
        )
        new_reply = row_to_dict(cur, cur.fetchone())
        conn.commit()
        return jsonify(new_reply), 201
    finally:
        conn.close()


if __name__ == '__main__':
    app.run(debug=True, port=5000)
