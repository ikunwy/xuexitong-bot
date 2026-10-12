import logging
from pathlib import Path
import yaml

from app.utils.paths import CONFIG_PATH

DEFAULT_CONFIG = {
    "log_level": "INFO",
    "engine": {"rounds": 3, "interval": 1.0},
}


def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG_PATH
    if not path.exists():
        logging.getLogger("app").warning("配置文件不存在: %s，使用默认配置", path)
        return DEFAULT_CONFIG
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = {**DEFAULT_CONFIG, **data}
    return merged