
import os
import sys
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from pymongo import MongoClient
from bs4 import BeautifulSoup
import requests
from io import BytesIO
import numpy as np
from tqdm import tqdm

# Configuration
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "danbooru_ranker"
HTML_FILE = r'h:/MEGA/AG/Artists_Gens.html'
SAMPLES_DIR = r'h:/MEGA/AG/Artists_Gens_files/samples'
MODEL_ID = "openai/clip-vit-base-patch32"
BATCH_SIZE = 32

def get_device():
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

from datetime import datetime

def update_status(db, status, progress=0, message="", current=0, total=0):
    db.system_status.update_one(
        {"_id": "style_analyzer"},
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

def parse_ground_truth(db):
    """Parses the HTML file to get Artist -> (Category, ImagePath) mapping."""
    print(f"Parsing {HTML_FILE}...")
    update_status(db, "running", 0, "Parsing ground truth HTML...", 0, 0)
    
    if not os.path.exists(HTML_FILE):
        print(f"Error: File not found: {HTML_FILE}")
        return {}

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    # Mapping: Category -> List of image paths
    category_images = {}
    
    headers = soup.find_all('h3')
    
    for h3 in headers:
        category_name = h3.get_text(strip=True).replace('¶', '').strip()
        if category_name not in category_images:
            category_images[category_name] = []
        
        # Find the next div which should contain the table
        curr = h3.next_sibling
        table = None
        for _ in range(5):
            if curr and curr.name == 'div':
                table = curr.find('table')
                if table:
                    break
            curr = curr.next_sibling if curr else None
            
        if table:
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    # Col 0: Artist Name
                    # Col 1: Sample Image
                    img_tag = cols[1].find('img')
                    if img_tag and img_tag.get('src'):
                        src = img_tag['src']
                        # src is like "./Artists_Gens_files/samples/filename.jpg"
                        filename = os.path.basename(src)
                        local_path = os.path.join(SAMPLES_DIR, filename)
                        if os.path.exists(local_path):
                            category_images[category_name].append(local_path)
    
    total_images = sum(len(imgs) for imgs in category_images.values())
    print(f"Found {total_images} sample images across {len(category_images)} categories.")
    return category_images

def load_model(device, db):
    print(f"Loading CLIP model ({MODEL_ID}) on {device}...")
    update_status(db, "running", 5, "Loading CLIP model...", 0, 0)
    model = CLIPModel.from_pretrained(MODEL_ID).to(device)
    processor = CLIPProcessor.from_pretrained(MODEL_ID)
    return model, processor

def compute_centroids(db, category_images, model, processor, device):
    print("Computing category centroids from sample images...")
    update_status(db, "running", 10, "Computing centroids...", 0, len(category_images))
    
    category_embeddings = {} # category -> centroid
    
    total_cats = len(category_images)
    processed_cats = 0
    
    for cat, image_paths in category_images.items():
        processed_cats += 1
        msg = f"Processing category: {cat} ({len(image_paths)} images)"
        print(msg)
        # Map progress 10-30%
        progress = 10 + int((processed_cats / total_cats) * 20)
        update_status(db, "running", progress, msg, processed_cats, total_cats)
        
        embeddings = []
        
        for path in image_paths:
            try:
                image = Image.open(path)
                inputs = processor(images=image, return_tensors="pt").to(device)
                with torch.no_grad():
                    outputs = model.get_image_features(**inputs)
                embeddings.append(outputs.cpu().numpy())
            except Exception as e:
                print(f"Error processing image {path}: {e}")
        
        if embeddings:
            # Stack and compute mean
            stacked = np.vstack(embeddings)
            centroid = np.mean(stacked, axis=0)
            # Normalize centroid
            centroid = centroid / np.linalg.norm(centroid)
            category_embeddings[cat] = centroid
        else:
            print(f"  - No valid images for category {cat}.")
            
    return category_embeddings

def classify_images(db, centroids, model, processor, device):
    print("Classifying all images in database...")
    
    # Get all images that don't have a style_category yet (or update all if needed)
    # For now, let's update all to be safe
    total_images = db.images.count_documents({})
    cursor = db.images.find({})
    
    batch_images = []
    batch_ids = []
    
    processed_count = 0
    update_status(db, "running", 30, "Starting classification...", 0, total_images)
    
    for doc in tqdm(cursor, total=total_images):
        path = doc.get('local_path')
        if not path or not os.path.exists(path):
            processed_count += 1
            continue
            
        try:
            image = Image.open(path)
            batch_images.append(image)
            batch_ids.append(doc['_id'])
            
            if len(batch_images) >= BATCH_SIZE:
                process_batch(db, batch_images, batch_ids, centroids, model, processor, device)
                processed_count += len(batch_images)
                
                # Map progress 30-100%
                progress = 30 + int((processed_count / total_images) * 70)
                msg = f"Classified {processed_count}/{total_images} images"
                update_status(db, "running", progress, msg, processed_count, total_images)
                
                batch_images = []
                batch_ids = []
                
        except Exception as e:
            print(f"Error loading {path}: {e}")
            processed_count += 1
            
    # Process remaining
    if batch_images:
        process_batch(db, batch_images, batch_ids, centroids, model, processor, device)
        processed_count += len(batch_images)
        update_status(db, "running", 100, "Classification complete", processed_count, total_images)

def process_batch(db, images, ids, centroids, model, processor, device):
    try:
        inputs = processor(images=images, return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            image_features = model.get_image_features(**inputs)
        
        # Normalize features
        image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
        image_features = image_features.cpu().numpy()
        
        for i, img_id in enumerate(ids):
            emb = image_features[i]
            
            best_cat = "Unknown"
            best_score = -1.0
            
            for cat, centroid in centroids.items():
                # Cosine similarity
                score = np.dot(emb, centroid.T).item() # centroid is (1, 512) or (512,)
                if score > best_score:
                    best_score = score
                    best_cat = cat
            
            # Update DB
            db.images.update_one(
                {'_id': img_id},
                {'$set': {'style_category': best_cat, 'style_score': float(best_score)}}
            )
            
    except Exception as e:
        print(f"Batch processing error: {e}")

def main():
    device = get_device()
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    try:
        # 1. Parse Ground Truth
        categories = parse_ground_truth(db)
        if not categories:
            print("No categories found. Exiting.")
            update_status(db, "error", 0, "No categories found", 0, 0)
            return

        # 2. Load Model
        model, processor = load_model(device, db)
        
        # 3. Compute Centroids
        centroids = compute_centroids(db, categories, model, processor, device)
        
        if not centroids:
            print("No centroids computed. Exiting.")
            update_status(db, "error", 0, "No centroids computed", 0, 0)
            return
            
        # 4. Classify Images
        classify_images(db, centroids, model, processor, device)
        
        print("Style analysis complete!")
        update_status(db, "idle", 100, "Style analysis complete!", 0, 0)
        
    except Exception as e:
        print(f"Style analysis failed: {e}")
        update_status(db, "error", 0, f"Error: {str(e)}", 0, 0)

if __name__ == "__main__":
    main()
