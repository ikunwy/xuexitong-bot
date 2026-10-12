from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.events import Events

router = APIRouter(prefix="/api")


def _ctx(request: Request):
    return request.app.state.ctx

def response_json(data: dict):
    return {
        "ok": True,
        "data": data,
        "ts": time.time(),
    }


@router.get("/commands")
def list_commands(request: Request):
    """列出所有已注册的命令。"""
    ctx = _ctx(request)
    return ctx.commands.stats()

@router.get("/commands/{name}")
async def call_command_get(
    request: Request,
    name: str,
    timeout: float = Query(30.0, ge=1, le=300),
    # 任意查询参数都会进这里
):
    ctx = _ctx(request)

    # 把 URL 查询参数转成 kwargs（去掉 timeout）
    kwargs = {k: v for k, v in request.query_params.items() if k != "timeout"}

    # 类型推断：数字字符串转 int/float
    kwargs = {k: _coerce(v) for k, v in kwargs.items()}
    try:
        task = ctx.commands.submit(name, kwargs)
    except KeyError as e:
        raise HTTPException(404, detail=str(e))

    ok = await asyncio.to_thread(task.done.wait, timeout)
    if not ok:
        raise HTTPException(504, detail="timeout")
    if task.error:
        raise HTTPException(500, detail=task.error)

    return response_json(task.result)

def _coerce(v: str):
    """把字符串尽量转成合适类型。"""
    import json
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("none", "null"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    if v.startswith(("{", "[")):
        try:
            return json.loads(v)
        except Exception:
            pass
    return v



@router.get("/config")
async def get_config(request: Request):
    ctx = _ctx(request)
    return response_json(ctx.config)

@router.post("/commands_control/{name}")
async def call_command_post(
     request: Request,
        name: str,
        timeout: float = Query(30.0, ge=1, le=300)
):
    ctx = _ctx(request)
    
    # 把 URL 查询参数转成 kwargs（去掉 timeout）
    kwargs = {k: v for k, v in request.query_params.items() if k != "timeout"}
    
    # 类型推断：数字字符串转 int/float
    kwargs = {k: _coerce(v) for k, v in kwargs.items()}
    try:
        task = ctx.commands.submit(name, kwargs)
    except KeyError as e:
        raise HTTPException(404, detail=str(e))

    ok = await asyncio.to_thread(task.done.wait, timeout)
    if not ok:
        raise HTTPException(504, detail="timeout")
    if task.error:
        raise HTTPException(500, detail=task.error)

    return response_json(task.result)


# ======================================================================
# 健康检查
# ======================================================================

@router.get("/health")
def health():
    return {"ok": True}


# ======================================================================
# 状态 / 数据
# ======================================================================

@router.get("/status")
def status(request: Request):
    ctx = _ctx(request)
    eng = ctx.engine
    return {
        "running": getattr(eng, "running", False),
        "paused": getattr(eng, "paused", False),
        "finished": getattr(eng, "finished", False),
        "has_driver": getattr(eng, "driver", None) is not None,
        "tasks": list(getattr(eng, "tasks", {}).keys()),
        "plugins": list(getattr(ctx.plugins, "loaded", [])),
        "stats": ctx.repo.stats(),
        "hub": ctx.hub.stats(),
    }


@router.get("/records")
def records(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    event: str | None = None,
):
    return _ctx(request).repo.recent_records(limit=limit, event=event)


# ======================================================================
# 事件历史 / SSE
# ======================================================================

@router.get("/events/recent")
def events_recent(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    event: str | None = None,
    since_seq: int = 0,
):
    ctx = _ctx(request)
    return {
        "items": ctx.hub.recent(limit=limit, event=event, since_seq=since_seq),
        "stats": ctx.hub.stats(),
    }

@router.get("/logs/stream")
async def logs_stream(
    request: Request,
    level: str | None = Query(None, description="最低级别: DEBUG/INFO/WARNING/ERROR"),
    keyword: str | None = Query(None, description="只推送包含关键字的日志"),
    heartbeat: float = 15.0,
):
    ctx = _ctx(request)
    q = ctx.log_hub.subscribe()

    level_order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    min_lv = level_order.get((level or "DEBUG").upper(), 0)
    kw = keyword.lower() if keyword else None

    async def gen():
        try:
            yield _sse({"event": "__ready__", "ts": __import__("time").time()})

            last_beat = __import__("time").time()
            while True:
                if await request.is_disconnected():
                    break

                try:
                    item = await asyncio.to_thread(q.get, True, 1.0)
                except Exception:
                    item = None

                if item is not None:
                    # 过滤
                    if level_order.get(item["level"], 0) < min_lv:
                        continue
                    if kw and kw not in item["message"].lower():
                        continue
                    yield _sse(item)
                    last_beat = __import__("time").time()
                elif __import__("time").time() - last_beat > heartbeat:
                    yield ": ping\n\n"
                    last_beat = __import__("time").time()
        finally:
            ctx.log_hub.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )



# ======================================================================
# 辅助
# ======================================================================

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"