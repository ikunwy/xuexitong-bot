from __future__ import annotations

import logging
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from app.core.events import Events
from typing import Literal
from math import ceil

log = logging.getLogger("app.browser.course")


class CoursePage:
    def __init__(self, ctx, navigator) -> None:
        self.ctx = ctx
        self.nav = navigator
        self.driver = navigator.driver
        self.current_mode = 'unknown'  # 当前节次的模式：video / docment / audio / empty / unknown
        self.current_chapter_tap = 0
        self.retry_num = 1 # 重试次数

        self.data = {
            "courses": [],
            "chapters": []
        }

        cfg = ctx.config.get("course", {})
        self.video_cfg = ctx.config.get("video", {})
        self.docment_cfg = ctx.config.get("docment", {})
        self.course_name: str = cfg.get("name", "")
        self.course_index: int = int(cfg.get("index", 0))
        self.ctx.commands.register("get_courses", lambda: self.data.get('courses'))  # 返回课程列表

        # 可外部覆盖的卡片选择器，默认给一组常见的
        self.card_selectors: list[str] = cfg.get(
            "card_selectors",
            [
                "div.course",
                "div.course-info",
                "a.course-card",
                "div.course-cover",
                "li.course-item",
                "//div[contains(@class,'course')]//a",
            ],
        )
        # iframe 候选（name 或 css）
        self.iframe_selectors: list[str] = cfg.get(
            "iframe_selectors",
            ["frame_content", "iframe[name='frame_content']", "iframe"],
        )

    # ---------- 选课 ----------

    def scroll_course(self):
        self._switch_to_course_frame(10.0)
        course_content = self.driver.find_element(By.CSS_SELECTOR, '.content')
        if not len(self.data.get('courses')):
            self._scroll_height(el=course_content)  # 滑动课程列表，使课程全部刷新出来
        self._find_cards()

    def select_course(self, name: str | None = None,
                      index: int | None = None,) -> bool:
        name =  name or self.course_name

        index = self.course_index if index is None else index
        cards = self._find_cards()
        if not cards:
            log.error("未找到课程元素，请检查配置 login.card_selectors")
            return False
        target = None
        if name:
            for card in cards:
                text = (card.text or "").strip()
                if name in text:
                    target = card
                    log.info("匹配到课程: %s", text[:40])
                    self.course_name = text
                    break
            if target is None:
                log.warning("未找到名称包含 '%s' 的课程", name)
                return False
        else:
            idx = min(index, len(cards) - 1)
            target = cards[idx]
            log.info("按序号选中第 %d 个课程: %s", idx,
                     (target.text or "")[:40])

        old_handles = set(self.driver.window_handles)
        self.driver.execute_script("arguments[0].scrollIntoView(true);", target)
        time.sleep(0.3)
        target.find_element(By.CSS_SELECTOR, 'a').click()
        time.sleep(2)

        new_handles = set(self.driver.window_handles) - old_handles
        if new_handles:
            self.driver.switch_to.window(new_handles.pop())
            log.info("课程在新标签页打开，已切换")

        self.ctx.bus.emit(Events.COURSE_SELECTED,
                          name=name, url=self.driver.current_url)
        menu_nav = self.driver.find_elements(By.CSS_SELECTOR, 'a[title="章节"]')
        if menu_nav:
                menu_nav[0].click()
        self._enter_chapter()
        return True

    # ---------- 内部 ----------

    def _find_cards(self) -> list:
        self._switch_to_course_frame(5.0)
        for sel in self.card_selectors:
            if sel.startswith("//"):
                cards = self.driver.find_elements(By.XPATH, sel)
            else:
                cards = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if cards:
                log.info("选择器 '%s' 命中 %d 个课程元素", sel, len(cards))
                if not self.data.get('courses'):
                    courses = []
                    for card in cards:
                        info = card.find_elements(By.CSS_SELECTOR, '.course-info')
                        info_text = info[0].text.split('\n') if info and len(info) > 0 else None
                        img = card.find_elements(By.CSS_SELECTOR, 'img')
                        img_src = img[0].get_attribute('src') if img and len(img) > 0 else None
                        progress = card.find_elements(By.CSS_SELECTOR, '.btm-cover')
                        progress_text = progress[0].text if progress and len(progress) > 0 else None
                        progress_info = []
                        if progress_text:
                            l, r = progress_text.split('\n')
                            progress_info = [l, r]
                        
                        courses.append({
                            "title": info_text,
                            "img": img_src,
                            "progress": progress_info,
                            'ts': time.time()
                        })
                    self.data['courses'] = courses
                return cards
        return []

    def _switch_to_course_frame(self, timeout: float) -> None:
        for sel in self.iframe_selectors:
            try:
                if sel.startswith("//") or "[" in sel or "#" in sel or "." in sel:
                    by, loc = By.CSS_SELECTOR, sel
                elif sel == "iframe":
                    by, loc = By.TAG_NAME, sel
                else:
                    by, loc = By.NAME, sel
                WebDriverWait(self.driver, 0).until(
                    EC.frame_to_be_available_and_switch_to_it((by, loc))
                )
                log.info("已切入 iframe: %s", sel)
                return
            except Exception:
                continue
        log.debug("未发现课程 iframe，保持当前上下文")

    def _enter_chapter(self) -> None:
        self.driver.switch_to.window(self.driver.window_handles[1])
        self.nav.frames.switch_to(id="frame_content-zj")
        festivals = self.driver.find_elements(By.CSS_SELECTOR, '.catalog_level .chapter_item')
        for festival in festivals:
            title = festival.find_element(By.CSS_SELECTOR, '.catalog_name').text
            un_festival_num = festival.find_elements(By.CSS_SELECTOR, '.catalog_task .catalog_points_yi')
            if un_festival_num:
                self.ctx.bus.emit(Events.CHAPTER_START)
                log.info('当前节次 %s 正在进入...', title)
                festival.click()
                time.sleep(0.5)
                self.get_chapters_text()
                self._judgment_mode()
                break

    def get_chapters_text(self) -> dict:
        self.nav.frames.switch_to_default()
        chapters = self.driver.find_element(By.CSS_SELECTOR, '#coursetree')
        lis = chapters.find_elements(By.CSS_SELECTOR, 'li .posCatalog_select')
        chapters = []
        for li in lis:
            if li.get_attribute('class') == 'posCatalog_select':
                name, *num = li.text.split('\n')
                num = num[0] if num else ''
                stage_chapter = int(name[:2].replace('.', ''))
                if len(chapters) < stage_chapter:
                    chapters.append([])
                chapters[stage_chapter - 1].append([name, num])
        chapters = {
            'name': self.course_name,
            'count': len(chapters),
            'list': chapters,
        }
        self.ctx.bus.emit(Events.CHAPTER_LIST, chapter=chapters)
        self.data['chapters'] = chapters
        self.ctx.commands.register("get_chapters_text", lambda: self.data.get('chapters'))  # 返回课程列表
    
    def _chapter_next(self) -> None:
        if self.ctx.config.get('paused'):
            print('刷课已暂停')
            return
        # tpas = self.driver.find_elements(By.CSS_SELECTOR, '.prev_ul.clearfix li')
        # if tpas and len(tpas) > 0:
        #     if self.current_chapter_tap == len(tpas):
        #         self._chapter_list_next()
        #         return
        time.sleep(0.3)
        self.nav.frames.switch_to_default()
        
        try:
            next_btn = self.driver.find_element(By.CSS_SELECTOR, '#prevNextFocusNext')
            next_btn.click()
            try:
                next_btn_un = self.driver.find_element(By.CSS_SELECTOR, '.popBottom .nextChapter')
                if next_btn_un:
                    next_btn_un.click()
            except:
                pass
            self._judgment_mode()
            log.info('当前模式 %s', self.current_mode)
            self.nav.frames.switch_to_default()
            self.ctx.bus.emit(Events.CHAPTER_NEXT)
        except Exception as err:
            print(err)
            log.info('当前节次已是最后一节')
            return
        
    def _start(self) -> None:
        if self.current_mode == 'empty':
            print('无匹配模式，进入下一节')
            # self.current_chapter_tap += 1
            self._chapter_next()
        if self.current_mode == 'video':
            self._play_video()
        if self.current_mode == 'docment':
            self._handle_docment()
        if self.current_mode == 'unknown':
            print('未定义模式，进入下一节')
            self._chapter_next()

    # def _chapter_list_next(self) -> None:
    #     chapters = self.driver.find_elements(By.CSS_SELECTOR, '#coursetree .posCatalog_name')
    #     if chapters and len(chapters) > 0:
    #         for chapter in chapters:
    #             chapter_nums = chapter.find_elements(By.CSS_SELECTOR, '.prevTips .orangeNew')
    #             if chapter_nums and len(chapter_nums) > 0:
    #                 log.info('当前章节 %s 正在进入...', chapter.text)
    #                 chapter.click()

    def _update_mode(self, mode: Literal['video', 'docment', 'audio', 'empty', 'do_exercises', 'unknown']) -> None:
        self.current_mode = mode
        return mode

    def _judgment_mode(self) -> None:
        self.nav.frames.switch_to_default()
        self.nav.frames.switch_to(id="iframe")
        mode = 'unknown'
        time.sleep(1)
        # 空章节
        try:
            empty_str = self.driver.find_element(By.CSS_SELECTOR, '.ans-cc dd')
            if empty_str and empty_str[0] == '暂无内容':
                mode = self._update_mode('empty')
                return mode
        except Exception:
                pass
        # 音频
        try:
            self.nav.frames.switch_to_default()
            self.nav.frames.switch_to(id="iframe")
            iframes_of_audio = self.driver.find_elements(By.CSS_SELECTOR, "iframe[class='ans-attach-online ans-insertaudio']")
            if iframes_of_audio and len(iframes_of_audio) > 0:
                self.nav.frames.switch_to(element=iframes_of_audio)
            audio = self.driver.find_element(By.CSS_SELECTOR, '#audio_html5_api')
            if audio:
                mode = self._update_mode('audio')
                return
        except Exception:
            pass
       
        # 视频
        try:
            self.nav.frames.switch_to_default()
            self.nav.frames.switch_to(id="iframe")
            iframes_of_video = self.driver.find_elements(By.CSS_SELECTOR, "iframe[class='ans-attach-online ans-insertvideo-online']")
            if iframes_of_video and len(iframes_of_video) > 0:
                mode = self._update_mode('video')
                return
        except Exception:
            pass

        # 文档
        try:
            docment_els = ["iframe[class='ans-attach-online insertdoc-online-pdf']", "iframe[class='ans-attach-online insertdoc-online-ppt']"]
            for docment_el in docment_els:
                docment = self.driver.find_elements(By.CSS_SELECTOR, docment_el)
                if docment and len(docment) > 0:
                    mode = self._update_mode('docment')
                    return
        except Exception:
            pass

        # 描述（空章节）直接下一节
        try:
            self.nav.frames.switch_to_default()
            self.nav.frames.switch_to(id="iframe")
            desc = self.driver.find_element(By.CSS_SELECTOR, '#pageDiv')
            if desc and desc[0] == '暂无内容':
                mode = self._update_mode('empty')
                return
        except Exception:
            pass

        if mode == 'unknown':
            self._update_mode('unknown')

    def _play_video(self) -> None:
        def _play(video_el) -> None:
            self.nav.frames.switch_to(element=video_el)
            video = self.driver.find_element(By.CSS_SELECTOR, '#video_html5_api')
            self.driver.execute_script(f"arguments[0].muted = {self.video_cfg.get('mute', 'true')}", video)  # 静音
            self.driver.execute_script(f"arguments[0].playbackRate  = {self.video_cfg.get('playback_rate', 2)}", video)  # 2倍速
            self.driver.execute_script("arguments[0].play()", video)
            time.sleep(3)
            while True:
                video_state = self.driver.execute_script("return arguments[0].paused", video)
                if not video_state:
                    break
            time.sleep(0.3)
            try:
                video_duration = self.driver.execute_script("return arguments[0].duration", video)
                self.driver.execute_script(f"arguments[0].currentTime = {float(video_duration * float(self.video_cfg.get('skip', 0.95)))}", video)
                video_current_time = self.driver.execute_script("return arguments[0].currentTime", video)
                if int(video_current_time) != int(float(video_duration) * float(self.video_cfg.get('skip', 0.95))):
                    self.driver.execute_script("arguments[0].play()", video)
                while True:
                    video_current_time = self.driver.execute_script("return arguments[0].currentTime", video)
                    if int(video_current_time) == int(float(video_duration) * float(self.video_cfg.get('skip', 0.95))):
                        log.info('视频播放完毕')
                        self.nav.frames.switch_to_default()
                        time.sleep(self.video_cfg.get('wait_after_finish', 2))
                        self._chapter_next()
                        break
            except Exception:
                if self.retry_num < 3:
                    self._play_video()
                else:
                    self.retry_num = 1
                    log.error('视频播放失败，已重试 %d 次', self.retry_num)
                self.retry_num += 1
                pass
        self.nav.frames.switch_to_default()
        self._scroll_height(el=self.driver.find_element(By.CSS_SELECTOR, '#mainid')) # 滑动
        self.nav.frames.switch_to(id="iframe")
        videos = self.driver.find_elements(By.CSS_SELECTOR, "iframe[class='ans-attach-online ans-insertvideo-online']")
        print(videos, len(videos))
        if videos and len(videos) > 0:
            for video in videos:
                _play(video)

    def _handle_docment(self) -> None:
        self.nav.frames.switch_to_default()
        depth = 0
        self._scroll_height(el=self.driver.find_element(By.CSS_SELECTOR, '#mainid')) # 滑动
        if self.nav.frames.switch_to(id="iframe"):
            depth += 1
        docment_iframes = ["iframe[class='ans-attach-online insertdoc-online-pdf']", "iframe[class='ans-attach-online insertdoc-online-ppt']"]
        for docment_iframe in docment_iframes:
            els = self.driver.find_elements(By.CSS_SELECTOR, docment_iframe)
            if els and len(els) > 0:
                depth = 2
                print(els, len(els))
                for el in els:
                    self.nav.frames.switch_to(element=el)
                    self.nav.frames.switch_to(id="panView")
                    self.driver.execute_script("window.scrollTo(0, 2000000)")
                    # 重置
                    self.nav.frames.switch_to_default()
                    self.nav.frames.switch_to(id="iframe")
                    depth = 3
                    time.sleep(0.5)
                break

        log.info('当前文档深度 %s', depth if depth > 0 else '未切入文档 iframe')
        if depth == 0:
            log.warning('未切入文档 iframe，暂停刷课')
            return
        time.sleep(self.docment_cfg.get('wait_after_finish', 2))
        self._chapter_next()

    def _scroll_height(self, el) -> None:
        scroll_height = self.driver.execute_script("return arguments[0].scrollHeight", el)
        height_distance = 300 # 每次滑动距离
        scroll_nums = ceil(scroll_height / height_distance)
        for i in range(scroll_nums):
            self.driver.execute_script(f"window.scrollTo(0, {i*height_distance})")  # 滑动课程列表，使课程全部刷新出来
            time.sleep(0.3)
        self.driver.execute_script("window.scrollTo(0, 2000000)")

