# Danbooru Likeness Ranker - Configuration Guide

## Folder Configuration

You can customize where files are stored by editing the `config.py` file in the root directory.

### Generated Images Folder

To change where generated images are saved (useful if you want to use a different disk with more storage):

1. Open `config.py`
2. Find the line:
   ```python
   GENERATED_DIR = os.path.join(DATA_DIR, "generated")
   ```
3. Change it to your desired path. Examples:
   ```python
   # Windows - Different drive
   GENERATED_DIR = r"h:\danbooru_generated"
   
   # Windows - Network path
   GENERATED_DIR = r"\\server\share\danbooru_generated"
   
   # Relative path (less recommended)
   GENERATED_DIR = r"../generated_images"
   ```
4. Save the file
5. **Restart the FastAPI server** for changes to take effect

### Other Configurable Paths

In `config.py` you can also configure:

- **IMAGES_DIR**: Where scraped original images are stored
  - Default: `g:\python\danbooru_ranker\data\images`
- **DATA_DIR**: Base directory for all data
  - Default: `g:\python\danbooru_ranker\data`

## Database Configuration

- **MONGO_URI**: MongoDB connection string
  - Default: `mongodb://localhost:27017/`
- **DB_NAME**: Database name
  - Default: `danbooru_ranker`

## API Configuration

- **DANBOORU_API_URL**: Danbooru API endpoint
  - Default: `https://danbooru.donmai.us`
- **SD_API_URL**: Stable Diffusion WebUI API endpoint  
  - Default: `http://127.0.0.1:7860`

## Notes

- Always use raw strings (prefix with `r`) for Windows paths to avoid escape character issues
- Folders will be created automatically if they don't exist
- After changing configuration, restart the FastAPI server (`python app/main.py`)
