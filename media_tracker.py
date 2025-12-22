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
    TMDB_API_KEY = "YOUR_TMDB_API_KEY_HERE"

GOOGLE_SHEET_NAME = 'My Media Tracker'

# --- SETUP APIS ---
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = 'en'
# We need two image sizes: one for posters (w400) and one for header backdrops (w780)
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

# --- SEARCH LOGIC ---
def search_unified(query, selected_types):
    results_data = []
    
    # 1. TMDB SEARCH
    live_action = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action):
        search = Search()
        if "Movies" in selected_types:
            for r in search.movies(query): process_tmdb(r, "Movie", results_data, selected_types)
        if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
            for r in search.tv_shows(query): process_tmdb(r, "TV", results_data, selected_types)

    # 2. ANILIST SEARCH
    asian_comics = ["Anime", "Manga", "Manhwa", "Manhua"]
    if any(t in selected_types for t in asian_comics):
        modes = []
        if "Anime" in selected_types: modes.append("ANIME")
        if any(t in ["Manga", "Manhwa", "Manhua"] for t in selected_types): modes.append("MANGA")
        for m in set(modes):
            for r in fetch_anilist(query, m): process_anilist(r, m, results_data, selected_types)

    return results_data

def process_tmdb(res, media_kind, results_list, selected_types):
    origin = getattr(res, 'original_language', 'en')
    detected_type = "Movies" if media_kind == "Movie" else "Western Series"
    country_disp = "Western"
    
    if media_kind == "TV":
        if origin == 'ko': detected_type, country_disp = "K-Drama", "South Korea"
        elif origin == 'zh': detected_type, country_disp = "C-Drama", "China"
        elif origin == 'th': detected_type, country_disp = "Thai Drama", "Thailand"
        elif origin == 'ja': detected_type, country_disp = "J-Drama", "Japan"
    
    if detected_type not in selected_types: return

    # Get Details
    poster = getattr(res, 'poster_path', None)
    backdrop = getattr(res, 'backdrop_path', None)
    
    img_url = f"{tmdb_poster_base}{poster}" if poster else ""
    backdrop_url = f"{tmdb_backdrop_base}{backdrop}" if backdrop else ""
    
    # Rating (TMDB is out of 10)
    rating = getattr(res, 'vote_average', 0)
    overview = getattr(res, 'overview', 'No overview available.')
    
    genre_ids = getattr(res, 'genre_ids', [])
    res_genres = [tmdb_genres_map.get(gid, "Unknown") for gid in genre_ids]

    results_list.append({
        "Title": getattr(res, 'title', getattr(res, 'name', 'Unknown')),
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res_genres),
        "Image": img_url,
        "Overview": overview,
        "Rating": f"{rating}/10",
        "Backdrop": backdrop_url
    })

def fetch_anilist(query, type_):
    q = '''query ($s: String, $t: MediaType) { Page(perPage: 10) { media(search: $s, type: $t) { title { romaji english } coverImage { large } bannerImage genres countryOfOrigin type description averageScore } } }'''
    try:
        r = requests.post('https://graphql.anilist.co', json={'query': q, 'variables': {'s': query, 't': type_}})
        return r.json()['data']['Page']['media']
    except: return []

def process_anilist(res, api_type, results_list, selected_types):
    origin = res['countryOfOrigin']
    detected_type = "Anime"
    country_disp = "Japan"
    
    if api_type == "MANGA":
        if origin == 'KR': detected_type, country_disp = "Manhwa", "South Korea"
        elif origin == 'CN': detected_type, country_disp = "Manhua", "China"
        else: detected_type = "Manga"
    
    if detected_type not in selected_types: return

    # Clean HTML tags from Anilist description
    import re
    raw_desc = res.get('description', '')
    clean_desc = re.sub('<[^<]+?>', '', raw_desc) if raw_desc else "No description."

    # Rating (Anilist is out of 100, convert to 10 for consistency)
    score = res.get('averageScore')
    rating_disp = f"{score/10}/10" if score else "N/A"

    results_list.append({
        "Title": res['title']['english'] if res['title']['english'] else res['title']['romaji'],
        "Type": detected_type,
        "Country": country_disp,
        "Genres": ", ".join(res['genres']),
        "Image": res['coverImage']['large'],
        "Overview": clean_desc,
        "Rating": rating_disp,
        "Backdrop": res.get('bannerImage', '') # AniList banner
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
        with st.spinner("Searching..."):
            results = search_unified(search_query, selected_types)
        
        if not results: st.warning("No results found.")
        
        for item in results:
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    if item['Image']: st.image(item['Image'], use_container_width=True)
                with col_txt:
                    st.subheader(item['Title'])
                    st.markdown(f"**{item['Type']}** | ⭐ {item['Rating']}")
                    st.caption(f"{item['Country']} • {item['Genres']}")
                    st.write(item['Overview'][:200] + "..." if len(item['Overview']) > 200 else item['Overview'])
                    
                    if st.button(f"➕ Add to Library", key=f"add_{item['Title']}_{item['Type']}"):
                        if sheet:
                            sheet.append_row([
                                item['Title'],
                                item['Type'],
                                item['Country'],
                                "Plan to Watch",
                                item['Genres'],
                                item['Image'],
                                item['Overview'],   # Col G
                                item['Rating'],     # Col H
                                item['Backdrop']    # Col I
                            ])
                            st.toast(f"Saved: {item['Title']}")
            st.divider()

# --- TAB 2: MY GALLERY (UPDATED WITH DETAILS) ---
elif tab == "My Gallery":
    st.header("My Collection")
    
    if sheet:
        data = sheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
            
            # Filters
            with st.expander("🔎 Filter Collection"):
                c1, c2, c3 = st.columns([2, 1, 1])
                local_search = c1.text_input("Title Search")
                filter_type = c2.multiselect("Type", df['Type'].unique() if 'Type' in df.columns else [])
                filter_status = c3.multiselect("Status", df['Status'].unique() if 'Status' in df.columns else [])
            
            # Apply Filters
            if local_search: df = df[df['Title'].astype(str).str.contains(local_search, case=False, na=False)]
            if filter_type: df = df[df['Type'].isin(filter_type)]
            if filter_status: df = df[df['Status'].isin(filter_status)]

            st.divider()

            # RENDER GRID WITH DETAILS
            if not df.empty:
                cols_per_row = 4
                rows = [df.iloc[i:i + cols_per_row] for i in range(0, len(df), cols_per_row)]
                
                for row in rows:
                    cols = st.columns(cols_per_row)
                    for idx, (_, item) in enumerate(row.iterrows()):
                        with cols[idx]:
                            # 1. Poster Image
                            img_url = item.get('Image')
                            if not img_url: img_url = "https://via.placeholder.com/200x300?text=No+Image"
                            st.image(img_url, use_container_width=True)
                            
                            # 2. Title & Status
                            st.markdown(f"**{item['Title']}**")
                            
                            # 3. "View Details" Expander (The Interactive Part)
                            with st.expander("🔽 View Details"):
                                # HEADER IMAGE (Backdrop)
                                backdrop = item.get('Backdrop')
                                if backdrop:
                                    st.image(backdrop, use_container_width=True)
                                
                                # RATING & INFO
                                st.markdown(f"⭐ **Rating:** {item.get('Rating', 'N/A')}")
                                st.markdown(f"📍 **Origin:** {item.get('Country')}")
                                st.caption(f"🎭 {item.get('Genres')}")
                                
                                # OVERVIEW
                                st.markdown("**Plot:**")
                                st.write(item.get('Overview', 'No overview saved.'))
                                
                                # UPDATE STATUS (Optional Bonus)
                                current_status = item.get('Status', 'Plan to Watch')
                                st.markdown(f"**Status:** `{current_status}`")

            else:
                st.info("No matches found.")
        else:
            st.info("Library empty.")

# --- TAB 3: DECIDER ---
elif tab == "Decider":
    st.header("🎲 Random Picker")
    if st.button("Pick Something!"):
        if sheet:
            import random
            data = sheet.get_all_records()
            if data:
                choice = random.choice(data)
                
                # Show the full experience for the random pick too
                if choice.get('Backdrop'):
                    st.image(choice['Backdrop'], use_container_width=True)
                
                c1, c2 = st.columns([1, 2])
                with c1:
                    if choice.get('Image'): st.image(choice['Image'])
                with c2:
                    st.balloons()
                    st.success(f"Watch This: **{choice['Title']}**")
                    st.markdown(f"⭐ **{choice.get('Rating', 'N/A')}**")
                    st.write(choice.get('Overview', ''))
