from __future__ import annotations

import base64
import json
import logging
import threading
import time

import requests
import websocket

from app.core.events import Events

log = logging.getLogger("app.screencast")


class CDPScreencaster:
    """通过 CDP 抓取浏览器画面并转发给 WebSocket 客户端。

    支持多标签页切换：监听 TAB_SWITCH 事件，按 targetId 重连。
    """

    def __init__(self, ctx, debug_port: int = 9222) -> None:
        self.ctx = ctx
        self.debug_port = debug_port
        self.ws: websocket.WebSocket | None = None
        self.current_target_id: str | None = None
        self._recv_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reconnect_lock = threading.RLock()
        self._frame_id = 0
        self._subscribers: list = []
        self._lock = threading.RLock()
        self._msg_id = 0
        self._last_frame = None      
        self._stop_recv_evt = threading.Event()      # 只控制 recv 线程
        self._stop_monitor_evt = threading.Event()   # 只控制 monitor 线程
        # ★ 监听标签页切换
        ctx.bus.on(Events.TAB_SWITCH, self._on_tab_switch, priority=-50)

    # ------------------------------------------------------------------
    # 事件驱动重连
    # ------------------------------------------------------------------

    def _on_tab_switch(self, target_id: str | None = None, **payload) -> None:
        if not target_id:
            return
        if target_id == self.current_target_id:
            return

        threading.Thread(
            target=self._reconnect_to, args=(target_id,),
            daemon=True, name="screencast-reconnect",
        ).start()

    def _reconnect_to(self, target_id: str) -> None:
        """重连到指定 target。"""
        with self._reconnect_lock:
            self._stop_recv()

            ws_url = f"ws://127.0.0.1:{self.debug_port}/devtools/page/{target_id}"

            try:
                self.ws = websocket.create_connection(ws_url, timeout=5)
                self.current_target_id = target_id
            except Exception:
                log.exception("[screencast] 连接新 target 失败")
                return

            self._send("Page.enable", {})
            self._send("Page.startScreencast", {
                "format": "jpeg",
                "quality": 70,
                "maxWidth": 1280,
                "maxHeight": 900,
                "everyNthFrame": 1,
            })

            self._stop.clear()
            self._recv_thread = threading.Thread(
                target=self._recv_loop, name="cdp-recv", daemon=True,
            )
            self._recv_thread.start()

            self.ctx.bus.emit(Events.SCREENCAST_RECONNECTED, target_id=target_id)
            try:
                self._send("Runtime.evaluate", {
                    "expression": "window.dispatchEvent(new Event('resize'));"
                                "window.scrollBy(0,1);window.scrollBy(0,-1);"
                })
            except Exception:
                pass



    def _stop_recv(self) -> None:
        self._stop.set()
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=2)
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self.ws = None

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    def start(self, retries: int = 20, interval: float = 0.5) -> bool:
        if self.ws is not None and self._recv_thread and self._recv_thread.is_alive():
            log.info("[screencast] 已在运行")
            return True

        # ★ 每次都启动监控（幂等）
        self.start_monitor()

        target_id = None
        for i in range(retries):
            target_id = self._find_active_target_id()
            if target_id:
                break
            if i == 0:
                log.info("[screencast] 等待 CDP 就绪...")
            time.sleep(interval)

        if not target_id:
            log.error("[screencast] CDP target 始终未就绪")
            return False

        self._reconnect_to(target_id)

        # ★ 启动监控线程兜底（应对手动点击 Chrome UI 切标签）
        self.start_monitor()
        return self.ws is not None

    def stop(self) -> None:
        self._stop_recv()
        self.current_target_id = None

    # ------------------------------------------------------------------
    # 兜底监控（每 2 秒检查活跃 target）
    # ------------------------------------------------------------------

    def start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="cdp-monitor", daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        import time
        log.info("[screencast] 监控线程启动")

        while not self._stop_monitor_evt.is_set():
            time.sleep(2)

            if self._stop_monitor_evt.is_set():
                break

            # ★ CDP 没连，主动重连
            if self.ws is None:
                log.info("[screencast] 监控：CDP 未连接，尝试重连")
                try:
                    self.start(retries=3, interval=1.0)
                except Exception:
                    log.exception("[screencast] 监控重连异常")
                continue

            # CDP 已连，检查 target 是否变化
            try:
                active_id = self._find_active_target_id()
                if active_id and active_id != self.current_target_id:
                    log.info("[screencast] 监控：target 变化 %s...", active_id[:16])
                    self._reconnect_to(active_id)
            except Exception:
                log.exception("[screencast] 监控异常")

        log.info("[screencast] 监控线程退出")

    def _find_active_target_id(self) -> str | None:
        try:
            r = requests.get(f"http://127.0.0.1:{self.debug_port}/json", timeout=3)
            targets = r.json()
            for t in targets:
                if t.get("type") == "page" and not t.get("url", "").startswith("devtools"):
                    return t.get("id")
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 接收帧
    # ------------------------------------------------------------------

    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self.ws.recv()
                if not msg:
                    break
                data = json.loads(msg)
                method = data.get("method")
                if method == "Page.screencastFrame":
                    self._on_frame(data["params"])
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                if not self._stop.is_set():
                    log.exception("[screencast] 接收异常")
                break

    def _on_frame(self, params: dict) -> None:
        session_id = params.get("sessionId")
        b64 = params.get("data", "")
        metadata = params.get("metadata", {})

        # 必须 ack，否则 CDP 不再推下一帧
        self._send("Page.screencastFrameAck", {"sessionId": session_id})

        self._frame_id += 1
        payload = {
            "id": self._frame_id,
            "ts": time.time(),
            "data": b64,
            "width": metadata.get("deviceWidth"),
            "height": metadata.get("deviceHeight"),
        }

        self._last_frame = payload

        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(payload)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    # ------------------------------------------------------------------
    # 发送 CDP 命令
    # ------------------------------------------------------------------

    def _send(self, method: str, params: dict) -> None:
        if not self.ws:
            return
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params}
        try:
            self.ws.send(json.dumps(msg))
        except Exception:
            log.exception("[screencast] 发送失败: %s", method)
            self.ws = None

    # ------------------------------------------------------------------
    # 输入转发
    # ------------------------------------------------------------------

    def mouse(self, x: int, y: int, event_type: str = "click",
          button: str = "left", buttons: int = 0) -> None:
        """转发鼠标事件。

        event_type:
        - click  完整点击（pressed + released）
        - down   按下
        - up     松开
        - move   移动
        buttons: 位掩码，1=左键按下，2=右键按下
        """
        if not self.ws:
            return

        try:
            x = int(x)
            y = int(y)
            buttons = int(buttons)
        except (TypeError, ValueError):
            log.warning("[screencast] 非法鼠标参数: x=%r y=%r buttons=%r",
                        x, y, buttons)
            return

        try:
            if event_type == "click":
                self._send("Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": x, "y": y,
                    "button": button, "buttons": 1, "clickCount": 1,
                })
                self._send("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": x, "y": y,
                    "button": button, "buttons": 0, "clickCount": 1,
                })

            elif event_type == "down":
                self._send("Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": x, "y": y,
                    "button": button, "buttons": 1, "clickCount": 1,
                })

            elif event_type == "up":
                self._send("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": x, "y": y,
                    "button": button, "buttons": 0, "clickCount": 1,
                })

            elif event_type == "move":
                self._send("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": x, "y": y,
                    "button": button if button != "none" else "none",
                    "buttons": buttons,
                })

            else:
                log.warning("[screencast] 未知鼠标事件: %s", event_type)

        except Exception:
            log.exception("[screencast] 发送鼠标事件失败")

    def key(self, key: str, text: str = "", ctrl: bool = False) -> None:
        modifiers = 2 if ctrl else 0
        self._send("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": key, "text": text,
            "modifiers": modifiers,
        })
        self._send("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key, "modifiers": modifiers,
        })

    def insert_text(self, text: str) -> None:
        self._send("Input.insertText", {"text": text})

    def scroll(self, x: int, y: int, delta_y: int) -> None:
        self._send("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": x, "y": y,
            "deltaX": 0, "deltaY": delta_y,
        })

    # ------------------------------------------------------------------
    # 订阅
    # ------------------------------------------------------------------

    def subscribe(self, maxsize: int = 5):
        import queue
        q: queue.Queue = queue.Queue(maxsize=maxsize)

        with self._lock:
            if self._last_frame is not None:
                try:
                    q.put_nowait(self._last_frame)
                except Exception:
                    pass
            self._subscribers.append(q)

        self.trigger_repaint()

        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def stats(self) -> dict:
        with self._lock:
            return {
                "connected": self.ws is not None,
                "target_id": self.current_target_id,
                "subscribers": len(self._subscribers),
                "frame_count": self._frame_id,
            }

    def trigger_repaint(self) -> None:
        """触发远程页面重绘，逼 CDP 推新帧。

        页面静止时 CDP 不推帧，主动触发 resize / scroll / opacity 变化，
        让页面产生视觉变化。
        """
        if not self.ws:
            log.debug("[screencast] ws 未连接，跳过重绘")
            return

        try:
            self._send("Runtime.evaluate", {
                "expression": (
                    "(() => {"
                    "  try {"
                    # 1. resize 事件
                    "    window.dispatchEvent(new Event('resize'));"
                    # 2. opacity 微调 + requestAnimationFrame 恢复
                    "    if (document.body) {"
                    "      const old = document.body.style.opacity;"
                    "      document.body.style.opacity = '0.99';"
                    "      requestAnimationFrame(() => {"
                    "        document.body.style.opacity = old || '';"
                    "      });"
                    "    }"
                    # 3. 滚动 1 像素再滚回
                    "    const sy = window.scrollY;"
                    "    window.scrollBy(0, 1);"
                    "    setTimeout(() => window.scrollBy(0, -1), 10);"
                    "  } catch (e) {}"
                    "})()"
                ),
            })
        except Exception:
            log.exception("[screencast] 触发重绘失败")