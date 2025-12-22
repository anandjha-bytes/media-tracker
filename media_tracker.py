import os
import hashlib
import urllib.parse
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from tmdbv3api import TMDb, Search, Movie, TV, Discover

app = Flask(__name__)
app.secret_key = "CHANGE_ME_TO_SOMETHING_SECRET"

# --- DATABASE CONFIG ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///media.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- GOOGLE AUTH CONFIG ---
# (Keep your previous Client ID/Secret here if you have them)
app.config['GOOGLE_CLIENT_ID'] = 'YOUR_GOOGLE_CLIENT_ID'
app.config['GOOGLE_CLIENT_SECRET'] = 'YOUR_GOOGLE_CLIENT_SECRET'

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    access_token_url='https://accounts.google.com/o/oauth2/token',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    client_kwargs={'scope': 'openid email profile'},
)

# --- TMDB SETUP ---
tmdb = TMDb()
tmdb.api_key = "YOUR_TMDB_API_KEY_HERE"  # <--- PASTE API KEY
tmdb.language = 'en'
tmdb_poster_base = "https://image.tmdb.org/t/p/w400"

# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=True)
    auth_type = db.Column(db.String(50), default="local")

class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String(200))
    media_type = db.Column(db.String(50))
    image = db.Column(db.String(500))
    status = db.Column(db.String(50), default="Plan to Watch")
    overview = db.Column(db.Text)
    rating = db.Column(db.String(20))

with app.app_context():
    db.create_all()

# --- HELPERS ---
def get_gravatar(email):
    hash_val = hashlib.md5(email.lower().strip().encode('utf-8')).hexdigest()
    return f"https://www.gravatar.com/avatar/{hash_val}?d=identicon&s=200"

# --- SEARCH LOGIC (THE "WEB SERIES" UPDATE) ---
def search_unified(query):
    results = []
    
    # 1. TMDB (Movies / Web Series / Dramas)
    if query:
        search = Search()
        movies = search.movies(query)
        tv = search.tv_shows(query)
        
        # Process Movies
        for m in movies:
            if hasattr(m, 'poster_path') and m.poster_path:
                results.append({
                    'title': m.title,
                    'type': 'Movies',
                    'image': tmdb_poster_base + m.poster_path,
                    'overview': m.overview,
                    'rating': getattr(m, 'vote_average', 0)
                })
        
        # Process TV (The Logic Update!)
        for t in tv:
            if hasattr(t, 'poster_path') and t.poster_path:
                origin = getattr(t, 'original_language', 'en')
                detected = "Web Series" # Default to Web Series if not Asian
                
                # Language Logic
                if origin == 'ko': detected = "K-Drama"
                elif origin == 'zh': detected = "C-Drama"
                elif origin == 'th': detected = "Thai Drama"
                elif origin == 'ja': detected = "Anime"
                elif origin == 'en': detected = "Web Series" # Explicit English Drama
                
                results.append({
                    'title': t.name,
                    'type': detected,
                    'image': tmdb_poster_base + t.poster_path,
                    'overview': t.overview,
                    'rating': getattr(t, 'vote_average', 0)
                })

    # 2. AniList (Anime/Manga)
    if query:
        q_graphql = '''
        query ($s: String) {
            Page(perPage: 10) {
                media(search: $s, sort: POPULARITY_DESC) {
                    title { english romaji }
                    type
                    countryOfOrigin
                    coverImage { large }
                    description
                    averageScore
                }
            }
        }
        '''
        try:
            r = requests.post('https://graphql.anilist.co', json={'query': q_graphql, 'variables': {'s': query}})
            data = r.json()['data']['Page']['media']
            for item in data:
                m_type = item['type']
                origin = item['countryOfOrigin']
                detected = "Anime"
                
                if m_type == "MANGA":
                    if origin == "KR": detected = "Manhwa"
                    elif origin == "CN": detected = "Manhua"
                    else: detected = "Manga"
                
                title = item['title']['english'] if item['title']['english'] else item['title']['romaji']
                
                results.append({
                    'title': title,
                    'type': detected,
                    'image': item['coverImage']['large'],
                    'overview': item['description'].replace('<br>', '') if item['description'] else "No desc",
                    'rating': (item['averageScore'] / 10) if item['averageScore'] else 0
                })
        except: pass

    return results

# --- ROUTES ---

@app.route('/')
def home():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password, request.form['password']):
        session['user_id'] = user.id
        session['email'] = user.email
        session['username'] = user.username
        return redirect(url_for('dashboard'))
    flash("Invalid credentials")
    return redirect(url_for('home'))

@app.route('/register', methods=['POST'])
def register():
    try:
        pw_hash = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        user = User(username=request.form['username'], email=request.form['email'], password=pw_hash)
        db.session.add(user)
        db.session.commit()
        flash("Account created!")
    except:
        flash("Email already exists")
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('home'))
    media = Media.query.filter_by(user_id=session['user_id']).all()
    avatar = get_gravatar(session['email'])
    return render_template('dashboard.html', media=media, user=session['username'], avatar=avatar)

@app.route('/search', methods=['GET', 'POST'])
def search():
    if 'user_id' not in session: return redirect(url_for('home'))
    results = []
    filter_type = request.form.get('filter_type') # Get dropdown selection
    
    if request.method == 'POST' and request.form.get('query'):
        all_results = search_unified(request.form['query'])
        
        # Apply the Dropdown Filter Logic
        if filter_type and filter_type != "All":
            results = [x for x in all_results if x['type'] == filter_type]
        else:
            results = all_results
            
    return render_template('search.html', results=results, avatar=get_gravatar(session['email']))

@app.route('/add', methods=['POST'])
def add():
    if 'user_id' not in session: return redirect(url_for('home'))
    new_m = Media(
        user_id=session['user_id'],
        title=request.form['title'],
        media_type=request.form['type'],
        image=request.form['image'],
        overview=request.form['overview'],
        rating=request.form['rating']
    )
    db.session.add(new_m)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/delete/<int:id>')
def delete(id):
    m = Media.query.get(id)
    if m and m.user_id == session['user_id']:
        db.session.delete(m)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
