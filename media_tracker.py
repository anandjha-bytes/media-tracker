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

# --- CACHE GENRES (ID <-> Name Maps) ---
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
def update_status_in_sheet(title, new_status, new_ep):
    sheet = get_google_sheet()
    if sheet:
        try:
            cell = sheet.find(title)
            if cell:
                sheet.update_cell(cell.row, 4, new_status)
                sheet.update_cell(cell.row, 10, new_ep)
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

# --- SEARCH & DISCOVERY ENGINE ---
def search_unified(query, selected_types, selected_genres, min_rating):
    results_data = []
    
    # 1. TMDB (Movies & TV)
    live_action_types = ["Movies", "Western Series", "K-Drama", "C-Drama", "Thai Drama"]
    if any(t in selected_types for t in live_action_types):
        
        # Prepare Genre IDs for Discovery
        genre_ids_str = ""
        if selected_genres:
            ids = [str(tmdb_name_map.get(g)) for g in selected_genres if tmdb_name_map.get(g)]
            genre_ids_str = ",".join(ids)

        # A. DISCOVERY MODE (No Text)
        if not query:
            discover = Discover()
            kwargs = {
                'sort_by': 'popularity.desc',
                'vote_average.gte': min_rating,
                'with_genres': genre_ids_str
            }
            
            if "Movies" in selected_types:
                for r in discover.discover_movies(kwargs): 
                    process_tmdb(r, "Movie", results_data, selected_types, selected_genres, min_rating)
            
            if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                for r in discover.discover_tv_shows(kwargs): 
                    process_tmdb(r, "TV", results_data, selected_types, selected_genres, min_rating)

        # B. SEARCH MODE (With Text)
        else:
            search = Search()
            if "Movies" in selected_types:
                for r in search.movies(query): 
                    process_tmdb(r, "Movie", results_data, selected_types, selected_genres, min_rating)
            if any(t in ["Western Series", "K-Drama", "C-Drama", "Thai Drama"] for t in selected_types):
                for r in search.tv_shows(query): 
                    process_tmdb(r, "TV", results_data, selected_types, selected_genres, min_rating)

    # 2. ANILIST (Anime/Manga)
    asian_comic_types = ["Anime", "Manga", "Manhwa", "Manhua"]
    if any(t in selected_types for t in asian_comic_types):
        modes = []
        if "Anime" in selected_types: modes.append("ANIME")
        if any(t in ["Manga", "Manhwa", "Manhua"] for t in selected_types): modes.append("MANGA")
        
        for m in set(modes):
            # If no query, we pass None to let GraphQL discover
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
    
    # 1. TYPE FILTER
    if detected_type not in selected_types: return

    # 2. RATING FILTER
    rating = getattr(res, 'vote_average', 0)
    if rating < min_rating: return

    # 3. GENRE FILTER (Double Check)
    genre_ids = getattr(res, 'genre_ids', [])
    res_genres = [tmdb_id_map.get(gid, "Unknown") for gid in genre_ids]
    
    if selected_genres:
        # If discovery mode used IDs, this is just a safety check
        res_genre_str = ", ".join(res_genres).lower()
        if not any(sel.lower() in res_genre_str for sel in selected_genres): return

    poster = getattr(res, 'poster_path', None)
    backdrop = getattr(res, 'backdrop_path', None)
    img_url = f"{tmdb_poster_base}{poster}" if poster else ""
    backdrop_url = f"{tmdb_backdrop_base}{backdrop}" if backdrop else ""
