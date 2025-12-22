import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Genre
import requests
import time

# --- CONFIGURATION ---
try:
    TMDB_API_KEY = st.secrets["tmdb_api_key"]
except:
    TMDB_API_KEY = "YOUR_TMDB_API_KEY_HERE"

GOOGLE_SHEET_NAME = 'My Media Tracker'

# --- SETUP APIS ---
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = 'en'
tmdb_poster_base = "https://image.tmdb.org/t/p/w400"
tmdb_backdrop_base = "https://image.tmdb.org/t/p/w780"

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
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    except:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        except:
            return None
    client = gspread.authorize(creds)
    try:
        return client.open(GOOGLE_SHEET_NAME).sheet1
    except:
        return None

# --- DATABASE ACTIONS (Update & Delete) ---
def update_status_in_sheet(title, new_status, new_ep):
    sheet = get_google_sheet()
    if sheet:
        try:
            cell = sheet.find(title)
            if cell:
                sheet.update_cell(cell.row, 4, new_status) # Col 4 = Status
                sheet.update_cell(cell.row, 10, new_ep)    # Col 10 = Current Ep
                st.toast(f"✅ Saved: {title}")
                time.sleep(1)
        except Exception as e:
            st.error(f"Could not save: {e}")

def delete_from_sheet(title):
    sheet = get_google_sheet()
    if sheet:
        try:
            cell = sheet.find(title)
            if cell:
                sheet.delete_rows(cell.row)
                st.toast(f"🗑️ Deleted: {title}")
                time.sleep(1)
        except Exception as e:
            st.error(f"Could not delete: {e}")

# --- SEARCH LOGIC ---
def search_unified(query, selected_types, selected_genres, min_rating):
    results_data = []
    
    # 1. TMDB SEARCH
    live_action = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action):
        search = Search()
        if "Movies" in selected_types:
            for r in search.movies(query): process_tmdb(r, "Movie", results_data, selected_types, selected_genres, min_rating)
        if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
            for r in search.tv_shows(query): process_tmdb(r, "TV", results_data, selected_types, selected_genres, min_rating)

    # 2. ANILIST SEARCH
    asian_comics = ["Anime", "Manga", "Manhwa", "Manhua"]
    if any(t in selected_types for t in asian_comics):
        modes = []
        if "Anime" in selected_types: modes.append("ANIME")
        if any(t in ["Manga", "Manhwa", "Manhua"] for t in selected_types): modes.append("MANGA")
        for m in set(modes):
            for r in fetch_anilist(query, m): process_anilist(r, m, results_data, selected_types, selected_genres, min_rating)

    return results_data

def process_tmdb(res, media_kind, results_list, selected_types, selected_genres, min_rating):
    origin = getattr(res, 'original_language', 'en')
    detected_type = "Movies" if media_kind == "Movie" else "Western Series"
    country_disp = "Western"
    total_eps = "?"
    
    if media_kind == "TV":
        if origin == 'ko': detected_type, country_disp = "K-Drama", "South Korea"
        elif origin == 'zh': detected_type, country_disp = "C-Drama", "China"
        elif origin == 'th': detected_type, country_disp = "Thai Drama", "Thailand"
        elif origin == 'ja': detected_type, country_disp = "J-Drama", "Japan"
    
    if detected_type not in selected_types: return

    rating = getattr(res, 'vote_average', 0)
    if rating < min_rating: return

    genre_ids = getattr(res, 'genre_ids', [])
    res_genres = [tmdb_genres_map.get(gid, "Unknown") for gid in genre_ids]
    if selected_genres and not any(g in res_genres for g in selected_genres): return

    poster = getattr(res, 'poster_path', None)
    backdrop = getattr(res, 'backdrop_path', None)
    img_url = f"{tmdb_poster_base}{poster}" if poster else ""
    backdrop_url = f"{tmdb_backdrop_base}{backdrop}" if backdrop else ""
    overview = getattr(res, 'overview', 'No overview.')

    results_list.append({
        "Title": getattr(res, 'title', getattr(res, 'name', 'Unknown')),
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res_genres),
        "Image": img_url,
        "Overview": overview,
        "Rating": f"{rating}/10",
        "Backdrop": backdrop_url,
        "Total_Eps": total_eps
    })

def fetch_anilist(query, type_):
    q = '''query ($s: String, $t: MediaType) { Page(perPage: 10) { media(search: $s, type: $t) { title { romaji english } coverImage { large } bannerImage genres countryOfOrigin type description averageScore episodes chapters } } }'''
    try:
        r = requests.post('https://graphql.anilist.co', json={'query': q, 'variables': {'s': query, 't': type_}})
        return r.json()['data']['Page']['media']
    except: return []

def process_anilist(res, api_type, results_list, selected_types, selected_genres, min_rating):
    origin = res['countryOfOrigin']
    detected_type = "Anime"
    country_disp = "Japan"
    total = res.get('episodes') if api_type == "ANIME" else res.get('chapters')
    if not total: total = "?"

    if api_type == "MANGA":
        if origin == 'KR': detected_type, country_disp = "Manhwa", "South Korea"
        elif origin == 'CN': detected_type, country_disp = "Manhua", "China"
        else: detected_type = "Manga"
    
    if detected_type not in selected_types: return

    score = res.get('averageScore', 0)
    rating_val = score / 10 if score else 0
    if rating_val < min_rating: return

    res_genres = res.get('genres', [])
    if selected_genres and not any(g in res_genres for g in selected_genres): return

    import re
    raw_desc = res.get('description', '')
    clean_desc = re.sub('<[^<]+?>', '', raw_desc) if raw_desc else "No description."

    results_list.append({
        "Title": res['title']['english'] if res['title']['english'] else res['title']['romaji'],
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res_genres),
        "Image": res.get('coverImage', {}).get('large', ''),
        "Overview": clean_desc,
        "Rating": f"{rating_val}/10",
        "Backdrop": res.get('bannerImage', ''),
        "Total_Eps": total
    })

# --- UI START ---
st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="🎬")
st.title("🎬 Ultimate Media Tracker")

sheet = get_google_sheet()
if "refresh_key" not in st.session_state: st.session_state.refresh_key = 0

tab = st.sidebar.radio("Menu", ["My Gallery", "Search & Add"], key="main_nav")
COMMON_GENRES = ["Action", "Adventure", "Comedy", "Drama", "Fantasy", "Horror", "Mystery", "Romance", "Sci-Fi", "Thriller", "Slice of Life", "Sports"]

# --- TAB: SEARCH & ADD ---
if tab == "Search & Add":
    st.subheader("Global Database Search")
    with st.expander("🔎 Search Filters", expanded=True):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        with c1: search_query = st.text_input("Enter Title", placeholder="Naruto, Inception, etc.")
        with c2: 
            selected_types = st.multiselect("Type", ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama", "Anime", "Manga", "Manhwa", "Manhua"], default=None)
            if not selected_types: selected_types = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama", "Anime", "Manga", "Manhwa", "Manhua"]
        with c3: selected_genres = st.multiselect("Genre", COMMON_GENRES)
        with c4: min_rating = st.slider("Min Rating", 0, 10, 0)

    if search_query:
        with st.spinner("Scanning..."):
            results = search_unified(search_query, selected_types, selected_genres, min_rating)
        
        if not results: st.warning("No results found.")
        
        for item in results:
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    if item['Image']: st.image(item['Image'], use_container_width=True)
                with col_txt:
                    st.subheader(item['Title'])
                    st.caption(f"{item['Type']} | {item['Country']} | ⭐ {item['Rating']}")
                    st.caption(f"🏷️ {item['Genres']}")
                    st.write(item['Overview'][:200] + "...")
                    
                    if st.button(f"➕ Add to Library", key=f"add_{item['Title']}_{item['Type']}"):
                        if sheet:
                            sheet.append_row([
                                item['Title'], item['Type'], item['Country'],
                                "Plan to Watch", item['Genres'], item['Image'], item['Overview'],
                                item['Rating'], item['Backdrop'], 0, item['Total_Eps']
                            ])
                            st.toast(f"Saved {item['Title']}!")

# --- TAB: MY GALLERY ---
elif tab == "My Gallery":
    st.subheader("My Library")
    if st.button("🔄 Refresh Data"): st.cache_data.clear()
    
    if sheet:
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            
            with st.expander("🌪️ Filter Collection", expanded=False):
                f1, f2, f3, f4 = st.columns(4)
                with f1: filter_text = st.text_input("Search Title")
                with f2: filter_type = st.multiselect("Filter Type", df['Type'].unique() if 'Type' in df.columns else [])
                with f3: filter_genre = st.multiselect("Filter Genre", COMMON_GENRES)
                with f4: filter_status = st.multiselect("Status", ["Plan to Watch", "Watching", "Completed", "Dropped"])
            
            if filter_text: df = df[df['Title'].astype(str).str.contains(filter_text, case=False, na=False)]
            if filter_type: df = df[df['Type'].isin(filter_type)]
            if filter_status: df = df[df['Status'].isin(filter_status)]
            if filter_genre:
                mask = df['Genres'].apply(lambda x: any(g in str(x) for g in filter_genre))
                df = df[mask]

            st.divider()

            if not df.empty:
                cols_per_row = 4
                rows = [df.iloc[i:i + cols_per_row] for i in range(0, len(df), cols_per_row)]
                
                for row in rows:
                    cols = st.columns(cols_per_row)
                    for idx, (_, item) in enumerate(row.iterrows()):
                        with cols[idx]:
                            img_url = item.get('Image', '')
                            if not str(img_url).startswith("http"): img_url = "https://via.placeholder.com/200x300?text=No+Image"
                            st.image(img_url, use_container_width=True)
                            st.markdown(f"**{item['Title']}**")
                            
                            with st.expander(f"⚙️ Manage"):
                                status_options = ["Plan to Watch", "Watching", "Completed", "Dropped"]
                                current_status = item.get('Status', 'Plan to Watch')
                                if current_status not in status_options: current_status = "Plan to Watch"
                                
                                new_status = st.selectbox("Status", status_options, key=f"stat_{item['Title']}", index=status_options.index(current_status))
                                
                                current_ep = item.get('Current_Ep')
                                if current_ep == '': current_ep = 0
                                new_ep = current_ep
                                if item['Type'] != "Movies":
                                    c_min, c_val, c_plus = st.columns([1, 1, 1])
                                    with c_min: 
                                        if st.button("➖", key=f"min_{item['Title']}"): new_ep = int(current_ep) - 1
                                    with c_val:
                                        st.markdown(f"<center>{current_ep}</center>", unsafe_allow_html=True)
                                    with c_plus:
                                        if st.button("➕", key=f"plu_{item['Title']}"): new_ep = int(current_ep) + 1
                                
                                c_save, c_del = st.columns([1, 1])
                                with c_save:
                                    if st.button("💾 Save", key=f"save_{item['Title']}"):
                                        update_status_in_sheet(item['Title'], new_status, new_ep)
                                        st.rerun()
                                with c_del:
                                    # THE DELETE BUTTON
                                    if st.button("🗑️ Remove", key=f"del_{item['Title']}"):
                                        delete_from_sheet(item['Title'])
                                        st.rerun()

                            with st.popover("📜 Info"):
                                if str(item.get('Backdrop')).startswith("http"):
                                    st.image(item['Backdrop'], use_container_width=True)
                                st.write(f"**Rating:** {item.get('Rating')}")
                                st.write(f"**Genres:** {item.get('Genres')}")
                                st.write(item.get('Overview'))
            else:
                st.info("No items match your filters.")
        else:
            st.info("Library is empty.")
