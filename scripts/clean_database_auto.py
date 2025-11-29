import pymongo
import os
import shutil

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import MONGO_URI, DB_NAME, DATA_DIR, IMAGES_DIR, GENERATED_DIR

def clean_database():
    """Clean the database and remove all downloaded files"""
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    print("Cleaning database...")
    
    # Drop all collections
    print("  Dropping authors collection...")
    db.authors.drop()
    
    print("  Dropping images collection...")
    db.images.drop()
    
    print("  Dropping generations collection...")
    db.generations.drop()
    
    print("  Dropping system_status collection...")
    db.system_status.drop()
    
    # Clean data directories
    print("\nCleaning data directories...")
    
    if os.path.exists(IMAGES_DIR):
        print(f"  Removing {IMAGES_DIR}...")
        shutil.rmtree(IMAGES_DIR)
        os.makedirs(IMAGES_DIR)
    
    if os.path.exists(GENERATED_DIR):
        print(f"  Removing {GENERATED_DIR}...")
        shutil.rmtree(GENERATED_DIR)
        os.makedirs(GENERATED_DIR)
    
    manual_dir = os.path.join(DATA_DIR, "manual")
    if os.path.exists(manual_dir):
        print(f"  Removing {manual_dir}...")
        shutil.rmtree(manual_dir)
        os.makedirs(manual_dir)
    
    print("\nDatabase and files cleaned successfully!")
    print("You can now start the scraper fresh.")

if __name__ == "__main__":
    # Auto-confirm for non-interactive use
    clean_database()
