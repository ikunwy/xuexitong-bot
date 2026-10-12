class Events:
    APP_START = "app.start"
    APP_EXIT = "app.exit"

    ROUND_START = "round.start"
    ROUND_END = "round.end"
    TASK_DONE = "task.done"
    TASK_ERROR = "task.error"

    # 状态
    STATUS_UPDATE = "status.update"
    STATUS_RUNNING = "status.running"
    STATUS_PAUSE = "status.pause"

    # 浏览器/页面
    PAGE_ENTER = "page.enter"
    COURSE_ENTER = "course.enter"
    CHAPTER_ENTER = "chapter.enter"

    # 视频
    VIDEO_START = "video.start"
    VIDEO_PROGRESS = "video.progress"
    VIDEO_FINISH = "video.finish"

    # 登录
    LOGIN_SUCCESS = "login.success"

    # 选择课程
    COURSE_SELECTED = "course.selected"
    COURSE_LIST = "course.list"

    # 章节
    CHAPTER_START = "chapter.enter" # 进入
    CHAPTER_PAUSE = "chapter.pause" # 暂停
    CHAPTER_RESUME = "chapter.resume" # 恢复
    CHAPTER_RESTART = "chapter.restart" # 重启
    CHAPTER_REPLAY = "chapter.prev" # 上一个
    CHAPTER_NEXT = "chapter.next" # 下一个
    CHAPTER_END = "chapter.exit" # 退出

    # 课程章节信息
    CHAPTER_INFO = "chapter.info"
    CHAPTER_LIST = "chapter.list"

    # iframe
    FRAME_ENTER = "frame.enter"
    FRAME_EXIT = "frame.exit"
    FRAME_ERROR = "frame.error"



    # ★ 控制事件
    CONTROL_STOP = "control.stop"
    CONTROL_PAUSE = "control.pause"
    CONTROL_RESTART = "control.restart" # 重启
    CONTROL_RESUME = "control.resume" # 恢复

    # ★ 状态通知
    STATE_CHANGED = "state.changed"


    TAB_SWITCH = "tab.switch"
    TAB_OPEN = "tab.open"
    TAB_CLOSE = "tab.close"

    # ★ 推流事件
    SCREENCAST_RECONNECTED = "screencast.reconnected"