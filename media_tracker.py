import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Genre
import requests

# --- CONFIGURATION ---
try:
    TMDB_API_KEY = st.secrets["tmdb_api_key"]
except:
    # REPLACE THIS WITH YOUR KEY IF RUNNING LOCALLY WITHOUT SECRETS FILE
    TMDB_API_KEY = "YOUR_TMDB_API_KEY_HERE"

GOOGLE_SHEET_NAME = 'My Media Tracker'

# --- SETUP APIS ---
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = 'en'
tmdb_img_base = "https://image.tmdb.org/t/p/w400"

# --- CACHE GENRES ---
@st.cache_data
def get_tmdb_genres():
    try:
        movie_genres = Genre().movie_list()
        tv_genres = Genre().tv_list()
        genre_map = {}
        for g in movie_genres: genre_map[g['id']] = g['name']
        for g in tv_genres: genre_map[g['id']] = g['name']
        return genre_map
    except:
        return {}

tmdb_genres_map = get_tmdb_genres()

# --- GOOGLE SHEETS CONNECTION ---
def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        # Try Cloud Secrets first
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    except:
        # Fallback to local file
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        except:
            st.error("⚠️ Authentication Error: credentials.json not found.")
            return None
    client = gspread.authorize(creds)
    try:
        return client.open(GOOGLE_SHEET_NAME).sheet1
    except:
        st.error(f"⚠️ Could not open Sheet '{GOOGLE_SHEET_NAME}'. Did you share it with the client_email?")
        return None

# --- SEARCH ENGINES ---
def search_unified(query, selected_types, selected_genres):
    results_data = []
    
    # TMDB Search
    live_action = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action):
        search = Search()
        if "Movies" in selected_types:
            for r in search.movies(query): process_tmdb(r, "Movie", results_data, selected_types, selected_genres)
        if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
            for r in search.tv_shows(query): process_tmdb(r, "TV", results_data, selected_types, selected_genres)

    # AniList Search
    asian_comics = ["Anime", "Manga", "Manhwa", "Manhua"]
    if any(t in selected_types for t in asian_comics):
        modes = []
        if "Anime" in selected_types: modes.append("ANIME")
        if any(t in ["Manga", "Manhwa", "Manhua"] for t in selected_types): modes.append("MANGA")
        for m in set(modes):
            for r in fetch_anilist(query, m): process_anilist(r, m, results_data, selected_types, selected_genres)

    return results_data

def process_tmdb(res, media_kind, results_list, selected_types, selected_genres):
    origin = getattr(res, 'original_language', 'en')
    detected_type = "Movies" if media_kind == "Movie" else "Western Series"
    country_disp = "Western"
    
    if media_kind == "TV":
        if origin == 'ko': detected_type, country_disp = "K-Drama", "South Korea"
        elif origin == 'zh': detected_type, country_disp = "C-Drama", "China"
        elif origin == 'th': detected_type, country_disp = "Thai Drama", "Thailand"
        elif origin == 'ja': detected_type, country_disp = "J-Drama", "Japan"
    
    if detected_type not in selected_types: return

    genre_ids = getattr(res, 'genre_ids', [])
    res_genres = [tmdb_genres_map.get(gid, "Unknown") for gid in genre_ids]
    if selected_genres and not any(g in selected_genres for g in res_genres): return

    poster = getattr(res, 'poster_path', None)
    img = f"{tmdb_img_base}{poster}" if poster else ""
    
    results_list.append({
        "Title": getattr(res, 'title', getattr(res, 'name', 'Unknown')),
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res_genres),
        "Image": img
    })

def fetch_anilist(query, type_):
    q = '''query ($s: String, $t: MediaType) { Page(perPage: 10) { media(search: $s, type: $t) { title { romaji english } coverImage { large } genres countryOfOrigin type } } }'''
    try:
        r = requests.post('https://graphql.anilist.co', json={'query': q, 'variables': {'s': query, 't': type_}})
        return r.json()['data']['Page']['media']
    except: return []

def process_anilist(res, api_type, results_list, selected_types, selected_genres):
    origin = res['countryOfOrigin']
    detected_type = "Anime"
    country_disp = "Japan"
    
    if api_type == "MANGA":
        if origin == 'KR': detected_type, country_disp = "Manhwa", "South Korea"
        elif origin == 'CN': detected_type, country_disp = "Manhua", "China"
        else: detected_type = "Manga"
    
    if detected_type not in selected_types: return
    if selected_genres and not any(g in selected_genres for g in res['genres']): return

    title = res['title']['english'] if res['title']['english'] else res['title']['romaji']
    results_list.append({
        "Title": title,
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res['genres']),
        "Image": res['coverImage']['large']
    })

# --- UI START ---
st.set_page_config(page_title="My Media Universe", layout="wide", page_icon="🌌")
st.title("🌌 My Media Universe")

sheet = get_google_sheet()
tab = st.sidebar.radio("Navigation", ["Search & Add", "My Gallery", "Decider"])

# --- TAB 1: SEARCH & ADD ---
if tab == "Search & Add":
    st.subheader("Global Search Engine")
    
    with st.expander("Search Filters", expanded=True):
        c1, c2 = st.columns([3, 1])
        all_types = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama", "Anime", "Manga", "Manhwa", "Manhua"]
        with c1: 
            search_query = st.text_input("Enter Title", placeholder="Search for anything...")
        with c2: 
            selected_types = st.multiselect("Filter Type", all_types, default=all_types)

    if search_query:
        if not selected_types: selected_types = all_types
        with st.spinner("Searching Databases..."):
            results = search_unified(search_query, selected_types, [])
        
        if not results:
            st.warning("No results found.")
        
        for item in results:
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    if item['Image']: st.image(item['Image'], use_container_width=True)
                with col_txt:
                    st.subheader(item['Title'])
                    st.markdown(f"**{item['Type']}** | {item['Country']} | {item['Genres']}")
                    
                    if st.button(f"➕ Add to Library", key=f"add_{item['Title']}_{item['Type']}"):
                        if sheet:
                            sheet.append_row([
                                item['Title'],
                                item['Type'],
                                item['Country'],
                                "Plan to Watch",
                                item['Genres'],
                                item['Image']
                            ])
                            st.toast(f"Saved: {item['Title']}")
            st.divider()

# --- TAB 2: MY GALLERY (UPDATED) ---
elif tab == "My Gallery":
    st.header("My Collection")
    
    if sheet:
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            
            # --- GALLERY SEARCH BAR ---
            with st.container():
                col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
                with col_s1:
                    local_search = st.text_input("🔍 Search within library", placeholder="Find a saved title...")
                with col_s2:
                    unique_types = list(df['Type'].unique()) if 'Type' in df.columns else []
                    filter_type = st.multiselect("Type", unique_types)
                with col_s3:
                    unique_countries = list(df['Country'].unique()) if 'Country' in df.columns else []
                    filter_country = st.multiselect("Country", unique_countries)
            
            st.divider()

            # --- APPLY FILTERS ---
            if local_search:
                df = df[df['Title'].astype(str).str.contains(local_search, case=False, na=False)]
            if filter_type:
                df = df[df['Type'].isin(filter_type)]
            if filter_country:
                df = df[df['Country'].isin(filter_country)]

            # --- RENDER GRID ---
            if not df.empty:
                cols_per_row = 5
                rows = [df.iloc[i:i + cols_per_row] for i in range(0, len(df), cols_per_row)]
                
                for row in rows:
                    cols = st.columns(cols_per_row)
                    for idx, (_, item) in enumerate(row.iterrows()):
                        with cols[idx]:
                            img_url = item.get('Image')
                            if not img_url: img_url = "https://via.placeholder.com/200x300?text=No+Image"
                            st.image(img_url, use_container_width=True)
                            st.markdown(f"**{item['Title']}**")
                            st.caption(f"{item['Type']} • {item['Country']}")
                            status = item.get('Status', 'Plan to Watch')
                            st.markdown(f"Status: **{status}**")
            else:
                st.info("No matches found in your library.")
        else:
            st.info("Your library is empty. Go add some movies!")

# --- TAB 3: DECIDER ---
elif tab == "Decider":
    st.header("🎲 Random Picker")
    if st.button("Pick Something for Me"):
        if sheet:
            import random
            data = sheet.get_all_records()
            if data:
                choice = random.choice(data)
                c1, c2 = st.columns([1, 2])
                with c1:
                    if choice.get('Image'): st.image(choice['Image'])
                with c2:
                    st.balloons()
                    st.success(f"Watch This: **{choice['Title']}**")
                    st.write(f"Type: {choice['Type']}")
                    st.write(f"Country: {choice['Country']}")