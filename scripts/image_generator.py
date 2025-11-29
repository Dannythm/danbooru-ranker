import requests
import base64
import time
import os
import pymongo
import argparse
from datetime import datetime
import sys
import concurrent.futures
import queue

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MONGO_URI, DB_NAME, SD_API_URLS, GENERATED_DIR

# Quality Prompts
QUALITY_PROMPT = "masterpiece, best quality, very aesthetic, absurdres"
NEGATIVE_PROMPT = "low quality, worst quality, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, jpeg artifacts, signature, watermark, username, blurry"

def get_db():
    client = pymongo.MongoClient(MONGO_URI)
    return client[DB_NAME]

def escape_sd_chars(text):
    if not text:
        return ""
    text = text.replace('(', r'\(')
    text = text.replace(')', r'\)')
    text = text.replace('[', r'\[')
    text = text.replace(']', r'\]')
    return text

def get_sd_models(api_url=None):
    url = api_url or SD_API_URLS[0]
    try:
        response = requests.get(f"{url}/sdapi/v1/sd-models")
        response.raise_for_status()
        return [m["title"] for m in response.json()]
    except Exception as e:
        print(f"Error fetching models from {url}: {e}")
        return []

def set_sd_model(model_title, api_url):
    payload = {"sd_model_checkpoint": model_title}
    try:
        requests.post(f"{api_url}/sdapi/v1/options", json=payload)
        print(f"Switched model to: {model_title} on {api_url}")
    except Exception as e:
        print(f"Error setting model on {api_url}: {e}")

def generate_image(prompt, negative_prompt, steps, cfg_scale, sampler_name, scheduler, width, height, api_url, seed=-1):
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_name": sampler_name,
        "scheduler": scheduler,
        "width": width,
        "height": height,
        "seed": seed
    }
    
    try:
        response = requests.post(f"{api_url}/sdapi/v1/txt2img", json=payload)
        response.raise_for_status()
        r = response.json()
        return r["images"][0] # Base64 string
    except Exception as e:
        print(f"Error generating image on {api_url}: {e}")
        return None

def update_status(db, status, progress=0, message="", current=0, total=0):
    db.system_status.update_one(
        {"_id": "generator"},
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

def check_control(db, task_id="generator"):
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

def process_image(image, model_name, target_model, args, db, url_queue, model_safe_name):
    api_url = url_queue.get()
    try:
        image_id = image["_id"]
        generations_collection = db["generations"]
        
        # Check if already generated (double check inside worker to be safe)
        existing = generations_collection.find_one({
            "original_image_id": image_id,
            "model": target_model,
            "steps": args.steps,
            "cfg": args.cfg
        })
        
        if existing:
            return {"status": "skipped", "msg": f"Skipping {image_id} (already exists)"}

        # Fetch author name
        author = db.authors.find_one({"_id": image["author_id"]})
        author_name = author["name"] if author else "unknown"
        
        # Construct Prompt
        prompt_parts = []
        if args.prompt:
            prompt_parts.append(args.prompt)
            
        tags = image.get("tags", "").replace(" ", ", ")
        escaped_tags = escape_sd_chars(tags)
        prompt_parts.append(escaped_tags)
        
        escaped_artist = escape_sd_chars(author_name)
        prompt_parts.append(escaped_artist)
        
        full_prompt = ", ".join(part for part in prompt_parts if part)
        
        # Folder Structure
        artist_safe = "".join(c for c in author_name if c.isalnum() or c in (' ', '.', '_', '-')).strip().replace(" ", "_")
        output_dir = os.path.join(GENERATED_DIR, artist_safe, model_safe_name)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # Resolution
        w, h = image.get("width", 512), image.get("height", 512)
        aspect = w / h
        if w > 1024 or h > 1024:
            if w > h:
                w = 1024
                h = int(1024 / aspect)
            else:
                h = 1024
                w = int(1024 * aspect)
        
        w = (w // 8) * 8
        h = (h // 8) * 8

        # Generate
        b64_image = generate_image(
            prompt=full_prompt,
            negative_prompt=NEGATIVE_PROMPT,
            steps=args.steps,
            cfg_scale=args.cfg,
            sampler_name=args.sampler,
            scheduler=args.scheduler,
            width=w,
            height=h,
            api_url=api_url
        )
        
        if b64_image:
            filename = f"{image_id}.png"
            file_path = os.path.join(output_dir, filename)
            
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_image))
            
            gen_data = {
                "original_image_id": image_id,
                "author_id": image["author_id"],
                "model": target_model,
                "prompt": full_prompt,
                "negative_prompt": NEGATIVE_PROMPT,
                "steps": args.steps,
                "cfg": args.cfg,
                "sampler": args.sampler,
                "scheduler": args.scheduler,
                "local_path": file_path,
                "created_at": datetime.now()
            }
            generations_collection.insert_one(gen_data)
            return {"status": "generated", "msg": f"Generated {filename}"}
        else:
            return {"status": "failed", "msg": "Failed to generate"}
            
    except Exception as e:
        return {"status": "error", "msg": str(e)}
    finally:
        url_queue.put(api_url)

def main():
    parser = argparse.ArgumentParser(description="SD Image Generator")
    parser.add_argument("--models", nargs='+', required=True, help="List of SD Model Checkpoints")
    parser.add_argument("--steps", type=int, default=28, help="Sampling steps")
    parser.add_argument("--cfg", type=float, default=7.0, help="CFG Scale")
    parser.add_argument("--sampler", type=str, default="Euler a", help="Sampler name")
    parser.add_argument("--scheduler", type=str, default="Automatic", help="Scheduler name")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of generations (0 for all)")
    parser.add_argument("--prompt", type=str, default="", help="Prompt suffix")
    parser.add_argument("--authors", type=str, default="", help="Comma separated author IDs to filter")
    parser.add_argument("--skip-existing-authors", action="store_true", help="Skip authors who already have generations")
    args = parser.parse_args()

    db = get_db()
    images_collection = db["images"]
    generations_collection = db["generations"]

    # Initialize URL Queue
    url_queue = queue.Queue()
    for url in SD_API_URLS:
        url_queue.put(url)

    try:
        total_models = len(args.models)
        current_model_idx = 0

        for model_name in args.models:
            current_model_idx += 1
            print(f"\n--- Processing Model {current_model_idx}/{total_models}: {model_name} ---")
            
            # 1. Select Model
            available_models = get_sd_models() # Check first URL for models
            target_model = None
            for m in available_models:
                if model_name.lower() in m.lower():
                    target_model = m
                    break
            
            if not target_model:
                print(f"Model matching '{model_name}' not found. Available: {available_models}")
                continue
            else:
                # Set model on ALL instances
                print(f"Setting model to {target_model} on all instances...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(SD_API_URLS)) as executor:
                    futures = [executor.submit(set_sd_model, target_model, url) for url in SD_API_URLS]
                    concurrent.futures.wait(futures)

            # 2. Determine Images to Process
            query = {}
            if args.authors:
                author_ids = [int(aid.strip()) for aid in args.authors.split(",") if aid.strip()]
                query["author_id"] = {"$in": author_ids}
                target_images = list(images_collection.find(query))
            else:
                print("Finding authors with no generations...")
                update_status(db, "running", 0, "Finding authors with no generations...", 0, 0)
                
                all_authors = db.authors.find({})
                valid_author_ids = []
                
                for a in all_authors:
                    gen_count = generations_collection.count_documents({"author_id": a["_id"], "model": target_model})
                    if gen_count == 0:
                        valid_author_ids.append(a["_id"])
                
                print(f"Found {len(valid_author_ids)} authors with no generations.")
                
                if valid_author_ids:
                    print(f"Fetching all images for {len(valid_author_ids)} authors...")
                    target_images = list(images_collection.find({"author_id": {"$in": valid_author_ids}}))
                    print(f"Found {len(target_images)} images to process.")
                else:
                    print("All authors have generations. No new images to process.")
                    target_images = []

            if not target_images:
                print(f"No images found to process for model {model_name}.")
                continue

            total_images = len(target_images)
            if args.limit > 0:
                total_images = min(total_images, args.limit)
                target_images = target_images[:total_images]
                
            update_status(db, "running", 0, f"Starting generation with {target_model}...", 0, total_images)

            processed = 0
            skipped_count = 0
            generated_count = 0
            
            model_safe_name = "".join(c for c in model_name if c.isalnum() or c in (' ', '.', '_')).strip().replace(" ", "_")

            # Parallel Processing
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(SD_API_URLS)) as executor:
                active_futures = set()
                image_iter = iter(target_images)
                
                # Initial fill
                for _ in range(len(SD_API_URLS)):
                    try:
                        img = next(image_iter)
                        active_futures.add(executor.submit(process_image, img, model_name, target_model, args, db, url_queue, model_safe_name))
                    except StopIteration:
                        break
                
                while active_futures:
                    # Check control
                    if check_control(db) == "cancel":
                        print("Generator cancelled.")
                        executor.shutdown(wait=False, cancel_futures=True)
                        return

                    # Wait for one to finish
                    done, active_futures = concurrent.futures.wait(active_futures, return_when=concurrent.futures.FIRST_COMPLETED)
                    
                    for future in done:
                        result = future.result()
                        processed += 1
                        progress = int((processed / total_images) * 100) if total_images > 0 else 0
                        
                        if result["status"] == "generated":
                            generated_count += 1
                            msg = f"Generated ({processed}/{total_images})"
                            print(msg)
                        elif result["status"] == "skipped":
                            skipped_count += 1
                            msg = f"Skipped ({processed}/{total_images})"
                        else:
                            msg = f"Failed: {result['msg']}"
                            print(msg)
                            
                        update_status(db, "running", progress, msg, processed, total_images)
                        
                        # Submit next
                        try:
                            img = next(image_iter)
                            active_futures.add(executor.submit(process_image, img, model_name, target_model, args, db, url_queue, model_safe_name))
                        except StopIteration:
                            pass

            print(f"--- Model {model_name} Complete ---")
            print(f"Generated: {generated_count}, Skipped: {skipped_count}")
            update_status(db, "running", 100, f"Model {model_name} complete. Generated: {generated_count}, Skipped: {skipped_count}", total_images, total_images)
            time.sleep(2)

        update_status(db, "idle", 100, "All generations complete", 0, 0)
        print("All generations complete")

    except Exception as e:
        print(f"Generator failed: {e}")
        update_status(db, "error", 0, f"Error: {str(e)}", 0, 0)

if __name__ == "__main__":
    main()
