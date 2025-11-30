import sys
import os
import shutil
import pymongo

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import config
except ImportError:
    print("Error: config.py not found. Please copy config.example.py to config.py")
    sys.exit(1)

def confirm_action(message):
    response = input(f"{message} (y/N): ").lower()
    return response == 'y'

def reset_data():
    print("!!! WARNING: THIS WILL DELETE ALL DATA !!!")
    print(f"Database: {config.DB_NAME}")
    print(f"Images Dir: {config.IMAGES_DIR}")
    print(f"Generated Dir: {config.GENERATED_DIR}")
    
    if not confirm_action("Are you sure you want to delete all data?"):
        print("Operation cancelled.")
        return

    # 1. Drop Database
    print(f"Dropping database '{config.DB_NAME}'...")
    try:
        client = pymongo.MongoClient(config.MONGO_URI)
        client.drop_database(config.DB_NAME)
        print("Database dropped.")
    except Exception as e:
        print(f"Error dropping database: {e}")

    # 2. Delete Directories
    for dir_path in [config.IMAGES_DIR, config.GENERATED_DIR]:
        if os.path.exists(dir_path):
            print(f"Cleaning {dir_path}...")
            try:
                shutil.rmtree(dir_path)
                os.makedirs(dir_path, exist_ok=True)
                print(f"Recreated empty {dir_path}")
            except Exception as e:
                print(f"Error cleaning directory: {e}")
        else:
            print(f"Directory {dir_path} does not exist, creating...")
            os.makedirs(dir_path, exist_ok=True)

    print("\nReset complete. You can now start from scratch.")

if __name__ == "__main__":
    reset_data()
