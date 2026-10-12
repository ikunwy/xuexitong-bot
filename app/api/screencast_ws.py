from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("app.api.screencast_ws")

router = APIRouter()


@router.websocket("/api/screencast")
async def screencast_ws(websocket: WebSocket):
    await websocket.accept()

    ctx = websocket.app.state.ctx
    sc = ctx.screencast
    if not sc:
        await websocket.send_json({"type": "error", "msg": "screencast 未初始化"})
        await websocket.close()
        return

    if not sc.ws:
        try:
            ok = await asyncio.to_thread(sc.start, 10, 0.5)   # 5 秒内重试
        except Exception:
            log.exception("[screencast-ws] 启动 CDP 异常")

    q = sc.subscribe()

    async def forward_frames():
        no_frame_count = 0
        try:
            while True:
                try:
                    frame = await asyncio.to_thread(q.get, True, 1.0)
                    no_frame_count = 0
                except Exception:
                    no_frame_count += 1
                    if no_frame_count >= 5:
                        no_frame_count = 0
                        try:
                            if not sc.ws:
                                await asyncio.to_thread(sc.start, 3, 0.5)
                            else:
                                sc.trigger_repaint()
                        except Exception:
                            log.exception("[screencast-ws] 兜底重连失败")
                    continue

                try:
                    await websocket.send_json({
                        "type": "frame",
                        "id": frame["id"],
                        "ts": frame["ts"],
                        "data": frame["data"],
                        "width": frame["width"],
                        "height": frame["height"],
                    })
                except Exception:
                    break
        except Exception:
            log.exception("[screencast-ws] 转发线程异常")
        finally:
            log.info("[screencast-ws] 转发线程结束")

    async def recv_input():
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                except Exception:
                    continue

                t = data.get("type")

                # 刷新请求
                if t == "refresh":
                    try:
                        if not sc.ws:
                            await asyncio.to_thread(sc.start, 3, 0.5)
                        sc.trigger_repaint()
                    except Exception:
                        log.exception("[screencast-ws] 刷新失败")
                    continue

                try:
                    if t == "mouse":
                        x = _safe_int(data.get("x"))
                        y = _safe_int(data.get("y"))
                        if x is None or y is None:
                            continue
                        sc.mouse(x, y,
                                 event_type=data.get("event", "click"),
                                 button=data.get("button", "left"),
                                 buttons=_safe_int(data.get("buttons")) or 0)
                    elif t == "key":
                        sc.key(str(data.get("key", "")),
                               str(data.get("text", "")),
                               ctrl=bool(data.get("ctrl", False)))
                    elif t == "text":
                        sc.insert_text(str(data.get("text", "")))
                    elif t == "scroll":
                        sc.scroll(
                            _safe_int(data.get("x")) or 0,
                            _safe_int(data.get("y")) or 0,
                            _safe_int(data.get("deltaY")) or 0,
                        )
                except Exception:
                    log.exception("[screencast-ws] 处理消息失败: %s", data)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("[screencast-ws] 接收线程异常")
        finally:
            log.info("[screencast-ws] 接收线程结束")

    try:
        await asyncio.gather(forward_frames(), recv_input())
    finally:
        sc.unsubscribe(q)


def _safe_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

