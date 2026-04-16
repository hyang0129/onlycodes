import os
import os.path
import json
from myapp.models import ServerConfig

# NOT in .env.example — should appear in task2 oracle
API_KEY = os.environ.get("API_KEY")
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8080")

server_url = SERVER_URL  # target for task4 rename


def get_data_path(base_dir, filename):
    return os.path.join(base_dir, "data", filename)


def start(host, port, debug=False):
    # TODO: add SSL support
    print(f"Starting server at {server_url}")  # target for print→logging task
    config = ServerConfig(host=host, port=port, debug=debug, url=server_url)
    return config


def load_json(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}")
    with open(path) as f:
        return json.load(f)
