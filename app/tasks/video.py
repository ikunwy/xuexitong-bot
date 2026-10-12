from __future__ import annotations

import time

from app.core.events import Events
from app.tasks.base import BaseTask


class VideoTask(BaseTask):
    name = "video"

    # 页面元素选择器（按实际情况调整）
    SEL_VIDEO = ("css selector", "video")
    SEL_PLAY_BTN = ("css selector", ".vjs-big-play-button, .prism-big-play-btn")

    def run(self, chapter_url: str | None = None, **kwargs) -> dict:
        cfg = self.ctx.config.get("video", {})
        rate = float(cfg.get("playback_rate", 1.0))
        finish_ratio = float(cfg.get("finish_ratio", 0.95))
        wait_after = float(cfg.get("wait_after_finish", 3.0))

        if chapter_url:
            self.nav.get(chapter_url)
            self.ctx.bus.emit(
                Events.CHAPTER_ENTER,
                chapter_id=kwargs.get("chapter_id", ""),
                name=kwargs.get("name", ""),
                type="video",
            )

        video = self._find_video()
        if video is None:
            self.log.warning("未找到 video 元素，跳过")
            return {"status": "skipped", "reason": "no_video"}

        self.ctx.bus.emit(Events.VIDEO_START, rate=rate)
        self._apply_rate(video, rate)
        self._click_play()

        result = self._monitor(video, finish_ratio, wait_after)
        self.ctx.bus.emit(Events.VIDEO_FINISH, **result)
        return result

    def _find_video(self):
        by, loc = self.SEL_VIDEO
        try:
            from app.browser.waits import wait_present
            return wait_present(self.driver, by, loc, timeout=15)
        except Exception:
            return None

    def _apply_rate(self, video, rate: float) -> None:
        try:
            self.driver.execute_script(
                "arguments[0].playbackRate = arguments[1];", video, rate
            )
            self.log.info("已设置倍速: %sx", rate)
        except Exception:
            self.log.exception("设置倍速失败")

    def _click_play(self) -> None:
        try:
            from app.browser.waits import wait_clickable
            by, loc = self.SEL_PLAY_BTN
            btn = wait_clickable(self.driver, by, loc, timeout=3)
            btn.click()
        except Exception:
            # 有的页面自动播放，点击失败属正常
            self.log.debug("未找到播放按钮，尝试直接播放")

    def _monitor(self, video, finish_ratio: float, wait_after: float) -> dict:
        last_emitted = -1
        while True:
            try:
                state = self.driver.execute_script(
                    """
                    const v = arguments[0];
                    return {
                        current: v.currentTime,
                        total: v.duration || 0,
                        paused: v.paused,
                        ended: v.ended,
                    };
                    """,
                    video,
                )
            except Exception:
                self.log.exception("读取视频状态失败")
                return {"status": "error", "reason": "read_state"}

            total = float(state.get("total") or 0)
            current = float(state.get("current") or 0)
            if total <= 0:
                time.sleep(1)
                continue

            percent = current / total
            bucket = int(percent * 100)
            if bucket != last_emitted and bucket % 5 == 0:
                self.ctx.bus.emit(
                    Events.VIDEO_PROGRESS,
                    current=round(current, 1),
                    total=round(total, 1),
                    percent=round(percent, 3),
                )
                last_emitted = bucket

            if state.get("ended") or percent >= finish_ratio:
                time.sleep(wait_after)
                return {
                    "status": "done",
                    "current": round(current, 1),
                    "total": round(total, 1),
                    "percent": round(percent, 3),
                }

            time.sleep(2)