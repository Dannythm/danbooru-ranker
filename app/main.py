from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import List, Optional
import os
import shutil
import subprocess
import shlex
from datetime import datetime
import requests
import sys

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MONGO_URI, DB_NAME, DATA_DIR, IMAGES_DIR, GENERATED_DIR, SD_API_URL, SD_API_URLS

# Manual upload directory
MANUAL_DIR = os.path.join(DATA_DIR, "manual")

# Ensure directories exist
os.makedirs(MANUAL_DIR, exist_ok=True)

# Initialize FastAPI
app = FastAPI()

# Database
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Models
class Author(BaseModel):
    id: int
    name: str
    other_names: List[str] = []

class ImageResponse(BaseModel):
    id: int
    author_id: int
    file_url: str
    tags: str
    local_path: str
    generations: List[dict] = []

class ScraperRequest(BaseModel):
    limit_authors: int = 10
    max_images: int = 5
    min_posts: int = 50

class GeneratorRequest(BaseModel):
    models: List[str]
    steps: int = 28
    cfg: float = 7.0
    sampler: str = "Euler a"
    scheduler: str = "Automatic"
    width: int = 0
    height: int = 0
    seed: int = -1
    batch_count: int = 1
    prompt: str = ""
    limit: int = 0
    authors: str = "" # Comma separated IDs
    skip_existing: bool = False

class ConfigModel(BaseModel):
    mongo_uri: str
    db_name: str
    data_dir: str
    sd_api_urls: List[str]
    style_html_path: Optional[str] = ""
    style_samples_dir: Optional[str] = ""

# Routes

@app.get("/api/stats")
async def get_stats():
    author_count = await db.authors.count_documents({})
    image_count = await db.images.count_documents({})
    gen_count = await db.generations.count_documents({})
    return {"authors": author_count, "images": image_count, "generations": gen_count}

@app.post("/api/tasks/{task_id}/{action}")
async def control_task(task_id: str, action: str):
    if action not in ["pause", "resume", "cancel"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    update = {}
    if action == "pause":
        update = {"control": "pause", "status": "paused"}
    elif action == "resume":
        update = {"control": "resume", "status": "running"}
    elif action == "cancel":
        update = {"control": "cancel", "status": "cancelled"}
        
    await db.system_status.update_one({"_id": task_id}, {"$set": update})
    return {"status": "success"}

@app.get("/api/status")
async def get_status():
    cursor = db.system_status.find({})
    statuses = await cursor.to_list(length=100)
    
    result = {}
    for s in statuses:
        result[s["_id"]] = {
            "status": s.get("status", "idle"),
            "progress": s.get("progress", 0),
            "message": s.get("message", ""),
            "current": s.get("current", 0),
            "total": s.get("total", 0)
        }
        
    return result

@app.get("/api/config")
async def get_config():
    """Get current configuration settings"""
    from config import SD_API_URLS
    
    # Try to load from MongoDB first
    config_doc = await db.app_config.find_one({"_id": "settings"})
    
    if config_doc:
        return {
            "mongo_uri": config_doc.get("mongo_uri", MONGO_URI),
            "db_name": config_doc.get("db_name", DB_NAME),
            "data_dir": config_doc.get("data_dir", DATA_DIR),
            "sd_api_urls": config_doc.get("sd_api_urls", SD_API_URLS),
            "style_html_path": config_doc.get("style_html_path", ""),
            "style_samples_dir": config_doc.get("style_samples_dir", "")
        }
    else:
        # Return defaults from config.py
        return {
            "mongo_uri": MONGO_URI,
            "db_name": DB_NAME,
            "data_dir": DATA_DIR,
            "sd_api_urls": SD_API_URLS,
            "style_html_path": "",
            "style_samples_dir": ""
        }

@app.post("/api/config")
async def update_config(config: ConfigModel):
    """Update configuration settings"""
    config_data = {
        "_id": "settings",
        "mongo_uri": config.mongo_uri,
        "db_name": config.db_name,
        "data_dir": config.data_dir,
        "sd_api_urls": config.sd_api_urls,
        "style_html_path": config.style_html_path,
        "style_samples_dir": config.style_samples_dir,
        "updated_at": datetime.now()
    }
    
    await db.app_config.update_one(
        {"_id": "settings"},
        {"$set": config_data},
        upsert=True
    )
    
    return {"status": "success", "message": "Configuration saved. Restart the app to apply changes."}

@app.post("/api/config/scan-sd")
async def scan_sd_instances():
    """Scan for running Stable Diffusion WebUI instances"""
    found_urls = []
    
    for port in range(7860, 7870):  # Check ports 7860-7869
        url = f"http://127.0.0.1:{port}"
        try:
            response = requests.get(f"{url}/sdapi/v1/sd-models", timeout=3)
            if response.status_code == 200:
                models = response.json()
                found_urls.append({
                    "url": url,
                    "model_count": len(models),
                    "status": "online"
                })
            else:
                found_urls.append({
                    "url": url,
                    "model_count": 0,
                    "status": "error",
                    "detail": f"HTTP {response.status_code} (Check --api)"
                })
        except Exception as e:
            pass
    
    return {"instances": found_urls, "found_count": len(found_urls)}

@app.post("/api/config/reset")
async def reset_configuration():
    """
    Factory Reset: Drops the database and clears data directories.
    """
    try:
        # Drop Database
        client = AsyncIOMotorClient(config.MONGO_URI)
        await client.drop_database(config.DB_NAME)
        
        # Clear Directories
        for dir_path in [config.IMAGES_DIR, config.GENERATED_DIR]:
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)
                os.makedirs(dir_path, exist_ok=True)
            else:
                os.makedirs(dir_path, exist_ok=True)
                
        return {"message": "Factory reset complete. All data has been cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/validate-paths")
async def validate_style_paths(html_path: str = Form(...), samples_dir: str = Form(...)):
    """Validate that style analysis paths exist"""
    html_exists = os.path.exists(html_path) if html_path else False
    samples_exists = os.path.exists(samples_dir) if samples_dir else False
    
    return {
        "html_valid": html_exists,
        "samples_valid": samples_exists,
        "both_valid": html_exists and samples_exists
    }

@app.get("/api/categories")
async def get_categories():
    categories = await db.authors.distinct("style_category")
    return [c for c in categories if c]

@app.get("/api/authors")
async def get_authors(page: int = 1, limit: int = 50, search: str = "", category: str = "", sort_by: str = "name", order: str = "asc"):
    skip = (page - 1) * limit
    query = {}
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    if category:
        query["style_category"] = category
    
    direction = 1 if order == "asc" else -1
    
    if sort_by in ["name", "_id"]:
        total = await db.authors.count_documents(query)
        cursor = db.authors.find(query).sort(sort_by, direction).skip(skip).limit(limit)
        authors = await cursor.to_list(length=limit)
    else:
        cursor = db.authors.find(query)
        all_authors = await cursor.to_list(length=10000)
        
        for a in all_authors:
            a["id"] = a["_id"]
            a["image_count"] = await db.images.count_documents({"author_id": a["_id"]})
            a["gen_count"] = await db.generations.count_documents({"author_id": a["_id"]})
            
        all_authors.sort(key=lambda x: x.get(sort_by, 0), reverse=(order == "desc"))
        total = len(all_authors)
        authors = all_authors[skip:skip+limit]

    if sort_by in ["name", "_id"]:
         for a in authors:
            a["id"] = a["_id"]
            a["image_count"] = await db.images.count_documents({"author_id": a["_id"]})
            a["gen_count"] = await db.generations.count_documents({"author_id": a["_id"]})

    return {
        "items": authors,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@app.get("/api/images/{author_id}")
async def get_images(author_id: int):
    cursor = db.images.find({"author_id": author_id})
    images = await cursor.to_list(length=100)
    
    results = []
    for img in images:
        gens_cursor = db.generations.find({"original_image_id": img["_id"]})
        gens = await gens_cursor.to_list(length=100)
        
        # Calculate relative path for original image
        try:
            rel_path = os.path.relpath(img['local_path'], DATA_DIR).replace("\\", "/")
            img_url = f"/data/{rel_path}"
        except Exception:
            # Fallback
            img_url = f"/data/images/{os.path.basename(img['local_path'])}"

        img_data = {
            "id": img["_id"],
            "author_id": img["author_id"],
            "file_url": img["file_url"],
            "tags": img.get("tags", ""),
            "local_path": img_url,
            "generations": []
        }
        
        for g in gens:
            rel_path = os.path.relpath(g["local_path"], DATA_DIR).replace("\\", "/")
            
            img_data["generations"].append({
                "model": g["model"],
                "prompt": g["prompt"],
                "steps": g.get("steps"),
                "cfg": g.get("cfg"),
                "local_path": f"/data/{rel_path}"
            })
            
        results.append(img_data)
        
    return results

@app.post("/api/upload")
async def upload_image(
    file: UploadFile = File(...),
    author_id: int = Form(...),
    original_image_id: int = Form(...),
    model: str = Form(...),
    prompt: str = Form(""),
    steps: int = Form(None),
    cfg: float = Form(None)
):
    filename = f"manual_{int(datetime.now().timestamp())}_{file.filename}"
    file_path = os.path.join(MANUAL_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    gen_data = {
        "original_image_id": original_image_id,
        "author_id": author_id,
        "model": model,
        "prompt": prompt,
        "steps": steps,
        "cfg": cfg,
        "local_path": file_path,
        "created_at": datetime.now(),
        "is_manual": True
    }
    
    await db.generations.insert_one(gen_data)
    return {"status": "success", "path": file_path}

@app.post("/api/import")
async def import_url(url: str = Query(...)):
    try:
        if "danbooru.donmai.us/posts/" in url:
            post_id = url.split("/posts/")[-1].split("?")[0]
            api_url = f"https://danbooru.donmai.us/posts/{post_id}.json"
            
            resp = requests.get(api_url, headers={"User-Agent": "DanbooruRanker/1.0"})
            resp.raise_for_status()
            data = resp.json()
            
            artist_name = data.get("tag_string_artist", "unknown").split(" ")[0]
            
            artist = await db.authors.find_one({"name": artist_name})
            if not artist:
                artist_id = abs(hash(artist_name)) % 10000000
                await db.authors.update_one(
                    {"name": artist_name},
                    {"$set": {"_id": artist_id, "name": artist_name, "imported": True}},
                    upsert=True
                )
            else:
                artist_id = artist["_id"]
            
            file_url = data.get("file_url")
            if not file_url:
                raise HTTPException(status_code=400, detail="No file URL found in post")
                
            ext = data.get("file_ext", "jpg")
            filename = f"{post_id}.{ext}"
            file_path = os.path.join(ORIGINALS_DIR, filename)
            
            with open(file_path, "wb") as f:
                f.write(requests.get(file_url).content)
                
            image_data = {
                "_id": int(post_id),
                "author_id": artist_id,
                "author_name": artist_name,
                "tags": data.get("tag_string"),
                "file_url": file_url,
                "local_path": file_path,
                "width": data.get("image_width"),
                "height": data.get("image_height"),
                "created_at": data.get("created_at"),
                "fetched_at": datetime.now()
            }
            
            await db.images.update_one(
                {"_id": int(post_id)},
                {"$set": image_data},
                upsert=True
            )
            
            return {"status": "success", "image_id": post_id, "author_id": artist_id}
            
        else:
            raise HTTPException(status_code=400, detail="Only Danbooru URLs supported for now")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Script Triggering ---

@app.post("/api/scraper/start")
async def start_scraper(req: ScraperRequest):
    # Set initial status
    await db.system_status.update_one(
        {"_id": "scraper"},
        {"$set": {"status": "starting", "control": "running", "progress": 0, "message": "Starting scraper...", "updated_at": datetime.now()}},
        upsert=True
    )
    
    # Run scraper as detached process
    # Run scraper as detached process
    cmd = f"python g:/python/danbooru_ranker/scripts/danbooru_scraper.py --limit-authors {req.limit_authors} --max-images {req.max_images} --min-posts {req.min_posts}"
    subprocess.Popen(shlex.split(cmd))
    
    return {"status": "Scraper started"}

@app.post("/api/generator/start")
async def start_generator(req: GeneratorRequest):
    # Set initial status
    await db.system_status.update_one(
        {"_id": "generator"},
        {"$set": {"status": "starting", "control": "running", "progress": 0, "message": "Starting generator...", "updated_at": datetime.now()}},
        upsert=True
    )
    
    # Run generator as detached process passing all models
    models_str = " ".join([f'"{m}"' for m in req.models])
    cmd = f'python g:/python/danbooru_ranker/scripts/image_generator.py --models {models_str} --steps {req.steps} --cfg {req.cfg} --sampler "{req.sampler}"'
    if req.limit > 0:
        cmd += f" --limit {req.limit}"
    if req.prompt:
        cmd += f' --prompt "{req.prompt}"'
    if req.authors:
        cmd += f' --authors "{req.authors}"'
    
    subprocess.Popen(shlex.split(cmd))
    
    return {"status": "Generator started", "models": req.models}

@app.post("/api/style/analyze")
async def start_style_analysis():
    await db.system_status.update_one(
        {"_id": "style_analyzer"},
        {"$set": {"status": "starting", "progress": 0, "message": "Starting style analysis...", "updated_at": datetime.now()}},
        upsert=True
    )
    cmd = "python g:/python/danbooru_ranker/scripts/style_analyzer.py"
    subprocess.Popen(shlex.split(cmd))
    return {"status": "started"}

@app.post("/api/style/aggregate")
async def start_style_aggregation():
    await db.system_status.update_one(
        {"_id": "aggregator"},
        {"$set": {"status": "starting", "progress": 0, "message": "Starting aggregation...", "updated_at": datetime.now()}},
        upsert=True
    )
    cmd = "python g:/python/danbooru_ranker/scripts/aggregate_styles.py"
    subprocess.Popen(shlex.split(cmd))
    return {"status": "started"}

# --- SD Proxy ---
@app.get("/api/sd/models")
def get_sd_models():
    try:
        resp = requests.get(f"{SD_API_URL}/sdapi/v1/sd-models")
        return resp.json()
    except:
        return []

@app.get("/api/sd/samplers")
def get_sd_samplers():
    try:
        resp = requests.get(f"{SD_API_URL}/sdapi/v1/samplers")
        return resp.json()
    except:
        return []

@app.get("/api/sd/schedulers")
def get_sd_schedulers():
    try:
        resp = requests.get(f"{SD_API_URL}/sdapi/v1/schedulers")
        return resp.json()
    except:
        return []

# Static Files
app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")
app.mount("/", StaticFiles(directory=r"g:\python\danbooru_ranker\app\static", html=True), name="static")
