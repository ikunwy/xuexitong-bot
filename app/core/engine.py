from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By
from app.core.events import Events
from app.browser.course import CoursePage


class Engine:
    """主调度引擎：负责浏览器生命周期、登录、选课、任务执行。"""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.log = logging.getLogger("app.engine")
        self.driver = None
        self.nav = None
        self.tasks: dict = {}

        # 事件监听 启动/暂停
        ctx.bus.on(Events.STATUS_RUNNING, lambda: self.ctx.config.update({'running': True}) and ctx.bus.emit(Events.STATUS_UPDATE))
        ctx.bus.on(Events.STATUS_PAUSE, lambda: self.ctx.config.update({'running': False}) and ctx.bus.emit(Events.STATUS_UPDATE))
        
    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _ensure_browser(self) -> None:
        """按需创建浏览器 + Navigator + 任务实例（幂等）。"""
        if self.driver is not None:
            return

        from app.browser.driver import create_driver
        from app.browser.navigator import Navigator
        from app.tasks.video import VideoTask

        browser_cfg = self.ctx.config.get("browser", {})
        self.log.info("启动浏览器...")
        self.driver = create_driver(browser_cfg)
        self.nav = Navigator(self.ctx, self.driver)

        # ★ 注册可在主线程执行的命令
        self._register_commands()

        # 注册所有可用任务，按 engine.mode 选择
        self.tasks = {
            "video": VideoTask(self.ctx, self.nav),
        }
        if self.ctx.config.get("screencast", {}).get("enabled", True):
            import threading
            threading.Thread(
                target=self._start_screencast_later,
                daemon=True,
                name="screencast-init",
            ).start()
            self.log.info("浏览器已启动，可用任务: %s", list(self.tasks.keys()))

    def _register_commands(self) -> None:
        """注册所有可被 API 调用的命令。这些 handler 会在主线程执行。"""

        def get_chapters(course_name: str | None = None, **_) -> dict:
            page = CoursePage(self.ctx, self.nav)
            data = page.list_chapters(course_name=course_name)   # 需实现
            return data

        def get_current_status(**_):
            url = self.driver.current_url if self.driver else ""
            title = self.driver.title if self.driver else ""
            return {
                "url": url,
                "title": title,
                "running": self.running,
                "paused": self.paused,
                "task": None,
            }

        def goto(url: str, **_):
            self.nav.get(url)
            return {"url": url, "title": self.driver.title}

        def switch_top(**_):
            self.nav.frames.switch_to_top()
            return {"ok": True}

        def eval_js(script: str, **_):
            return {"result": self.driver.execute_script(script)}

        self.ctx.commands.register("get_chapters", get_chapters)
        self.ctx.commands.register("get_current_status", get_current_status)
        self.ctx.commands.register("goto", goto)
        self.ctx.commands.register("switch_top", switch_top)
        self.ctx.commands.register("eval_js", eval_js)

        self.ctx.commands.register("course_control_stop", self.shutdown)  # 结束刷课
        self.ctx.commands.register("course_control_pause", self._on_pause)  # 暂停刷课
        self.ctx.commands.register("course_control_resume", self._on_resume)  # 恢复刷课
        self.ctx.commands.register("course_navigator_back", self.nav.back)  # 返回上一页

        self.ctx.commands.register(
            "tab_list",
            lambda **_: self.nav.tabs.list_tabs(),
        )
        self.ctx.commands.register(
            "tab_switch_index",
            lambda index=0, **_: {
                "ok": self.nav.tabs.switch_to_index(int(index)),
                "current": self.driver.current_url,
            },
        )


        self.ctx.commands.register("tab_close_current", self.nav.tabs.close_current)

    def shutdown(self) -> None:
        """停止引擎并关闭浏览器。"""
        if self.nav is not None:
            try:
                self.nav.quit()

            except Exception:
                self.log.exception("关闭浏览器异常")
            finally:
                self.nav = None
                self.driver = None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def _tick(self, poll: float = 0.5) -> bool:
        self._process_commands()        # ★ 必须要有这一行
        while self.paused and self.running:
            self._process_commands()    # ★ 暂停时也要处理
            time.sleep(poll)
        return self.running

    def _process_commands(self) -> None:
        try:
            n = self.ctx.commands.process_pending()
            if n:
                self.log.info("处理了 %d 个命令", n)
        except Exception:
            self.log.exception("处理命令异常")
    
    def run(self) -> None:
        engine_cfg = self.ctx.config.get("engine", {})
        login_cfg = self.ctx.config.get("login", {})
        course_cfg = self.ctx.config.get("course", {})
        # mode = engine_cfg.get("mode", None)
        # courses = engine_cfg.get("courses", []) or []
        # interval = float(engine_cfg.get("interval", 2.0))
        if self.ctx.config.get("screencast", {}).get("enabled", True):
            self.ctx.screencast.start()
        # ---------- 1. 登录阶段 ----------
        if login_cfg.get("enabled", True):
            if not self._do_login(login_cfg):
                self.log.error("登录失败，终止流程")
                self.shutdown()
                return
            # 登录后可选自动选课
            if not self._do_select_course(course_cfg):
                self.log.error("选课失败，终止流程")
                self.shutdown()
                return
        else:
            self.log.info("login.enabled = false，跳过登录")

        page = CoursePage(self.ctx, self.nav)
        page.scroll_course()
        self.ctx.commands.register("course_select", page.select_course)  # 恢复刷课

        # page._enter_chapter()
        while self.ctx.config.get('running'):
            self._process_commands()
            if self.ctx.config.get('paused'):
                # self.log.info("引擎已暂停，等待恢复...")
                time.sleep(2)
                continue
            page._chapter_next()
            page._start()
            # self.log.info("开始执行任务")

            

        # ---------- 3. 真实任务：需要浏览器 ----------
        # self._ensure_browser()

        # task = self.tasks.get(mode)
        # if task is None:
        #     self.log.error("未知任务类型: %s（可用: %s）", mode, list(self.tasks))
        #     self.shutdown()
        #     return

        # try:
        #     for idx, url in enumerate(courses, 1):
        #         if not self.running:
        #             self.log.info("收到停止信号，跳出循环")
        #             break

        #         self.log.info("=== 课程 %d/%d: %s ===", idx, len(courses), url)
        #         self.ctx.bus.emit(Events.ROUND_START, round=idx)

        #         self._run_one_course(url, task)

        #         self.ctx.bus.emit(Events.ROUND_END, round=idx)

        #         if idx < len(courses):
        #             time.sleep(interval)

        #     self.log.info("所有课程处理完毕")
        # finally:
        #     self.shutdown()

    # ------------------------------------------------------------------
    # 登录 / 选课
    # ------------------------------------------------------------------

    def _do_login(self, login_cfg: dict) -> bool:
        """执行登录，返回是否成功。"""
        self.log.info("开始登录流程，目标: %s", login_cfg.get("url", "(未配置)"))
        self._ensure_browser()

        from app.browser.login import LoginPage

        try:
            page = LoginPage(self.ctx, self.nav)
            ok = page.login()
            if ok:
                self.ctx.config['login']['is_login'] = True
                self.ctx.repo.add_record(event="login.success",
                                         message=login_cfg.get("url", ""))
            else:
                self.ctx.repo.add_record(event="login.failed", message="timeout")
            return ok
        except Exception as exc:
            self.log.exception("登录过程异常")
            self.ctx.bus.emit(Events.TASK_ERROR, task="login", exc=exc, retry=False)
            return False

    def _do_select_course(self, course_cfg: dict) -> bool:
        """根据配置判断是否需要选课，需要则执行。"""
        name = course_cfg.get("name", "") or ""
        index = int(course_cfg.get("index", 0) or 0)

        # 无课程名且索引为 0 视为“不自动选课”
        if not name and index == 0:
            self.log.info("未配置自动选课（course/name 为空且 course/index=0），跳过")
            return True

        self.log.info("开始自动选课: name=%r, index=%d", name, index)

        try:
            menu_nav = self.driver.find_elements(By.CSS_SELECTOR, 'div[name="课程"]')
            if menu_nav:
                menu_nav[0].click()
            return True
        except Exception as exc:
            self.log.exception("选课过程异常")
            self.ctx.bus.emit(Events.TASK_ERROR, task="course", exc=exc, retry=False)
            return False

    def _run_one_course(self, url: str, task) -> None:
        """打开课程 URL 并执行指定任务。"""
        # 打开课程页
        try:
            self.nav.get(url)
            self.ctx.bus.emit(Events.COURSE_ENTER, course_url=url)
        except Exception as exc:
            self.log.exception("进入课程失败: %s", url)
            self.ctx.bus.emit(
                Events.TASK_ERROR, task="course", exc=exc, retry=False
            )
            return

        # 执行任务
        try:
            self.log.info("执行任务: %s", task.name)
            result = task.run()
            self.log.info("任务完成: %s", result)

            self.ctx.repo.add_record(event="task.done", message=str(result))
            self.ctx.bus.emit(Events.TASK_DONE, task=task.name, result=result)
        except Exception as exc:
            self.log.exception("任务 %s 执行失败", task.name)
            self.ctx.repo.add_record(event="task.error", message=str(exc)[:200])
            self.ctx.bus.emit(
                Events.TASK_ERROR, task=task.name, exc=exc, retry=True
            )



    def _on_stop(self, **_):
        """收到停止指令：改标志。可能在 API 线程执行。"""
        self.ctx.config['running'] = False
        self.ctx.config['paused'] = False
        self.log.info("[控制] 停止指令已生效: running=%s paused=%s",
                    self.ctx.config['running'], self.ctx.config['paused'])
        self.ctx.commands.register("course_control_stop", self.shutdown)  # 结束刷课


    def _on_pause(self, **_):
        """收到暂停指令：只改标志。"""
        if not self.ctx.config['running']:
            return
        self.ctx.config['paused'] = True
        self.log.info("[控制] 暂停指令已生效")
        

    def _on_resume(self, **_):
        self.ctx.config['paused'] = False
        self.log.info("[控制] 继续指令已生效")
        print(self.ctx.config.get('paused'))


    def _start_screencast_later(self):
        """浏览器启动后延迟启动 CDP 推流，避免端口未就绪。"""
        import time
        time.sleep(3)
        try:
            ok = self.ctx.screencast.start()
            if ok:
                self.log.info("CDP 推流已就绪")
            else:
                self.log.warning("CDP 推流启动失败，可调 /api/commands/screencast_start")
        except Exception:
            self.log.exception("启动 CDP 推流异常")



