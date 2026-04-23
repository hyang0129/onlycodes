import os

# DATABASE_URL is in .env.example — should NOT appear in task2 oracle
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")

# These are NOT in .env.example — should appear in task2 oracle
SECRET_TOKEN = os.environ.get("SECRET_TOKEN")
TIMEOUT_MS = int(os.environ.get("TIMEOUT_MS", "5000"))


def get_config():
    return {
        "database_url": DATABASE_URL,
        "secret_token": SECRET_TOKEN,
        "timeout_ms": TIMEOUT_MS,
    }
