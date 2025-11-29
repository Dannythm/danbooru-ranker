
from pymongo import MongoClient
from collections import Counter

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "danbooru_ranker"

from datetime import datetime

def update_status(db, status, progress=0, message="", current=0, total=0):
    db.system_status.update_one(
        {"_id": "aggregator"},
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

def aggregate_styles():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    print("Aggregating styles for authors...")
    
    total_authors = db.authors.count_documents({})
    update_status(db, "running", 0, "Starting aggregation...", 0, total_authors)
    
    authors = db.authors.find({})
    count = 0
    processed = 0
    
    for author in authors:
        processed += 1
        progress = int((processed / total_authors) * 100) if total_authors > 0 else 0
        
        if processed % 10 == 0:
            msg = f"Processed {processed}/{total_authors} authors"
            print(msg)
            update_status(db, "running", progress, msg, processed, total_authors)
            
        author_id = author["_id"]
        
        # Get all images for this author
        images = list(db.images.find({"author_id": author_id}))
        
        if not images:
            continue
            
        styles = []
        for img in images:
            if "style_category" in img:
                styles.append(img["style_category"])
        
        if styles:
            # Find most common style
            most_common = Counter(styles).most_common(1)[0][0]
            
            # Update author
            db.authors.update_one(
                {"_id": author_id},
                {"$set": {"style_category": most_common}}
            )
            count += 1
            
    print(f"Updated {count} authors with style categories.")
    update_status(db, "idle", 100, f"Aggregation complete. Updated {count} authors.", processed, total_authors)

if __name__ == "__main__":
    aggregate_styles()
