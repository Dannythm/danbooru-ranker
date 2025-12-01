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
import threading

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

def get_sd_models(api_url):
    try:
        response = requests.get(f"{api_url}/sdapi/v1/sd-models", timeout=5)
        response.raise_for_status()
        return [m["title"] for m in response.json()]
    except Exception as e:
        print(f"Error fetching models from {api_url}: {e}")
        return []

def set_sd_model(model_title, api_url):
    payload = {"sd_model_checkpoint": model_title}
    try:
        requests.post(f"{api_url}/sdapi/v1/options", json=payload, timeout=300)
        print(f"[{api_url}] Switched model to: {model_title}")
        return True
    except Exception as e:
        print(f"[{api_url}] Error setting model: {e}")
        return False

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
        response = requests.post(f"{api_url}/sdapi/v1/txt2img", json=payload, timeout=300)
        response.raise_for_status()
        r = response.json()
        return r["images"][0] # Base64 string
    except Exception as e:
        print(f"[{api_url}] Error generating image: {e}")
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

def get_workload_for_model(db, model_name, args):
    """
    Identifies images needing generation for a specific model.
    Prioritizes authors with ZERO generations, then PARTIAL generations.
    Strictly checks for missing images.
    """
    images_collection = db["images"]
    generations_collection = db["generations"]
    
    # 1. Resolve full model name
    # We need a real instance to check model name, but for planning we can just use the requested name
    # and verify it later on the worker.
    
    print(f"Analyzing workload for model: {model_name}...")
    
    query = {}
    if args.authors:
        author_ids = [int(aid.strip()) for aid in args.authors.split(",") if aid.strip()]
        query["_id"] = {"$in": author_ids}
    
    all_authors = list(db.authors.find(query))
    
    zero_gen_authors = []
    partial_gen_authors = []
    
    # Pre-fetch all generations for this model to minimize DB hits? 
    # Or just query per author. Query per author is safer for memory if DB is huge, 
    # but slower. Let's do per author for now.
    
    # We need the EXACT model name stored in DB. 
    # If the user passed a partial name (e.g. "pony"), we might have issues if we don't resolve it first.
    # However, we can't resolve it without hitting an API. 
    # We'll assume the worker resolves it and we just use the user-provided string for 'planning' 
    # but we need to check the DB against the *actual* model name used in previous gens.
    # This is tricky. 
    # SOLUTION: We will resolve the model name on the FIRST available instance before planning.
    
    return all_authors

def resolve_model_name(model_query, api_url):
    available = get_sd_models(api_url)
    for m in available:
        if model_query.lower() in m.lower():
            return m
    return None

def process_image_task(db, image, model_full_name, args, api_url):
    """
    Generates a single image on the specified API URL.
    """
    try:
        image_id = image["_id"]
        generations_collection = db["generations"]
        
        # Double check existence (race condition protection)
        existing = generations_collection.find_one({
            "original_image_id": image_id,
            "model": model_full_name,
            "steps": args.steps,
            "cfg": args.cfg
        })
        if existing:
            return {"status": "skipped", "msg": "Already exists"}

        # Fetch author
        author = db.authors.find_one({"_id": image["author_id"]})
        author_name = author["name"] if author else "unknown"
        
        # Construct Prompt
        prompt_parts = []
        if args.prompt: prompt_parts.append(args.prompt)
        tags = image.get("tags", "").replace(" ", ", ")
        prompt_parts.append(escape_sd_chars(tags))
        prompt_parts.append(escape_sd_chars(author_name))
        full_prompt = ", ".join(part for part in prompt_parts if part)
        
        # Output Path
        model_safe = "".join(c for c in model_full_name if c.isalnum() or c in (' ', '.', '_')).strip().replace(" ", "_")
        artist_safe = "".join(c for c in author_name if c.isalnum() or c in (' ', '.', '_', '-')).strip().replace(" ", "_")
        output_dir = os.path.join(GENERATED_DIR, artist_safe, model_safe)
        os.makedirs(output_dir, exist_ok=True)
        
        # Resolution
        w, h = image.get("width", 512), image.get("height", 512)
        aspect = w / h
        if w > 1024 or h > 1024:
            if w > h: w, h = 1024, int(1024 / aspect)
            else: h, w = 1024, int(1024 * aspect)
        w, h = (w // 8) * 8, (h // 8) * 8
        
        # Generate
        b64 = generate_image(full_prompt, NEGATIVE_PROMPT, args.steps, args.cfg, args.sampler, args.scheduler, w, h, api_url)
        
        if b64:
            filename = f"{image_id}.png"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
                
            gen_data = {
                "original_image_id": image_id,
                "author_id": image["author_id"],
                "model": model_full_name,
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
            return {"status": "failed", "msg": "Generation failed"}
            
    except Exception as e:
        return {"status": "error", "msg": str(e)}

def worker_thread(worker_id, api_url, model_queue, image_queue, db, args, status_lock, shared_status):
    """
    Worker thread that manages a specific SD instance.
    Strategy:
    1. If image_queue is populated (Single Model Mode), process it.
    2. If model_queue is populated (Multi Model Mode), pick a model, load it, then find work for it.
    """
    print(f"[Worker {worker_id}] Started on {api_url}")
    
    while True:
        # Check Control
        if check_control(db) == "cancel":
            break
            
        # MODE 1: Single Model (Shared Image Queue)
        # If the main thread populated image_queue, we just consume it.
        if not image_queue.empty():
            try:
                task = image_queue.get(timeout=1)
                # task = (image_doc, model_full_name)
                image, model_full_name = task
                
                res = process_image_task(db, image, model_full_name, args, api_url)
                
                with status_lock:
                    shared_status['processed'] += 1
                    if res['status'] == 'generated': shared_status['generated'] += 1
                    elif res['status'] == 'skipped': shared_status['skipped'] += 1
                    
                    # Update DB every 5 items or so to reduce load? Or just every time.
                    # Let's do every time for responsiveness.
                    msg = f"[{worker_id}] {res['msg']}"
                    print(msg)
                    update_status(db, "running", 
                                int((shared_status['processed'] / shared_status['total']) * 100) if shared_status['total'] > 0 else 0,
                                msg, shared_status['processed'], shared_status['total'])
                
                image_queue.task_done()
                continue
            except queue.Empty:
                pass

        # MODE 2: Multi Model (Model Queue)
        # If image_queue is empty, maybe we need to pick a model?
        # But wait, if we are in Single Model mode, model_queue will be empty too.
        # If we are in Multi Model mode, image_queue will be empty initially.
        
        if not model_queue.empty():
            try:
                model_req = model_queue.get(timeout=1)
                # model_req = model_name_string
                
                # 1. Resolve and Load Model
                full_model_name = resolve_model_name(model_req, api_url)
                if not full_model_name:
                    print(f"[{worker_id}] Model '{model_req}' not found on {api_url}")
                    model_queue.task_done()
                    continue
                    
                if not set_sd_model(full_model_name, api_url):
                    print(f"[{worker_id}] Failed to set model {full_model_name}")
                    model_queue.task_done()
                    continue
                
                # 2. Find Work for this Model
                # We do this HERE so we check the DB state at the moment of execution
                print(f"[{worker_id}] finding work for {full_model_name}...")
                authors = get_workload_for_model(db, full_model_name, args)
                
                # Prioritize
                zero_gen = []
                partial_gen = []
                
                images_coll = db.images
                gens_coll = db.generations
                
                for a in authors:
                    img_count = images_coll.count_documents({"author_id": a["_id"]})
                    if img_count == 0: continue
                    
                    gen_count = gens_coll.count_documents({"author_id": a["_id"], "model": full_model_name})
                    
                    if gen_count == 0:
                        zero_gen.append(a)
                    elif gen_count < img_count:
                        partial_gen.append(a)
                
                target_authors = zero_gen + partial_gen
                print(f"[{worker_id}] Found {len(zero_gen)} new authors and {len(partial_gen)} partial authors for {full_model_name}")
                
                # Collect Images
                tasks = []
                for a in target_authors:
                    imgs = list(images_coll.find({"author_id": a["_id"]}))
                    for img in imgs:
                        # Strict check
                        if not gens_coll.find_one({"original_image_id": img["_id"], "model": full_model_name, "steps": args.steps, "cfg": args.cfg}):
                            tasks.append(img)
                            if args.limit > 0 and len(tasks) >= args.limit: break
                    if args.limit > 0 and len(tasks) >= args.limit: break
                
                print(f"[{worker_id}] Queued {len(tasks)} images for {full_model_name}")
                
                with status_lock:
                    shared_status['total'] += len(tasks)
                
                # Process these images locally on this worker
                for img in tasks:
                    if check_control(db) == "cancel": break
                    
                    res = process_image_task(db, img, full_model_name, args, api_url)
                    
                    with status_lock:
                        shared_status['processed'] += 1
                        if res['status'] == 'generated': shared_status['generated'] += 1
                        elif res['status'] == 'skipped': shared_status['skipped'] += 1
                        
                        msg = f"[{worker_id}] {res['msg']}"
                        print(msg)
                        update_status(db, "running", 
                                    int((shared_status['processed'] / shared_status['total']) * 100) if shared_status['total'] > 0 else 0,
                                    msg, shared_status['processed'], shared_status['total'])
                
                model_queue.task_done()
                
            except queue.Empty:
                pass
        else:
            # Both queues empty
            # If we are in multi-model mode, we are done when model_queue is empty.
            # If we are in single-model mode, we are done when image_queue is empty.
            # We can break if both are empty?
            if image_queue.empty() and model_queue.empty():
                break
            time.sleep(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs='+', required=True)
    parser.add_argument("--steps", type=int, default=28)
    parser.add_argument("--cfg", type=float, default=7.0)
    parser.add_argument("--sampler", type=str, default="Euler a")
    parser.add_argument("--scheduler", type=str, default="Automatic")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--prompt", type=str, default="")
    parser.add_argument("--authors", type=str, default="")
    parser.add_argument("--skip-existing-authors", action="store_true") # Deprecated but kept for compat
    args = parser.parse_args()

    db = get_db()
    print(f"Loaded {len(SD_API_URLS)} SD instances: {SD_API_URLS}")
    
    # Shared State
    model_queue = queue.Queue()
    image_queue = queue.Queue()
    
    status_lock = threading.Lock()
    shared_status = {
        'total': 0,
        'processed': 0,
        'generated': 0,
        'skipped': 0
    }
    
    # Strategy Selection
    if len(args.models) == 1:
        print("--- Single Model Mode ---")
        # 1. Resolve Model Name (using first instance)
        target_model_query = args.models[0]
        full_model_name = resolve_model_name(target_model_query, SD_API_URLS[0])
        
        if not full_model_name:
            print(f"Model {target_model_query} not found!")
            return

        # 2. Set Model on ALL instances
        print(f"Setting model {full_model_name} on all instances...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(SD_API_URLS)) as executor:
            futures = [executor.submit(set_sd_model, full_model_name, url) for url in SD_API_URLS]
            concurrent.futures.wait(futures)
            
        # 3. Plan Workload
        print("Planning workload...")
        authors = get_workload_for_model(db, full_model_name, args)
        
        # Prioritize
        zero_gen = []
        partial_gen = []
        images_coll = db["images"]
        gens_coll = db["generations"]
        
        for a in authors:
            img_count = images_coll.count_documents({"author_id": a["_id"]})
            if img_count == 0: continue
            gen_count = gens_coll.count_documents({"author_id": a["_id"], "model": full_model_name})
            
            if gen_count == 0: zero_gen.append(a)
            elif gen_count < img_count: partial_gen.append(a)
            
        target_authors = zero_gen + partial_gen
        print(f"Found {len(zero_gen)} new authors and {len(partial_gen)} partial authors.")
        
        tasks = []
        for a in target_authors:
            imgs = list(images_coll.find({"author_id": a["_id"]}))
            for img in imgs:
                if not gens_coll.find_one({"original_image_id": img["_id"], "model": full_model_name, "steps": args.steps, "cfg": args.cfg}):
                    tasks.append((img, full_model_name))
                    if args.limit > 0 and len(tasks) >= args.limit: break
            if args.limit > 0 and len(tasks) >= args.limit: break
            
        print(f"Queued {len(tasks)} images total.")
        shared_status['total'] = len(tasks)
        
        for t in tasks:
            image_queue.put(t)
            
    else:
        print("--- Multi-Model Mode ---")
        # Just populate the model queue
        # Workers will pick a model, resolve it, find work, and execute it.
        for m in args.models:
            model_queue.put(m)
            
    # Start Workers
    threads = []
    for i, url in enumerate(SD_API_URLS):
        t = threading.Thread(target=worker_thread, args=(i, url, model_queue, image_queue, db, args, status_lock, shared_status))
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()
        
    print("All tasks complete.")
    update_status(db, "idle", 100, f"Complete. Generated: {shared_status['generated']}, Skipped: {shared_status['skipped']}", 0, 0)

if __name__ == "__main__":
    main()
