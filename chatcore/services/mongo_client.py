from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from django.conf import settings
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database


class MongoStore:
    _client: MongoClient | None = None
    _db: Database | None = None
    _lock = Lock()
    _indexes_ready = False

    @classmethod
    def client(cls) -> MongoClient:
        if cls._client is None:
            cls._client = MongoClient(
                settings.MONGODB_URI,
                appname="pulsepair-chat",
                maxPoolSize=80,
                minPoolSize=5,
                retryWrites=True,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=20000,
            )
        return cls._client

    @classmethod
    def db(cls) -> Database:
        if cls._db is None:
            cls._db = cls.client()[settings.MONGODB_DB_NAME]
        return cls._db

    @classmethod
    def users(cls) -> Collection:
        cls.ensure_indexes()
        return cls.db()["users"]

    @classmethod
    def room_messages(cls) -> Collection:
        cls.ensure_indexes()
        return cls.db()["room_messages"]

    @classmethod
    def dm_messages(cls) -> Collection:
        cls.ensure_indexes()
        return cls.db()["dm_messages"]

    @classmethod
    def ensure_indexes(cls) -> None:
        if cls._indexes_ready:
            return
        with cls._lock:
            if cls._indexes_ready:
                return

            db = cls.db()

            users = db["users"]
            users.create_index([("email_lower", ASCENDING)], unique=True, name="uniq_email_lower")
            users.create_index([("username_lower", ASCENDING)], unique=True, name="uniq_username_lower")
            users.create_index([("created_at", DESCENDING)], name="users_created_desc")

            room_messages = db["room_messages"]
            room_messages.create_index(
                [("room_id", ASCENDING), ("sent_at", DESCENDING), ("_id", DESCENDING)],
                name="room_msgs_room_time_desc",
            )

            dm_messages = db["dm_messages"]
            dm_messages.create_index(
                [("thread_key", ASCENDING), ("sent_at", DESCENDING), ("_id", DESCENDING)],
                name="dm_thread_time_desc",
            )
            dm_messages.create_index(
                [("recipient_id", ASCENDING), ("read_at", ASCENDING), ("sent_at", DESCENDING)],
                name="dm_unread_recipient",
            )
            dm_messages.create_index(
                [("participants", ASCENDING), ("sent_at", DESCENDING)],
                name="dm_participants_time_desc",
            )

            cls._indexes_ready = True



def utc_now() -> datetime:
    return datetime.now(UTC)
