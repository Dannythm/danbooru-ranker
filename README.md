# Danbooru Likeness Ranker

A web application for collecting, generating, and comparing AI-generated images in the style of various artists from Danbooru. This tool helps evaluate how well different Stable Diffusion models can replicate specific artistic styles.

## Features

- **Automated Data Collection**: Scrape artist information and images from Danbooru with automatic rate limiting
- **Gelbooru Fallback**: Automatically falls back to Gelbooru when Danbooru images are unavailable (Gold account requirements, removed content)
- **Multi-Model Generation**: Generate images using multiple Stable Diffusion models for comparison
- **Parallel Processing**: Utilize multiple GPUs/SD instances simultaneously for faster generation
- **Process Control**: Pause, resume, and cancel long-running scraping and generation tasks from the UI
- **Interactive Web UI**: Browse artists, view original images, and compare generated outputs
- **Style Analysis**: Organize and categorize artists by artistic style
- **Pagination & Search**: Efficiently navigate large collections of artists

## Prerequisites

- **Python 3.8+**
- **MongoDB**: For data storage
- **Stable Diffusion WebUI**: Running with API enabled (`--api` flag)
  - For parallel generation, run multiple instances on different ports
- **Ranking and categorization**: Download the mega from [Artists list](https://rentry.org/artists_list) to use as base for ranking and categorization.

## Installation

1. **Clone the repository**:
   ```bash
   git clone git@github.com:Dannythm/danbooru-ranker.git
   cd danbooru-ranker
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up MongoDB**:
   - Install MongoDB and ensure it's running on `localhost:27017`
   - Or modify `MONGO_URI` in `config.py` to point to your MongoDB instance

4. **Configure the application**:
   ```bash
# Stable Diffusion API Configuration
# Add multiple URLs to enable parallel generation across GPUs
SD_API_URLS = [
    "http://127.0.0.1:7860",  # First GPU
    # "http://127.0.0.1:7861",  # Second GPU (uncomment and configure)
]

# Directory Configuration
DATA_DIR = r"d:\Pictures\sd_outputs\danbooru_ranker"
IMAGES_DIR = os.path.join(DATA_DIR, "images")
GENERATED_DIR = os.path.join(DATA_DIR, "generated")
```

## Usage

### 1. Start the Web Application

```bash
cd app
python main.py
```

The web interface will be available at `http://localhost:5050`

### 2. Collect Artist Data

From the **Control Panel** tab:
- Set the number of artists to fetch
- Set maximum images per artist
- Set minimum posts threshold (to filter out less active artists)
- Click "Start Scraper"

The scraper will:
- Fetch artist metadata from Danbooru
- Download sample images for each artist
- Automatically fall back to Gelbooru if Danbooru images are unavailable

### 3. Generate Images

From the **Control Panel** tab:
- Select one or more Stable Diffusion models
- Configure generation parameters (steps, CFG, sampler, scheduler)
- Optionally add a prompt suffix
- Click "Start Generation"

For parallel generation:
- Configure multiple SD instances in `SD_API_URLS` in `config.py`
- The system will automatically distribute work across all configured instances

### 4. Browse and Compare

From the **Browse & Compare** tab:
- Search and filter artists by name or style
- Click an artist to view their original images and generated outputs
- Compare results across different models

### 5. Process Control

While scraping or generating:
- **Pause**: Temporarily halt the process (can be resumed later)
- **Resume**: Continue a paused task
- **Cancel**: Stop the process completely

Control buttons appear in the status bar at the bottom when tasks are running.

## Project Structure

```
danbooru_ranker/
├── app/
│   ├── main.py              # FastAPI web server
│   ├── static/
│   │   └── index.html       # Web UI
│   └── task_manager.py      # Background task management
├── scripts/
│   ├── danbooru_scraper.py  # Danbooru data collection
│   ├── gelbooru_scraper.py  # Gelbooru fallback scraper
│   ├── image_generator.py   # Stable Diffusion image generation
│   └── ...                  # Utility scripts
├── config.py                # Configuration settings
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## API Endpoints

The FastAPI server provides the following endpoints:

- `GET /api/authors` - List artists with pagination and filtering
- `GET /api/images/{author_id}` - Get images for a specific artist
- `GET /api/categories` - List available style categories
- `GET /api/stats` - Get collection statistics
- `GET /api/status` - Get status of background tasks
- `POST /api/tasks/{task_id}/{action}` - Control tasks (pause/resume/cancel)
- `POST /api/scraper/start` - Start the scraper
- `POST /api/generator/start` - Start image generation
- `POST /api/upload` - Upload generated images manually

## Tips for Multi-GPU Setup

1. **Start multiple SD WebUI instances**:
   ```bash
   # Terminal 1 (GPU 0)
   python launch.py --api --port 7860 --device-id 0
   
   # Terminal 2 (GPU 1)
   python launch.py --api --port 7861 --device-id 1
   ```

2. **Configure `SD_API_URLS` in `config.py`**:
   ```python
   SD_API_URLS = [
       "http://127.0.0.1:7860",
       "http://127.0.0.1:7861",
   ]
   ```

3. **Start generation** - The system will automatically distribute work across both instances

## Troubleshooting

**MongoDB connection failed**:
- Ensure MongoDB is running: `mongod --version`
- Check `MONGO_URI` in `config.py`

**Stable Diffusion API not responding**:
- Verify SD WebUI is running with `--api` flag
- Check URLs in `SD_API_URLS` in `config.py`
- Test API: `curl http://127.0.0.1:7860/sdapi/v1/sd-models`

**Images not downloading**:
- Check internet connection
- Verify `IMAGES_DIR` has write permissions
- Check Danbooru rate limits (1 request per second)

## License

This project is open source and available under the Unlicense License.

## Acknowledgments

- [Danbooru](https://danbooru.donmai.us/) for the artist and image data
- [Gelbooru](https://gelbooru.com/) for fallback image sources
- [AUTOMATIC1111's Stable Diffusion WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) for the generation API