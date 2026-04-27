import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import gspread
import pandas as pd
import requests
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials
from tmdbv3api import TMDb, Movie, TV, Search, Genre, Discover, Collection

# --- PAGE CONFIG ---
st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="📚")

# --- HIDE STREAMLIT HEADER ---
st.markdown("""
    <style>
        .stAppDeployButton {display:none;}
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- HANDLE QUERY PARAMS (For Link-Based Navigation) ---
if "search" in st.query_params:
    st.session_state.search_query_trigger = st.query_params["search"]
    st.query_params.clear()

st.title("🎬 Ultimate Media Tracker")

# --- IMPORT SORTABLES ---
try:
    from streamlit_sortables import sort_items
    HAS_SORTABLES = True
except ImportError:
    HAS_SORTABLES = False

# --- CONFIGURATION ---
try:
    TMDB_API_KEY = st.secrets["tmdb_api_key"]
except Exception:
    st.error("Secrets not found. Please set up .streamlit/secrets.toml")
    st.stop()

GOOGLE_SHEET_NAME = "My Media Tracker"
PLACEHOLDER_IMG = "https://placehold.co/300x450/1a1a2e/ffffff?text=No+Image"

# --- SETUP APIS ---
tmdb = TMDb()
tmdb.api_key = TMDB_API_KEY
tmdb.language = "en"
tmdb_poster_base = "https://image.tmdb.org/t/p/w400"
tmdb_backdrop_base = "https://image.tmdb.org/t/p/w780"

# --- GENRE MAPS ---
TMDB_GENRE_MAP = {
    "Action": 28, "Adventure": 12, "Animation": 16, "Comedy": 35,
    "Crime": 80, "Documentary": 99, "Drama": 18, "Family": 10751,
    "Fantasy": 14, "History": 36, "Horror": 27, "Music": 10402,
    "Mystery": 9648, "Romance": 10749, "Sci-Fi": 878, "TV Movie": 10770,
    "Thriller": 53, "War": 10752, "Western": 37,
    "Action & Adventure": 10759, "Sci-Fi & Fantasy": 10765, "War & Politics": 10768,
}
ID_TO_GENRE = {v: k for k, v in TMDB_GENRE_MAP.items()}

BOOK_GENRES = [
    "Web Novel", "Fiction", "Fantasy", "Sci-Fi", "Mystery", "Thriller", "Romance",
    "History", "Biography", "Business", "Self-Help", "Psychology",
    "Philosophy", "Science", "Technology", "Manga", "Light Novel", "Computers",
    "Horror", "Poetry", "Comics", "Art", "Cooking",
]

# --- REQUIRED SHEET HEADERS ---
# NOTE: Column positions (1-based) must stay in sync with update_status_in_sheet()
# Col:  1       2      3         4        5        6       7          8        9
REQUIRED_HEADERS = [
    "Title", "Type", "Country", "Status", "Genres", "Image", "Overview", "Rating", "Backdrop",
    # Col: 10               11           12           13               14    15       16                17           18
    "Current_Season", "Current_Ep", "Total_Eps", "Total_Seasons", "ID", "Notes", "Personal_Rating", "Date_Added", "Favorite",
]
COL = {h: i + 1 for i, h in enumerate(REQUIRED_HEADERS)}  # header → 1-based column index


# --- CACHE COUNTRIES ---
@st.cache_data
def get_tmdb_countries():
    try:
        url = f"https://api.themoviedb.org/3/configuration/countries?api_key={TMDB_API_KEY}"
        resp = requests.get(url, timeout=10).json()
        countries = {c["english_name"]: c["iso_3166_1"] for c in resp}
        return dict(sorted(countries.items()))
    except Exception:
        return {"United States": "US", "India": "IN", "United Kingdom": "GB"}


tmdb_countries = get_tmdb_countries()


# --- GOOGLE SHEETS CONNECTION ---
@st.cache_resource(ttl=600)
def _get_sheet_client():
    """Create and cache the gspread client (credentials are expensive to build)."""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google Sheets auth error: {e}")
        return None


def get_google_sheet():
    client = _get_sheet_client()
    if not client:
        return None
    try:
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        vals = sheet.get_all_values()
        if not vals:
            sheet.resize(cols=len(REQUIRED_HEADERS))
            sheet.append_row(REQUIRED_HEADERS)
        else:
            existing = vals[0]
            # Append any missing headers at the end (safe for existing sheets)
            missing = [h for h in REQUIRED_HEADERS if h not in existing]
            if missing:
                for h in missing:
                    col_pos = len(existing) + 1
                    sheet.update_cell(1, col_pos, h)
                    existing.append(h)
        return sheet
    except Exception as e:
        st.error(f"Google Sheets connection error: {e}")
        return None


# --- LIBRARY CACHE ---
def get_library_data():
    if "lib_data" not in st.session_state:
        sheet = get_google_sheet()
        if sheet:
            try:
                data = sheet.get_all_records()
                lib_map = {}
                for item in data:
                    t = str(item.get("Title", "")).strip()
                    if t:
                        lib_map[t.lower()] = item  # key is lowercase for case-insensitive lookup
                st.session_state.lib_data = lib_map
            except Exception:
                st.session_state.lib_data = {}
        else:
            st.session_state.lib_data = {}
    return st.session_state.lib_data


def refresh_library():
    st.session_state.pop("lib_data", None)
    get_library_data()


def is_in_library(title: str) -> bool:
    """Case-insensitive membership check."""
    return title.strip().lower() in get_library_data()


def get_from_library(title: str):
    return get_library_data().get(title.strip().lower())


# --- DATABASE ACTIONS ---
def fetch_details_and_add(item):
    sheet = get_google_sheet()
    if not sheet:
        return False

    if is_in_library(item["Title"]):
        st.toast(f"⚠️ '{item['Title']}' is already in your library!")
        return True

    total_seasons = 1
    total_eps = item.get("Total_Eps", "?")
    media_id = item.get("ID")

    if item.get("Type") in ["Web Series", "K-Drama", "C-Drama", "Thai Drama", "Vertical Drama"] and media_id:
        try:
            tv_api = TV()
            details = tv_api.details(media_id)
            total_seasons = getattr(details, "number_of_seasons", 1)
            total_eps = getattr(details, "number_of_episodes", "?")
        except Exception:
            pass

    default_status = "Plan to Watch"
    if item.get("Type") in ["Manga", "Manhwa", "Manhua", "Book", "Novel"]:
        default_status = "Plan to Read"

    today = date.today().isoformat()
    try:
        row_data = [
            item.get("Title", ""), item.get("Type", ""), item.get("Country", ""),
            default_status, item.get("Genres", ""), item.get("Image", ""),
            item.get("Overview", ""), item.get("Rating", ""), item.get("Backdrop", ""),
            1, 0, total_eps, total_seasons, media_id,
            "",   # Notes
            "",   # Personal_Rating
            today,  # Date_Added
            "No",  # Favorite
        ]
        sheet.append_row(row_data)
        st.toast(f"✅ Added: {item.get('Title', '')}")

        new_entry = {h: v for h, v in zip(REQUIRED_HEADERS, row_data)}
        if "lib_data" in st.session_state:
            st.session_state.lib_data[item["Title"].strip().lower()] = new_entry

        return True
    except Exception as e:
        st.error(f"Error adding item: {e}")
        return False


def update_status_in_sheet(title, new_status, new_season, new_ep, notes=None, personal_rating=None, favorite=None):
    sheet = get_google_sheet()
    if not sheet:
        return
    try:
        # Search in column 1 (Title)
        cell = sheet.find(title, in_column=1)
        if cell:
            updates = {
                COL["Status"]: new_status,
                COL["Current_Season"]: new_season,
                COL["Current_Ep"]: new_ep,
            }
            if notes is not None:
                updates[COL["Notes"]] = notes
            if personal_rating is not None:
                updates[COL["Personal_Rating"]] = personal_rating
            if favorite is not None:
                updates[COL["Favorite"]] = favorite

            for col_idx, val in updates.items():
                sheet.update_cell(cell.row, col_idx, val)

            st.toast(f"✅ Saved: {title}")

            # Update local cache
            lib_data = get_library_data()
            key = title.lower()
            if key in lib_data:
                lib_data[key]["Status"] = new_status
                lib_data[key]["Current_Season"] = new_season
                lib_data[key]["Current_Ep"] = new_ep
                if notes is not None:
                    lib_data[key]["Notes"] = notes
                if personal_rating is not None:
                    lib_data[key]["Personal_Rating"] = personal_rating
                if favorite is not None:
                    lib_data[key]["Favorite"] = favorite
    except Exception as e:
        st.error(f"Save error: {e}")


def delete_from_sheet(title):
    sheet = get_google_sheet()
    if not sheet:
        return
    try:
        cell = sheet.find(title, in_column=1)
        if cell:
            sheet.delete_rows(cell.row)
            st.toast(f"🗑️ Deleted: {title}")
            lib_data = get_library_data()
            lib_data.pop(title.lower(), None)
    except Exception as e:
        st.error(f"Delete error: {e}")


def bulk_update_order(new_df):
    sheet = get_google_sheet()
    if not sheet:
        return
    try:
        header = sheet.row_values(1)
        data_to_upload = new_df.astype(str).values.tolist()
        # Use batch update instead of clear+rewrite to reduce data-loss window
        all_rows = [header] + data_to_upload
        sheet.update(f"A1", all_rows)
        st.toast("✅ Order Saved!")
        refresh_library()
        time.sleep(0.5)
        st.rerun()
    except Exception as e:
        st.error(f"Order save error: {e}")


# --- HELPERS ---
def recover_tmdb_id(title, media_type):
    search = Search()
    try:
        if media_type == "movie":
            results = search.movies(title)
        else:
            results = search.tv_shows(title)
        if results:
            return results[0].id
    except Exception:
        return None
    return None


def get_streaming_info(tmdb_id, media_type, country_code):
    if not tmdb_id:
        return None
    try:
        clean_id = int(float(tmdb_id))
    except (TypeError, ValueError):
        return None
    url = f"https://api.themoviedb.org/3/{media_type}/{clean_id}/watch/providers?api_key={TMDB_API_KEY}"
    try:
        r = requests.get(url, timeout=8)
        data = r.json()
        if "results" in data and country_code in data["results"]:
            return data["results"][country_code]
    except Exception:
        return None
    return None


def get_provider_link(provider_name, title):
    q = urllib.parse.quote(title)
    p = provider_name.lower()
    if "netflix" in p:
        return f"https://www.netflix.com/search?q={q}"
    if "amazon" in p or "prime" in p:
        return f"https://www.amazon.com/s?k={q}&i=instant-video"
    if "youtube" in p:
        return f"https://www.youtube.com/results?search_query={q}"
    if "disney" in p:
        return f"https://www.disneyplus.com/search/{q}"
    if "apple" in p:
        return f"https://tv.apple.com/search?term={q}"
    if "hulu" in p:
        return f"https://www.hulu.com/search?q={q}"
    return f"https://www.google.com/search?q=watch+{q}+on+{urllib.parse.quote(provider_name)}"


# --- RELATIONS / SEQUEL FETCHERS ---
@st.cache_data(ttl=3600)
def get_tmdb_relations(tmdb_id, media_type, current_title):
    if not tmdb_id:
        return []
    relations = []
    try:
        clean_id = int(float(tmdb_id))
        if media_type == "movie":
            movie_api = Movie()
            details = movie_api.details(clean_id)
            if getattr(details, "belongs_to_collection", None):
                col_data = details.belongs_to_collection
                if "id" in col_data:
                    col_api = Collection()
                    col_details = col_api.details(col_data["id"])
                    parts = getattr(col_details, "parts", [])
                    parts.sort(key=lambda x: x.get("release_date", "9999"))
                    for p in parts:
                        if p["id"] != clean_id:
                            relations.append({"title": p["title"], "type": "Movie", "relation": "Part of Series"})
        elif media_type == "tv":
            url = f"https://api.themoviedb.org/3/tv/{clean_id}/recommendations?api_key={TMDB_API_KEY}&language=en-US&page=1"
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                recs = r.json().get("results", [])[:6]
                base_title = current_title.split(":")[0].split("Season")[0].strip().lower()
                for rec in recs:
                    rec_name = rec["name"]
                    if base_title in rec_name.lower() or "Season" in rec_name:
                        relations.append({"title": rec_name, "type": "TV", "relation": "Sequel/Related"})
    except Exception:
        pass
    return relations


@st.cache_data(ttl=3600)
def get_season_details(tmdb_id, season_num):
    if not tmdb_id:
        return None
    try:
        clean_id = int(float(tmdb_id))
        url = f"https://api.themoviedb.org/3/tv/{clean_id}/season/{season_num}?api_key={TMDB_API_KEY}"
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {"episode_count": len(data.get("episodes", [])), "name": data.get("name")}
    except Exception:
        return None
    return None


@st.cache_data(ttl=3600)
def fetch_anilist_data_single(title, media_type, format_in=None, fetch_relations=False):
    relation_query = ""
    if fetch_relations:
        relation_query = """
        relations {
            edges {
                relationType
                node { title { romaji english } type }
            }
        }
        """
    query = f"""
    query ($s: String, $t: MediaType, $f: MediaFormat) {{
        Page(perPage: 1) {{
            media(search: $s, type: $t, format: $f) {{
                id
                trailer {{ id site }}
                externalLinks {{ site url }}
                episodes chapters volumes
                {relation_query}
            }}
        }}
    }}
    """
    variables = {"s": title, "t": media_type}
    if format_in:
        variables["f"] = format_in
    try:
        r = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": variables},
            timeout=10,
        )
        data = r.json()
        if data["data"]["Page"]["media"]:
            return data["data"]["Page"]["media"][0]
    except Exception:
        pass
    return {}


@st.cache_data(ttl=3600)
def fetch_anilist_list_raw(query, type_, genres, sort_opt, page, country=None, fmt=None):
    anilist_sort = "POPULARITY_DESC"
    if sort_opt == "Top Rated":
        anilist_sort = "SCORE_DESC"
    elif sort_opt == "Relevance" and query:
        anilist_sort = "SEARCH_MATCH"

    variables = {"t": type_, "p": page, "sort": [anilist_sort]}
    query_args = ["$p: Int", "$t: MediaType", "$sort: [MediaSort]"]
    media_args = ["type: $t", "sort: $sort"]

    if query:
        query_args.append("$s: String")
        media_args.append("search: $s")
        variables["s"] = query
    if genres:
        query_args.append("$g: [String]")
        media_args.append("genre_in: $g")
        variables["g"] = genres
    if country:
        query_args.append("$c: CountryCode")
        media_args.append("countryOfOrigin: $c")
        variables["c"] = country
    if fmt:
        query_args.append("$f: MediaFormat")
        media_args.append("format: $f")
        variables["f"] = fmt

    query_str = f"""
    query ({', '.join(query_args)}) {{
      Page(page: $p, perPage: 15) {{
        media({', '.join(media_args)}) {{
          title {{ romaji english }} coverImage {{ large }} bannerImage genres countryOfOrigin type format description averageScore episodes chapters volumes
          externalLinks {{ site url }}
        }}
      }}
    }}"""
    try:
        r = requests.post(
            "https://graphql.anilist.co",
            json={"query": query_str, "variables": variables},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()["data"]["Page"]["media"]
    except Exception:
        pass
    return []


@st.cache_data(ttl=3600)
def fetch_open_library_raw(query, genre=None):
    url = "https://openlibrary.org/search.json"
    params = {"limit": 15}
    if query:
        params["q"] = query
        if genre and genre != "Web Novel":
            params["q"] += f" subject:{genre}"
    elif genre:
        params["subject"] = genre
    else:
        params["subject"] = "fiction"
    try:
        headers = {"User-Agent": "MediaTrackerApp/1.0"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get("docs", [])
    except Exception:
        pass
    return []


def get_tmdb_trailer(tmdb_id, media_type):
    if not tmdb_id:
        return None
    try:
        clean_id = int(float(tmdb_id))
        url = f"https://api.themoviedb.org/3/{media_type}/{clean_id}/videos?api_key={TMDB_API_KEY}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if "results" in data and data["results"]:
            for priority in ["Trailer", "Teaser", None]:
                for vid in data["results"]:
                    if vid["site"] == "YouTube" and (priority is None or vid["type"] == priority):
                        return f"https://www.youtube.com/watch?v={vid['key']}"
    except Exception:
        pass
    return None


# --- RESULT PROCESSORS ---
def process_open_library(items, detected_type):
    results = []
    for item in items:
        cover_id = item.get("cover_i")
        img_url = (
            f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
            if cover_id
            else PLACEHOLDER_IMG
        )
        title = item.get("title", "Unknown")
        author_list = item.get("author_name", [])
        authors = ", ".join(author_list[:2])
        if authors:
            title += f" - {authors}"
        desc = f"First published in {item.get('first_publish_year', 'Unknown')}."
        if item.get("first_sentence"):
            desc = f"\"{item['first_sentence'][0]}\" — " + desc
        rating_val = item.get("ratings_average", 0)

        results.append({
            "Title": title,
            "Type": detected_type,
            "Country": "International",
            "Genres": ", ".join(item.get("subject", [])[:3]),
            "Image": img_url,
            "Overview": desc,
            "Rating": f"{round(rating_val, 1)}/5",
            "Backdrop": "",
            "Total_Eps": str(item.get("number_of_pages_median", "?")),
            "ID": item.get("key"),
            "Source": "OpenLibrary",
            "Links": [],
        })
    return results


def process_anilist_results(res_list, forced_type, selected_genres):
    results = []
    for res in res_list:
        origin = res.get("countryOfOrigin", "JP")
        if forced_type == "Donghua" and origin != "CN":
            continue
        if forced_type == "Manhwa" and origin != "KR":
            continue
        if forced_type == "Manhua" and origin != "CN":
            continue

        res_genres = res.get("genres", [])
        if selected_genres:
            filtered = [g for g in selected_genres if g != "Web Novel"]
            if filtered and not any(g in res_genres for g in filtered):
                continue

        raw = res.get("description", "")
        clean = re.sub("<[^<]+?>", "", raw) if raw else "No description."
        total = res.get("episodes") or res.get("chapters") or res.get("volumes") or "?"
        avg_score = res.get("averageScore")
        rating_str = f"{avg_score / 10:.1f}/10" if avg_score else "?/10"

        results.append({
            "Title": res["title"]["english"] or res["title"]["romaji"],
            "Type": forced_type,
            "Country": origin,
            "Genres": ", ".join(res_genres),
            "Image": res.get("coverImage", {}).get("large", ""),
            "Overview": clean,
            "Rating": rating_str,
            "Backdrop": res.get("bannerImage", ""),
            "Total_Eps": total,
            "ID": None,
            "Links": res.get("externalLinks", []),
        })
    return results


def process_tmdb_results_batch(results, media_kind, specific_type, selected_types, selected_genres, query):
    processed = []
    for r in results:
        res_lang = getattr(r, "original_language", "en")
        match = True
        if not query:
            if specific_type == "K-Drama" and res_lang != "ko":
                match = False
            elif specific_type == "C-Drama" and res_lang != "zh":
                match = False
            elif specific_type == "Thai Drama" and res_lang != "th":
                match = False
            elif specific_type == "Vertical Drama" and res_lang != "zh":
                match = False

        genre_ids = getattr(r, "genre_ids", [])
        res_genres = [ID_TO_GENRE.get(gid, "Unknown") for gid in genre_ids]
        if selected_genres:
            if not any(g in res_genres for g in selected_genres):
                match = False

        if match:
            detected_type = "Web Series"
            if media_kind == "Movie":
                detected_type = "Movies"
            elif res_lang == "ko":
                detected_type = "K-Drama"
            elif res_lang == "zh":
                detected_type = "Vertical Drama" if specific_type == "Vertical Drama" else "C-Drama"
            elif res_lang == "th":
                detected_type = "Thai Drama"
            elif res_lang == "ja":
                detected_type = "Anime"
            elif res_lang == "en":
                detected_type = "Web Series"

            if detected_type not in selected_types:
                continue

            poster = getattr(r, "poster_path", None)
            img_url = f"{tmdb_poster_base}{poster}" if poster else ""

            processed.append({
                "Title": getattr(r, "title", getattr(r, "name", "Unknown")),
                "Type": detected_type,
                "Country": res_lang,
                "Genres": ", ".join(res_genres),
                "Image": img_url,
                "Overview": getattr(r, "overview", "No overview."),
                "Rating": f"{getattr(r, 'vote_average', 0)}/10",
                "Backdrop": f"{tmdb_backdrop_base}{getattr(r, 'backdrop_path', '')}",
                "Total_Eps": "?",
                "ID": getattr(r, "id", None),
            })
    return processed


# --- PARALLEL SEARCH ENGINE ---
def search_unified(query, selected_types, selected_genres, sort_option, page=1):
    results_data = []
    futures = []

    live_action = ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama", "Vertical Drama"]
    if any(t in selected_types for t in live_action):
        tmdb_genres = [g for g in selected_genres if g in TMDB_GENRE_MAP]
        g_ids = "|".join(str(TMDB_GENRE_MAP[g]) for g in tmdb_genres)
        tmdb_sort = "vote_average.desc" if sort_option == "Top Rated" else "popularity.desc"

        discover = Discover()
        search = Search()

        def run_tmdb_job(media_kind, specific_type, lang_filter=None):
            try:
                active_q = query
                if query and specific_type == "K-Drama":
                    active_q = f"{query} Korean"
                elif query and specific_type == "C-Drama":
                    active_q = f"{query} Chinese"

                if active_q:
                    raw = search.movies(active_q, page=page) if media_kind == "Movie" else search.tv_shows(active_q, page=page)
                else:
                    kwargs = {"sort_by": tmdb_sort, "page": page, "vote_count.gte": 5}
                    if g_ids:
                        kwargs["with_genres"] = g_ids
                    if lang_filter:
                        kwargs["with_original_language"] = lang_filter
                    raw = discover.discover_movies(kwargs) if media_kind == "Movie" else discover.discover_tv_shows(kwargs)

                return process_tmdb_results_batch(raw, media_kind, specific_type, selected_types, selected_genres, query)
            except Exception:
                return []

    def run_anilist_job(q, t, g, s, p, c=None, f=None, forced_t="Anime"):
        raw = fetch_anilist_list_raw(q, t, g, s, p, c, f)
        return process_anilist_results(raw, forced_t, g)

    def run_openlib_job(q, g, forced_t):
        q_mod = q + " novel" if forced_t == "Novel" and q else (q or "fantasy novel")
        raw = fetch_open_library_raw(q_mod, g)
        return process_open_library(raw, forced_t)

    with ThreadPoolExecutor(max_workers=10) as executor:
        if "Movies" in selected_types:
            futures.append(executor.submit(run_tmdb_job, "Movie", "Movies"))
        if "Web Series" in selected_types:
            futures.append(executor.submit(run_tmdb_job, "TV", "Web Series"))
        if "K-Drama" in selected_types:
            futures.append(executor.submit(run_tmdb_job, "TV", "K-Drama", "ko"))
        if "C-Drama" in selected_types:
            futures.append(executor.submit(run_tmdb_job, "TV", "C-Drama", "zh"))
        if "Thai Drama" in selected_types:
            futures.append(executor.submit(run_tmdb_job, "TV", "Thai Drama", "th"))
        if "Vertical Drama" in selected_types:
            futures.append(executor.submit(run_tmdb_job, "TV", "Vertical Drama", "zh"))

        if "Anime" in selected_types:
            futures.append(executor.submit(run_anilist_job, query, "ANIME", selected_genres, sort_option, page, None, None, "Anime"))
        if "Donghua" in selected_types:
            futures.append(executor.submit(run_anilist_job, query, "ANIME", selected_genres, sort_option, page, "CN", None, "Donghua"))
        if "Manga" in selected_types:
            futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "JP", None, "Manga"))
        if "Manhwa" in selected_types:
            futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "KR", None, "Manhwa"))
        if "Manhua" in selected_types:
            futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "CN", None, "Manhua"))

        if "Novel" in selected_types:
            futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, None, "NOVEL", "Novel"))
            if "Web Novel" in selected_genres:
                futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "KR", "NOVEL", "Novel"))
                futures.append(executor.submit(run_anilist_job, query, "MANGA", selected_genres, sort_option, page, "CN", "NOVEL", "Novel"))
            futures.append(executor.submit(run_openlib_job, query, None, "Novel"))

        if "Book" in selected_types:
            target_genre = None
            if selected_genres:
                book_genres = [g for g in selected_genres if g in BOOK_GENRES]
                if book_genres:
                    target_genre = book_genres[0]
            futures.append(executor.submit(run_openlib_job, query, target_genre, "Book"))

        for future in as_completed(futures):
            try:
                data = future.result()
                if data:
                    results_data.extend(data)
            except Exception:
                pass

    return results_data


# ============================================================
# --- UI SESSION STATE ---
# ============================================================
if "refresh_key" not in st.session_state:
    st.session_state.refresh_key = 0
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "search_page" not in st.session_state:
    st.session_state.search_page = 1
if "search_query_trigger" not in st.session_state:
    st.session_state.search_query_trigger = ""
if "last_search_query" not in st.session_state:
    st.session_state.last_search_query = None


# --- NAVIGATION ---
default_tab = 1 if st.session_state.search_query_trigger else 0
tab = st.radio(
    "Navigation",
    ["🏠 My Library", "🔍 Search & Add"],
    horizontal=True,
    label_visibility="collapsed",
    index=default_tab,
)
st.write("---")


# ============================================================
# --- SEARCH TAB ---
# ============================================================
if tab == "🔍 Search & Add":
    st.subheader("Global Database Search")

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])

    default_q = ""
    if st.session_state.search_query_trigger:
        default_q = st.session_state.search_query_trigger
        st.session_state.search_query_trigger = ""

    with c1:
        search_query = st.text_input("Title (Optional)", value=default_q, key="search_box_input")
    with c2:
        all_types = [
            "Movies", "Web Series", "K-Drama", "C-Drama", "Vertical Drama",
            "Thai Drama", "Anime", "Donghua", "Manga", "Manhwa", "Manhua", "Novel", "Book",
        ]
        selected_types = st.multiselect("Type", all_types, default=[], help="Leave empty to search ALL types")

    current_genres = list(TMDB_GENRE_MAP.keys())
    if "Book" in selected_types or "Novel" in selected_types:
        current_genres = sorted(set(current_genres + BOOK_GENRES))

    with c3:
        selected_genres = st.multiselect("Genre", current_genres)
    with c4:
        sort_option = st.selectbox("Sort By", ["Popularity", "Relevance", "Top Rated"])

    # BUG FIX: Only trigger search on button click, not on every text change
    do_search = st.button("🚀 Search / Discover")
    if default_q and not st.session_state.search_results:
        do_search = True  # Auto-trigger only for sequel links

    if do_search:
        st.session_state.search_page = 1
        st.session_state.search_results = []
        st.session_state.last_search_query = search_query
        with st.spinner("Fetching from global databases..."):
            active_types = selected_types if selected_types else all_types
            results = search_unified(search_query, active_types, selected_genres, sort_option, page=1)
            st.session_state.search_results = results
        if not st.session_state.search_results:
            st.warning("No results found. Try a different query or type.")

    if st.session_state.search_results:
        lib_map = get_library_data()

        for idx, item in enumerate(st.session_state.search_results):
            with st.container():
                col_img, col_txt = st.columns([1, 6])
                with col_img:
                    img = item.get("Image") or PLACEHOLDER_IMG
                    st.image(img, use_container_width=True)
                with col_txt:
                    st.subheader(item.get("Title", "Unknown"))
                    st.caption(f"**{item.get('Type', '')}** | ⭐ {item.get('Rating', '')} | {item.get('Country', '')}")
                    st.caption(f"🏷️ {item.get('Genres', '')}")

                    with st.popover("📜 Overview"):
                        tmdb_id = item.get("ID")
                        m_type = "movie" if item.get("Type") == "Movies" else "tv"

                        st.write(item.get("Overview", ""))

                        # Relations
                        found_relations = []
                        if item.get("Type") in ["Anime", "Donghua", "Manga", "Manhwa", "Manhua", "Novel"]:
                            ad = fetch_anilist_data_single(
                                item.get("Title", ""),
                                "ANIME" if item.get("Type") in ["Anime", "Donghua"] else "MANGA",
                                fetch_relations=True,
                            )
                            if ad and "relations" in ad:
                                for edge in ad["relations"]["edges"]:
                                    rtype_raw = edge["relationType"]
                                    if rtype_raw not in ["SEQUEL", "PREQUEL", "PARENT", "SIDE_STORY", "ALTERNATIVE", "SOURCE"]:
                                        continue
                                    rtype = rtype_raw.replace("_", " ").title()
                                    rtitle = edge["node"]["title"]["english"] or edge["node"]["title"]["romaji"]
                                    if rtitle:
                                        found_relations.append({"type": rtype, "title": rtitle})
                        elif tmdb_id:
                            found_relations.extend(get_tmdb_relations(tmdb_id, m_type, item.get("Title", "")))

                        if found_relations:
                            st.write("---")
                            links = [
                                f"[{r['type']}: {r['title']}](/?search={urllib.parse.quote(r['title'])})"
                                for r in found_relations
                            ]
                            st.markdown(f"**Watch Order:** {' | '.join(links)}")
                            st.write("---")

                        # Trailer
                        trailer_url = None
                        try:
                            if item.get("Type") in ["Anime", "Donghua"]:
                                ad = fetch_anilist_data_single(item.get("Title", ""), "ANIME")
                                if ad and ad.get("trailer") and ad["trailer"].get("site") == "youtube":
                                    trailer_url = f"https://www.youtube.com/watch?v={ad['trailer']['id']}"
                            elif item.get("Type") in ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama", "Vertical Drama"]:
                                if tmdb_id:
                                    trailer_url = get_tmdb_trailer(tmdb_id, m_type)
                        except Exception:
                            trailer_url = None

                        if trailer_url:
                            st.caption("🎬 Trailer")
                            st.video(trailer_url)

                        if item.get("Type") in ["Manga", "Manhwa", "Manhua", "Novel"] and item.get("Links"):
                            st.write("**Official Sources:**")
                            for link in item["Links"]:
                                st.link_button(f"🔗 {link['site']}", link["url"])

                    is_added = is_in_library(item.get("Title", ""))

                    if is_added:
                        existing_data = get_from_library(item.get("Title", ""))
                        st.success("✅ In Collection")

                        with st.expander("Update Status", expanded=False):
                            is_read = item.get("Type") in ["Book", "Novel", "Manga", "Manhwa", "Manhua"]
                            opts = (
                                ["Plan to Read", "Reading", "Completed", "Dropped"]
                                if is_read
                                else ["Plan to Watch", "Watching", "Completed", "Dropped"]
                            )
                            curr_status = existing_data.get("Status", opts[0])
                            if curr_status not in opts:
                                curr_status = opts[0]
                            try:
                                curr_sea = int(existing_data.get("Current_Season", 1))
                            except (TypeError, ValueError):
                                curr_sea = 1
                            try:
                                curr_ep = int(existing_data.get("Current_Ep", 0))
                            except (TypeError, ValueError):
                                curr_ep = 0

                            new_s = st.selectbox("Status", opts, index=opts.index(curr_status), key=f"s_search_{idx}")

                            if item.get("Type") != "Movies":
                                c_s, c_e = st.columns(2)
                                lbl1 = "Vol." if is_read else "S"
                                lbl2 = "Ch." if is_read else "E"
                                ns = c_s.number_input(lbl1, value=curr_sea, min_value=1, key=f"ns_search_{idx}")
                                ne = c_e.number_input(lbl2, value=curr_ep, min_value=0, key=f"ne_search_{idx}")
                            else:
                                ns, ne = 1, 0

                            c1_btn, c2_btn = st.columns(2)
                            with c1_btn:
                                if st.button("Save", key=f"save_search_{idx}"):
                                    update_status_in_sheet(item.get("Title", ""), new_s, ns, ne)
                                    st.rerun()
                            with c2_btn:
                                if st.button("Delete", key=f"del_search_{idx}"):
                                    delete_from_sheet(item.get("Title", ""))
                                    st.rerun()
                    else:
                        if st.button(f"➕ Add to Library", key=f"add_{idx}"):
                            with st.spinner("Adding..."):
                                success = fetch_details_and_add(item)
                                if success:
                                    st.rerun()
            st.divider()

        if st.button("⬇️ Load More Results"):
            st.session_state.search_page += 1
            with st.spinner(f"Loading Page {st.session_state.search_page}..."):
                active_types = selected_types if selected_types else all_types
                new = search_unified(
                    st.session_state.get("last_search_query", ""),
                    active_types, selected_genres, sort_option,
                    page=st.session_state.search_page,
                )
                st.session_state.search_results.extend(new)
                st.rerun()


# ============================================================
# --- LIBRARY TAB ---
# ============================================================
elif tab == "🏠 My Library":

    col_h, col_c = st.columns([3, 1])
    with col_h:
        st.subheader("My Library")
    with col_c:
        try:
            def_ix = list(tmdb_countries.keys()).index("India")
        except ValueError:
            def_ix = 0
        stream_country = st.selectbox("Streaming Country", list(tmdb_countries.keys()), index=def_ix)
        country_code = tmdb_countries[stream_country]

    sheet = get_google_sheet()

    if sheet:
        get_library_data()
        raw_data = sheet.get_all_values()

        if len(raw_data) > 1:
            safe_rows = []
            for row in raw_data[1:]:
                if not row or not row[0].strip():
                    continue
                if len(row) < len(REQUIRED_HEADERS):
                    row = row + [""] * (len(REQUIRED_HEADERS) - len(row))
                safe_rows.append(row[: len(REQUIRED_HEADERS)])

            df = pd.DataFrame(safe_rows, columns=REQUIRED_HEADERS)

            # --- STATS PANEL ---
            with st.expander("📊 Library Statistics", expanded=False):
                total = len(df)
                st.markdown(f"**Total items:** {total}")

                sc1, sc2 = st.columns(2)
                with sc1:
                    st.markdown("**By Status:**")
                    status_counts = df["Status"].value_counts()
                    for s, c in status_counts.items():
                        pct = int(c / total * 100)
                        emoji = {"Completed": "✅", "Watching": "▶️", "Reading": "📖",
                                 "Plan to Watch": "🕒", "Plan to Read": "📌", "Dropped": "❌"}.get(s, "•")
                        st.markdown(f"{emoji} **{s}:** {c} ({pct}%)")
                with sc2:
                    st.markdown("**By Type:**")
                    type_counts = df["Type"].value_counts()
                    for t, c in type_counts.items():
                        st.markdown(f"• **{t}:** {c}")

            # --- CURRENTLY WATCHING STRIP ---
            active_statuses = ["Watching", "Reading"]
            active_df = df[df["Status"].isin(active_statuses)]
            if not active_df.empty:
                with st.expander(f"🔥 Currently Active ({len(active_df)})", expanded=True):
                    act_cols = st.columns(min(len(active_df), 6))
                    for col, (_, item) in zip(act_cols, active_df.iterrows()):
                        with col:
                            img = item.get("Image", "") or PLACEHOLDER_IMG
                            if not str(img).startswith("http"):
                                img = PLACEHOLDER_IMG
                            st.image(img, use_container_width=True)
                            title_short = (item["Title"][:18] + "…") if len(item["Title"]) > 18 else item["Title"]
                            st.caption(f"**{title_short}**")
                            ep_info = f"S{item.get('Current_Season', 1)} E{item.get('Current_Ep', 0)}"
                            if item.get("Type") in ["Manga", "Manhwa", "Manhua"]:
                                ep_info = f"Vol.{item.get('Current_Season', 1)} Ch.{item.get('Current_Ep', 0)}"
                            elif item.get("Type") in ["Book", "Novel"]:
                                ep_info = f"Pg.{item.get('Current_Season', 0)}"
                            st.caption(ep_info)

            st.divider()

            # --- FILTERS ---
            with st.expander("🔽 Filter Collection", expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    filter_text = st.text_input("Search Title")
                with c2:
                    filter_type = st.multiselect("Filter Type", sorted(df["Type"].unique()))
                with c3:
                    filter_status = st.multiselect(
                        "Status",
                        ["Plan to Watch", "Plan to Read", "Watching", "Reading", "Completed", "Dropped"],
                    )
                with c4:
                    filter_fav = st.checkbox("⭐ Favorites Only")

            if filter_text:
                df = df[df["Title"].astype(str).str.contains(filter_text, case=False, na=False)]
            if filter_type:
                df = df[df["Type"].isin(filter_type)]
            if filter_status:
                df = df[df["Status"].isin(filter_status)]
            if filter_fav:
                df = df[df.get("Favorite", pd.Series("No")) == "Yes"]

            # --- EXPORT ---
            col_exp1, col_exp2 = st.columns([6, 1])
            with col_exp2:
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Export CSV",
                    data=csv_bytes,
                    file_name="my_media_library.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            # --- REORDER ---
            if HAS_SORTABLES and not df.empty:
                with st.expander("🔄 Reorder List", expanded=False):
                    st.caption("Drag items to change order, then click Save.")
                    subset_titles = df["Title"].tolist()
                    sorted_titles = sort_items(subset_titles, key="sort_all")
                    if sorted_titles != subset_titles:
                        if st.button("💾 Save Order"):
                            title_map = {}
                            for idx in df.index.tolist():
                                tv = df.loc[idx, "Title"]
                                title_map.setdefault(tv, []).append(idx)
                            new_order_indices = []
                            for title in sorted_titles:
                                if title in title_map and title_map[title]:
                                    new_order_indices.append(title_map[title].pop(0))
                            new_df = df.iloc[new_order_indices].reset_index(drop=True)
                            bulk_update_order(new_df)

            # --- GALLERY GRID ---
            if not df.empty:
                cols_per_row = 5
                rows = [df.iloc[i: i + cols_per_row] for i in range(0, len(df), cols_per_row)]

                for row_chunk in rows:
                    cols = st.columns(cols_per_row)
                    for col, (index, item) in zip(cols, row_chunk.iterrows()):
                        with col:
                            img = item.get("Image", "") or PLACEHOLDER_IMG
                            if not str(img).startswith("http"):
                                img = PLACEHOLDER_IMG
                            st.image(img, use_container_width=True)

                            # Favorite badge
                            fav_badge = "❤️ " if item.get("Favorite") == "Yes" else ""
                            st.markdown(f"**{fav_badge}{item.get('Title', '')}**")

                            unique_key = f"gal_{index}"

                            # BUG FIX: Define is_book and is_comic BEFORE any popover/expander
                            is_book = item.get("Type") in ["Book", "Novel"]
                            is_comic = item.get("Type") in ["Manga", "Manhwa", "Manhua"]
                            is_read = is_book or is_comic

                            with st.popover("📜 Overview"):
                                tmdb_id = item.get("ID")
                                m_type = "movie" if item.get("Type") == "Movies" else "tv"
                                if not tmdb_id and item.get("Type") in [
                                    "Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama", "Vertical Drama"
                                ]:
                                    tmdb_id = recover_tmdb_id(item.get("Title", ""), m_type)

                                st.write(item.get("Overview", ""))

                                # Relations
                                found_relations = []
                                if item.get("Type") in ["Anime", "Donghua", "Manga", "Manhwa", "Manhua", "Novel"]:
                                    ad = fetch_anilist_data_single(
                                        item.get("Title", ""),
                                        "ANIME" if item.get("Type") in ["Anime", "Donghua"] else "MANGA",
                                        fetch_relations=True,
                                    )
                                    if ad and "relations" in ad:
                                        for edge in ad["relations"]["edges"]:
                                            rtype_raw = edge["relationType"]
                                            if rtype_raw not in ["SEQUEL", "PREQUEL", "PARENT", "SIDE_STORY", "ALTERNATIVE", "SOURCE"]:
                                                continue
                                            rtype = rtype_raw.replace("_", " ").title()
                                            rtitle = edge["node"]["title"]["english"] or edge["node"]["title"]["romaji"]
                                            if rtitle:
                                                found_relations.append({"type": rtype, "title": rtitle})
                                elif tmdb_id:
                                    found_relations.extend(get_tmdb_relations(tmdb_id, m_type, item.get("Title", "")))

                                if found_relations:
                                    st.write("---")
                                    links = [
                                        f"[{r['type']}: {r['title']}](/?search={urllib.parse.quote(r['title'])})"
                                        for r in found_relations
                                    ]
                                    st.markdown(f"**Watch Order:** {' | '.join(links)}")
                                    st.write("---")

                                # Trailer
                                trailer_url = None
                                try:
                                    if item.get("Type") in ["Anime", "Donghua"]:
                                        ad = fetch_anilist_data_single(item.get("Title", ""), "ANIME")
                                        if ad and ad.get("trailer") and ad["trailer"].get("site") == "youtube":
                                            trailer_url = f"https://www.youtube.com/watch?v={ad['trailer']['id']}"
                                    elif item.get("Type") in ["Movies", "Web Series", "K-Drama", "C-Drama", "Thai Drama", "Vertical Drama"]:
                                        if tmdb_id:
                                            trailer_url = get_tmdb_trailer(tmdb_id, m_type)
                                except Exception:
                                    trailer_url = None

                                if trailer_url:
                                    st.caption("🎬 Trailer")
                                    st.video(trailer_url)

                                st.write(f"**Status:** {item.get('Status', '')}")
                                st.write(f"**TMDB Rating:** {item.get('Rating', '')}")
                                if item.get("Personal_Rating"):
                                    stars = "⭐" * int(item["Personal_Rating"]) if str(item["Personal_Rating"]).isdigit() else ""
                                    st.write(f"**Your Rating:** {stars} {item['Personal_Rating']}/5")
                                if item.get("Notes"):
                                    st.write(f"**Your Notes:** {item['Notes']}")
                                if item.get("Date_Added"):
                                    st.caption(f"Added: {item['Date_Added']}")
                                st.divider()

                                if is_book:
                                    st.caption("📖 Reading Options")
                                    st.link_button("📘 Search Google Books", f"https://www.google.com/search?tbm=bks&q={item.get('Title', '')}")
                                elif is_comic:
                                    st.caption("📖 Reading Options")
                                    st.link_button("📖 Search Comix.to", f"https://www.google.com/search?q=site:comix.to+{item.get('Title', '')}")
                                    live_data = fetch_anilist_data_single(item.get("Title", ""), "MANGA")
                                    if live_data and live_data.get("externalLinks"):
                                        st.write("**Official Sources:**")
                                        for lnk in live_data["externalLinks"]:
                                            st.link_button(f"🔗 {lnk['site']}", lnk["url"])
                                else:
                                    st.caption(f"📺 Watch in {stream_country}")
                                    if item.get("Type") == "Anime":
                                        st.link_button("🟠 Search Crunchyroll", f"https://www.crunchyroll.com/search?q={item.get('Title', '')}")
                                    elif item.get("Type") in ["K-Drama", "C-Drama", "Thai Drama", "Vertical Drama"]:
                                        st.link_button("💙 Watch on Viki", f"https://www.viki.com/search?q={urllib.parse.quote(item.get('Title', ''))}")

                                    provs = get_streaming_info(tmdb_id, m_type, country_code)
                                    has_streams = False
                                    if provs:
                                        for label, key in [("Streaming", "flatrate"), ("Rent", "rent"), ("Buy", "buy")]:
                                            if key in provs:
                                                st.write(f"**{label}:**")
                                                for p in provs[key]:
                                                    lnk = get_provider_link(p["provider_name"], item.get("Title", ""))
                                                    st.markdown(f"- [{p['provider_name']}]({lnk})")
                                                has_streams = True
                                    if not has_streams:
                                        st.caption("No official streams found.")

                            with st.expander("⚙️ Manage"):
                                opts = (
                                    ["Plan to Read", "Reading", "Completed", "Dropped"]
                                    if is_read
                                    else ["Plan to Watch", "Watching", "Completed", "Dropped"]
                                )
                                curr = item.get("Status", opts[0])
                                if curr not in opts:
                                    curr = opts[0]
                                new_s = st.selectbox("Status", opts, key=f"st_{unique_key}", index=opts.index(curr))

                                if is_book:
                                    try:
                                        c_pg = int(item.get("Current_Season", 0))
                                    except (TypeError, ValueError):
                                        c_pg = 0
                                    new_sea = st.number_input("Pages/Chapters", value=c_pg, key=f"s_{unique_key}")
                                    new_ep = 0
                                    st.caption(f"Total: {item.get('Total_Eps', '?')}")

                                elif item.get("Type") != "Movies":
                                    try:
                                        c_sea = int(item.get("Current_Season", 1))
                                    except (TypeError, ValueError):
                                        c_sea = 1
                                    try:
                                        c_ep = int(item.get("Current_Ep", 0))
                                    except (TypeError, ValueError):
                                        c_ep = 0

                                    sea_lbl, ep_lbl = ("Vol.", "Ch.") if is_comic else ("S", "E")
                                    total_str = item.get("Total_Eps", "?")
                                    if not is_comic and tmdb_id:
                                        si = get_season_details(tmdb_id, c_sea)
                                        if si:
                                            total_str = si["episode_count"]

                                    col_s, col_e = st.columns(2)
                                    with col_s:
                                        new_sea = st.number_input(sea_lbl, min_value=1, value=c_sea, key=f"s_{unique_key}")
                                    with col_e:
                                        lbl = f"{ep_lbl} (/{total_str})" if total_str != "?" else ep_lbl
                                        new_ep = st.number_input(lbl, min_value=0, value=c_ep, key=f"e_{unique_key}")
                                else:
                                    new_sea, new_ep = 1, 0

                                # Personal rating
                                try:
                                    curr_pr = int(item.get("Personal_Rating", 0))
                                except (TypeError, ValueError):
                                    curr_pr = 0
                                new_pr = st.slider("⭐ Your Rating (0–5)", min_value=0, max_value=5, value=curr_pr, key=f"pr_{unique_key}")

                                # Notes
                                curr_notes = str(item.get("Notes", ""))
                                new_notes = st.text_area("📝 Notes", value=curr_notes, key=f"nt_{unique_key}", height=80)

                                # Favorite toggle
                                curr_fav = item.get("Favorite", "No") == "Yes"
                                new_fav = st.checkbox("❤️ Favorite", value=curr_fav, key=f"fv_{unique_key}")

                                c_sv, c_dl = st.columns(2)
                                with c_sv:
                                    if st.button("💾 Save", key=f"sv_{unique_key}"):
                                        update_status_in_sheet(
                                            item.get("Title", ""), new_s, new_sea, new_ep,
                                            notes=new_notes,
                                            personal_rating=str(new_pr),
                                            favorite="Yes" if new_fav else "No",
                                        )
                                        st.rerun()
                                with c_dl:
                                    if st.button("🗑️ Delete", key=f"dl_{unique_key}"):
                                        delete_from_sheet(item.get("Title", ""))
                                        st.rerun()
            else:
                st.info("No items found matching your filters.")
        else:
            st.info("Your library is empty. Go to **Search & Add** to find something!")
    else:
        st.error("❌ Google Sheets connection failed. Check your secrets configuration.")
