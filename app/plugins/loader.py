from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from app.utils.paths import PLUGIN_DIR

log = logging.getLogger("app.plugins")


class PluginLoader:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.loaded: list[str] = []

    def load_all(self) -> None:
        for py in sorted(PLUGIN_DIR.glob("*.py")):
            if py.name.startswith("_"):
                continue
            self._load_one(py)

    def _load_one(self, path: Path) -> None:
        try:
            spec = importlib.util.spec_from_file_location(
                f"plugins.{path.stem}", path
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载 {path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            setup = getattr(mod, "setup", None)
            if callable(setup):
                setup(self.ctx)
                self.loaded.append(path.stem)
                log.info("插件已加载: %s", path.stem)
            else:
                log.warning("插件 %s 缺少 setup(ctx) 函数", path.name)
        except Exception:
            log.exception("插件加载失败: %s", path.name)