import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import pprint

async def check():
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    db = client['danbooru_ranker']
    
    # System Status
    docs = await db.system_status.find({}).to_list(None)
    print("--- System Status ---")
    for doc in docs:
        pprint.pprint(doc)
        
    # Counts
    n_authors = await db.authors.count_documents({})
    n_images = await db.images.count_documents({})
    n_gens = await db.generations.count_documents({})
    
    print("\n--- Database Counts ---")
    print(f"Authors:     {n_authors}")
    print(f"Images:      {n_images}")
    print(f"Generations: {n_gens}")

if __name__ == "__main__":
    asyncio.run(check())
