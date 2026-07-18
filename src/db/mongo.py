"""MongoDB client and operations for exam paper storage."""
import asyncio
from datetime import datetime, timezone
from typing import Any
from pymongo import MongoClient
from pymongo.collection import Collection
from src.config import settings


_client: MongoClient | None = None


def get_mongo_client() -> MongoClient:
    """Get or create MongoDB client (singleton)."""
    global _client
    if _client is None:
        _client = MongoClient(settings.mongodb_url, serverSelectionTimeoutMS=5000)
    return _client


def get_papers_collection() -> Collection:
    client = get_mongo_client()
    db = client[settings.mongodb_db]
    return db["papers"]


def get_uploads_collection() -> Collection:
    client = get_mongo_client()
    db = client[settings.mongodb_db]
    return db["uploads"]


def save_paper(run_id: str, paper: dict, exam_config: dict) -> str:
    """Save a generated exam paper to MongoDB."""
    collection = get_papers_collection()
    doc = {
        "_id": run_id,
        "run_id": run_id,
        "paper": paper,
        "exam_config": exam_config,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
    }
    collection.replace_one({"_id": run_id}, doc, upsert=True)
    return run_id


def update_paper_status(run_id: str, status: str, error: str | None = None):
    """Update the status of a paper generation run."""
    collection = get_papers_collection()
    update = {"$set": {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}}
    if error:
        update["$set"]["error"] = error
    collection.update_one({"_id": run_id}, update, upsert=True)


def update_paper_progress(run_id: str, progress: int, message: str, status: str | None = None):
    """Update progress percentage and status message of a generation run."""
    collection = get_papers_collection()
    update = {
        "$set": {
            "progress": progress,
            "status_message": message,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    }
    if status:
        update["$set"]["status"] = status
    collection.update_one({"_id": run_id}, update, upsert=True)


def create_paper_record(run_id: str, exam_config: dict):
    """Create initial paper record when generation starts."""
    collection = get_papers_collection()
    doc = {
        "_id": run_id,
        "run_id": run_id,
        "exam_config": exam_config,
        "paper": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    collection.insert_one(doc)


def get_paper(run_id: str) -> dict | None:
    """Get a paper by run_id."""
    collection = get_papers_collection()
    return collection.find_one({"_id": run_id}, {"_id": 0})


def list_papers(limit: int = 20, skip: int = 0) -> list[dict[str, Any]]:
    """List recent generated papers."""
    collection = get_papers_collection()
    cursor = collection.find(
        {"status": "completed"},
        {"_id": 0, "run_id": 1, "exam_config": 1, "created_at": 1, "paper.title": 1, "paper.total_marks": 1}
    ).sort("created_at", -1).skip(skip).limit(limit)
    return list(cursor)


def save_upload_metadata(blob_url: str, filename: str, file_type: str, size_bytes: int) -> str:
    """Save metadata about an uploaded document."""
    collection = get_uploads_collection()
    doc = {
        "blob_url": blob_url,
        "filename": filename,
        "file_type": file_type,
        "size_bytes": size_bytes,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    result = collection.insert_one(doc)
    return str(result.inserted_id)
