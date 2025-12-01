import requests
import time
import os
import pymongo
from datetime import datetime
import argparse
import sys

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MONGO_URI, DB_NAME, DANBOORU_API_URL, USER_AGENT, IMAGES_DIR
from gelbooru_scraper import GelbooruScraper

# Rate Limiting
DELAY = 1.0  # Seconds between requests

def get_db():
    client = pymongo.MongoClient(MONGO_URI)
    return client[DB_NAME]

def fetch_json(url, params=None):
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        time.sleep(DELAY)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        time.sleep(DELAY)
        return None

def download_image(url, file_path):
    if os.path.exists(file_path):
        return True
    
    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        time.sleep(DELAY)
        return True
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return False

def update_status(db, status, progress=0, message="", current=0, total=0):
    db.system_status.update_one(
        {"_id": "scraper"},
        {"$set": {
            "status": status,
            "progress": progress,
            "current": current,
            "total": total,
            "message": message,
            "updated_at": datetime.now()
        }},
        upsert=True
    )

def check_control(db, task_id="scraper"):
    status = db.system_status.find_one({"_id": task_id})
    if not status:
        return "running"
    
    control = status.get("control", "running")
    if control == "pause":
        print(f"Task {task_id} paused...")
        update_status(db, "paused", status.get("progress", 0), "Paused", status.get("current", 0), status.get("total", 0))
        while True:
            time.sleep(1)
            status = db.system_status.find_one({"_id": task_id})
            if status.get("control") != "pause":
                print(f"Task {task_id} resumed!")
                update_status(db, "running", status.get("progress", 0), status.get("message", "Resumed"), status.get("current", 0), status.get("total", 0))
                break
            if status.get("control") == "cancel":
                return "cancel"
    
    return control

def fetch_authors(db, limit=100, min_posts=50):
    """Fetch top authors from Danbooru by post count
    
    Note: min_posts parameter is kept for API compatibility but not used for filtering
    because the Danbooru API doesn't return post_count in responses. However, the API
    does sort by post_count (descending), so we naturally get the most active artists first.
    """
    print(f"Scanning for {limit} NEW authors (sorted by activity)...")
    update_status(db, "running", 0, f"Scanning for {limit} NEW authors...", 0, 0)
    
    page = 1
    authors_collection = db["authors"]
    fetched_new_count = 0
    target_new_count = limit
    max_pages = 1000 # Safety limit
    
    while fetched_new_count < target_new_count and page <= max_pages:
        if check_control(db) == "cancel":
            print("Scraper cancelled.")
            return fetched_new_count
            
        msg = f"Scanning page {page}... (Found {fetched_new_count}/{target_new_count} new)"
        print(msg)
        update_status(db, "running", int((fetched_new_count / target_new_count) * 10), msg, fetched_new_count, target_new_count)
        
        data = fetch_json(f"{DANBOORU_API_URL}/artists.json", params={
            "search[order]": "post_count",
            "limit": 100,
            "page": page
        })
        
        if not data or len(data) == 0:
            print(f"No more artists found at page {page}")
            break
            
        # Optimize: Check which ones exist in batch
        ids = [a["id"] for a in data]
        existing = authors_collection.find({"_id": {"$in": ids}}, {"_id": 1})
        existing_ids = set(doc["_id"] for doc in existing)
            
        for artist in data:
            if check_control(db) == "cancel":
                print("Scraper cancelled.")
                return fetched_new_count
            if artist["id"] in existing_ids:
                continue
                
            author_data = {
                "_id": artist["id"],
                "name": artist["name"],
                "other_names": artist.get("other_names", []),
                "urls": artist.get("urls", []),
                "updated_at": datetime.now()
            }
            
            authors_collection.insert_one(author_data)
            fetched_new_count += 1
            
            if fetched_new_count >= target_new_count:
                break
        
        page += 1
    
    print(f"Added {fetched_new_count} new authors")
    return fetched_new_count

def fetch_posts_for_authors(db, max_images=10, limit_authors=0):
    """Fetch images only for authors that don't have any images yet"""
    # Get all authors
    all_authors = list(db["authors"].find({}))
    
    # Filter to only those without images
    authors_needing_images = []
    for author in all_authors:
        if check_control(db) == "cancel":
            print("Scraper cancelled.")
            return
        image_count = db["images"].count_documents({"author_id": author["_id"]})
        if image_count == 0:
            authors_needing_images.append(author)
            if limit_authors > 0 and len(authors_needing_images) >= limit_authors:
                break  # Stop once we have enough
    
    total_authors = len(authors_needing_images)
    
    print(f"Processing {total_authors} authors that need images (out of {len(all_authors)} total, {len(all_authors) - len([a for a in all_authors if db['images'].count_documents({'author_id': a['_id']}) == 0])} already have images)")
    
    images_collection = db["images"]
    
    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)

    gelbooru = GelbooruScraper()
    processed = 0
    for author in authors_needing_images:
        author_id = author["_id"]
        author_name = author["name"]
        
        processed += 1
        progress = int((processed / total_authors) * 90) + 10  # 10-100%
        msg = f"Processing {author_name} ({processed}/{total_authors})"
        print(msg)
        update_status(db, "running", progress, msg, processed, total_authors)
        
        # Fetch posts for this artist with pagination
        downloaded_count = 0
        page = 1
        consecutive_empty_pages = 0
        
        while downloaded_count < max_images:
            if check_control(db) == "cancel":
                print("Scraper cancelled.")
                return

            # Calculate batch size (max 100 per request to be safe)
            batch_size = min(max_images - downloaded_count, 100)
            
            print(f"  Fetching page {page} for {author_name} (Need {max_images - downloaded_count} more)...")
            
            # Try Danbooru first
            source = "danbooru"
            posts_data = fetch_json(f"{DANBOORU_API_URL}/posts.json", params={
                "tags": author_name.replace(" ", "_"),
                "limit": batch_size,
                "page": page
            })
            
            # If Danbooru fails/empty on first page, try Gelbooru (only once for now as fallback)
            if not posts_data and page == 1:
                print(f"  No posts found on Danbooru for {author_name}, trying Gelbooru...")
                # Gelbooru fallback - currently just one batch
                posts_data = gelbooru.fetch_images_for_artist(author_name, limit=max_images)
                source = "gelbooru"
                
            if not posts_data:
                print(f"  No more posts found for {author_name}")
                break
                
            posts_processed_in_batch = 0
            for post in posts_data:
                if downloaded_count >= max_images:
                    break
                    
                if source == "gelbooru":
                    # Map Gelbooru post to our structure
                    image_data = gelbooru.map_post_to_image_data(post, author_id, author_name)
                    post_id = image_data["_id"]
                    file_url = image_data["file_url"]
                    if file_url:
                        ext = file_url.split('.')[-1]
                    else:
                        ext = "jpg"
                else:
                    # Danbooru post
                    post_id = post.get("id")
                    file_url = post.get("file_url")
                    ext = post.get("file_ext", "jpg")
                
                if not file_url:
                    continue
                
                # Skip non-image files (videos, etc.)
                if ext.lower() in ['mp4', 'webm', 'gif', 'zip', 'swf']:
                    print(f"  Skipping non-image file: {post_id}.{ext}")
                    continue
                    
                # Check if we already have this image
                if images_collection.count_documents({"_id": post_id}) > 0:
                    # print(f"  Image {post_id} already exists, skipping")
                    continue
                    
                # Download image
                filename = f"{post_id}.{ext}"
                
                # Sanitize artist name for folder
                safe_artist_name = "".join(c for c in author_name if c.isalnum() or c in (' ', '.', '_')).strip().replace(" ", "_")
                artist_dir = os.path.join(IMAGES_DIR, safe_artist_name)
                
                if not os.path.exists(artist_dir):
                    os.makedirs(artist_dir)
                    
                file_path = os.path.join(artist_dir, filename)
                
                if download_image(file_url, file_path):
                    # Save to DB
                    if source == "danbooru":
                        image_data = {
                            "_id": post_id,
                            "author_id": author_id,
                            "author_name": author_name,
                            "tags": post.get("tag_string", ""),
                            "file_url": file_url,
                            "local_path": file_path,
                            "width": post.get("image_width"),
                            "height": post.get("image_height"),
                            "created_at": post.get("created_at"),
                            "fetched_at": datetime.now(),
                            "source": "danbooru"
                        }
                    else:
                        # Already mapped, just update local_path
                        image_data["local_path"] = file_path
                    
                    images_collection.update_one(
                        {"_id": post_id},
                        {"$set": image_data},
                        upsert=True
                    )
                    print(f"  Downloaded {filename} ({downloaded_count + 1}/{max_images})")
                    downloaded_count += 1
                    posts_processed_in_batch += 1
            
            # If we didn't process any posts in this batch (e.g. all existed or invalid), 
            # but we still have posts, we should continue to next page.
            # But if source is Gelbooru, we don't support pagination yet in this loop structure easily without refactoring GelbooruScraper.
            # So for Gelbooru, we break after one batch.
            if source == "gelbooru":
                break
                
            page += 1

def main():
    parser = argparse.ArgumentParser(description="Danbooru Scraper")
    parser.add_argument("--limit-authors", type=int, default=10, help="Number of authors to fetch from Danbooru")
    parser.add_argument("--max-images", type=int, default=5, help="Max images per author")
    parser.add_argument("--min-posts", type=int, default=50, help="Minimum posts required for an artist")
    args = parser.parse_args()

    db = get_db()
    
    try:
        # 1. Fetch Authors (only fetch new ones if needed)
        fetch_authors(db, limit=args.limit_authors, min_posts=args.min_posts)
        
        # 2. Fetch Images (only for authors without images)
        fetch_posts_for_authors(db, max_images=args.max_images, limit_authors=args.limit_authors)
        
        update_status(db, "idle", 100, "Scraping complete", 0, 0)
        print("Scraping complete")
        
    except Exception as e:
        print(f"Scraper failed: {e}")
        update_status(db, "error", 0, f"Error: {str(e)}", 0, 0)

if __name__ == "__main__":
    main()
