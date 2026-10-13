# file_manager.py
import json
import os

INDEX_FILE = "file_index.json"

def init_index():
    if not os.path.exists(INDEX_FILE):
        save_index({"files": {}})

def load_index():
    init_index()
    try:
        with open(INDEX_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError):
        data = {}
    
    # Self-healing check: ensure 'files' key always exists
    if "files" not in data:
        data["files"] = {}
        save_index(data)
        
    return data

def save_index(data):
    with open(INDEX_FILE, "w") as f:
        json.dump(data, f, indent=4)

def register_file(filename, description=""):
    index = load_index()
    index["files"][filename] = {
        "description": description,
        "version": index["files"].get(filename, {}).get("version", 0) + 1,
        "path": os.path.abspath(filename)
    }
    save_index(index)
    print(f"[INDEX] Registered/Updated file: {filename}")

