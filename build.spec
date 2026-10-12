# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ---------------- 隐式导入 ----------------
hiddenimports = []

# SQLAlchemy 方言动态导入
hiddenimports += collect_submodules("sqlalchemy")
hiddenimports += ["sqlalchemy.sql.default_comparator"]

# uvicorn 动态加载 loop / protocol / lifespan
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto",
                  "uvicorn.loops.asyncio", "uvicorn.protocols.http.auto",
                  "uvicorn.protocols.http.h11_impl",
                  "uvicorn.protocols.websockets.auto",
                  "uvicorn.protocols.websockets.wsproto_impl",
                  "uvicorn.lifespan.on", "uvicorn.lifespan.off"]

# fastapi / pydantic / starlette
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("starlette")
hiddenimports += collect_submodules("pydantic")

# webdriver-manager（如果你用了自动下载）
hiddenimports += collect_submodules("webdriver_manager")

# 其它
hiddenimports += ["anyio", "h11", "click", "yaml", "encodings.idna"]

# ---------------- 打包的数据文件 ----------------
datas = [
    ("config/config.example.yaml", "config"),
    ("resources", "resources"),              # driver、图标
    ("static", "static"),        # ★ 加这行，否则静态文件会丢失
]

# ---------------- 排除无用库，减小体积 ----------------
excludes = [
    "tkinter", "matplotlib", "numpy", "pandas", "scipy",
    "PIL", "PyQt5", "PySide2", "notebook", "IPython",
    "test", "unittest", "pydoc_data",
]

# ---------------- Analysis ----------------
a = Analysis(
    ["index.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# ---------------- EXE ----------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XueXiTongBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX 容易误报，关掉
    console=True              # 想隐藏黑窗改 False
                              # icon="resources/icon.ico", 没有图标就删掉这行
)

# ---------------- COLLECT ----------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="XueXiTongBot",
)