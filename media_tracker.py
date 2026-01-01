import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Genre, Discover
import requests
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- PAGE CONFIG ---
st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="📚")
st.title("🎬 Ultimate Media Tracker")

# --- TRY IMPORTING SORTABLES ---
try:
    from streamlit_sortables import sort_items
    HAS_SORTABLES = True
except ImportError:
    HAS_SORTABLES = False

# --- CONFIGURATION ---
try:
    TMDB_API_KEY = st.secrets["tmdb_api_key"]
except:
    st.error("Secrets not found. Please set up .streamlit/secrets.toml")
    st.stop()

GOOGLE_SHEET_NAME = 'My Media Tracker'

# --- SETUP APIS ---
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = 'en'
tmdb_poster_base = "https://image.tmdb.org/t/p/w400"
tmdb_backdrop_base = "https://image.tmdb.org/t/p/w780"

# --- GENRE MAPS ---
TMDB_GENRE_MAP = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Sci-Fi": 878, "TV Movie": 10770,
    "Thriller": 53, "War": 10752, "Western": 37,
    "Action & Adventure": 10759, "Sci-Fi & Fantasy": 10765, "War & Politics": 10768
}
ID_TO_GENRE = {v: k for k, v in TMDB_GENRE_MAP.items()}

BOOK_GENRES = [
    "Web Novel", "Fiction", "Fantasy", "Sci-Fi", "Mystery", "Thriller", "Romance", 
    "History", "Biography", "Business", "Self-Help", "Psychology", 
    "Philosophy", "Science", "Technology", "Manga", "Light Novel", "Computers",
    "Horror", "Poetry", "Comics", "Art", "Cooking"
]

# --- CACHE COUNTRIES ---
@st.cache_data
def get_tmdb_countries():
    try:
        url = f"https://api.themoviedb.org/3/configuration/countries?api_key={TMDB_API_KEY}"
        resp = requests.get(url).json()
        countries = {c['english_name']: c['iso_3166_1'] for c in resp}
        return dict(sorted(countries.items()))
    except:
        return {'United States': 'US', 'India': 'IN', 'United Kingdom': 'GB'}

tmdb_countries = get_tmdb_countries()

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
    except:
        return None

# --- FAST LIBRARY CACHE ---
def get_library_data():
    """Reads sheet once and caches it for speed."""
    if 'lib_data' not in st.session_state:
        sheet = get_google_sheet()
        if sheet:
            try:
                # Get all records at once (faster than repeated calls)
                data = sheet.get_all_records()
                lib_map = {}
                for item in data:
                    t = item.get('Title', '').strip()
                    if t: lib_map[t] = item
                st.session_state.lib_data = lib_map
            except:
                st.session_state.lib_data = {}
        else:
            st.session_state.lib_data = {}
    return st.session_state.lib_data

def refresh_library():
    """Forces a re-fetch of the library."""
    if 'lib_data' in st.session_state:
        del st.session_state.lib_data
    get_library_data()

# --- DATABASE ACTIONS ---
def fetch_details_and_add(item):
    sheet = get_google_sheet()
    if not sheet: return False
    
    # 1. OPTIMIZED: Check Cache first instead of calling API
    lib_data = get_library_data()
    if item['Title'].strip() in lib_data:
        st.toast(f"⚠️ '{item['Title']}' is already in your library!")
        return True

    total_seasons = 1
    total_eps = item['Total_Eps']
    media_id = item.get('ID') 
    
    # Fetch details only if needed
    if item['Type'] in ["Web Series", "K-Drama", "C-Drama", "Thai Drama"] and media_id:
        try:
            tv_api = TV()
            details = tv_api.details(media_id)
            total_seasons = getattr(details, 'number_of_seasons', 1)
            total_eps = getattr(details, 'number_of_episodes', "?")
        except: pass

    default_status = "Plan to Watch"
    if item['Type'] in ["Manga", "Manhwa", "Manhua", "Book", "Novel"]:
        default_status = "Plan to Read"

    try:
        row_data = [
            item['Title'], item['Type'], item['Country'],
            default_status, item['Genres'], item['Image'], 
            item['Overview'], item['Rating'], item['Backdrop'], 
            1, 0, total_eps, total_seasons, media_id
        ]
        sheet.append_row(row_data)
        st.toast(f"✅ Added: {item['Title']}")
        
        # Update Cache Locally (Instant UI update)
        new_entry = {
            "Title": item['Title'], "Type": item['Type'], "Country": item['Country'],
            "Status": default_status, "Genres": item['Genres'], "Image": item['Image'],
            "Overview": item['Overview'], "Rating": item['Rating'], "Backdrop": item['Backdrop'],
            "Current_Season": 1, "Current_Ep": 0, "Total_Eps": total_eps, "Total_Seasons": total_seasons, "ID": media_id
        }
        if 'lib_data' in st.session_state:
            st.session_state.lib_data[item['Title'].strip()] = new_entry
            
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
                # Update Cache
                if 'lib_data' in st.session_state and title in st.session_state.lib_data:
                    st.session_state.lib_data[title]['Status'] = new_status
                    st.session_state.lib_data[title]['Current_Season'] = new_season
                    st.session_state.lib_data[title]['Current_Ep'] = new_ep
        except: pass

def delete_from_sheet(title):
    sheet = get_google_sheet()
    if sheet:
        try:
            cell = sheet.find(title)
            if cell:
                sheet.delete_rows(cell.row)
                st.toast(f"🗑️ Deleted: {title}")
                # Update Cache
                if 'lib_data' in st.session_state and title in st.session_state.lib_data:
                    del st.session_state.lib_data[title]
        except: pass

def bulk_update_order(new_df):
    sheet = get_google_sheet()
    if not sheet: return
    header = sheet.row_values(1)
    data_to_upload = new_df.astype(str).values.tolist()
    sheet.clear()
    sheet.append_row(header)
    sheet.append_rows(data_to_upload)
    st.toast("✅ Order Saved!")
    refresh_library()
    time.sleep(1)
    st.rerun()

# --- HELPERS ---
def recover_tmdb_id(title, media_type):
    search = Search()
    try:
        if media_type == 'movie': results = search.movies(title)
        else: results = search.tv_shows(title)
        if results: return results[0].id
    except: return None
    return None

def get_streaming_info(tmdb_id, media_type, country_code):
    if not tmdb_id: return None
    try: clean_id = int(float(tmdb_id))
    except: return None
    url = f"https://api.themoviedb.org/3/{media_type}/{clean_id}/watch/providers?api_key={TMDB_API_KEY}"
    try:
        r = requests.get(url)
        data = r.json()
        if 'results' in data and country_code in data['results']:
            return data['results'][country_code]
    except: return None
    return None

def get_provider_link(provider_name, title):
    q = urllib.parse.quote(title)
    p = provider_name.lower()
    if 'netflix' in p: return f"https://www.netflix.com/search?q={q}"
    if 'amazon' in p or 'prime' in p: return f"https://www.amazon.com/s?k={q}&i=instant-video"
    if 'youtube' in p: return f"https://www.youtube.com/results?search_query={q}"
    return f"https://www.google.com/search?q=watch+{q}+on+{urllib.parse.quote(provider_name)}"

# --- FETCHERS ---
@st.cache_data(ttl=3600)
def get_season_details(tmdb_id, season_num):
    if not tmdb_id: return None
    try:
        clean_id = int(float(tmdb_id))
        url = f"https://api.themoviedb.org/3/tv/{clean_id}/season/{season_num}?api_key={TMDB_API_KEY}"
        r = requests.get(url)
        if r.status_code == 200:
            data = r.json()
            return {"episode_count": len(data.get('episodes', [])), "name": data.get('name')}
    except: return None
    return None

@st.cache_data(ttl=3600)
def fetch_anilist_data_single(title, media_type, format_in=None):
    query = '''
    query ($s: String, $t: MediaType, $f: MediaFormat) {
        Page(perPage: 1) {
            media(search: $s, type: $t, format: $f) {
                id
                trailer { id site }
                externalLinks { site url }
                episodes
                chapters
                volumes
            }
        }
    }
    '''
    variables = {'s': title, 't': media_type}
    if format_in: variables['f'] = format_in
    try:
        r = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': variables})
        data = r.json()
        if data['data']['Page']['media']: 
            return data['data']['Page']['media'][0]
    except: pass
    return {}

@st.cache_data(ttl=3600)
def fetch_anilist_list_raw(query, type_, genres, sort_opt, page, country=None, format=None):
    """Raw AniList fetcher for threading."""
    anilist_sort = "POPULARITY_DESC"
    if sort_opt == "Top Rated": anilist_sort = "SCORE_DESC"
    elif sort_opt == "Relevance" and query: anilist_sort = "SEARCH_MATCH"
    
    variables = {'t': type_, 'p': page, 'sort': [anilist_sort]}
    query_args = ["$p: Int", "$t: MediaType", "$sort: [MediaSort]"]
    media_args = ["type: $t", "sort: $sort"]
    
    if query:
        query_args.append("$s: String"); media_args.append("search: $s"); variables['s'] = query
    if genres:
        query_args.append("$g: [String]"); media_args.append("genre_in: $g"); variables['g'] = genres
    if country:
        query_args.append("$c: CountryCode"); media_args.append("countryOfOrigin: $c"); variables['c'] = country
    if format:
        query_args.append("$f: MediaFormat"); media_args.append("format: $f"); variables['f'] = format

    query_str = f'''
    query ({', '.join(query_args)}) {{ 
      Page(page: $p, perPage: 15) {{ 
        media({', '.join(media_args)}) {{ 
          title {{ romaji english }} coverImage {{ large }} bannerImage genres countryOfOrigin type format description averageScore episodes chapters volumes
          externalLinks {{ site url }}
        }} 
      }} 
    }}'''
    try:
        r = requests.post('https://graphql.anilist.co', json={'query': query_str, 'variables': variables})
        if r.status_code == 200: return r.json()['data']['Page']['media']
    except: pass
    return []

@st.cache_data(ttl=3600)
def fetch_open_library_raw(query, genre=None):
    """Raw Open Library fetcher for threading."""
    url = "https://openlibrary.org/search.json"
    params = {'limit': 15}
    if query:
        params['q'] = query
        if genre and genre != "Web Novel":
             params['q'] += f" subject:{genre}"
    elif genre:
        params['subject'] = genre
    else:
        params['subject'] = "fiction" 

    try:
        headers = {'User-Agent': 'MediaTrackerApp/1.0'}
        r = requests.get(url, params=params, headers=headers)
        if r.status_code == 200:
            return r.json().get('docs', [])
    except: pass
    return []

def get_tmdb_trailer(tmdb_id, media_type):
    if not tmdb_id: return None
    try:
        clean_id = int(float(tmdb_id))
        url = f"https://api.themoviedb.org/3/{media_type}/{clean_id}/videos?api_key={TMDB_API_KEY}"
        r = requests.get(url)
        data = r.json()
        if 'results' in data:
            for vid in data['results']:
                if vid['site'] == 'YouTube' and vid['type'] == 'Trailer':
                    return f"https://www.youtube.com/watch?v={vid['key']}"
            for vid in data['results']:
                if vid['site'] == 'YouTube':
                    return f"https://www.youtube.com/watch?v={vid['key']}"
    except: return None
    return None

# --- PROCESSORS ---
def process_open_library(items, detected_type):
    results = []
    for item in items:
        cover_id = item.get('cover_i')
        img_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else "https://via.placeholder.com/300x450?text=No+Cover"
        
        title = item.get('title', 'Unknown')
        author_list = item.get('author_name', [])
        authors = ", ".join(author_list[:2])
        if authors: title += f" - {authors}"
        
        desc = f"First published in {item.get('first_publish_year', 'Unknown')}."
        if item.get('first_sentence'):
             desc = f"\"{item['first_sentence'][0]}\" - " + desc
        
        rating_val = item.get('ratings_average', 0)
        
        results.append({
            "Title": title,
            "Type": detected_type,
            "Country": "International",
            "Genres": ", ".join(item.get('subject', [])[:3]),
            "Image": img_url,
            "Overview": desc,
            "Rating": f"{round(rating_val, 1)}/5",
            "Backdrop": "",
            "Total_Eps": str(item.get('number_of_pages_median', '?')),
            "ID": item.get('key'),
            "Source": "OpenLibrary",
            "Links": []
        })
    return results

def process_anilist_results(res_list, forced_type, selected_genres):
    results = []
    for res in res_list:
        origin = res.get('countryOfOrigin', 'JP')
        final_type = forced_type
        
        if forced_type == "Donghua" and origin != "CN": continue
        if forced_type == "Manhwa" and origin != "KR": continue
        if forced_type == "Manhua" and origin != "CN": continue
        if forced_type == "Novel": pass 

        res_genres = res.get('genres', [])
        if selected_genres:
            filtered_genres = [g for g in selected_genres if g != "Web Novel"]
            if filtered_genres and not any(g in res_genres for g in filtered_genres): 
                continue

        import re
        raw = res.get('description', '')
        clean = re.sub('<[^<]+?>', '', raw) if raw else "No description."
        
        total = res.get('episodes') or res.get('chapters') or res.get('volumes') or "?"
        
        avg_score = res.get('averageScore')
        rating_str = f"{avg_score/10}/10" if avg_score else "?/10"
        
        results.append({
            "Title": res['title']['english'] if res['title']['english'] else res['title']['romaji'],
            "Type": final_type,
            "Country": origin,
            "Genres": ", ".join(res_genres),
            "Image": res.get('coverImage', {}).get('large', ''),
            "Overview": clean,
            "Rating": rating_str,
            "Backdrop": res.get('bannerImage', ''),
            "Total_Eps": total,
            "ID": None,
            "Links": res.get('externalLinks', [])
        })
    return results

def process_tmdb_results_batch(results, media_kind, specific_type, selected_types, selected_genres, query):
    processed = []
    for r in results:
        res_lang = getattr(r, 'original_language', 'en')
        match = True
        
        if not query:
            if specific_type == "K-Drama" and res_lang != 'ko': match = False
            elif specific_type == "C-Drama" and res_lang != 'zh': match = False
            elif specific_type == "Thai Drama" and res_lang != 'th': match = False
        
        # Genre Check
        genre_ids = getattr(r, 'genre_ids', [])
        res_genres = [ID_TO_GENRE.get(gid, "Unknown") for gid in genre_ids]
        if selected_genres:
            if not any(g in res_genres for g in selected_genres): match = False

        if match:
            origin = getattr(r, 'original_language', 'en')
            detected_type = "Web Series"
            if media_kind == "Movie": detected_type = "Movies"
            elif origin == 'ko': detected_type = "K-Drama"
            elif origin == 'zh': detected_type = "C-Drama"
            elif origin == 'th': detected_type = "Thai Drama"
            elif origin == 'ja': detected_type = "Anime"
            elif origin == 'en': detected_type = "Web Series"
            
            if detected_type not in selected_types: continue

            poster = getattr(r, 'poster_path', None)
            img_url = f"{tmdb_poster_base}{poster}" if poster else ""
            
            processed.append({
                "Title": getattr(r, 'title', getattr(r, 'name', 'Unknown')),
                "Type": detected_type,
                "Country": origin,
                "Genres": ", ".join(res_genres),
                "Image": img_url,
                "Overview": getattr(r, 'overview', 'No overview.'),
                "Rating": f"{getattr(r, 'vote_average', 0)}/10",
                "Backdrop": f"{tmdb_backdrop_base}{getattr(r, 'backdrop_path', '')}",
                "Total_Eps": "?", 
                "ID": getattr(r, 'id', None)
            })
    return processed

# --- PARALLEL SEARCH ENGINE ---
def search_unified(query, selected_types, selected_genres, sort_option, page=1):
    results_data = []
    futures = []
    
    # 1. VISUAL MEDIA (Movies, Shows, Asian Dramas)
    live_action = ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action):
        g_ids = ""
        tmdb_genres = [g for g in selected_genres if g in TMDB_GENRE_MAP]
        if tmdb_genres:
             ids = [str(TMDB_GENRE_MAP.get(g)) for g in tmdb_genres]
             g_ids = "|".join(ids)

        tmdb_sort = 'popularity.desc'
        if sort_option == 'Top Rated': tmdb_sort = 'vote_average.desc'

        discover = Discover()
        search = Search()
        
        # Define TMDB Job
        def run_tmdb_job(media_kind, specific_type, lang_filter=None):
            try:
                active_q = query
                if query and specific_type == "K-Drama": active_q = f"{query} Korean"
                elif query and specific_type == "C-Drama": active_q = f"{query} Chinese"
                
                if active_q:
                    if media_kind == "Movie": raw = search.movies(active_q, page=page)
                    else: raw = search.tv_shows(active_q, page=page)
                else:
                    kwargs = {'sort_by': tmdb_sort, 'page': page, 'vote_count.gte': 5}
                    if g_ids: kwargs['with_genres'] = g_ids
                    if lang_filter: kwargs['with_original_language'] = lang_filter
                    if media_kind == "Movie": raw = discover.discover_movies(kwargs)
                    else: raw = discover.discover_tv_shows(kwargs)
                
                return process_tmdb_results_batch(raw, media_kind, specific_type, selected_types, selected_genres, query)
            except: return []

    # 2. ANILIST & OPEN LIBRARY JOB DEFINITIONS
    def run_anilist_job(q, t, g, s, p, c=None, f=None, forced_t="Anime"):
        raw = fetch_anilist_list_raw(q, t, g, s, p, c, f)
        return process_anilist_results(raw, forced_t, g)

    def run_openlib_job(q, g, forced_t):
        q_mod = q
        if forced_t == "Novel": q_mod = q + " novel" if q else "fantasy novel"
        raw = fetch_open_library_raw(q_mod, g)
        return process_open_library(raw, forced_t)

    # EXECUTE IN PARALLEL
    with ThreadPoolExecutor(max_workers=10) as executor:
        # TMDB
        if "Movies" in selected_types: futures.append(executor.submit(run_tmdb_job, "Movie", "Movies"))
        if "Web Series" in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "Web Series"))
        if "K-Drama" in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "K-Drama", "ko"))
        if "C-Drama" in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "C-Drama", "zh"))
        if "Thai Drama" in selected_types: futures.append(executor.submit(run_tmdb_job, "TV", "Thai Drama", "th"))
        
        # ANILIST
        if "Anime" in selected_types: futures.append(executor.submit(run_anilist_job, query, "ANIME", selected_genres, sort_option, page, None, None, "Anime"))
        if "Donghua" in selected_types: futures.append(executor.submit(run_anilist_job, query, "ANIME", selected_genres, sort_option, page, "CN", None, "Donghua"))
        if "Manga" in selected_types: futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "JP", None, "Manga"))
        if "Manhwa" in selected_types: futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "KR", None, "Manhwa"))
        if "Manhua" in selected_types: futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "CN", None, "Manhua"))
        
        # NOVELS (Mix)
        if "Novel" in selected_types:
            futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, None, "NOVEL", "Novel"))
            if "Web Novel" in selected_genres:
                 futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "KR", "NOVEL", "Novel"))
                 futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "CN", "NOVEL", "Novel"))
            futures.append(executor.submit(run_openlib_job, query, None, "Novel"))

        # BOOKS (OpenLib)
        if "Book" in selected_types:
            target_genre = None
            if selected_genres:
                book_genres = [g for g in selected_genres if g in BOOK_GENRES]
                if book_genres: target_genre = book_genres[0]
            futures.append(executor.submit(run_openlib_job, query, target_genre, "Book"))

        # GATHER RESULTS
        for future in as_completed(futures):
            try:
                data = future.result()
                if data: results_data.extend(data)
            except: pass

    return results_data

# --- UI START ---
if "refresh_key" not in st.session_state: st.session_state.refresh_key = 0
if 'search_results' not in st.session_state: st.session_state.search_results = []
if 'search_page' not in st.session_state: st.session_state.search_page = 1

tab = st.sidebar.radio("Menu", ["My Gallery", "Search & Add"], key="main_nav")

# --- SEARCH TAB ---
if tab == "Search & Add":
    st.subheader("Global Database Search")
    
    # 1. SEARCH INPUT (Enter triggers search)
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1: 
        search_query = st.text_input("Title (Optional)", on_change=None) 
    with c2: 
        all_types = ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama", "Anime", "Donghua", "Manga", "Manhwa", "Manhua", "Novel", "Book"]
        selected_types = st.multiselect("Type", all_types, default=["Movies"])
    
    current_genres = list(TMDB_GENRE_MAP.keys())
    if "Book" in selected_types or "Novel" in selected_types:
            current_genres = sorted(list(set(current_genres + BOOK_GENRES)))

    with c3: selected_genres = st.multiselect("Genre", current_genres)
    with c4: sort_option = st.selectbox("Sort By", ["Popularity", "Relevance", "Top Rated"])
    
    if st.button("🚀 Search / Discover") or search_query:
        if search_query or st.session_state.get('search_trigger', False) or selected_types:
            st.session_state.search_page = 1
            st.session_state.search_results = []
            with st.spinner("Fetching..."):
                if not selected_types: selected_types = ["Movies"]
                results = search_unified(search_query, selected_types, selected_genres, sort_option, page=1)
                st.session_state.search_results = results
            if not st.session_state.search_results: st.warning("No results found.")

    if st.session_state.search_results:
        lib_map = get_library_data() # Use Fast Cache
        
        for idx, item in enumerate(st.session_state.search_results):
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    if item['Image']: st.image(item['Image'], use_container_width=True)
                with col_txt:
                    st.subheader(item['Title'])
                    st.caption(f"**{item['Type']}** | ⭐ {item['Rating']} | {item['Country']}")
                    st.caption(f"🏷️ {item['Genres']}")
                    
                    with st.popover("📜 Read Overview"):
                        st.write(item['Overview'])
                        if item['Type'] in ["Manga", "Manhwa", "Manhua", "Novel"] and item.get('Links'):
                            st.write("**Official Sources:**")
                            for link in item['Links']:
                                st.link_button(f"🔗 {link['site']}", link['url'])

                    # "ADDED" LOGIC & DIRECT MANAGE
                    is_added = item['Title'].strip() in lib_map
                    
                    if is_added:
                        existing_data = lib_map[item['Title'].strip()]
                        st.success("✅ In Collection")
                        
                        with st.expander("Update Status", expanded=False):
                            is_read = item['Type'] in ["Book", "Novel", "Manga", "Manhwa", "Manhua"]
                            opts = ["Plan to Read", "Reading", "Completed", "Dropped"] if is_read else ["Plan to Watch", "Watching", "Completed", "Dropped"]
                            
                            curr_status = existing_data.get('Status', opts[0])
                            if curr_status not in opts: curr_status = opts[0]
                            
                            try: curr_sea = int(existing_data.get('Current_Season', 1))
                            except: curr_sea = 1
                            try: curr_ep = int(existing_data.get('Current_Ep', 0))
                            except: curr_ep = 0

                            new_s = st.selectbox("Status", opts, index=opts.index(curr_status), key=f"s_search_{idx}")
                            
                            if item['Type'] != "Movies":
                                c_s, c_e = st.columns(2)
                                lbl1 = "Vol." if is_read else "S"
                                lbl2 = "Ch." if is_read else "E"
                                ns = c_s.number_input(lbl1, value=curr_sea, min_value=1, key=f"ns_search_{idx}")
                                ne = c_e.number_input(lbl2, value=curr_ep, min_value=0, key=f"ne_search_{idx}")
                            else:
                                ns, ne = 1, 0
                            
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.button("Save", key=f"save_search_{idx}"):
                                    update_status_in_sheet(item['Title'], new_s, ns, ne)
                                    st.rerun()
                            with c2:
                                if st.button("Delete", key=f"del_search_{idx}"):
                                    delete_from_sheet(item['Title'])
                                    st.rerun()

                    else:
                        if st.button(f"➕ Add Library", key=f"add_{idx}"):
                            with st.spinner("Adding..."):
                                success = fetch_details_and_add(item)
                                if success: st.rerun()
            st.divider()
        if st.button("⬇️ Load More Results"):
            st.session_state.search_page += 1
            with st.spinner(f"Loading Page {st.session_state.search_page}..."):
                new = search_unified(search_query, selected_types, selected_genres, sort_option, page=st.session_state.search_page)
                st.session_state.search_results.extend(new)
                st.rerun()

# --- GALLERY TAB ---
elif tab == "My Gallery":
    
    col_h, col_c = st.columns([3, 1])
    with col_h: st.subheader("My Library")
    with col_c:
        try: def_ix = list(tmdb_countries.keys()).index("India")
        except: def_ix = 0
        stream_country = st.selectbox("Streaming Country", list(tmdb_countries.keys()), index=def_ix)
        country_code = tmdb_countries[stream_country]

    sheet = get_google_sheet()
    
    if sheet:
        # Load Cache to ensure sync
        get_library_data()
        
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
                c1, c2, c3 = st.columns(3)
                with c1: filter_text = st.text_input("Search Title")
                with c2: filter_type = st.multiselect("Filter Type", df['Type'].unique())
                with c3: filter_status = st.multiselect("Status", ["Plan to Watch", "Plan to Read", "Watching", "Reading", "Completed", "Dropped"])
            
            if filter_text: df = df[df['Title'].astype(str).str.contains(filter_text, case=False, na=False)]
            if filter_type: df = df[df['Type'].isin(filter_type)]
            if filter_status: df = df[df['Status'].isin(filter_status)]

            st.divider()

            # SINGLE GRID VIEW
            if HAS_SORTABLES and not df.empty:
                with st.expander("🔄 Reorder List", expanded=False):
                    st.caption("Drag items to change order, then click Save.")
                    subset_titles = df['Title'].tolist()
                    sorted_titles = sort_items(subset_titles, key="sort_all")
                    if sorted_titles != subset_titles:
                        if st.button("💾 Save Order"):
                            original_indices = df.index.tolist()
                            title_map = {}
                            for idx in original_indices:
                                title_val = df.loc[idx, 'Title']
                                if title_val not in title_map: title_map[title_val] = []
                                title_map[title_val].append(idx)
                            new_order_indices = []
                            for title in sorted_titles:
                                if title in title_map and title_map[title]:
                                    new_order_indices.append(title_map[title].pop(0))
                            new_df = df.iloc[new_order_indices].reset_index(drop=True)
                            bulk_update_order(new_df)

            if not df.empty:
                cols_per_row = 5
                rows = [df.iloc[i:i + cols_per_row] for i in range(0, len(df), cols_per_row)]
                
                for row_chunk in rows:
                    cols = st.columns(cols_per_row)
                    for col, (index, item) in zip(cols, row_chunk.iterrows()):
                        with col:
                            img = item.get('Image', '')
                            if not img.startswith("http"): img = "https://via.placeholder.com/300x450?text=No+Image"
                            st.image(img, use_container_width=True)
                            
                            st.markdown(f"**{item['Title']}**")
                            unique_key = f"gal_{index}"
                            
                            with st.popover("📜 Overview"):
                                # --- 1. MEDIA DETAILS ---
                                tmdb_id = item.get('ID')
                                m_type = 'movie' if item['Type'] == "Movies" else 'tv'
                                if not tmdb_id and item['Type'] in ["Movies", "Web Series", "K-Drama"]: 
                                    tmdb_id = recover_tmdb_id(item['Title'], m_type)

                                # --- 2. TRAILER LOGIC ---
                                trailer_url = None
                                if item['Type'] in ["Anime", "Donghua"]:
                                     ad = fetch_anilist_data_single(item['Title'], "ANIME")
                                     if ad and 'trailer' in ad and ad['trailer'] and ad['trailer']['site'] == 'youtube':
                                         trailer_url = f"https://www.youtube.com/watch?v={ad['trailer']['id']}"
                                elif item['Type'] in ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama"]:
                                     trailer_url = get_tmdb_trailer(tmdb_id, m_type)

                                if trailer_url:
                                    st.caption("🎬 Trailer")
                                    st.video(trailer_url)

                                st.write(f"**Status:** {item['Status']}")
                                st.write(f"**Rating:** {item['Rating']}")
                                st.caption(item['Overview'])
                                st.divider()
                                
                                # --- 4. LINKS / STREAMS ---
                                is_book = item['Type'] in ["Book", "Novel"]
                                is_comic = item['Type'] in ["Manga", "Manhwa", "Manhua"]
                                
                                if is_book:
                                    st.caption("📖 Reading Options")
                                    st.link_button("📘 Read on Google Books", f"https://www.google.com/search?tbm=bks&q={item['Title']}")
                                elif is_comic:
                                    st.caption("📖 Reading Options")
                                    st.link_button("📖 Read on Comix.to", f"https://www.google.com/search?q=site:comix.to+{item['Title']}")
                                    live_data = fetch_anilist_data_single(item['Title'], "MANGA")
                                    if live_data and live_data.get('externalLinks'):
                                        st.write("**Official Sources:**")
                                        for l in live_data['externalLinks']:
                                            st.link_button(f"🔗 {l['site']}", l['url'])
                                else:
                                    st.caption(f"📺 Watch in {stream_country}")
                                    if item['Type'] == "Anime":
                                        st.link_button("🟠 Search Crunchyroll", f"https://www.crunchyroll.com/search?q={item['Title']}")
                                    elif item['Type'] in ["K-Drama", "C-Drama", "Thai Drama"]:
                                        st.link_button("💙 Watch on Viki", f"https://www.viki.com/search?q={urllib.parse.quote(item['Title'])}")
                                    
                                    provs = get_streaming_info(tmdb_id, m_type, country_code)
                                    has_streams = False
                                    if provs:
                                        if 'flatrate' in provs:
                                            st.write("**Streaming:**")
                                            for p in provs['flatrate']:
                                                lnk = get_provider_link(p['provider_name'], item['Title'])
                                                st.markdown(f"- [{p['provider_name']}]({lnk})")
                                            has_streams = True
                                        if 'rent' in provs:
                                            st.write("**Rent:**")
                                            for p in provs['rent']:
                                                lnk = get_provider_link(p['provider_name'], item['Title'])
                                                st.markdown(f"- [{p['provider_name']}]({lnk})")
                                            has_streams = True
                                        if 'buy' in provs:
                                            st.write("**Buy:**")
                                            for p in provs['buy']:
                                                lnk = get_provider_link(p['provider_name'], item['Title'])
                                                st.markdown(f"- [{p['provider_name']}]({lnk})")
                                            has_streams = True
                                    if not has_streams: st.caption("No official streams found.")

                            # --- 5. MANAGEMENT ---
                            with st.expander("⚙️ Manage"):
                                is_read = is_book or is_comic
                                opts = ["Plan to Read", "Reading", "Completed", "Dropped"] if is_read else ["Plan to Watch", "Watching", "Completed", "Dropped"]
                                curr = item.get('Status', opts[0])
                                if curr not in opts: curr = opts[0]
                                new_s = st.selectbox("Status", opts, key=f"st_{unique_key}", index=opts.index(curr))
                                
                                if is_book or item['Type'] == "Novel":
                                    col_s, col_e = st.columns(2)
                                    try: c_pg = int(item.get('Current_Season', 0)) 
                                    except: c_pg = 0
                                    with col_s: st.caption("Pages/Chs")
                                    with col_e: new_sea = st.number_input("Count", value=c_pg, key=f"s_{unique_key}")
                                    new_ep = 0
                                    st.caption(f"Total: {item.get('Total_Eps', '?')}")
                                
                                elif item['Type'] != "Movies":
                                    try: c_sea = int(item.get('Current_Season', 1))
                                    except: c_sea = 1
                                    try: c_ep = int(item.get('Current_Ep', 0))
                                    except: c_ep = 0
                                    
                                    if is_comic: sea_lbl, ep_lbl = "Vol.", "Ch."
                                    else: sea_lbl, ep_lbl = "S", "E"

                                    total_str = item.get('Total_Eps', '?')
                                    if not is_comic and tmdb_id:
                                         si = get_season_details(tmdb_id, c_sea)
                                         if si: total_str = si['episode_count']
                                    
                                    col_s, col_e = st.columns(2)
                                    with col_s: new_sea = st.number_input(sea_lbl, min_value=1, value=c_sea, key=f"s_{unique_key}")
                                    with col_e: 
                                        lbl = f"{ep_lbl} ({total_str})" if total_str != "?" else ep_lbl
                                        new_ep = st.number_input(lbl, min_value=0, value=c_ep, key=f"e_{unique_key}")
                                else: new_sea, new_ep = 1, 0

                                c_sv, c_dl = st.columns(2)
                                with c_sv: 
                                    if st.button("Save", key=f"sv_{unique_key}"):
                                        update_status_in_sheet(item['Title'], new_s, new_sea, new_ep)
                                        st.rerun()
                                with c_dl:
                                    if st.button("Del", key=f"dl_{unique_key}"):
                                        delete_from_sheet(item['Title'])
                                        st.rerun()
            else:
                st.info("No items found matching filters.")
    else:
        st.error("Connection Failed. Check Secrets.")
