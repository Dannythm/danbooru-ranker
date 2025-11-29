"""
Configuration file for Danbooru Ranker
Copy this file to config.py and edit the values to customize your setup
"""

import os

# MongoDB Configuration
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "danbooru_ranker"

# Danbooru API Configuration
DANBOORU_API_URL = "https://danbooru.donmai.us"
USER_AGENT = "DanbooruRanker/1.0"

# Stable Diffusion API Configuration
# List of API URLs for parallel generation
# Add multiple URLs to utilize multiple GPUs/instances
SD_API_URLS = [
    "http://127.0.0.1:7860",
    # "http://127.0.0.1:7861",  # Uncomment and add more instances here
]
SD_API_URL = SD_API_URLS[0]  # For backward compatibility

# Directory Configuration
# Base directory for all data
# IMPORTANT: Change this to your preferred location
DATA_DIR = r"YOUR_PATH_HERE\danbooru_ranker_data"

# Directory for downloaded original images
IMAGES_DIR = os.path.join(DATA_DIR, "images")

# Directory for generated images
# You can change this to a different disk if needed
# Example: r"h:\danbooru_generated" or r"d:\generated_images"
GENERATED_DIR = os.path.join(DATA_DIR, "generated")

# Create directories if they don't exist
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)

# Style Analysis Configuration
STYLE_HTML_PATH = None
STYLE_SAMPLES_DIR = None

# Load configuration from MongoDB if available
try:
    from pymongo import MongoClient
    
    def load_config_from_db():
        global MONGO_URI, DB_NAME, DATA_DIR, SD_API_URLS, SD_API_URL, STYLE_HTML_PATH, STYLE_SAMPLES_DIR
        
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
            db = client[DB_NAME]
            config = db.app_config.find_one({"_id": "settings"})
            
            if config:
                print("Loading configuration from MongoDB...")
                if 'mongo_uri' in config: MONGO_URI = config['mongo_uri']
                if 'db_name' in config: DB_NAME = config['db_name']
                if 'data_dir' in config: DATA_DIR = config['data_dir']
                if 'sd_api_urls' in config and config['sd_api_urls']: 
                    SD_API_URLS = config['sd_api_urls']
                    SD_API_URL = SD_API_URLS[0]
                if 'style_html_path' in config: STYLE_HTML_PATH = config['style_html_path']
                if 'style_samples_dir' in config: STYLE_SAMPLES_DIR = config['style_samples_dir']
                
                # Update derived paths
                global IMAGES_DIR, GENERATED_DIR
                IMAGES_DIR = os.path.join(DATA_DIR, "images")
                GENERATED_DIR = os.path.join(DATA_DIR, "generated")
                
        except Exception as e:
            print(f"Failed to load config from DB: {e}")

    # Load config on startup
    load_config_from_db()

except ImportError:
    print("pymongo not installed, skipping DB config load")
