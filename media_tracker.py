# --- GALLERY TAB ---
elif tab == "My Gallery":
    st.subheader("My Library")
    
    sheet = get_google_sheet()
    
    if sheet:
        # Fetch all data
        raw_data = sheet.get_all_values()
        HEADERS = ["Title", "Type", "Country", "Status", "Genres", "Image", "Overview", "Rating", "Backdrop", "Current_Season", "Current_Ep", "Total_Eps", "Total_Seasons", "ID"]
        
        if len(raw_data) > 1:
            safe_rows = []
            for row in raw_data[1:]:
                # Skip empty rows
                if not row or not row[0].strip(): continue
                # Ensure row has enough columns
                if len(row) < len(HEADERS): row += [""] * (len(HEADERS) - len(row))
                safe_rows.append(row[:len(HEADERS)])
            
            # Create DataFrame (Index 0, 1, 2... represents the row number)
            df = pd.DataFrame(safe_rows, columns=HEADERS)
            
            # 1. Get Unique Types for Tabs
            unique_types = sorted(df['Type'].unique().tolist())
            
            if unique_types:
                # 2. Create Tabs
                tabs = st.tabs(unique_types)
                
                # 3. Iterate through each tab
                for t, category in zip(tabs, unique_types):
                    with t:
                        # FILTER DATA FOR THIS TAB (Preserving original row indices)
                        subset = df[df['Type'] == category]
                        
                        # --- DRAG & DROP REORDER (Specific to this Tab) ---
                        if HAS_SORTABLES and not subset.empty:
                            with st.expander(f"🔄 Reorder {category}", expanded=False):
                                st.caption("Drag items to change order, then click Save.")
                                
                                subset_titles = subset['Title'].tolist()
                                sorted_titles = sort_items(subset_titles, key=f"sort_{category}")
                                
                                # LOGIC: Update Order safely handling Duplicate Titles
                                if sorted_titles != subset_titles:
                                    if st.button(f"💾 Save {category} Order"):
                                        # 1. Get original indices for this category
                                        original_indices = subset.index.tolist()
                                        
                                        # 2. Map Titles to their Row Indices (Handle Duplicates)
                                        # Example: "Naruto" -> [Row 5, Row 12]
                                        title_map = {}
                                        for idx in original_indices:
                                            title_val = df.loc[idx, 'Title']
                                            if title_val not in title_map: title_map[title_val] = []
                                            title_map[title_val].append(idx)
                                        
                                        # 3. Build the new list of indices based on the user's sorted titles
                                        new_order_indices = []
                                        for title in sorted_titles:
                                            if title in title_map and title_map[title]:
                                                # Pop the first available index for this title
                                                new_order_indices.append(title_map[title].pop(0))
                                        
                                        # 4. Apply this new order to the Global DataFrame
                                        # We keep non-category items where they are, and just shuffle the category items
                                        final_global_indices = df.index.tolist()
                                        
                                        # Sort the original slots (so we fill them top-to-bottom)
                                        slots_to_fill = sorted(original_indices)
                                        
                                        # Place the new sorted items into those slots
                                        for slot, new_idx in zip(slots_to_fill, new_order_indices):
                                            final_global_indices[slot] = new_idx
                                            
                                        # 5. Reorder the actual DataFrame
                                        new_df = df.iloc[final_global_indices].reset_index(drop=True)
                                        
                                        # 6. Save
                                        bulk_update_order(new_df)

                        # --- GRID DISPLAY ---
                        if not subset.empty:
                            cols_per_row = 5
                            rows = [subset.iloc[i:i + cols_per_row] for i in range(0, len(subset), cols_per_row)]
                            
                            for row_chunk in rows:
                                cols = st.columns(cols_per_row)
                                for col, (index, item) in zip(cols, row_chunk.iterrows()):
                                    with col:
                                        img = item.get('Image', '')
                                        if not img.startswith("http"): img = "https://via.placeholder.com/200x300?text=No+Image"
                                        st.image(img, use_container_width=True)
                                        
                                        st.markdown(f"**{item['Title']}**")
                                        unique_key = f"{category}_{index}"
                                        
                                        with st.popover("📜 Overview"):
                                            st.write(f"**Status:** {item['Status']}")
                                            st.write(f"**Rating:** {item['Rating']}")
                                            st.caption(item['Overview'])
                                            
                                            if item['Type'] == "Anime":
                                                st.link_button("📺 Search Anikai", f"https://www.google.com/search?q=site:anikai.to+{item['Title']}")
                                            
                                        with st.expander("⚙️ Manage"):
                                            # Status Management
                                            opts = ["Plan to Watch", "Watching", "Completed", "Dropped"]
                                            curr = item.get('Status', 'Plan to Watch')
                                            if curr not in opts: curr = "Plan to Watch"
                                            new_s = st.selectbox("Status", opts, key=f"st_{unique_key}", index=opts.index(curr))
                                            
                                            # Ep/Season Management
                                            if item['Type'] != "Movies":
                                                try: c_sea = int(item.get('Current_Season', 1))
                                                except: c_sea = 1
                                                try: c_ep = int(item.get('Current_Ep', 0))
                                                except: c_ep = 0
                                                
                                                sea_lbl = "Vol." if "Manga" in item['Type'] else "S"
                                                ep_lbl = "Ch." if "Manga" in item['Type'] else "E"
                                                
                                                col_s, col_e = st.columns(2)
                                                with col_s: new_sea = st.number_input(sea_lbl, min_value=1, value=c_sea, key=f"s_{unique_key}")
                                                with col_e: new_ep = st.number_input(ep_lbl, min_value=0, value=c_ep, key=f"e_{unique_key}")
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
                            st.info(f"No {category} items found.")
            else:
                st.info("Library Empty.")
        else:
            st.info("Library Empty.")
    else:
        st.error("Connection Failed. Check Secrets.")
