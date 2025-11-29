import pymongo

client = pymongo.MongoClient('mongodb://localhost:27017/')
db = client['danbooru_ranker']

# Get a few sample images
imgs = list(db.images.find().limit(5))

if imgs:
    print("Sample image paths:")
    for img in imgs:
        print(f"  ID {img['_id']}: {img.get('local_path', 'NO PATH')}")
else:
    print("No images in database")
