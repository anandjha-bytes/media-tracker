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
    st.error("CRITICAL ERROR: TMDB_API_KEY not found in secrets.")
    st.stop()

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
    creds = None
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = st.secrets["gcp_service_account"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    except: return None

    try:
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        
        # --- AUTO-REPAIR HEADERS ---
        vals = sheet.get_all_values()
        REQUIRED_HEADERS = [
            "Title", "Type", "Country", "Status", "Genres", "Image", 
            "Overview", "Rating", "Backdrop", "Current_Season", 
            "Current_Ep", "Total_Eps", "Total_Seasons", "ID"
        ]
        
        if not vals:
            sheet.append_row(REQUIRED_HEADERS)
        elif vals[0] != REQUIRED_HEADERS:
            if len(vals[0]) < len(REQUIRED_HEADERS):
                 sheet.resize(cols=len(REQUIRED_HEADERS))
                 for i, header in enumerate(REQUIRED_HEADERS):
                     sheet.update_cell(1, i+1, header)
                
        return sheet
    except Exception as e:
        return None

# --- DATABASE ACTIONS ---
def fetch_details_and_add(item):
    sheet = get_google_sheet()
    if not sheet: return False
    
    total_seasons = 1
    total_eps = item['Total_Eps']
    media_id = item.get('ID') 
    
    # Deep fetch for TV shows to get accurate counts
    if item['Type'] not in ["Movies", "Anime", "Manga", "Manhwa", "Manhua"] and media_id:
        try:
            tv_api = TV()
            details = tv_api.details(media_id)
            total_seasons = getattr(details, 'number_of_seasons', 1)
            total_eps = getattr(details, 'number_of_episodes', "?")
        except: pass

    try:
        row_data = [
            item['Title'], item['Type'], item['Country'],
            "Plan to Watch", item['Genres'], item['Image'], 
            item['Overview'], item['Rating'], item['Backdrop'], 
            1, 0, total_eps, total_seasons, media_id
        ]
        sheet.append_row(row_data)
        return True
    except Exception as e:
        st.error(f"Error: {e}")
        return False

def update_status_in_sheet(title, new_status, new_season, new_ep):
    sheet = get_google_sheet()
    if sheet:
        try:
            cell = sheet.find(title)
            if cell:
                sheet.update_cell(cell.row, 4, new_status)
                sheet.update_cell(cell.row, 10, new_season)
                sheet.update_cell(cell.row, 11, new_ep)
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

# --- SEARCH ENGINE (SMART DISCOVERY) ---
def search_unified(query, selected_types, selected_genres, sort_option, page=1):
    results_data = []
    
    # --- 1. TMDB (MOVIES/TV) ---
    live_action = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action):
        lang = None
        if "K-Drama" in selected_types and len(selected_types) == 1: lang = "ko"
        elif "C-Drama" in selected_types and len(selected_types) == 1: lang = "zh"
        elif "Thai Drama" in selected_types and len(selected_types) == 1: lang = "th"

        g_ids = ""
        if selected_genres:
            ids = [str(tmdb_name_map.get(g)) for g in selected_genres if tmdb_name_map.get(g)]
            g_ids = ",".join(ids)

        tmdb_sort = 'popularity.desc'
        if sort_option == 'Top Rated': tmdb_sort = 'vote_average.desc'

        if not query:
            # DISCOVERY MODE
            discover = Discover()
            kwargs = {
                'sort_by': tmdb_sort, 
                'with_genres': g_ids, 
                'page': page,
                'vote_count.gte': 50
            }
            if lang: kwargs['with_original_language'] = lang

            if "Movies" in selected_types:
                try: 
                    for r in discover.discover_movies(kwargs): process_tmdb(r, "Movie", results_data, selected_types, selected_genres)
                except: pass
            if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                try:
                    for r in discover.discover_tv_shows(kwargs): process_tmdb(r, "TV", results_data, selected_types, selected_genres)
                except: pass
        else:
            # SEARCH MODE
            search = Search()
            current_results = []
            if "Movies" in selected_types:
                try:
                    for r in search.movies(query, page=page): process_tmdb(r, "Movie", current_results, selected_types, selected_genres)
                except: pass
            if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                try:
                    for r in search.tv_shows(query, page=page): process_tmdb(r, "TV", current_results, selected_types, selected_genres)
                except: pass
            
            if sort_option == "Top Rated":
                current_results.sort(key=lambda x: float(x['Rating'].split('/')[0]), reverse=True)
            
            results_data.extend(current_results)

    # --- 2. ANILIST (ANIME/MANGA) ---
    asian_comics = ["Anime", "Manga", "Manhwa", "Manhua"]
    if any(t in selected_types for t in asian_comics):
        modes = []
        if "Anime" in selected_types: modes.append("ANIME")
        if any(t in ["Manga", "Manhwa", "Manhua"] for t in selected_types): modes.append("MANGA")
        
        for m in set(modes):
            # STRICT COUNTRY FILTERING FOR MANHWA/MANHUA
            country_filter = None
            if m == "MANGA":
                if "Manhwa" in selected_types and "Manga" not in selected_types and "Manhua" not in selected_types:
                    country_filter = "KR" # Force Korea
                elif "Manhua" in selected_types and "Manga" not in selected_types and "Manhwa" not in selected_types:
                    country_filter = "CN" # Force China
                elif "Manga" in selected_types and "Manhwa" not in selected_types and "Manhua" not in selected_types:
                    country_filter = "JP" # Force Japan

            q_val = query if query else None 
            
            for r in fetch_anilist(q_val, m, selected_genres, sort_option, page, country_filter): 
                process_anilist(r, m, results_data, selected_types, selected_genres)

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
    
    rating = getattr(res, 'vote_average', 0)
    genre_ids = getattr(res, 'genre_ids', [])
    res_genres = [tmdb_id_map.get(gid, "Unknown") for gid in genre_ids]
    
    if selected_genres:
        res_str = ", ".join(res_genres).lower()
        if not any(s.lower() in res_str for s in selected_genres): return

    poster = getattr(res, 'poster_path', None)
    img_url = f"{tmdb_poster_base}{poster}" if poster else ""
    
    results_list.append({
        "Title": getattr(res, 'title', getattr(res, 'name', 'Unknown')),
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res_genres),
        "Image": img_url,
        "Overview": getattr(res, 'overview', 'No overview.'),
        "Rating": f"{rating}/10",
        "Backdrop": f"{tmdb_backdrop_base}{getattr(res, 'backdrop_path', '')}",
        "Total_Eps": "?", 
        "ID": getattr(res, 'id', None)
    })

def fetch_anilist(query, type_, genres=None, sort_opt="Popularity", page=1, country=None):
    anilist_sort = "POPULARITY_DESC"
    if sort_opt == "Top Rated": anilist_sort = "SCORE_DESC"
    elif sort_opt == "Relevance" and query: anilist_sort = "SEARCH_MATCH"
    
    # 1. Start with base variables
    variables = {
        't': type_, 
        'p': page, 
        'sort': [anilist_sort]
    }
    
    # 2. Build Query DYNAMICALLY to avoid syntax errors
    query_args = ["$p: Int", "$t: MediaType", "$sort: [MediaSort]"]
    media_args = ["type: $t", "page: $p", "sort: $sort"]
    
    if query:
        query_args.append("$s: String")
        media_args.append("search: $s")
        variables['s'] = query
        
    if genres:
        query_args.append("$g: [String]")
        media_args.append("genre_in: $g")
        variables['g'] = genres
        
    if country:
        query_args.append("$c: CountryCode")
        media_args.append("countryOfOrigin: $c")
        variables['c'] = country

    query_str = f'''
    query ({', '.join(query_args)}) {{ 
      Page(perPage: 15) {{ 
        media({', '.join(media_args)}) {{ 
          title {{ romaji english }} coverImage {{ large }} bannerImage genres countryOfOrigin type description averageScore episodes chapters 
        }} 
      }} 
    }}
    '''

    try:
        r = requests.post('https://graphql.anilist.co', json={'query': query_str, 'variables': variables})
        if r.status_code == 200:
            return r.json()['data']['Page']['media']
        else:
            return []
    except: return []

def process_anilist(res, api_type, results_list, selected_types, selected_genres):
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
        "Total_Eps": total,
        "ID": None
    })

# --- UI START ---
st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="🎬")
st.title("🎬 Ultimate Media Tracker")

sheet = get_google_sheet()
if "refresh_key" not in st.session_state: st.session_state.refresh_key = 0

if 'search_results' not in st.session_state: st.session_state.search_results = []
if 'search_page' not in st.session_state: st.session_state.search_page = 1

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
        with c4: 
            sort_option = st.selectbox("Sort By", ["Popularity", "Relevance", "Top Rated"])
        
        if st.button("🚀 Search / Discover"):
            st.session_state.search_page = 1
            st.session_state.search_results = []
            with st.spinner("Fetching..."):
                if not selected_types: selected_types = ["Movies"]
                results = search_unified(search_query, selected_types, selected_genres, sort_option, page=1)
                st.session_state.search_results = results
            
            if not st.session_state.search_results: st.warning("No results found.")

    if st.session_state.search_results:
        for idx, item in enumerate(st.session_state.search_results):
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    if item['Image']: st.image(item['Image'], use_container_width=True)
                with col_txt:
                    st.subheader(item['Title'])
                    st.caption(f"**{item['Type']}** | ⭐ {item['Rating']} | {item['Country']}")
                    st.caption(f"🏷️ {item['Genres']}")
                    st.write(item['Overview'][:250] + "...")
                    
                    if st.button(f"➕ Add Library", key=f"add_{item['Title']}_{idx}"):
                        with st.spinner("Fetching details..."):
                            success = fetch_details_and_add(item)
                        if success: st.toast(f"✅ Saved: {item['Title']}")
                        else: st.toast("❌ Error saving.")
            st.divider()

        if st.button("⬇️ Load More Results"):
            st.session_state.search_page += 1
            with st.spinner(f"Loading Page {st.session_state.search_page}..."):
                new_results = search_unified(search_query, selected_types, selected_genres, sort_option, page=st.session_state.search_page)
                st.session_state.search_results.extend(new_results)
                st.rerun()

# --- GALLERY TAB ---
elif tab == "My Gallery":
    st.subheader("My Library")
    if st.button("🔄 Refresh"): st.cache_data.clear()
    
    if sheet:
        raw_data = sheet.get_all_values()
        HEADERS = ["Title", "Type", "Country", "Status", "Genres", "Image", "Overview", "Rating", "Backdrop", "Current_Season", "Current_Ep", "Total_Eps", "Total_Seasons", "ID"]
        
        if len(raw_data) > 1:
            safe_rows = []
            for row in raw_data[1:]:
                if not row or not row[0].strip(): continue
                if len(row) < len(HEADERS): row += [""] * (len(HEADERS) - len(row))
                safe_rows.append(row[:len(HEADERS)])
            
            df = pd.DataFrame(safe_rows, columns=HEADERS)
            
            with st.expander("Filter Collection", expanded=False):
                f1, f2, f3, f4 = st.columns(4)
                with f1: filter_text = st.text_input("Search Title")
                with f2: filter_type = st.multiselect("Filter Type", df['Type'].unique() if not df.empty else [])
                with f3: filter_genre = st.multiselect("Filter Genre", GENRES)
                with f4: filter_status = st.multiselect("Status", ["Plan to Watch", "Watching", "Completed", "Dropped"])
            
            if not df.empty:
                if filter_text: df = df[df['Title'].astype(str).str.contains(filter_text, case=False, na=False)]
                if filter_type: df = df[df['Type'].isin(filter_type)]
                if filter_status: df = df[df['Status'].isin(filter_status)]
                if filter_genre: mask = df['Genres'].apply(lambda x: any(g.lower() in str(x).lower() for g in filter_genre)); df = df[mask]

            st.divider()
            
            if not df.empty:
                cols_per_row = 4
                rows = [df.iloc[i:i + cols_per_row] for i in range(0, len(df), cols_per_row)]
                for row in rows:
                    cols = st.columns(cols_per_row)
                    for idx, (_, item) in enumerate(row.iterrows()):
                        with cols[idx]:
                            img_url = str(item.get('Image', '')).strip()
                            if not img_url.startswith("http"): img_url = "https://via.placeholder.com/200x300?text=No+Image"
                            st.image(img_url, use_container_width=True)
                            st.markdown(f"**{item['Title']}**")
                            
                            with st.expander("⚙️ Manage"):
                                opts = ["Plan to Watch", "Watching", "Completed", "Dropped"]
                                curr = item.get('Status', 'Plan to Watch')
                                if curr not in opts: curr = "Plan to Watch"
                                new_s = st.selectbox("Status", opts, key=f"st_{item['Title']}_{idx}", index=opts.index(curr))
                                
                                if item['Type'] != "Movies":
                                    try: c_sea = int(item.get('Current_Season', 1))
                                    except: c_sea = 1
                                    try: c_ep = int(item.get('Current_Ep', 0))
                                    except: c_ep = 0

                                    tot_eps = item.get('Total_Eps', '?')
                                    tot_sea = item.get('Total_Seasons', '?')

                                    is_manga = "Manga" in item['Type'] or "Manhwa" in item['Type'] or "Manhua" in item['Type']
                                    
                                    col_sea, col_ep = st.columns(2)
                                    with col_sea:
                                        if not is_manga:
                                            new_sea = st.number_input("Season:", min_value=1, value=c_sea, step=1, key=f"sea_{item['Title']}_{idx}")
                                            st.caption(f"Total: {tot_sea}")
                                        else: new_sea = 1
                                    with col_ep:
                                        label = "Chapter" if is_manga else "Episode"
                                        new_ep = st.number_input(f"{label}:", min_value=0, value=c_ep, step=1, key=f"ep_{item['Title']}_{idx}")
                                        st.caption(f"Total: {tot_eps}")
                                else:
                                    new_sea = 1; new_ep = 0

                                c_sv, c_dl = st.columns([1, 1])
                                with c_sv:
                                    if st.button("💾 Save", key=f"sv_{item['Title']}_{idx}"):
                                        update_status_in_sheet(item['Title'], new_s, new_sea, new_ep)
                                        st.rerun()
                                with c_dl:
                                    if st.button("🗑️ Del", key=f"dl_{item['Title']}_{idx}"):
                                        delete_from_sheet(item['Title'])
                                        st.rerun()
                            
                            with st.popover("📜 Info"):
                                bd = str(item.get('Backdrop', '')).strip()
                                if bd.startswith("http"): st.image(bd, use_container_width=True)
                                
                                # --- READ BUTTON FOR MANGA/MANHWA ---
                                if "Manga" in item['Type'] or "Manhwa" in item['Type'] or "Manhua" in item['Type']:
                                    search_url = f"https://comix.to/search?q={item['Title'].replace(' ', '+')}"
                                    st.link_button("📖 Read on Comix.to", search_url)
                                
                                st.write(f"Rating: {item.get('Rating')}")
                                st.write(item.get('Overview'))
            else: st.info("No matches.")
        else: st.info("Empty Library")
    else: st.error("Connection Failed. Check Secrets.")
