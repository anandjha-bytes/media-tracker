import streamlit as st
import pandas as pd
import requests
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. API WRAPPERS (The Logic Engine)
# ==========================================

class MediaAPI:
    """Unified API handler for TMDB, AniList, and OpenLibrary"""
    
    def __init__(self):
        # Ensure secrets are set in .streamlit/secrets.toml
        try:
            self.tmdb_key = st.secrets["api"]["tmdb_key"]
        except:
            st.error("Missing TMDB API Key in secrets.toml")
            self.tmdb_key = ""
    
    # --- TMDB (Movies & TV) ---
    def search_tmdb(self, query):
        if not self.tmdb_key: return []
        url = f"https://api.themoviedb.org/3/search/multi?api_key={self.tmdb_key}&query={query}"
        try:
            data = requests.get(url).json().get('results', [])
            return [
                {
                    "id": i['id'], 
                    "title": i.get('title', i.get('name')), 
                    "type": 'movie' if i['media_type'] == 'movie' else 'tv',
                    "poster": f"https://image.tmdb.org/t/p/w200{i.get('poster_path')}" if i.get('poster_path') else None,
                    "overview": i.get('overview', '')
                } for i in data if i['media_type'] in ['movie', 'tv']
            ]
        except:
            return []

    def get_tmdb_timeline(self, media_id, media_type):
        """Fetches sequels/prequels/collections"""
        timeline = []
        if not self.tmdb_key: return []
        
        try:
            # If it's a movie, check for "Belongs to Collection"
            if media_type == 'movie':
                url = f"https://api.themoviedb.org/3/movie/{media_id}?api_key={self.tmdb_key}"
                details = requests.get(url).json()
                collection = details.get('belongs_to_collection')
                
                if collection:
                    c_url = f"https://api.themoviedb.org/3/collection/{collection['id']}?api_key={self.tmdb_key}"
                    c_data = requests.get(c_url).json()
                    parts = c_data.get('parts', [])
                    # Sort by release date
                    parts.sort(key=lambda x: x.get('release_date', '9999') or '9999')
                    
                    for part in parts:
                        timeline.append({
                            "id": part['id'],
                            "title": part['title'],
                            "type": "movie",
                            "relation": "Part of Collection",
                            "poster": f"https://image.tmdb.org/t/p/w200{part.get('poster_path')}"
                        })
                else:
                    # No collection, just return self
                    timeline.append({
                        "id": details['id'], "title": details['title'], "type": "movie", 
                        "relation": "Current", "poster": f"https://image.tmdb.org/t/p/w200{details.get('poster_path')}"
                    })

            # If it's TV, simpler logic (Seasons)
            elif media_type == 'tv':
                url = f"https://api.themoviedb.org/3/tv/{media_id}?api_key={self.tmdb_key}"
                details = requests.get(url).json()
                for season in details.get('seasons', []):
                     if season['season_number'] > 0: # Skip specials usually
                        timeline.append({
                            "id": media_id, # TV Show ID is same
                            "title": season['name'],
                            "type": "tv_season",
                            "relation": f"Season {season['season_number']}",
                            "poster": f"https://image.tmdb.org/t/p/w200{season.get('poster_path')}"
                        })
        except:
            pass
                    
        return timeline

    # --- ANILIST (Anime) ---
    def search_anilist(self, query):
        query_gql = '''
        query ($search: String) {
            Page(perPage: 5) {
                media(search: $search, type: ANIME) {
                    id
                    title { romaji English }
                    coverImage { large }
                    description
                }
            }
        }
        '''
        try:
            response = requests.post('https://graphql.anilist.co', json={'query': query_gql, 'variables': {'search': query}})
            data = response.json()['data']['Page']['media']
            return [
                {
                    "id": i['id'],
                    "title": i['title'].get('English') or i['title']['romaji'],
                    "type": 'anime',
                    "poster": i['coverImage']['large'],
                    "overview": i.get('description', '')
                } for i in data
            ]
        except:
            return []

    def get_anilist_timeline(self, media_id):
        query_gql = '''
        query ($id: Int) {
            Media(id: $id, type: ANIME) {
                id
                title { romaji English }
                coverImage { large }
                relations {
                    edges {
                        relationType(version: 2)
                        node {
                            id
                            title { romaji English }
                            coverImage { large }
                            type
                        }
                    }
                }
            }
        }
        '''
        try:
            response = requests.post('https://graphql.anilist.co', json={'query': query_gql, 'variables': {'id': media_id}})
            data = response.json().get('data', {}).get('Media', {})
            
            timeline = []
            if not data: return []

            # Current Item
            timeline.append({
                "id": data['id'],
                "title": data['title'].get('English') or data['title']['romaji'],
                "type": 'anime',
                "relation": "Current",
                "poster": data['coverImage']['large']
            })

            # Relations
            edges = data.get('relations', {}).get('edges', [])
            for edge in edges:
                if edge['node']['type'] == 'ANIME' and edge['relationType'] in ['PREQUEL', 'SEQUEL', 'PARENT', 'SIDE_STORY']:
                    timeline.append({
                        "id": edge['node']['id'],
                        "title": edge['node']['title'].get('English') or edge['node']['title']['romaji'],
                        "type": 'anime',
                        "relation": edge['relationType'],
                        "poster": edge['node']['coverImage']['large']
                    })
            
            # Simple Sort: Prequel -> Parent -> Current -> Sequel -> Side Story
            order = {'PREQUEL': 1, 'PARENT': 2, 'Current': 3, 'SEQUEL': 4, 'SIDE_STORY': 5}
            timeline.sort(key=lambda x: order.get(x['relation'], 99))
            return timeline
        except:
            return []

    # --- OPENLIBRARY (Books) ---
    def search_openlibrary(self, query):
        url = f"https://openlibrary.org/search.json?q={query}&limit=5"
        try:
            data = requests.get(url).json().get('docs', [])
            results = []
            for i in data:
                cover_id = i.get('cover_i')
                results.append({
                    "id": i.get('key').replace('/works/', ''),
                    "title": i.get('title'),
                    "type": 'book',
                    "poster": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else None,
                    "overview": f"By {', '.join(i.get('author_name', []))}"
                })
            return results
        except:
            return []

    def get_openlibrary_timeline(self, work_id):
        # Basic placeholder for books as Series APIs are complex
        url = f"https://openlibrary.org/works/{work_id}.json"
        try:
            data = requests.get(url).json()
            timeline = [{
                "id": work_id,
                "title": data.get('title'),
                "type": "book",
                "relation": "Current",
                "poster": None 
            }]
            return timeline
        except:
            return []

# ==========================================
# 2. STREAMLIT UI COMPONENTS
# ==========================================

def render_timeline(timeline_data, current_id):
    """Horizontal Franchise Timeline"""
    st.markdown("### 🧬 Watch Order & Related Seasons")
    
    # CSS for nice cards
    st.markdown("""
    <style>
    div[data-testid="column"] img {
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s;
    }
    div[data-testid="column"] img:hover {
        transform: scale(1.03);
    }
    .relation-tag {
        font-size: 0.8em;
        color: #aaa;
    }
    </style>
    """, unsafe_allow_html=True)

    # Display items
    display_items = timeline_data[:8] # Limit to 8 to fit screen
    
    cols = st.columns(len(display_items))
    
    for idx, item in enumerate(display_items):
        with cols[idx]:
            # Visual check for current item
            is_active = str(item['id']) == str(current_id)
            
            if item['poster']:
                st.image(item['poster'], use_container_width=True)
            else:
                st.info("No Image")
                
            if is_active:
                st.markdown(f"📍 **{item['relation']}**")
            else:
                st.markdown(f"<span class='relation-tag'>{item['relation']}</span>", unsafe_allow_html=True)
                # When clicked, update state to this new item
                if st.button("View", key=f"jump_{item['id']}_{idx}"):
                    st.session_state['selected_media'] = item
                    st.rerun()

def save_to_sheet(item, status, score):
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        existing_data = conn.read()
        
        # Check if exists
        if str(item['id']) in existing_data['External_ID'].astype(str).values:
            st.toast("Item already in your list!", icon="⚠️")
            return

        new_row = pd.DataFrame([{
            "ID": len(existing_data) + 1,
            "Title": item['title'],
            "Type": item['type'],
            "Status": status,
            "Score": score,
            "Current_Progress": 0,
            "External_ID": item['id'],
            "Poster_Url": item['poster'] # Added poster storage for the dashboard
        }])
        
        updated_df = pd.concat([existing_data, new_row], ignore_index=True)
        conn.update(data=updated_df)
        st.toast(f"Added {item['title']} to your list!", icon="✅")
        
    except Exception as e:
        st.error(f"Error saving to sheet: {e}")

# ==========================================
# 3. MAIN APP LOGIC
# ==========================================

def main():
    st.set_page_config(page_title="Ultimate Media Tracker", layout="wide", page_icon="🎬")
    
    # Initialize API
    api = MediaAPI()
    
    # Initialize Session State
    if 'selected_media' not in st.session_state:
        st.session_state['selected_media'] = None

    # --- SIDEBAR: Search ---
    with st.sidebar:
        st.header("🔍 Global Search")
        search_type = st.selectbox("Category", ["Anime", "Movies/TV", "Books"])
        query = st.text_input("Search Title...", placeholder="e.g. Naruto, Dune")
        
        if query:
            with st.spinner("Searching..."):
                if search_type == "Anime":
                    results = api.search_anilist(query)
                elif search_type == "Movies/TV":
                    results = api.search_tmdb(query)
                else:
                    results = api.search_openlibrary(query)
            
            st.markdown("---")
            for res in results:
                # Search Result Card
                with st.container(border=True):
                    c1, c2 = st.columns([1, 2.5])
                    with c1:
                        if res['poster']: st.image(res['poster'])
                    with c2:
                        st.write(f"**{res['title']}**")
                        st.caption(f"{res['type'].upper()}")
                        
                        # The Select Button now implies exploring the franchise
                        if st.button("Explore & Add", key=f"sel_{res['id']}"):
                            st.session_state['selected_media'] = res
                            st.rerun()

    # --- MAIN PAGE ---
    
    # If a user selected something from Search OR Dashboard, show details + timeline
    if st.session_state['selected_media']:
        # === DETAIL & TIMELINE VIEW ===
        media = st.session_state['selected_media']
        
        # 1. Timeline / Franchise View (Moved to Top for visibility)
        st.title(media['title'])
        st.caption(f"Details for ID: {media['id']}")
        
        # Load Timeline Logic
        timeline = []
        with st.spinner(f"Finding Prequels, Sequels & Seasons for {media['title']}..."):
            if media['type'] == 'anime':
                timeline = api.get_anilist_timeline(media['id'])
            elif media['type'] in ['movie', 'tv', 'tv_season']:
                timeline = api.get_tmdb_timeline(media['id'], media['type'])
            else:
                timeline = api.get_openlibrary_timeline(media['id'])
        
        # Render the Timeline Component
        if timeline:
            render_timeline(timeline, media['id'])
        else:
            st.info("No related sequels or prequels found.")

        st.divider()

        # 2. Media Info & Actions
        col1, col2 = st.columns([1, 4])
        
        with col1:
            if media['poster']: st.image(media['poster'])
            
            # Action Box
            with st.container(border=True):
                st.markdown("**Add to Library**")
                status = st.selectbox("Status", ["Planning", "Watching", "Completed", "Dropped"])
                score = st.slider("Score", 0, 10, 5)
                if st.button("💾 Save Progress"):
                    save_to_sheet(media, status, score)

        with col2:
            st.markdown("### Synopsis")
            st.write(media.get('overview', 'No description available.'))
            
            # Button to go back home
            st.markdown("---")
            if st.button("← Back to My Dashboard"):
                st.session_state['selected_media'] = None
                st.rerun()

    else:
        # === DASHBOARD (COLLECTION) VIEW ===
        st.title("📊 My Media Collection")
        
        conn = st.connection("gsheets", type=GSheetsConnection)
        try:
            df = conn.read()
            
            # Top Stats
            if not df.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Items", len(df))
                m2.metric("Completed", len(df[df['Status'] == 'Completed']))
                m3.metric("Watching Now", len(df[df['Status'] == 'Watching']))
                st.divider()

                # INTERACTIVE GALLERY (Instead of plain dataframe)
                st.subheader("Your Library")
                
                # Filter Options
                filter_status = st.multiselect("Filter by Status", df['Status'].unique(), default=df['Status'].unique())
                filtered_df = df[df['Status'].isin(filter_status)]

                # Grid Layout for items
                # We iterate through the dataframe and create columns
                rows = [filtered_df.iloc[i:i+4] for i in range(0, len(filtered_df), 4)]
                
                for row in rows:
                    cols = st.columns(4)
                    for idx, (index, item) in enumerate(row.iterrows()):
                        with cols[idx]:
                            with st.container(border=True):
                                # If you saved poster_url in sheet, use it, else generic icon
                                if 'Poster_Url' in item and pd.notna(item['Poster_Url']):
                                    st.image(item['Poster_Url'], use_container_width=True)
                                else:
                                    st.markdown("🎬")
                                
                                st.write(f"**{item['Title']}**")
                                st.caption(f"{item['Type']} • {item['Status']}")
                                st.progress(item['Score']/10, text=f"Score: {item['Score']}/10")
                                
                                # CLICK TO VIEW RELATIONS
                                if st.button("Open", key=f"dash_btn_{item['ID']}"):
                                    # Construct a media object compatible with the API
                                    st.session_state['selected_media'] = {
                                        "id": item['External_ID'],
                                        "title": item['Title'],
                                        "type": item['Type'],
                                        "poster": item['Poster_Url'] if 'Poster_Url' in item else None,
                                        "overview": "Loaded from collection."
                                    }
                                    st.rerun()
            else:
                st.info("Your collection is empty. Use the sidebar search to add items!")
                
        except Exception as e:
            st.warning("Could not load database. Ensure secrets.toml is set up and Google Sheet has correct headers.")
            st.code(str(e))
            st.markdown("Required Sheet Headers: `ID`, `Title`, `Type`, `Status`, `Score`, `Current_Progress`, `External_ID`, `Poster_Url`")

if __name__ == "__main__":
    main()
