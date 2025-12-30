import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Genre, Discover
import requests
import time
import urllib.parse

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
                # Create a lookup dict: Title -> Row Data
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
    
    # 1. Check Cache first (Instant check)
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
                # Update Cache
                if 'lib_data' in st.session_state and title in st.session_state.lib_data:
                    del st.session_state.lib_data[title]
                time.sleep(0.5)
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
def fetch_anilist_list(query, type_, genres, sort_opt, page, country=None, format=None):
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
def fetch_open_library(query, genre=None):
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
def process_open_library(items, results_list, detected_type):
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
        
        results_list.append({
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

def process_anilist_results(res_list, results_list, forced_type, selected_genres):
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
        
        results_list.append({
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

# --- SEARCH ENGINE ---
def search_unified(query, selected_types, selected_genres, sort_option, page=1):
    results_data = []
    
    # 1. VISUAL MEDIA
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
        
        def run_tmdb(media_kind, specific_type, lang_filter=None):
            try:
                active_q = query
                if query and specific_type == "K-Drama": active_q = f"{query} Korean"
                elif query and specific_type == "C-Drama": active_q = f"{query} Chinese"
                
                if active_q:
                    if media_kind == "Movie": results = search.movies(active_q, page=page)
                    else: results = search.tv_shows(active_q, page=page)
                else:
                    kwargs = {'sort_by': tmdb_sort, 'page': page, 'vote_count.gte': 5}
                    if g_ids: kwargs['with_genres'] = g_ids
                    if lang_filter: kwargs['with_original_language'] = lang_filter
                    if media_kind == "Movie": results = discover.discover_movies(kwargs)
                    else: results = discover.discover_tv_shows(kwargs)

                for r in results:
                    res_lang = getattr(r, 'original_language', 'en')
                    match = True
                    if not query:
                        if specific_type == "K-Drama" and res_lang != 'ko': match = False
                        elif specific_type == "C-Drama" and res_lang != 'zh': match = False
                        elif specific_type == "Thai Drama" and res_lang != 'th': match = False
                    
                    if match:
                        process_tmdb_result(r, media_kind, results_data, selected_types, selected_genres)
            except: pass

        if "Movies" in selected_types: run_tmdb("Movie", "Movies")
        if "Web Series" in selected_types: run_tmdb("TV", "Web Series")
        if "K-Drama" in selected_types: run_tmdb("TV", "K-Drama", "ko")
        if "C-Drama" in selected_types: run_tmdb("TV", "C-Drama", "zh")
        if "Thai Drama" in selected_types: run_tmdb("TV", "Thai Drama", "th")

    # 2. ANILIST
    if any(t in selected_types for t in ["Anime", "Donghua", "Novel", "Manga", "Manhwa", "Manhua"]):
        if "Anime" in selected_types: 
            r = fetch_anilist_list(query, "ANIME", selected_genres, sort_option, page, country=None)
            process_anilist_results(r, results_data, "Anime", selected_genres)
        if "Donghua" in selected_types:
            r = fetch_anilist_list(query, "ANIME", selected_genres, sort_option, page, country="CN")
            process_anilist_results(r, results_data, "Donghua", selected_genres)
        
        if "Manga" in selected_types:
            r = fetch_anilist_list(query, "MANGA", selected_genres, sort_option, page, country="JP")
            process_anilist_results(r, results_data, "Manga", selected_genres)
        if "Manhwa" in selected_types:
            r = fetch_anilist_list(query, "MANGA", selected_genres, sort_option, page, country="KR")
            process_anilist_results(r, results_data, "Manhwa", selected_genres)
        if "Manhua" in selected_types:
            r = fetch_anilist_list(query, "MANGA", selected_genres, sort_option, page, country="CN")
            process_anilist_results(r, results_data, "Manhua", selected_genres)

        if "Novel" in selected_types:
             r1 = fetch_anilist_list(query, "MANGA", selected_genres, sort_option, page, format="NOVEL")
             process_anilist_results(r1, results_data, "Novel", selected_genres)
             if "Web Novel" in selected_genres:
                 r2 = fetch_anilist_list(query, "MANGA", selected_genres, sort_option, page, country="KR", format="NOVEL")
                 process_anilist_results(r2, results_data, "Novel", selected_genres)
                 r3 = fetch_anilist_list(query, "MANGA", selected_genres, sort_option, page, country="CN", format="NOVEL")
                 process_anilist_results(r3, results_data, "Novel", selected_genres)

    # 3. OPEN LIBRARY
    if "Book" in selected_types or "Novel" in selected_types:
        target_genre = None
        if selected_genres:
            book_genres = [g for g in selected_genres if g in BOOK_GENRES]
            if book_genres: target_genre = book_genres[0]

        if "Novel" in selected_types:
             q_mod = query + " novel" if query else "fantasy novel"
             items = fetch_open_library(q_mod, genre=target_genre)
             process_open_library(items, results_data, "Novel")
             
        if "Book" in selected_types:
             items = fetch_open_library(query, genre=target_genre)
             process_open_library(items, results_data, "Book")

    return results_data

def process_tmdb_result(res, media_kind, results_list, selected_types, selected_genres):
    origin = getattr(res, 'original_language', 'en')
    detected_type = "Web Series" 
    
    if media_kind == "Movie": 
        detected_type = "Movies"
    elif origin == 'ko': detected_type = "K-Drama"
    elif origin == 'zh': detected_type = "C-Drama"
    elif origin == 'th': detected_type = "Thai Drama"
    elif origin == 'ja': detected_type = "Anime"
    elif origin == 'en': detected_type = "Web Series"
    
    if detected_type not in selected_types: return
    
    genre_ids = getattr(res, 'genre_ids', [])
    res_genres = [ID_TO_GENRE.get(gid, "Unknown") for gid in genre_ids]
    if selected_genres:
        if not any(g in res_genres for g in selected_genres): return

    poster = getattr(res, 'poster_path', None)
    img_url = f"{tmdb_poster_base}{poster}" if poster else ""
    
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
        # Standard text_input searches on Enter by default
        search_query = st.text_input("Title (Optional)", on_change=None) 
    with c2: 
        all_types = ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama", "Anime", "Donghua", "Manga", "Manhwa", "Manhua", "Novel", "Book"]
        selected_types = st.multiselect("Type", all_types, default=["Movies"])
    
    current_genres = list(TMDB_GENRE_MAP.keys())
    if "Book" in selected_types or "Novel" in selected_types:
            current_genres = sorted(list(set(current_genres + BOOK_GENRES)))

    with c3: selected_genres = st.multiselect("Genre", current_genres)
    with c4: sort_option = st.selectbox("Sort By", ["Popularity", "Relevance", "Top Rated"])
    
    # Button is still here for explicit clicks, but Enter works on the input above
    if st.button("🚀 Search / Discover") or search_query:
        # Only search if triggered
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
                safe_rows.append(row[:len(HEADERS
