from dataclasses import asdict, dataclass
import json
import os
import re
from pathlib import Path
import tempfile
import tomllib

CONFIG_PATH = Path.home() / ".config/typeflo/config.toml"
LEGACY_PATH = Path.home() / ".config/dictate/config.toml"
DATA_PATH = Path.home() / "Library/Application Support/Typeflo"
MODEL_FILES = ["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja", "*.tiktoken"]
STYLES = {"clean", "verbatim", "formal", "casual"}


@dataclass(frozen=True)
class Config:
    hotkey: str = "fn"
    hands_free_hotkey: str = "fn+space"
    asr_model: str = "mlx-community/parakeet-tdt-0.6b-v2"
    llm_model: str = "mlx-community/Qwen2.5-3B-Instruct-4bit"
    llm_enabled: bool = True
    personal_dictionary: tuple[str, ...] = ()
    snippets: tuple[dict, ...] = ()
    style: str = "clean"
    microphone: str = "default"
    history_enabled: bool = True
    show_overlay: bool = True
    launch_at_login: bool = False


def validate_config(values: dict) -> Config:
    from .hotkey import parse_hotkey

    unknown = values.keys() - Config.__dataclass_fields__.keys()
    if unknown:
        raise ValueError(f"Unknown config keys: {', '.join(sorted(unknown))}")
    merged = asdict(Config()) | values
    for name in ("hotkey", "hands_free_hotkey", "asr_model", "llm_model", "microphone", "style"):
        if not isinstance(merged[name], str) or not merged[name].strip():
            raise ValueError(f"{name} must be a non-empty string")
    for name in ("hotkey", "hands_free_hotkey"):
        merged[name] = merged[name].lower().replace(" ", "")
        parse_hotkey(merged[name])
    if parse_hotkey(merged["hotkey"]) == parse_hotkey(merged["hands_free_hotkey"]):
        raise ValueError("Push-to-talk and hands-free shortcuts must be different")
    for name in ("llm_enabled", "history_enabled", "show_overlay", "launch_at_login"):
        if type(merged[name]) is not bool:
            raise ValueError(f"{name} must be true or false")
    if merged["style"] not in STYLES:
        raise ValueError("Unknown writing style")
    dictionary = merged["personal_dictionary"]
    if not isinstance(dictionary, (list, tuple)) or any(
        not isinstance(word, str) or not word.strip() or len(word) > 120 for word in dictionary
    ):
        raise ValueError("Dictionary entries must be non-empty words or names (up to 120 characters)")
    merged["personal_dictionary"] = tuple(dict.fromkeys(word.strip() for word in dictionary))
    if len(dictionary) > 500:
        raise ValueError("The dictionary can contain up to 500 entries")
    snippets = merged["snippets"]
    if not isinstance(snippets, (list, tuple)) or len(snippets) > 200:
        raise ValueError("Snippets must be a list with at most 200 entries")
    seen = set()
    for snippet in snippets:
        if not isinstance(snippet, dict) or set(snippet) != {"trigger", "text"}:
            raise ValueError("Each snippet needs a trigger and text")
        if any(not isinstance(snippet[key], str) or not snippet[key].strip() for key in ("trigger", "text")):
            raise ValueError("Snippet trigger and text cannot be empty")
        if len(snippet["trigger"]) > 60 or len(snippet["text"]) > 4000:
            raise ValueError("Snippets allow 60 characters for the trigger and 4,000 for the expansion")
        normalized = " ".join(re.findall(r"\w+", snippet["trigger"].casefold()))
        if not normalized:
            raise ValueError("A snippet trigger must contain a word")
        if normalized in seen:
            raise ValueError("That snippet trigger already exists")
        seen.add(normalized)
    merged["snippets"] = tuple(dict(item) for item in snippets)
    return Config(**merged)


def config_toml(config: Config) -> str:
    lines = []
    values = asdict(config)
    snippets = values.pop("snippets")
    for key, value in values.items():
        lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    for snippet in snippets:
        lines.extend(["", "[[snippets]]", f"trigger = {json.dumps(snippet['trigger'], ensure_ascii=False)}",
                      f"text = {json.dumps(snippet['text'], ensure_ascii=False)}"])
    return "\n".join(lines) + "\n"


def save_config(config: Config, path: Path = CONFIG_PATH):
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(config_toml(config))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_config(path: Path = CONFIG_PATH) -> Config:
    path = path.expanduser()
    if not path.exists():
        values = {}
        if path == CONFIG_PATH and LEGACY_PATH.exists():
            with LEGACY_PATH.open("rb") as file:
                values = tomllib.load(file)
            values["hotkey"] = "fn"
        config = validate_config(values)
        save_config(config, path)
        return config
    with path.open("rb") as file:
        return validate_config(tomllib.load(file))


def model_path(identifier: str) -> Path:
    local = Path(identifier).expanduser()
    if local.is_dir():
        return local.resolve()
    from huggingface_hub import snapshot_download

    try:
        return Path(snapshot_download(identifier, local_files_only=True, allow_patterns=MODEL_FILES))
    except Exception as error:
        raise RuntimeError(f"Download {identifier} in Models, or run `uv run typeflo --download-models`.") from error


def download_models(config: Config, model: str | None = None) -> None:
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    from huggingface_hub import snapshot_download

    names = [model] if model else [config.asr_model] + ([config.llm_model] if config.llm_enabled else [])
    for name in dict.fromkeys(names):
        if Path(name).expanduser().is_dir():
            continue
        print(f"Downloading model files: {name}", flush=True)
        snapshot_download(name, allow_patterns=MODEL_FILES)
