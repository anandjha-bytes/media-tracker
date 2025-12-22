import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Genre, Discover
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
        id_to_name = {}
        name_to_id = {}
        for g in movie_genres + tv_genres:
            id_to_name[g['id']] = g['name']
            name_to_id[g['name']] = g['id']
        return id_to_name, name_to_id
    except:
        return {}, {}

tmdb_id_map, tmdb_name_map = get_tmdb_genres()

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

# --- DATABASE ACTIONS ---
def add_to_sheet(item):
    sheet = get_google_sheet()
    if sheet:
        try:
            # We explicitly define the row to ensure no mismatch errors
            row_data = [
                item['Title'], 
                item['Type'], 
                item['Country'],
                "Plan to Watch", 
                item['Genres'], 
                item['Image'], 
                item['Overview'],
                item['Rating'], 
                item['Backdrop'], 
                0, 
                item['Total_Eps']
            ]
            sheet.append_row(row_data)
            return True
        except Exception as e:
            st.error(f"Error saving to Drive: {e}")
            return False
    return False

def update_status_in_sheet(title, new_status, new_ep):
    sheet = get_google_sheet()
    if sheet:
        try:
            cell = sheet.find(title)
            if cell:
                sheet.update_cell(cell.row, 4, new_status)
                sheet.update_cell(cell.row, 10, new_ep)
                st.toast(f"✅ Saved: {title}")
                time.sleep(0.5)
        except: pass

def delete_from_sheet(title):
    sheet = get_google_sheet()
    if sheet:
        try:
            cell = sheet.find(title)
            if cell:
                sheet.delete_rows(cell.row)
                st.toast(f"🗑️ Deleted: {title}")
                time.sleep(0.5)
        except: pass

# --- SEARCH & DISCOVERY ENGINE ---
def search_unified(query, selected_types, selected_genres, min_rating):
    results_data = []
    
    # 1. TMDB LOGIC
    live_action = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action):
        
        # Determine strict language filters for better discovery
        lang = None
        if "K-Drama" in selected_types and len(selected_types) == 1: lang = "ko"
        elif "C-Drama" in selected_types and len(selected_types) == 1: lang = "zh"
        elif "Thai Drama" in selected_types and len(selected_types) == 1: lang = "th"

        # Prepare Genres
        g_ids = ""
        if selected_genres:
            ids = [str(tmdb_name_map.get(g)) for g in selected_genres if tmdb_name_map.get(g)]
            g_ids = ",".join(ids)

        # MODE A: DISCOVERY (No Text)
        if not query:
            discover = Discover()
            kwargs = {'sort_by': 'popularity.desc', 'vote_average.gte': min_rating, 'with_genres': g_ids, 'page': 1}
            if lang: kwargs['with_original_language'] = lang

            if "Movies" in selected_types:
                try: 
                    for r in discover.discover_movies(kwargs): process_tmdb(r, "Movie", results_data, selected_types, selected_genres, min_rating)
                except: pass
            
            if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                try:
                    for r in discover.discover_tv_shows(kwargs): process_tmdb(r, "TV", results_data, selected_types, selected_genres, min_rating)
                except: pass

        # MODE B: SEARCH (With Text)
        else:
            search = Search()
            # We fetch 2 pages to increase chance of finding Asian dramas in global search
            if "Movies" in selected_types:
                for r in search.movies(query): process_tmdb(r, "Movie", results_data, selected_types, selected_genres, min_rating)
            
            if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                for r in search.tv_shows(query): process_tmdb(r, "TV", results_data, selected_types, selected_genres, min_rating)

    # 2. ANILIST LOGIC
    asian_comics = ["Anime", "Manga", "Manhwa", "Manhua"]
    if any(t in selected_types for t in asian_comics):
        modes = []
        if "Anime" in selected_types: modes.append("ANIME")
        if any(t in ["Manga", "Manhwa", "Manhua"] for t in selected_types): modes.append("MANGA")
        
        for m in set(modes):
            # If query is empty, we pass None to trigger pure discovery
            q_val = query if query else None 
            for r in fetch_anilist(q_val, m, selected_genres): 
                process_anilist(r, m, results_data, selected_types, selected_genres, min_rating)

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
    res_genres = [tmdb_id_map.get(gid, "Unknown") for gid in genre_ids]
    
    if selected_genres:
        res_str = ", ".join(res_genres).lower()
        if not any(s.lower() in res_str for s in selected_genres): return

    poster = getattr(res, 'poster_path', None)
    img_url = f"{tmdb_poster_base}{poster}" if poster else ""
    backdrop = getattr(res, 'backdrop_path', None)
    bd_url = f"{tmdb_backdrop_base}{backdrop}" if backdrop else ""
    
    results_list.append({
        "Title": getattr(res, 'title', getattr(res, 'name', 'Unknown')),
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res_genres),
        "Image": img_url,
        "Overview": getattr(res, 'overview', 'No overview.'),
        "Rating": f"{rating}/10",
        "Backdrop": bd_url,
        "Total_Eps": total_eps
    })

def fetch_anilist(query, type_, genres=None):
    # If no query, we REMOVE the 'search' parameter entirely to allow pure discovery
    if query:
        query_graphql = '''
        query ($s: String, $t: MediaType, $g: [String]) { 
          Page(perPage: 15) { 
            media(search: $s, type: $t, genre_in: $g, sort: POPULARITY_DESC) { 
              title { romaji english } coverImage { large } bannerImage genres countryOfOrigin type description averageScore episodes chapters 
            } 
          } 
        }
        '''
        variables = {'s': query, 't': type_}
    else:
        # Discovery Mode Query (No search term)
        query_graphql = '''
        query ($t: MediaType, $g: [String]) { 
          Page(perPage: 15) { 
            media(type: $t, genre_in: $g, sort: POPULARITY_DESC) { 
              title { romaji english } coverImage { large } bannerImage genres countryOfOrigin type description averageScore episodes chapters 
            } 
          } 
        }
        '''
        variables = {'t': type_}

    if genres: variables['g'] = genres

    try:
        r = requests.post('https://graphql.anilist.co', json={'query': query_graphql, 'variables': variables})
        return r.json()['data']['Page']['media']
    except: return []

def process_anilist(res, api_type, results_list, selected_types, selected_genres, min_rating):
    origin = res.get('countryOfOrigin', 'JP')
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
    if selected_genres:
        res_str = ", ".join(res_genres).lower()
        if not any(s.lower() in res_str for s in selected_genres): return

    import re
    raw = res.get('description', '')
    clean = re.sub('<[^<]+?>', '', raw) if raw else "No description."

    results_list.append({
        "Title": res['title']['english'] if res['title']['english'] else res['title']['romaji'],
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res_genres),
        "Image": res.get('coverImage', {}).get('large', ''),
        "Overview": clean,
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
GENRES = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Drama", "Fantasy", "Horror", "Mystery", "Romance", "Sci-Fi", "Sports", "Thriller", "War"]

# --- SEARCH TAB ---
if tab == "Search & Add":
    st.subheader("Global Database Search")
    
    with st.expander("🔎 Filter Options", expanded=True):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        with c1: search_query = st.text_input("Title (Optional)", placeholder="Leave empty to discover...")
        with c2: selected_types = st.multiselect("Type", ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama", "Anime", "Manga", "Manhwa", "Manhua"], default=["Movies"])
        with c3: selected_genres = st.multiselect("Genre", GENRES)
        with c4: min_rating = st.slider("Min Rating", 0, 10, 0)
        
        if st.button("🚀 Search / Discover"):
            with st.spinner("Fetching..."):
                if not selected_types: selected_types = ["Movies"]
                results = search_unified(search_query, selected_types, selected_genres, min_rating)
            
            if not results: st.warning("No results found.")
            else: st.session_state['last_results'] = results

    # Display Results (Persistent)
    if 'last_results' in st.session_state:
        for item in st.session_state['last_results']:
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    if item['Image']: st.image(item['Image'], use_container_width=True)
                with col_txt:
                    st.subheader(item['Title'])
                    st.caption(f"**{item['Type']}** | ⭐ {item['Rating']} | {item['Country']}")
                    st.caption(f"🏷️ {item['Genres']}")
                    st.write(item['Overview'][:250] + "...")
                    
                    # FIX FOR ADD BUTTON: Direct Call
                    if st.button(f"➕ Add Library", key=f"add_{item['Title']}_{item['Type']}"):
                        success = add_to_sheet(item)
                        if success:
                            st.toast(f"✅ Saved: {item['Title']}")
                        else:
                            st.toast("❌ Error saving. Check connection.")
            st.divider()

# --- GALLERY TAB ---
elif tab == "My Gallery":
    st.subheader("My Library")
    if st.button("🔄 Refresh"): st.cache_data.clear()
    
    if sheet:
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            
            with st.expander("Filter Collection", expanded=False):
                f1, f2, f3, f4 = st.columns(4)
                with f1: filter_text = st.text_input("Search Title")
                with f2: filter_type = st.multiselect("Filter Type", df['Type'].unique() if 'Type' in df.columns else [])
                with f3: filter_genre = st.multiselect("Filter Genre", GENRES)
                with f4: filter_status = st.multiselect("Status", ["Plan to Watch", "Watching", "Completed", "Dropped"])
            
            # Apply Filters
            if filter_text: df = df[df['Title'].astype(str).str.contains(filter_text, case=False, na=False)]
            if filter_type: df = df[df['Type'].isin(filter_type)]
            if filter_status: df = df[df['Status'].isin(filter_status)]
            if filter_genre:
                mask = df['Genres'].apply(lambda x: any(g.lower() in str(x).lower() for g in filter_genre))
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
                            
                            with st.expander("⚙️ Manage"):
                                opts = ["Plan to Watch", "Watching", "Completed", "Dropped"]
                                curr = item.get('Status', 'Plan to Watch')
                                if curr not in opts: curr = "Plan to Watch"
                                new_s = st.selectbox("Status", opts, key=f"st_{item['Title']}", index=opts.index(curr))
                                
                                c_ep = item.get('Current_Ep')
                                if c_ep == '': c_ep = 0
                                new_e = c_ep
                                if item['Type'] != "Movies":
                                    c1, c2, c3 = st.columns([1, 1, 1])
                                    with c1: 
                                        if st.button("➖", key=f"m_{item['Title']}"): new_e = int(c_ep) - 1
                                    with c2: st.markdown(f"<center>{c_ep}</center>", unsafe_allow_html=True)
                                    with c3: 
                                        if st.button("➕", key=f"p_{item['Title']}"): new_e = int(c_ep) + 1
                                
                                c_sv, c_dl = st.columns([1, 1])
                                with c_sv:
                                    if st.button("💾", key=f"sv_{item['Title']}"):
                                        update_status_in_sheet(item['Title'], new_s, new_e)
                                        st.rerun()
                                with c_dl:
                                    if st.button("🗑️", key=f"dl_{item['Title']}"):
                                        delete_from_sheet(item['Title'])
                                        st.rerun()
                            
                            with st.popover("📜 Info"):
                                if str(item.get('Backdrop')).startswith("http"):
                                    st.image(item['Backdrop'], use_container_width=True)
                                st.write(f"Rating: {item.get('Rating')}")
                                st.write(item.get('Overview'))
            else: st.info("No matches.")
        else: st.info("Empty Library")
