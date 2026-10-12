import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """可写根目录：exe 同级 / 源码根目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    """只读资源根目录。"""
    if is_frozen():
        return Path(sys._MEIPASS)    # type: ignore[attr-defined]
    return app_root()


# ---- 可写路径（永远在 exe 旁边）----
DATA_DIR = app_root() / "data"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "app.db"
DRIVER_DIR = DATA_DIR / "driver"
CHROME_PROFILE_DIR = DATA_DIR / "chrome_profile"
PLUGIN_DIR = app_root() / "plugins"
CONFIG_PATH = app_root() / "config" / "config.yaml"

# ---- 只读路径（打包时塞进 _MEIPASS）----
RESOURCE_DIR = resource_root()
BUNDLED_DRIVER = RESOURCE_DIR / "resources" / "driver" / "chromedriver.exe"
CONFIG_TEMPLATE = RESOURCE_DIR / "config" / "config.example.yaml"

# ---- 自动建目录 ----
for _d in (DATA_DIR, LOG_DIR, DRIVER_DIR, CHROME_PROFILE_DIR, PLUGIN_DIR,
           CONFIG_PATH.parent):
    _d.mkdir(parents=True, exist_ok=True)

# ---- 首次运行：把 config 模板复制到可写目录 ----
if not CONFIG_PATH.exists() and CONFIG_TEMPLATE.exists():
    import shutil
    shutil.copy2(CONFIG_TEMPLATE, CONFIG_PATH)

# ---- 首次运行：把 chromedriver 复制到 data/driver ----
if not (DRIVER_DIR / "chromedriver.exe").exists() and BUNDLED_DRIVER.exists():
    import shutil
    shutil.copy2(BUNDLED_DRIVER, DRIVER_DIR / "chromedriver.exe")