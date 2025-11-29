import requests
import time
import os
from datetime import datetime

# Gelbooru API
GELBOORU_API_URL = "https://gelbooru.com/index.php"
USER_AGENT = "DanbooruRanker/1.0"
DELAY = 1.0

class GelbooruScraper:
    def __init__(self):
        self.headers = {"User-Agent": USER_AGENT}

    def fetch_images_for_artist(self, artist_name, limit=5):
        """Fetch images for an artist from Gelbooru"""
        print(f"Fetching images for {artist_name} from Gelbooru...")
        
        # Gelbooru uses tags for searching. Artist name is a tag.
        # We need to handle special characters if necessary, but usually name is enough.
        tags = f"{artist_name} rating:general" # Prefer general, but maybe we want all?
        # Let's try to get safe/general first, or just all and filter?
        # User didn't specify rating, but Danbooru scraper defaults to safe/general usually?
        # Actually Danbooru scraper didn't filter by rating explicitly in the URL params I saw earlier, 
        # but let's stick to just the artist tag to get *something*.
        
        params = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": 1,
            "tags": artist_name,
            "limit": limit
        }
        
        try:
            response = requests.get(GELBOORU_API_URL, params=params, headers=self.headers)
            response.raise_for_status()
            # Gelbooru returns raw JSON list or empty
            data = response.json()
            
            # Gelbooru sometimes returns a dict with 'post' key if XML converted? 
            # But json=1 usually returns list of dicts or dict with 'post' key.
            # Let's check the structure.
            # Recent Gelbooru API (0.2.5) returns {"post": [...]} or just [...] depending on version/impl.
            # Let's handle both.
            
            posts = []
            if isinstance(data, list):
                posts = data
            elif isinstance(data, dict) and "post" in data:
                posts = data["post"]
                
            return posts
            
        except Exception as e:
            print(f"Error fetching from Gelbooru for {artist_name}: {e}")
            return []

    def map_post_to_image_data(self, post, author_id, author_name):
        """Map Gelbooru post to our Image schema"""
        # Gelbooru post keys: id, file_url, width, height, tags, created_at, etc.
        
        return {
            "_id": int(post["id"]) + 1000000000, # Offset ID to avoid collision with Danbooru? Or just use it.
            # Danbooru IDs are usually < 10M. Gelbooru IDs are also < 10M usually.
            # To avoid collision, let's add a large offset or use a prefix if _id was string.
            # Since _id is int, let's add 1,000,000,000 (1 billion).
            
            "author_id": author_id,
            "author_name": author_name,
            "tags": post.get("tags", ""),
            "file_url": post.get("file_url"),
            "local_path": "", # To be filled after download
            "width": int(post.get("width", 0)),
            "height": int(post.get("height", 0)),
            "created_at": post.get("created_at"), # Format might differ
            "fetched_at": datetime.now(),
            "source": "gelbooru"
        }
