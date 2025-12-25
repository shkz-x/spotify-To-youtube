import json
from pathlib import Path
from typing import Dict, Any

def load_state(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"version": 1, "added": {}}  # initial state
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "added" not in data:
        data["added"] = {}
    if "version" not in data:
        data["version"] = 1
    return data

def save_state(path: str, data: Dict[str, Any]) -> None:
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)