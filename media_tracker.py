import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Genre, Discover
import requests
import time
import urllib.parse

# --- TRY IMPORTING SORTABLES ---
try:
    from streamlit_sortables import sort_items
    HAS_SORTABLES = True
except ImportError:
    HAS_SORTABLES = False

# --- PAGE CONFIG ---
st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="🎬")
st.title("🎬 Ultimate Media Tracker")

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

# --- GENRE MAP ---
GENRE_MAP = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Sci-Fi": 878, "TV Movie": 10770,
    "Thriller": 53, "War": 10752, "Western": 37,
    "Action & Adventure": 10759, "Sci-Fi & Fantasy": 10765, "War & Politics": 10768
}
ID_TO_GENRE = {v: k for k, v in GENRE_MAP.items()}

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

# --- DATABASE ACTIONS ---
def fetch_details_and_add(item):
    sheet = get_google_sheet()
    if not sheet: return False
    
    total_seasons = 1
    total_eps = item['Total_Eps']
    media_id = item.get('ID') 
    
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

def bulk_update_order(new_df):
    """Updates the entire sheet with the new order"""
    sheet = get_google_sheet()
    if not sheet: return
    
    # Keep header
    header = sheet.row_values(1)
    
    # Prepare data (convert DF back to list of lists)
    # Ensure all columns are strings for safety
    data_to_upload = new_df.astype(str).values.tolist()
    
    # Clear and Update
    sheet.clear()
    sheet.append_row(header)
    sheet.append_rows(data_to_upload)
    st.toast("✅ Order Saved!")
    time.sleep(1)
    st.rerun()

# --- HELPERS ---
def generate_provider_link(provider_name, title):
    q = urllib.parse.quote(title)
    p = provider_name.lower()
    if 'netflix' in p: return f"https://www.netflix.com/search?q={q}"
    if 'disney' in p: return f"https://www.disneyplus.com/search?q={q}"
    if 'amazon' in p or 'prime' in p: return f"https://www.amazon.com/s?k={q}&i=instant-video"
    if 'crunchyroll' in p: return f"https://www.crunchyroll.com/search?q={q}"
    if 'hotstar' in p: return f"https://www.hotstar.com/in/search?q={q}"
    if 'jiocinema' in p: return f"https://www.jiocinema.com/search?q={q}"
    if 'viki' in p: return f"https://www.viki.com/search?q={q}"
    return f"https://www.google.com/search?q=watch+{q}+on+{urllib.parse.quote(provider_name)}"

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
        else: return "No Info"
    except: return None

def fetch_anime_details(title):
    query = '''
    query ($s: String) {
        Page(perPage: 1) {
            media(search: $s, type: ANIME) {
                trailer { id site }
                externalLinks { site url }
            }
        }
    }
    '''
    try:
        r = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': {'s': title}})
        data = r.json()
        if data['data']['Page']['media']: return data['data']['Page']['media'][0]
    except: pass
    return {}

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

# --- SEARCH ENGINE ---
def search_unified(query, selected_types, selected_genres, sort_option, page=1):
    results_data = []
    
    live_action = ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action):
        lang = None
        if "K-Drama" in selected_types and len(selected_types) == 1: lang = "ko"
        elif "C-Drama" in selected_types and len(selected_types) == 1: lang = "zh"
        elif "Thai Drama" in selected_types and len(selected_types) == 1: lang = "th"

        g_ids = ""
        if selected_genres:
            ids = [str(GENRE_MAP.get(g)) for g in selected_genres if GENRE_MAP.get(g)]
            g_ids = "|".join(ids)

        tmdb_sort = 'popularity.desc'
        if sort_option == 'Top Rated': tmdb_sort = 'vote_average.desc'

        if not query:
            discover = Discover()
            kwargs = {'sort_by': tmdb_sort, 'with_genres': g_ids, 'page': page, 'vote_count.gte': 10}
            if lang: kwargs['with_original_language'] = lang

            if "Movies" in selected_types:
                try: 
                    for r in discover.discover_movies(kwargs): process_tmdb(r, "Movie", results_data, selected_types, selected_genres)
                except: pass
            
            if any(t in ["Web Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                try:
                    for r in discover.discover_tv_shows(kwargs): process_tmdb(r, "TV", results_data, selected_types, selected_genres)
                except: pass
        else:
            search = Search()
            current_results = []
            if "Movies" in selected_types:
                try:
                    for r in search.movies(query, page=page): process_tmdb(r, "Movie", current_results, selected_types, selected_genres)
                except: pass
            if any(t in ["Web Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                try:
                    for r in search.tv_shows(query, page=page): process_tmdb(r, "TV", current_results, selected_types, selected_genres)
                except: pass
            
            if sort_option == "Top Rated":
                current_results.sort(key=lambda x: float(x['Rating'].split('/')[0]), reverse=True)
            results_data.extend(current_results)

    # AniList Search
    asian_comics = ["Anime", "Manga", "Manhwa", "Manhua"]
    if any(t in selected_types for t in asian_comics):
        modes = []
        if "Anime" in selected_types: modes.append("ANIME")
        if any(t in ["Manga", "Manhwa", "Manhua"] for t in selected_types): modes.append("MANGA")
        
        for m in set(modes):
            country_filter = None
            if m == "MANGA":
                if "Manhwa" in selected_types and "Manga" not in selected_types and "Manhua" not in selected_types: country_filter = "KR" 
                elif "Manhua" in selected_types and "Manga" not in selected_types and "Manhwa" not in selected_types: country_filter = "CN" 
                elif "Manga" in selected_types and "Manhwa" not in selected_types and "Manhua" not in selected_types: country_filter = "JP" 

            q_val = query if query else None 
            for r in fetch_anilist(q_val, m, selected_genres, sort_option, page, country_filter): 
                process_anilist(r, m, results_data, selected_types, selected_genres)

    return results_data

def process_tmdb(res, media_kind, results_list, selected_types, selected_genres):
    origin = getattr(res, 'original_language', 'en')
    detected_type = "Movies" if media_kind == "Movie" else "Web Series"
    
    if media_kind == "TV":
        if origin == 'ko': detected_type = "K-Drama"
        elif origin == 'zh': detected_type = "C-Drama"
        elif origin == 'th': detected_type = "Thai Drama"
        elif origin == 'ja': detected_type = "Anime"
        elif origin == 'en': detected_type = "Web Series"
        else: detected_type = "Web Series"
    
    if detected_type not in selected_types: return
    
    rating = getattr(res, 'vote_average', 0)
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
        "Rating": f"{rating}/10",
        "Backdrop": f"{tmdb_backdrop_base}{getattr(res, 'backdrop_path', '')}",
        "Total_Eps": "?", 
        "ID": getattr(res, 'id', None)
    })

def fetch_anilist(query, type_, genres=None, sort_opt="Popularity", page=1, country=None):
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

    query_str = f'''
    query ({', '.join(query_args)}) {{ 
      Page(page: $p, perPage: 15) {{ 
        media({', '.join(media_args)}) {{ 
          title {{ romaji english }} coverImage {{ large }} bannerImage genres countryOfOrigin type description averageScore episodes chapters 
          externalLinks {{ site url }}
        }} 
      }} 
    }}'''
    try:
        r = requests.post('https://graphql.anilist.co', json={'query': query_str, 'variables': variables})
        if r.status_code == 200: return r.json()['data']['Page']['media']
        else: return []
    except: return []

def process_anilist(res, api_type, results_list, selected_types, selected_genres):
    origin = res.get('countryOfOrigin', 'JP')
    detected_type = "Anime"
    total = res.get('episodes') if api_type == "ANIME" else res.get('chapters')
    if not total: total = "?"

    if api_type == "MANGA":
        if origin == 'KR': detected_type = "Manhwa"
        elif origin == 'CN': detected_type = "Manhua"
        else: detected_type = "Manga"
    
    if detected_type not in selected_types: return
    
    score = res.get('averageScore', 0)
    rating_val = score / 10 if score else 0
    res_genres = res.get('genres', [])
    if selected_genres:
        if not any(g in res_genres for g in selected_genres): return

    import re
    raw = res.get('description', '')
    clean = re.sub('<[^<]+?>', '', raw) if raw else "No description."

    results_list.append({
        "Title": res['title']['english'] if res['title']['english'] else res['title']['romaji'],
        "Type": detected_type,
        "Country": "Japan" if origin == "JP" else origin,
        "Genres": ", ".join(res_genres),
        "Image": res.get('coverImage', {}).get('large', ''),
        "Overview": clean,
        "Rating": f"{rating_val}/10",
        "Backdrop": res.get('bannerImage', ''),
        "Total_Eps": total,
        "ID": None,
        "Links": res.get('externalLinks', [])
    })

# --- UI START ---
if "refresh_key" not in st.session_state: st.session_state.refresh_key = 0
if 'search_results' not in st.session_state: st.session_state.search_results = []
if 'search_page' not in st.session_state: st.session_state.search_page = 1

tab = st.sidebar.radio("Menu", ["My Gallery", "Search & Add"], key="main_nav")
GENRES = list(GENRE_MAP.keys())

# --- SEARCH TAB ---
if tab == "Search & Add":
    st.subheader("Global Database Search")
    with st.expander("🔎 Filter Options", expanded=True):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        with c1: search_query = st.text_input("Title (Optional)")
        with c2: selected_types = st.multiselect("Type", ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama", "Anime", "Manga", "Manhwa", "Manhua"], default=["Movies"])
        with c3: selected_genres = st.multiselect("Genre", GENRES)
        with c4: sort_option = st.selectbox("Sort By", ["Popularity", "Relevance", "Top Rated"])
        
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
                    if st.button(f"➕ Add Library", key=f"add_{idx}"):
                        with st.spinner("Fetching..."):
                            success = fetch_details_and_add(item)
                        if success: st.toast(f"✅ Saved: {item['Title']}")
                        else: st.toast("❌ Error saving.")
            st.divider()
        if st.button("⬇️ Load More Results"):
            st.session_state.search_page += 1
            with st.spinner(f"Loading Page {st.session_state.search_page}..."):
                new = search_unified(search_query, selected_types, selected_genres, sort_option, page=st.session_state.search_page)
                st.session_state.search_results.extend(new)
                st.rerun()

# --- GALLERY TAB ---
elif tab == "My Gallery":
    st.subheader("My Library")
    
    # ---------------------------
    #  DRAG & DROP REORDER AREA
    # ---------------------------
    sheet = get_google_sheet()
    
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
            
            # --- SORTABLE COMPONENT ---
            if HAS_SORTABLES:
                with st.expander("≡ Drag & Drop Reorder", expanded=False):
                    st.caption("Drag items to sort, then click 'Save Order'.")
                    titles = df['Title'].tolist()
                    sorted_titles = sort_items(titles)
                    
                    if st.button("💾 Save New Order"):
                        # Reorder DF based on new title list
                        new_df = df.set_index('Title').loc[sorted_titles].reset_index()
                        bulk_update_order(new_df)
            else:
                if st.button("🔄 Refresh"): st.cache_data.clear()

            with st.expander("Filter Collection", expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    def_idx = list(tmdb_countries.keys()).index("India") if "India" in tmdb_countries else 0
                    stream_country = st.selectbox("Select Country", list(tmdb_countries.keys()), index=def_idx)
                    country_code = tmdb_countries[stream_country]
                with c2: filter_text = st.text_input("Search Title")
                with c3: filter_type = st.multiselect("Filter Type", df['Type'].unique())
                with c4: filter_status = st.multiselect("Status", ["Plan to Watch", "Watching", "Completed"])
            
            if not df.empty:
                if filter_text: df = df[df['Title'].astype(str).str.contains(filter_text, case=False, na=False)]
                if filter_type: df = df[df['Type'].isin(filter_type)]
                if filter_status: df = df[df['Status'].isin(filter_status)]

            st.divider()
            
            if not df.empty:
                cols_per_row = 5
                rows = [df.iloc[i:i + cols_per_row] for i in range(0, len(df), cols_per_row)]
                for row_chunk in rows:
                    cols = st.columns(cols_per_row)
                    for col, (index, item) in zip(cols, row_chunk.iterrows()):
                        with col:
                            img = item.get('Image', '')
                            if not img.startswith("http"): img = "https://via.placeholder.com/200x300?text=No+Image"
                            st.image(img, use_container_width=True)
                            
                            st.markdown(f"**{item['Title']}**")
                            unique_key = f"{index}"
                            
                            with st.popover("📜 Overview & Streaming"):
                                tmdb_id = item.get('ID')
                                m_type = 'movie' if item['Type'] == "Movies" else 'tv'
                                if not tmdb_id and item['Type'] not in ["Anime", "Manga", "Manhwa", "Manhua"]:
                                    tmdb_id = recover_tmdb_id(item['Title'], m_type)
                                
                                # Anime/Manga Links
                                if item['Type'] == "Anime":
                                    details = fetch_anime_details(item['Title'])
                                    if 'trailer' in details and details['trailer'] and details['trailer']['site'] == 'youtube':
                                        st.video(f"https://www.youtube.com/watch?v={details['trailer']['id']}")
                                    
                                    # Anikai Button
                                    anikai_url = f"https://www.google.com/search?q=site:anikai.to+{item['Title'].replace(' ', '+')}"
                                    st.link_button("📺 Watch on Anikai.to", anikai_url)

                                    st.write("**Official Sources:**")
                                    links = details.get('externalLinks', [])
                                    found_cr = False
                                    if links:
                                        for l in links:
                                            if 'crunchyroll' in l['site'].lower():
                                                st.link_button(f"🟠 {l['site']}", l['url']); found_cr = True
                                            else: st.link_button(f"🔗 {l['site']}", l['url'])
                                    if not found_cr:
                                        st.link_button("🔍 Search Google", f"https://www.google.com/search?q=watch+{item['Title']}+anime")
                                
                                elif item['Type'] in ["Manga", "Manhwa", "Manhua"]:
                                    st.link_button("📖 Read (Comix.to)", f"https://www.google.com/search?q=site:comix.to+{item['Title']}")
                                
                                # TMDB Streaming
                                elif item['Type'] in ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama"]:
                                    trailer = get_tmdb_trailer(tmdb_id, m_type)
                                    if trailer: st.video(trailer)
                                    
                                    if item['Type'] in ["K-Drama", "C-Drama", "Thai Drama"]:
                                        st.link_button("💙 Search Viki", f"https://www.viki.com/search?q={urllib.parse.quote(item['Title'])}")

                                    if st.button(f"📺 Stream in {stream_country}?", key=f"stm_{unique_key}"):
                                        provs = get_streaming_info(tmdb_id, m_type, country_code)
                                        if not provs or provs == "No Info":
                                            st.warning("Not available.")
                                            st.link_button("🔍 Search Google", f"https://www.google.com/search?q=watch+{item['Title']}+online")
                                        else:
                                            if 'flatrate' in provs:
                                                st.write("🟢 **Stream:**")
                                                for p in provs['flatrate']: 
                                                    lnk = generate_provider_link(p['provider_name'], item['Title'])
                                                    st.markdown(f"- [{p['provider_name']}]({lnk})")
                                            if 'rent' in provs:
                                                st.write("🟡 **Rent:**")
                                                for p in provs['rent']: st.write(f"- {p['provider_name']}")
                                
                                st.write(f"**Rating:** {item.get('Rating')}")
                                st.write(item.get('Overview'))

                            with st.expander("⚙️ Manage"):
                                opts = ["Plan to Watch", "Watching", "Completed", "Dropped"]
                                curr = item.get('Status', 'Plan to Watch')
                                if curr not in opts: curr = "Plan to Watch"
                                new_s = st.selectbox("Status", opts, key=f"st_{unique_key}", index=opts.index(curr))
                                
                                if item['Type'] != "Movies":
                                    try: c_sea = int(item.get('Current_Season', 1))
                                    except: c_sea = 1
                                    try: c_ep = int(item.get('Current_Ep', 0))
                                    except: c_ep = 0
                                    
                                    if item['Type'] in ["Manga", "Manhwa", "Manhua"]:
                                        sea_label, ep_label = "Vol.", "Ch."
                                    else:
                                        sea_label, ep_label = "S", "E"

                                    col_s, col_e = st.columns(2)
                                    with col_s: new_sea = st.number_input(sea_label, min_value=1, value=c_sea, key=f"s_{unique_key}")
                                    with col_e: new_ep = st.number_input(ep_label, min_value=0, value=c_ep, key=f"e_{unique_key}")
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
            else: st.info("No items.")
        else: st.info("Library Empty.")
    else: st.error("Connection Failed. Check Secrets.")
