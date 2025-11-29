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
