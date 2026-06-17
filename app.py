import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Ensure the photos directory exists so the app doesn't crash on startup
PHOTOS_DIR = os.path.join(app.static_folder, 'photos')
os.makedirs(PHOTOS_DIR, exist_ok=True)

# Database connection helper
def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("Warning: DATABASE_URL not set.")
        return None
    try:
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

# Initialize the database table
def init_db():
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS chizzy_messages (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        city VARCHAR(255),
                        message TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                ''')
            conn.commit()
        finally:
            conn.close()

# Initialize DB on startup
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

        # Sort to keep order consistent
        for filename in sorted(os.listdir(PHOTOS_DIR)):
            # Exclude the background video from the gallery
            if filename == 'bg-video.mp4':
                continue

            lower_filename = filename.lower()
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
        if request.method == 'POST':
            data = request.json
            name = data.get('name')
            city = data.get('city', '')
            message = data.get('message')

            if not name or not message:
                return jsonify({"error": "Name and message are required"}), 400

            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chizzy_messages (name, city, message) VALUES (%s, %s, %s) RETURNING *;",
                    (name, city, message)
                )
                new_msg = cur.fetchone()
            conn.commit()
            return jsonify(new_msg), 201

        elif request.method == 'GET':
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM chizzy_messages ORDER BY created_at DESC;")
                messages = cur.fetchall()
            return jsonify(messages)
    finally:
        conn.close()

if __name__ == '__main__':
    # Run locally for testing (use python app.py)
    app.run(debug=True, port=5000)
