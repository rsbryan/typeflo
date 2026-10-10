from .config import model_path

CATALOG = [
    {"id": "mlx-community/parakeet-tdt-0.6b-v2", "name": "Parakeet v2", "kind": "asr", "size": "0.6B",
     "detail": "Fast, accurate English transcription", "badge": "Recommended"},
    {"id": "mlx-community/parakeet-tdt-0.6b-v3", "name": "Parakeet v3", "kind": "asr", "size": "0.6B",
     "detail": "Multilingual transcription · 25 languages", "badge": "Multilingual"},
    {"id": "mlx-community/Qwen2.5-1.5B-Instruct-4bit", "name": "Qwen 2.5 · 1.5B", "kind": "llm", "size": "4-bit",
     "detail": "A smaller model for lightweight editing", "badge": "Lightweight"},
    {"id": "mlx-community/Qwen2.5-3B-Instruct-4bit", "name": "Qwen 2.5 · 3B", "kind": "llm", "size": "4-bit",
     "detail": "Balanced speed and transcript cleanup", "badge": "Recommended"},
    {"id": "mlx-community/Qwen2.5-7B-Instruct-4bit", "name": "Qwen 2.5 · 7B", "kind": "llm", "size": "4-bit",
     "detail": "More capacity for nuanced editing", "badge": "Higher capacity"},
]


def catalog(config):
    items = [dict(item) for item in CATALOG]
    for kind in ("asr", "llm"):
        name = getattr(config, f"{kind}_model")
        if not any(item["id"] == name for item in items):
            items.append({"id": name, "name": name.split("/")[-1], "kind": kind, "size": "Custom",
                          "detail": "Your local model", "badge": "Custom"})
    for item in items:
        try:
            model_path(item["id"])
            item["downloaded"] = True
        except RuntimeError:
            item["downloaded"] = False
        item["selected"] = getattr(config, f"{item['kind']}_model") == item["id"]
    return items
