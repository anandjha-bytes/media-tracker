import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from tmdbv3api import TMDb, Movie, TV, Search, Genre, Discover
import requests
import time
import urllib.parse

# --- 1. PAGE CONFIG ---
st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="🎬")

# --- 2. CONFIGURATION ---
try:
    TMDB_API_KEY = st.secrets["tmdb_api_key"]
except:
    # If using locally without secrets, paste key here
    TMDB_API_KEY = "YOUR_TMDB_API_KEY_HERE"

# --- 3. DATABASE ENGINE (SQLite) ---
DB_FILE = "media_tracker.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                )''')
    # Media Table
    c.execute('''CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    title TEXT,
                    type TEXT,
                    country TEXT,
                    status TEXT,
                    genres TEXT,
                    image TEXT,
                    overview TEXT,
                    rating TEXT,
                    backdrop TEXT,
                    current_season INTEGER,
                    current_ep INTEGER,
                    total_eps TEXT,
                    total_seasons TEXT,
                    tmdb_id TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )''')
    conn.commit()
    conn.close()

init_db()

# --- 4. AUTHENTICATION ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return hashed_text
    return False

def add_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users(username, password) VALUES (?,?)', (username, make_hashes(password)))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username =? AND password = ?', (username, make_hashes(password)))
    data = c.fetchall()
    conn.close()
    return data

# --- 5. PRIVATE LIBRARY FUNCTIONS ---
def add_media_to_db(user_id, item):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO media (user_id, title, type, country, status, genres, image, overview, rating, backdrop, current_season, current_ep, total_eps, total_seasons, tmdb_id) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                  (user_id, item['Title'], item['Type'], item['Country'], "Plan to Watch", item['Genres'], item['Image'], item['Overview'], item['Rating'], item['Backdrop'], 1, 0, item['Total_Eps'], item.get('Total_Seasons', '?'), item.get('ID')))
        conn.commit()
        return True
    except Exception as e:
        st.error(e)
        return False
    finally:
        conn.close()

def get_user_media(user_id):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM media WHERE user_id = ?", conn, params=(user_id,))
    conn.close()
    return df

def delete_media_from_db(media_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM media WHERE id=?", (media_id,))
    conn.commit()
    conn.close()

def update_media_status(media_id, status, season, ep):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE media SET status=?, current_season=?, current_ep=? WHERE id=?", (status, season, ep, media_id))
    conn.commit()
    conn.close()

# --- 6. API SETUP & GENRES ---
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = 'en'
tmdb_poster_base = "https://image.tmdb.org/t/p/w400"
tmdb_backdrop_base = "https://image.tmdb.org/t/p/w780"

# HARDCODED GENRES FOR STABILITY
GENRE_MAP = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Sci-Fi": 878, "TV Movie": 10770,
    "Thriller": 53, "War": 10752, "Western": 37
}
ID_TO_GENRE = {v: k for k, v in GENRE_MAP.items()}

# --- 7. SESSION STATE INIT ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'username' not in st.session_state: st.session_state.username = None

# ==========================================
#        🔐 LOGIN / REGISTER UI
# ==========================================
if not st.session_state.logged_in:
    st.title("🎬 Media Tracker Login")
    menu = ["Login", "Register"]
    choice = st.selectbox("Select Action", menu)

    if choice == "Register":
        st.subheader("Create New Account")
        new_user = st.text_input("Username")
        new_password = st.text_input("Password", type='password')
        if st.button("Sign Up"):
            if add_user(new_user, new_password):
                st.success("Account created! Please go to Login.")
            else:
                st.error("Username already taken!")

    elif choice == "Login":
        st.subheader("Sign In")
        username = st.text_input("Username")
        password = st.text_input("Password", type='password')
        if st.button("Login"):
            result = login_user(username, password)
            if result:
                st.session_state.logged_in = True
                st.session_state.user_id = result[0][0] 
                st.session_state.username = username
                st.rerun()
            else:
                st.error("Incorrect Username/Password")
    st.stop() 

# ==========================================
#        🚀 MAIN USER APP
# ==========================================

st.sidebar.write(f"👤 **{st.session_state.username}**")
if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.rerun()

tab = st.sidebar.radio("Navigation", ["My Library", "Search & Add"])

# --- HELPERS ---
def get_tmdb_trailer(tmdb_id, media_type):
    if not tmdb_id: return None
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/videos?api_key={TMDB_API_KEY}"
        r = requests.get(url).json()
        for vid in r.get('results', []):
            if vid['site'] == 'YouTube' and vid['type'] == 'Trailer':
                return f"https://www.youtube.com/watch?v={vid['key']}"
    except: pass
    return None

def process_tmdb(res, media_kind, results_list, selected_types, selected_genres):
    origin = getattr(res, 'original_language', 'en')
    detected_type = "Movies" if media_kind == "Movie" else "Web Series" # Default
    
    if media_kind == "TV":
        # LOGIC UPDATE: Detect specific types based on language
        if origin == 'ko': detected_type = "K-Drama"
        elif origin == 'zh': detected_type = "C-Drama"
        elif origin == 'th': detected_type = "Thai Drama"
        elif origin == 'ja': detected_type = "Anime"
        elif origin == 'en': detected_type = "Web Series" # English TV = Web Series
        else: detected_type = "Web Series" # Fallback
    
    # Filter: Only add if type matches user selection
    if detected_type not in selected_types: return
    
    genre_ids = getattr(res, 'genre_ids', [])
    res_genres = [ID_TO_GENRE.get(gid, "Unknown") for gid in genre_ids]
    
    # Filter: Check genres
    if selected_genres:
        if not any(g in res_genres for g in selected_genres): return

    poster = getattr(res, 'poster_path', None)
    img_url = f"{tmdb_poster_base}{poster}" if poster else "https://via.placeholder.com/200x300?text=No+Image"
    
    results_list.append({
        "Title": getattr(res, 'title', getattr(res, 'name', 'Unknown')),
        "Type": detected_type,
        "Country": origin,
        "Genres": ", ".join(res_genres),
        "Image": img_url,
        "Overview": getattr(res, 'overview', 'No overview.'),
        "Rating": f"{getattr(res, 'vote_average', 0)}/10",
        "Backdrop": f"{tmdb_backdrop_base}{getattr(res, 'backdrop_path', '')}",
        "Total_Eps": "?", 
        "ID": getattr(res, 'id', None)
    })

# --- SEARCH TAB ---
if tab == "Search & Add":
    st.header("🔍 Global Search")
    
    with st.expander("Filter Options", expanded=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1: search_query = st.text_input("Title")
        with c2: 
            # RENAMED "Western Series" -> "Web Series"
            selected_types = st.multiselect("Type", ["Movies", "Web Series", "K-Drama", "C-Drama", "Anime"], default=["Movies"])
        with c3:
            selected_genres = st.multiselect("Genre", list(GENRE_MAP.keys()))
            
    if st.button("Search"):
        results = []
        search = Search()
        
        # 1. Search Movies
        if "Movies" in selected_types:
            for r in search.movies(search_query): process_tmdb(r, "Movie", results, selected_types, selected_genres)
            
        # 2. Search TV (Web Series, Dramas, Anime)
        if any(t in ["Web Series", "K-Drama", "C-Drama", "Anime"] for t in selected_types):
            for r in search.tv_shows(search_query): process_tmdb(r, "TV", results, selected_types, selected_genres)
        
        st.session_state.search_res = results

    if 'search_res' in st.session_state:
        if not st.session_state.search_res:
            st.warning("No results found.")
        
        for idx, item in enumerate(st.session_state.search_res):
            with st.container():
                c_img, c_txt = st.columns([1, 5])
                with c_img: st.image(item['Image'], width=100)
                with c_txt:
                    st.subheader(item['Title'])
                    st.caption(f"**{item['Type']}** | ⭐ {item['Rating']}")
                    st.write(item['Overview'][:150] + "...")
                    
                    if st.button(f"➕ Add to My Library", key=f"add_{idx}"):
                        if add_media_to_db(st.session_state.user_id, item):
                            st.toast(f"Saved: {item['Title']}")

# --- LIBRARY TAB ---
elif tab == "My Library":
    st.header(f"{st.session_state.username}'s Collection")
    
    df = get_user_media(st.session_state.user_id)
    
    if not df.empty:
        filter_status = st.multiselect("Status", ["Plan to Watch", "Watching", "Completed", "Dropped"])
        if filter_status: df = df[df['status'].isin(filter_status)]
        
        for idx, row in df.iterrows():
            with st.expander(f"{row['title']} ({row['status']})"):
                c1, c2 = st.columns([1, 3])
                with c1: 
                    st.image(row['image'], width=150)
                    
                    # LINK BUTTONS
                    if "Manga" in row['type'] or "Manhwa" in row['type']:
                        st.link_button("📖 Read", f"https://www.google.com/search?q=site:comix.to+{row['title']}")
                    elif "Anime" in row['type']:
                         st.link_button("📺 Watch Anime", f"https://www.google.com/search?q=watch+{row['title']}+anime")
                    else:
                         # Trailer logic
                         trailer = get_tmdb_trailer(row['tmdb_id'], 'movie' if row['type'] == 'Movies' else 'tv')
                         if trailer: st.video(trailer)
                         else: st.info("No Trailer")

                with c2:
                    st.write(row['overview'])
                    new_status = st.selectbox("Status", ["Plan to Watch", "Watching", "Completed", "Dropped"], index=["Plan to Watch", "Watching", "Completed", "Dropped"].index(row['status']), key=f"s_{row['id']}")
                    
                    cc1, cc2 = st.columns(2)
                    with cc1: n_s = st.number_input("Season", value=row['current_season'], key=f"ns_{row['id']}")
                    with cc2: n_e = st.number_input("Episode", value=row['current_ep'], key=f"ne_{row['id']}")
                    
                    if st.button("💾 Save Progress", key=f"sv_{row['id']}"):
                        update_media_status(row['id'], new_status, n_s, n_e)
                        st.rerun()
                        
                    if st.button("🗑️ Delete", key=f"del_{row['id']}"):
                        delete_media_from_db(row['id'])
                        st.rerun()
    else:
        st.info("Your library is empty. Go to 'Search & Add' to start!")
