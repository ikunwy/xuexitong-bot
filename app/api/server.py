from __future__ import annotations

import logging
import threading

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.api.screencast_ws import router as screencast_router
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.utils.paths import resource_root

log = logging.getLogger("app.api")

STATIC_DIR = resource_root() / "static"

def create_app(ctx) -> FastAPI:
    app = FastAPI(title="XueXiTong Bot API", version="1.0.0")
    app.state.ctx = ctx
    app.include_router(router)
    app.include_router(screencast_router)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    else:
        log.warning("静态目录不存在: %s", STATIC_DIR)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # 注意：allow_origins=["*"] 时不能为 True
        allow_methods=["*"],
        allow_headers=["*"],
    )
    token = ctx.config.get("api", {}).get("token", "")

    @app.get("/screen")
    def screen_page():
        return FileResponse("static/screencast.html")

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        if token and request.url.path.startswith("/api"):
            if request.headers.get("X-API-Token") != token:
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.on_event("startup")
    async def _startup():
        log.info("API 服务已启动")

    return app


def start_api(ctx) -> threading.Thread | None:
    cfg = ctx.config.get("api", {})
    if not cfg.get("enabled", False):
        log.info("api.enabled = false，跳过启动")
        return None

    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 8765))

    app = create_app(ctx)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=cfg.get("log_level", "warning"),
        access_log=False,
    )
    server = uvicorn.Server(config)
    # ★ 子线程里不能注册信号处理器
    server.install_signal_handlers = lambda: None

    t = threading.Thread(target=server.run, name="api-server", daemon=True)
    t.start()
    log.info("API 服务启动中: http://%s:%d/api", host, port)
    return t