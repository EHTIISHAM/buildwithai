"""MongoDB Atlas connection (async, via motor)."""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")  # full Atlas SRV link goes in .env
DB_NAME = os.getenv("DB_NAME", "buildwithai")

client = AsyncIOMotorClient(MONGODB_URL)
db = client[DB_NAME]


async def init_indexes():
    """Ensure google_id is unique so we never duplicate a signup."""
    await db.signups.create_index("google_id", unique=True)
    await db.signups.create_index("email")
