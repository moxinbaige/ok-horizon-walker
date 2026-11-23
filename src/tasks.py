import json
from datetime import datetime
from pathlib import Path
import re
import time

import cv2
from ok import BaseTask
from ok.task.exceptions import TaskDisabledException
from src.recovery import RecoveryMixin
from src.event import EventMixin
from src.event_profiles import EVENT_PROFILES
from src.shop import NewShopMixin
from src.interaction import UndispatchedClick
from src.settings import DEFAULTS, DESCRIPTIONS, RAID_TARGETS, TYPES, DailyConfig, task_option
from src.runtime import record_run
from src.stage_recovery import RoutineError, RecoverableStageError, recover_step

from src.vision import (ROOT, Templates, compact, normalize, parse_attempts,
                        parse_score, select_coin_wishes, valid_contract, is_sign_in_claim,
                        auto_battle_enabled, contract_unavailable)


class HorizonTask(BaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.templates = Templates()
        self.image = None
        self.words = []
        self.completed = False
        self.navigation_audit = []
        self.action_audit = []
        self.timings = {}
        self.stage_timings = []
        self._record_evidence = True

    def option(self, key):
        return task_option(self, key)

    def measure(self, name, started):
        if not hasattr(self, "timings"):
            self.timings = {}
        entry = self.timings.setdefault(name, {"count": 0, "seconds": 0.0})
        entry["count"] += 1
        entry["seconds"] = round(entry["seconds"]+time.perf_counter()-started, 6)

    @property
    def words(self):
        if self._words is None:
            started = time.perf_counter()
            self._words = self.ocr(frame=self.image, threshold=0.65)
            self.measure("full_ocr", started)
        return self._words

    @words.setter
    def words(self, value):
        self._words = value

    def observe(self):
        started = time.perf_counter()
        raw = self.next_frame()
        self.image = normalize(raw)
        self.words = None  # OCR is evaluated once, only when this frame needs text.
        self.measure("capture", started)
        self.check_inventory_full()
        return self.image

    def check_inventory_full(self):
        # A small fixed notification crop avoids full OCR on every combat frame.
        known = self.templates.find(self.image, "inventory_full") is not None
        if known or getattr(self, "_words", None) is not None:
            if self.has("物品已满", "扩展", "分解"):
                pending = getattr(self, "_event_pending", None)
                if pending is not None and pending.get("pending"):
                    pending["pending"]["blocked"] = True
                    self.event_journal(pending)
                self.fail("背包已满：请手动腾出空间后重新运行；不会自动扩展或分解物品")

    def ocr(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return super().ocr(*args, **kwargs)
        finally:
            self.measure("ocr_total", started)

    def text(self, rect=None):
        if rect is None:
            return compact(" ".join(b.name for b in self.words))
        x1, y1, x2, y2 = rect
        return compact(" ".join(b.name for b in self.words
            if x1 <= b.x+b.width/2 <= x2 and y1 <= b.y+b.height/2 <= y2))

    def has(self, *words):
        text = self.text()
        return all(word in text for word in words)

    def tap(self, x, y):
        height, width = self.frame.shape[:2]
        started = time.perf_counter()
        self.click(int(x*width/1920), int(y*height/1080), move_back=True, down_time=0.01)
        self.measure("input", started)
        started = time.perf_counter()
        self.sleep(0.65 if self.option("运行速度") == "保守" else 0.12)
        self.measure("click_settle", started)

    def click_text(self, expression, rect=None):
        pattern = re.compile(expression)
        candidates = [b for b in self.words if pattern.search(compact(b.name))]
        if rect:
            x1, y1, x2, y2 = rect
            candidates = [b for b in candidates if x1 <= b.x+b.width/2 <= x2
                          and y1 <= b.y+b.height/2 <= y2]
        if len(candidates) != 1:
            self.fail(f"按钮识别不唯一：{expression}（{len(candidates)} 个）", recoverable=True)
        b = candidates[0]
        self.tap(b.x+b.width/2, b.y+b.height/2)

    def wait(self, predicate, description, seconds=35, stable_seconds=0.8,
             raise_on_timeout=True, recoverable=False):
        started = time.perf_counter()
        deadline = time.monotonic() + seconds
        stable_since = None
        while time.monotonic() < deadline:
            self.observe()
            self.check_inventory_full()
            if predicate():
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic()-stable_since >= stable_seconds:
                    self.measure("wait_total", started)
                    return True
            else:
                stable_since = None
            self.sleep(0.5 if self.option("运行速度") == "保守" else 0.15)
        self.measure("wait_total", started)
        if raise_on_timeout:
            self.fail("等待超时：" + description, recoverable=recoverable)
        return False

    def menu_transition(self, action, source, destination, description):
        """Only for reversible menus; never purchases, claims or combat."""
        limit = max(1, min(3, int(self.option("安全导航重试次数"))))
        stable = 1.0 if self.option("运行速度") == "保守" else 0.35
        unsent = 0
        for attempt in range(1, limit+1):
            self.wait(lambda: source() or destination(), description+"：等待页面稳定",
                      seconds=15, stable_seconds=stable, recoverable=True)
            if destination():
                return
            event = {"description": description, "attempt": attempt,
                     "at": datetime.now().isoformat(), "confirmed": False}
            self.navigation_audit.append(event)
            try:
                action()  # Re-identify the target on the fresh, stable source image.
            except UndispatchedClick as error:
                event["undispatched"] = True
                event["reason"] = str(error)
                unsent += 1
                self.sleep(0.5)
                continue
            if self.wait(destination, description, seconds=7, stable_seconds=stable,
                         raise_on_timeout=False):
                event["confirmed"] = True
                return
            # A destination can appear just after the bounded verification wait.
            # The next iteration re-observes both pages; never reuse coordinates.
            self.observe()
            if not source() and not destination():
                if self.popup_kind() is not None:
                    self.close_startup_popup()
                self.wait(lambda: source() or destination(), description+"：页面过渡", seconds=15,
                          stable_seconds=1.0, recoverable=True)
                if destination():
                    event["confirmed"] = True
                    return
        if unsent == limit:
            self.fail(description+f"：{limit}次均因鼠标位置校验未通过而未发出点击", recoverable=True)
        self.fail(description+f"：{limit}次尝试均未确认成功", recoverable=True)

    def verified_action(self, action, source, destination, description, seconds=35):
        """Retry only definitely undispatched input; never repeat a sent consuming click."""
        if not hasattr(self, "action_audit"):
            self.action_audit = []
        for attempt in range(1, 4):
            self.wait(lambda: destination() or source(), description+"：确认当前状态",
                      recoverable=True)
            if destination():
                return
            event = {"description": description, "attempt": attempt, "dispatched": False,
                     "confirmed": False}
            self.action_audit.append(event)
            started = time.perf_counter()
            try:
                action()
            except UndispatchedClick as error:
                event["undispatched"] = True
                event["reason"] = str(error)
                self.sleep(0.5)
                continue
            except RecoverableStageError as error:
                # A consuming callback may contain multiple operations. Do not
                # downgrade an exception from inside it to a skippable failure.
                raise RoutineError(description+"：操作执行中异常，结果未核实") from error
            event["dispatched"] = True
            if self.wait(destination, description, seconds=seconds, raise_on_timeout=False):
                event["confirmed"] = True
                event["seconds"] = round(time.perf_counter()-started, 3)
                return
            self.fail(description+"：点击已发送但结果未确认，停止以避免重复消耗")
        self.fail(description+"：鼠标持续被移动，三次均未发送点击", recoverable=True)

    def run_stage(self, stage, action):
        self.stage = stage
        self.info["当前步骤"] = stage
        self.log_info("开始步骤："+stage)
        started = time.perf_counter()
        status = "completed"
        try:
            action()
            return True
        except TaskDisabledException:
            status = "stopped"
            raise
        except Exception as error:
            status = "stopped"
            if getattr(self, "_last_stage_exception", None) is not error \
                    and recover_step(self, stage, error):
                status = "skipped_error"
                self._last_stage_exception = None
                return False
            raise
        finally:
            if not hasattr(self, "stage_timings"):
                self.stage_timings = []
            self.stage_timings.append({"stage": stage, "status": status,
                                       "seconds": round(time.perf_counter()-started, 3)})

    def home_button(self):
        return self.templates.find(self.image, "home_icon") or self.templates.find(self.image, "shop_home") \
            or self.templates.find(self.image, "shop_new_home")

    def return_home(self, action=None):
        def click_home():
            icon = self.home_button()
            if icon is None:
                self.fail("未识别到返回首页图标，停止点击")
            if action:
                h, w = self.frame.shape[:2]
                action(round(icon.x*w/1920), round(icon.y*h/1080))
            else:
                self.tap(icon.x, icon.y)

        source = lambda: self.home_button() is not None \
            and not self.is_home()
        self.menu_transition(click_home, source,
                             lambda: self.is_home() or self.popup_kind() is not None,
                             "返回主界面")
        if self.popup_kind() is not None:
            self.home()

    def fail(self, message, recoverable=False):
        error = RecoverableStageError(message) if recoverable else RoutineError(message)
        if self.image is not None:
            error.evidence = self.save_evidence("failure")
        raise error

    def save_evidence(self, label):
        folder = ROOT / "screenshots"
        folder.mkdir(exist_ok=True)
        path = folder / (datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + label + ".png")
        if not cv2.imwrite(str(path), self.image):
            raise RoutineError("故障截图保存失败，已停止")
        return str(path)

    def is_home(self):
        return self.templates.find(self.image, "home_guard") is not None \
            and self.templates.find(self.image, "phone_checklist") is not None \
            and self.popup_kind() is None \
            and not any(self.has(text) for text in ("GetItem", "点击屏幕继续", "公告", "任务开放"))

    def popup_kind(self):
        if self.has("GetItem") or self.has("点击屏幕继续"):
            return None
        if self.is_checklist():
            return None
        if "资源管理" in self.text((600, 25, 1400, 200)):
            return "resource"
        if self.has("信仰等级", "收回贡品"):
            return "tribute"
        if "公告" in self.text((500, 25, 1400, 200)):
            return "announcement"
        if "每日签到" in self.text((650, 200, 1770, 440)):
            return "sign_in"
        if "任务开放" in self.text((650, 100, 1770, 600)):
            return "task_open"
        if "服装选择折扣礼包" in self.text((900, 200, 1770, 400)) \
                and "服装预览" in self.text((600, 80, 950, 200)):
            return "costume_offer"
        return None

    def close_startup_popup(self):
        kind = self.popup_kind()
        if kind is None:
            self.fail("未知弹窗，未尝试关闭")

        def source():
            return self.popup_kind() == kind and self.templates.popup_close(self.image) is not None

        def destination():
            return self.is_home() or (self.popup_kind() is not None and self.popup_kind() != kind)

        def action():
            button = self.templates.popup_close(self.image)
            if self.popup_kind() != kind or button is None:
                self.fail("弹窗或关闭按钮不确定，停止点击")
            self.save_evidence("popup-"+kind+"-before")
            self.tap(button.x, button.y)

        self.menu_transition(action, source, destination, "关闭首页弹窗："+kind)
        self.save_evidence("popup-"+kind+"-after")

    def is_daily(self):
        return self.has("每日积分", "每日任务") and not self.has("GetItem") \
            and not self.has("点击屏幕继续") and not self.is_event_identity()

    def is_event_identity(self):
        return any(profile["title"] in self.text((150, 0, 900, 110)) for profile in EVENT_PROFILES)

    def is_checklist(self):
        return "检查清单" in self.text((150, 0, 700, 150)) and not self.has("GetItem") and not self.has("点击屏幕继续")

    def dismiss_reward(self):
        self.wait(lambda: self.has("点击屏幕继续") or self.is_home()
                  or self.is_daily() and not self.has("GetItem"), "奖励结算")
        if self.has("点击屏幕继续"):
            self.save_evidence("reward-"+getattr(self, "stage", "inspection"))
            self.menu_transition(lambda: self.click_text("点击屏幕继续", (400, 850, 1450, 1030)),
                                 lambda: self.has("点击屏幕继续"),
                                 lambda: not self.has("点击屏幕继续") and not self.has("GetItem"),
                                 "关闭奖励回执")

    def close_shop_order(self):
        def source():
            return "订单" in self.text((850, 120, 1100, 240))
        def close():
            button = self.templates.find(self.image, "shop_order_close") \
                or self.templates.find(self.image, "shop_new_order_close")
            if button is None:
                self.fail("订单关闭按钮未确认")
            self.tap(button.x, button.y)
        self.menu_transition(close, source,
                             lambda: not source() and (self.has("充值商店") or self.has("限量商品") or self.is_home()),
                             "关闭商店订单")

    def is_raid_sweep_dialog(self):
        return "怪物讨伐" in self.text((150, 0, 400, 100)) \
            and "是否使用扫荡功能" in self.text((700, 375, 1220, 485)) \
            and "妖精的讨伐请求书" in self.text((810, 505, 1120, 585))

    def home(self):
        for _ in range(12):
            self.observe()
            if self.is_raid_sweep_dialog():
                self.menu_transition(lambda: self.click_text("^取消$", (550, 735, 780, 835)),
                                     self.is_raid_sweep_dialog,
                                     lambda: self.has("怪物讨伐", "出击", "返回")
                                     and not self.has("是否使用扫荡功能") and not self.has("CLEAR"),
                                     "取消讨伐扫荡弹窗")
                continue
            if "订单" in self.text((850, 120, 1100, 240)):
                self.close_shop_order()
                continue
            if self.popup_kind() is not None:
                self.close_startup_popup()
                continue
            if hasattr(self, "leave_event_scene") and self.leave_event_scene():
                continue
            if self.is_home():
                return
            if self.home_button() is not None \
                    and not self.has("GetItem") and not self.has("点击屏幕继续") \
                    and not self.has("公告") and not self.has("任务开放"):
                self.return_home()
                return
            if self.has("出击", "返回") and not self.has("是否使用扫荡功能"):
                self.menu_transition(lambda: self.click_text("^返回$", (850, 900, 1250, 1080)),
                                     lambda: self.has("出击", "返回") and not self.has("是否使用扫荡功能"),
                                     lambda: not self.has("出击") and
                                     (self.has("查看全部") or self.has("危险区域")), "退出出击详情")
                continue
            if self.has("点击屏幕继续") and self.has("道具"):
                self.dismiss_reward()
            else:
                # Wait for page/loading animations; never blindly send Escape.
                self.sleep(1)
        self.fail("无法返回主界面，请手动停在带手机菜单的主界面")

    def checklist_tab(self, label, destination):
        def visible():
            return [b for b in self.words if compact(b.name) == label
                    and 0 <= b.x and b.x+b.width <= 310 and 250 <= b.y and b.y+b.height <= 960]

        for start, end in ((.85, .40), (.40, .85)):
            for index in range(6):
                self.observe()
                if destination():
                    return
                if not self.is_checklist():
                    self.fail("检查清单页面未确认，停止拖动", recoverable=True)
                if len(visible()) == 1:
                    def click():
                        matches = visible()
                        if len(matches) != 1:
                            self.fail("检查清单标签位置已变化", recoverable=True)
                        box = matches[0]
                        self.tap(box.x+box.width/2, box.y+box.height/2)
                    self.menu_transition(click, self.is_checklist, destination, "打开"+label)
                    return
                if len(visible()) > 1:
                    self.fail("检查清单标签不唯一", recoverable=True)
                if index == 5:
                    break
                height, width = self.frame.shape[:2]
                self.swipe(int(width*.10), int(height*start),
                           int(width*.10), int(height*end), duration=.6, settle_time=.3)
                self.wait(self.is_checklist, "检查清单拖动后稳定", stable_seconds=1.0, recoverable=True)
                # Unchanged OCR does not prove the list is at its end: a drag can be missed.
        self.fail("检查清单未找到完整标签："+label, recoverable=True)

    def daily_page(self):
        self.observe()
        if self.is_daily():
            return
        if not self.is_checklist():
            self.home()
            def click_checklist():
                icon = self.templates.find(self.image, "phone_checklist")
                if icon is None:
                    self.fail("未识别到检查清单图标")
                self.tap(icon.x, icon.y)
            self.menu_transition(click_checklist, self.is_home, self.is_checklist, "打开检查清单")
        if not self.is_daily():
            self.checklist_tab("日程表", self.is_daily)

    def score(self):
        previous = None
        for attempt in range(6):
            self.observe()
            current = None
            if self.is_daily():
                labels = [b for b in self.words if compact(b.name) == "每日积分"
                          and 300 <= b.x <= 800 and 200 <= b.y <= 350]
                if len(labels) == 1:
                    label = labels[0]
                    top = label.y+label.height-2
                    text = self.ocr(frame=self.image, x=(label.x-20)/1920, y=top/1080,
                                    to_x=(label.x+label.width+35)/1920, to_y=(top+70)/1080,
                                    threshold=.7, target_height=2160)
                    value = parse_score("".join(b.name for b in text))
                    if value is not None:
                        panel = self.image[210:375, 300:1880].copy()
                        current = (value, label.x, label.y, panel)
                        if (previous is not None and value == previous[0]
                                and abs(label.x-previous[1]) <= 2 and abs(label.y-previous[2]) <= 2
                                and cv2.absdiff(panel, previous[3]).mean() < 3):
                            return value
            previous = current
            if attempt < 5:
                self.sleep(.5)
        self.fail("无法确认每日积分：重新取图后积分区域仍未稳定或识别失败")

    def chests(self):
        result = []
        for center in (1044, 1224, 1404, 1584, 1764):
            rect = (center-60, 230, center+60, 325)
            opened = self.templates.find(self.image, "chest_open", rect, 0.76)
            closed = self.templates.find(self.image, "chest_closed", rect, 0.76)
            if opened and (not closed or opened.score > closed.score + 0.025):
                result.append("claimed")
            elif closed and (not opened or closed.score > opened.score + 0.025):
                result.append("available")
            else:
                result.append("unknown")
        return result

    def attempts(self):
        value = parse_attempts(self.text((1680, 160, 1810, 250)))
        if value is None:
            self.fail("无法确认副本剩余次数")
        return value

    def stages(self):
        self.home()
        self.menu_transition(lambda: self.click_text("^关卡$", (1450, 400, 1760, 590)),
                             self.is_home, lambda: self.has("剧情", "讨伐"), "打开关卡菜单")

    def wish_map(self):
        self.stages()
        self.menu_transition(lambda: self.click_text("^愿望", (0, 500, 600, 800)),
                             lambda: self.has("剧情", "讨伐"),
                             lambda: self.has("查看全部", "愿望"), "打开愿望地图")


class CaptureTask(HorizonTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "后台截图检查（不点击）"
        self.group_name = "诊断工具"
        self.description = "连续取图，保存游戏画面和识别文字，不操作游戏"

    def run(self):
        records = []
        for _ in range(3):
            self.observe()
            records.append({"image": self.save_evidence("capture"), "text": self.text()})
            self.sleep(1)
        Path("docs/capture_result.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log_info("后台截图检查完成，见 screenshots 和 docs/capture_result.json", notify=True)
        self.completed = True


class CompatibilityTask(HorizonTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "后台输入兼容性对照（不消耗资源）"
        self.group_name = "诊断工具"
        self.description = "仅对照框架参考输入，打开检查清单后返回"

    def run(self):
        from src.compatibility import compare_backends
        result = compare_backends(self)
        self.info.update(result)


class InspectTask(HorizonTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "今日状态检查（不消耗资源）"
        self.group_name = "诊断工具"
        self.description = "仅打开每日任务和愿望菜单，检查积分、宝箱和剩余次数"

    def run(self):
        self.daily_page()
        result = {"score": self.score(), "chests": self.chests(),
                  "daily_image": self.save_evidence("daily-inspection")}
        self.wish_map()
        result["wish_attempts"] = self.attempts()
        coins = self.templates.all(self.image, "coin_map", (300, 150, 1850, 950))
        completed = self.templates.all(self.image, "wish_complete", (300, 150, 1850, 950))
        result["coin_wishes_available"] = len(select_coin_wishes(coins, completed))
        result["wish_image"] = self.save_evidence("wish-inspection")
        self.home()
        self.info.update(result)
        result["click_audit"] = self.executor.interaction.audit
        Path("docs/inspection_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.completed = True
        self.log_info(f"检查完成：{result['score']} 积分，愿望剩余 {result['wish_attempts']} 次", notify=True)


class DailyTask(EventMixin, NewShopMixin, RecoveryMixin, HorizonTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "每日任务"
        self.description = "贡品资源、商店、金币愿望、讨伐、复原任命、邮件、100积分宝箱"
        self.journal_path = ROOT / "configs/purchase_journal.json"
        self.default_config = DEFAULTS.copy()
        self.config_description = DESCRIPTIONS.copy()
        self.config_type = TYPES.copy()

    def load_config(self):
        self.config = DailyConfig(type(self).__name__, self.default_config, validator=self.validate)

    @record_run
    def run(self):
        self.observe()
        if self.is_event_result():
            self.finish_event_result()
        if self.is_sweep_result():
            self.finish_sweep_result()
        elif self.has("怪物讨伐", "CLEAR", "奖励列表") and "确认" in self.text((600, 850, 1250, 1080)):
            self.fail("已有讨伐扫荡结算的目标未确认，请手动退出结算")
        if self.has("GetItem") or self.has("点击屏幕继续"):
            self.dismiss_reward()
            self.observe()
        if self.has("CLEAR") and (self.has("奖励列表") or
                                  self.templates.find(self.image, "battle_exit") is not None):
            if self.templates.find(self.image, "recovery_exit") is not None:
                self.finish_recovery_result()
                self.wait(self.is_recovery_map, "恢复复原战斗结算", 80)
            else:
                self.finish_battle_result()
                self.wait(lambda: self.has("查看全部", "愿望") or self.has("危险区域"),
                          "恢复已有战斗结算", 80)
        self.daily_page()
        if self.score() >= 100 and self.chests() == ["claimed"] * 5:
            self.daily_rewards_complete = True
            self.log_info("今日已满100积分且五个宝箱均已领取，跳过重复执行", notify=True)
            self.save_evidence("daily-already-claimed")
            self.post_raid_actions()
            self.run_stage("event", self.event_actions)
            self.finish_daily()
            return
        if self.score() >= 100:
            self.run_stage("daily_rewards", self.claim_daily)
            self.daily_rewards_complete = True
            self.post_raid_actions()
            self.run_stage("event", self.event_actions)
            self.finish_daily()
            return
        for stage, action in (("resources", self.collect_resources),
                              ("shop", self.shop), ("wishes", self.wishes),
                              ("raids", self.raids), ("post_raids", self.post_raid_actions),
                              ("event", self.event_actions),
                              ("daily_rewards", self.claim_daily)):
            enabled = {"resources": self.option("贡品") or self.option("累计资源"),
                       "shop": self.option("免费金币"),
                       "wishes": self.option("金币愿望"), "raids": self.option("讨伐")}
            if not enabled.get(stage, True):
                self.info[stage] = "已按设置跳过"
                continue
            self.save_evidence(stage+"-start")
            self.run_stage(stage, action)
            if stage == "daily_rewards":
                self.daily_rewards_complete = True
            self.save_evidence(stage+"-end")
        self.finish_daily()

    def finish_daily(self):
        if not self.daily_rewards_complete:
            self.fail("每日积分与五个宝箱尚未核实，未报告完成")
        self.home()
        self.save_evidence("daily-final-home")
        self.completed = not self.stage_errors
        if self.stage_errors:
            self.log_info("每日奖励已领取，但部分步骤失败，请查看失败步骤与故障记录", notify=True)
        else:
            self.log_info("每日流程完成，已确认积分至少100且五个积分宝箱全部领取", notify=True)

    def sign_in(self):
        self.daily_page()
        self.checklist_tab("每日签到",
                           lambda: self.is_checklist() and self.has("签到") and not self.is_daily())
        self.observe()
        self.save_evidence("sign-in-panel")
        checked = self.templates.all(self.image, "sign_in_checked", (800, 350, 1850, 920))
        if len(checked) == 7:
            self.info["签到"] = "七天奖励均已领取"
            self.home()
            return
        buttons = [b for b in self.words if is_sign_in_claim(b.name)
                   and b.y > 900 and b.x > 1400]
        if len(buttons) == 1:
            def claim():
                buttons = [b for b in self.words if is_sign_in_claim(b.name)
                           and b.y > 900 and b.x > 1400]
                if len(buttons) != 1:
                    self.fail("签到领取按钮已变化")
                b = buttons[0]
                self.tap(b.x+b.width/2, b.y+b.height/2)
            self.verified_action(claim, lambda: self.is_checklist() and self.has("签到"),
                                 lambda: self.has("GetItem") or self.has("点击屏幕继续"), "签到奖励回执")
            self.dismiss_reward()
            self.wait(lambda: len(self.templates.all(self.image, "sign_in_checked", (800, 350, 1850, 920)))
                      > len(checked), "签到奖励领取确认")
            self.info["签到"] = "已领取并确认新增勾选"
        else:
            self.fail("签到领取按钮未唯一识别，未跳过该步骤")
        self.home()

    def collect_tribute(self):
        self.home()
        self.menu_transition(lambda: self.tap(1118, 300), self.is_home,
                             lambda: self.popup_kind() == "tribute", "打开贡品页面")
        self.harvest_free_resources("tribute")
        self.home()

    def collect_resources(self):
        if self.option("贡品"):
            self.collect_tribute()
        if not self.option("累计资源"):
            return
        # These fixed points are inside the identified home side widgets.
        self.menu_transition(lambda: self.tap(1118, 480), self.is_home,
                             lambda: self.popup_kind() == "resource", "打开资源管理")
        self.harvest_free_resources("resource")
        self.home()

    def harvest_free_resources(self, kind):
        def on_panel():
            return self.has("信仰等级", "收回贡品") if kind == "tribute" else self.has("资源管理")

        def empty():
            if kind == "tribute":
                if self.has("没有可收回的贡品"):
                    return True
                # Only positive item quantities authorize another free harvest click.
                quantities = self.ocr(frame=cv2.resize(self.image[770:815, 190:1735],
                                                       None, fx=3, fy=3), threshold=0.7)
                amounts = [compact(box.name).replace(",", "") for box in quantities]
                if not any(value.isdecimal() and int(value) > 0 for value in amounts):
                    self.fail("无法确认贡品剩余数量")
                return False
            count = re.search(r"(\d+)/(\d+)", self.text((800, 500, 1100, 590)))
            if count is None:
                quantities = self.ocr(frame=cv2.resize(self.image[530:585, 840:1080],
                                                       None, fx=3, fy=3), threshold=0.7)
                count = re.fullmatch(r"(\d+)/(\d+)",
                                     compact("".join(box.name for box in quantities)))
            if count is None:
                self.fail("无法确认累计资源数量")
            return int(count[1]) == 0

        for attempt in range(1, 4):
            self.observe()
            if not on_panel():
                self.fail("免费资源面板已变化，停止重试")
            if empty():
                self.info[kind] = "已确认无剩余资源"
                return
            self.save_evidence(kind+"-pending")
            try:
                if kind == "tribute":
                    self.click_text("^收回贡品$", (950, 800, 1550, 950))
                else:
                    self.click_text("回收收集资源|收集资源", (950, 850, 1500, 1010))
            except UndispatchedClick:
                self.sleep(0.5)
                continue
            if self.wait(lambda: self.has("GetItem") or self.has("点击屏幕继续"),
                         "免费资源收取回执", seconds=7, raise_on_timeout=False):
                self.dismiss_reward()
                self.info[kind] = "已确认奖励回执"
                return
            self.observe()
            if not on_panel():
                self.fail("收取结果不确定且页面已变化，停止重试")
            if empty():
                self.info[kind] = "已确认收取后清空"
                return
            self.log_info(f"{kind} 仍有可领资源，第{attempt}次未确认点击生效")
        self.fail("免费资源收取三次未确认成功")

    def journal(self, state=None):
        if state is None:
            if self.journal_path.exists():
                return json.loads(self.journal_path.read_text(encoding="utf-8"))
            return {}
        self.journal_path.parent.mkdir(exist_ok=True)
        self.journal_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def shop(self):
        self.home()
        self.menu_transition(lambda: self.click_text("^商店$", (1200, 90, 1480, 230)),
                             self.is_home, lambda: self.has("每日限量", "充值商店") or self.is_new_shop(), "打开商店")
        if self.is_new_shop():
            self.claim_new_free_coins()
        else:
            self.claim_free_coins()

    # Retained for future reactivation. The daily workflow never calls this method.
    def buy_a_contract(self):
        self.menu_transition(lambda: self.click_text("^每日限量$", (0, 250, 310, 500)),
                             lambda: self.has("每日限量", "充值商店"),
                             lambda: re.search(r"A级契约[券卷]", self.text()) is not None,
                             "每日限量商品")
        previous = self.journal()
        if previous.get("state") == "confirmed" and \
                str(previous.get("at", "")).split("T")[0] == datetime.now().date().isoformat():
            self.info["A级券"] = "当天购买已确认，跳过再次下单"
            return
        # Only this product's card, irrespective of neighboring items' labels.
        if contract_unavailable(self.text((700, 770, 1070, 1040))):
            return
        self.menu_transition(lambda: self.click_text("^A级契约[券卷]$", (650, 800, 1080, 1080)),
                             lambda: self.has("充值商店") and not self.has("订单"),
                             lambda: self.has("订单") and re.search(r"A级契约[券卷]", self.text()) is not None,
                             "A级券订单")
        if contract_unavailable(self.text((620, 230, 1310, 900))):
            self.info["A级券"] = "订单已无库存，未点击购买"
            self.save_evidence("contract-unavailable")
            self.close_shop_order()
        else:
            order_text = self.text((620, 230, 1310, 900))
            if not valid_contract(order_text, self.templates.find(self.image, "coin_price") is not None):
                self.fail("订单未同时满足A级契约券、金币图标、6000价格，停止购买")
            if previous.get("state") == "pending":
                self.fail("上次购买结果不确定，请核对商店库存后处理 configs/purchase_journal.json")
            self.journal({"state": "pending", "at": datetime.now().isoformat()})
            self.verified_action(lambda: self.click_text("^购买$", (700, 890, 1200, 1000)),
                                 lambda: self.has("订单") and valid_contract(
                                     self.text((620, 230, 1310, 900)),
                                     self.templates.find(self.image, "coin_price") is not None),
                                 lambda: self.has("是否购买该物品", "确认"), "购买确认")
            self.verified_action(lambda: self.click_text("^确认$", (900, 500, 1250, 750)),
                                 lambda: self.has("是否购买该物品", "确认"),
                                 lambda: self.has("PURCHASE") or self.has("点击屏幕继续"), "购买成功")
            self.journal({"state": "confirmed", "at": datetime.now().isoformat()})
            self.dismiss_reward()
            self.observe()
            if self.has("订单"):
                self.close_shop_order()
        self.wait(lambda: self.has("充值商店") and not self.has("订单"), "商店列表")

    def claim_free_coins(self):
        if not self.option("免费金币"):
            self.home()
            return
        self.observe()
        self.menu_transition(lambda: self.click_text("^充值商店$", (0, 300, 300, 1050)),
                             lambda: self.has("充值商店"),
                             lambda: self.has("妖精网支援金"), "免费金币")
        if "SoldOut" not in self.text((350, 300, 720, 720)) and \
                "免费" in self.text((350, 300, 720, 720)):
            self.menu_transition(lambda: self.click_text("妖精网支援金", (320, 450, 720, 720)),
                                 lambda: self.has("妖精网支援金") and not self.has("订单"),
                                 lambda: self.has("订单", "光辉币"), "免费金币订单")
            if "免费" not in self.text((700, 820, 1250, 900)):
                self.fail("未确认免费价格，停止领取")
            self.verified_action(lambda: self.click_text("^购买$", (700, 890, 1200, 1000)),
                                 lambda: self.has("订单", "光辉币") and
                                 "免费" in self.text((700, 820, 1250, 900)),
                                 lambda: self.has("GetItem") or self.has("点击屏幕继续"), "免费金币回执")
            self.dismiss_reward()
        self.home()

    def wishes(self):
        self.wish_map()
        for _ in range(3):
            self.observe()
            before = self.attempts()
            if before == 0:
                return
            coins = self.templates.all(self.image, "coin_map", (300, 150, 1850, 950))
            done = self.templates.all(self.image, "wish_complete", (300, 150, 1850, 950))
            choices = select_coin_wishes(coins, done)
            if not choices:
                self.fail("没有识别到未完成的金币愿望，未选择其他奖励", recoverable=True)
            target = choices[0]
            def open_wish():
                coins = self.templates.all(self.image, "coin_map", (300, 150, 1850, 950))
                done = self.templates.all(self.image, "wish_complete", (300, 150, 1850, 950))
                choices = select_coin_wishes(coins, done)
                if not choices:
                    self.fail("当前没有未完成金币愿望，停止点击", recoverable=True)
                self.tap(choices[0].x-130, choices[0].y)
            self.menu_transition(open_wish, lambda: self.has("查看全部", "愿望"),
                                 lambda: self.has("出击", "委托奖励", "愿望"), "愿望出击页面")
            if not self.has("光辉币") or not self.templates.find(self.image, "coin_detail"):
                self.fail("出击前未确认金币奖励")
            self.verified_action(lambda: self.click_text("^出击$", (1500, 920, 1780, 1080)),
                                 lambda: self.has("出击", "委托奖励", "光辉币") and
                                 self.templates.find(self.image, "coin_detail") is not None,
                                 lambda: self.templates.find(self.image, "battle_pause") is not None,
                                 "愿望进入战斗", seconds=100)
            self.battle()
            self.wait(lambda: self.has("查看全部", "愿望"), "返回愿望地图", 80)
            if self.attempts() != before-1:
                self.fail("愿望完成后剩余次数未按预期减少")
        if self.attempts() != 0:
            self.fail("3次愿望未完成")

    def battle(self, recovery=False):
        started = time.perf_counter()
        self.wait(lambda: self.templates.find(self.image, "battle_pause") is not None,
                  "进入战斗", 100)
        if not auto_battle_enabled(self.image):
            self.menu_transition(lambda: self.tap(168, 75),
                                 lambda: self.templates.find(self.image, "battle_pause") is not None
                                 and not auto_battle_enabled(self.image),
                                 lambda: auto_battle_enabled(self.image), "开启自动战斗")
        next_failure_check = [0.0]
        def result_ready():
            if any(self.templates.find(self.image, name) is not None
                   for name in ("battle_next", "battle_exit", "recovery_exit")):
                return True
            # Ordinary combat frames need no full OCR on every poll.
            if time.monotonic() >= next_failure_check[0]:
                next_failure_check[0] = time.monotonic()+2
                return self.has("失败")
            return False
        self.wait(result_ready, "自动战斗结算", 360)
        if self.has("失败"):
            self.fail("战斗失败，停止以免重复消耗次数")
        if recovery:
            self.finish_recovery_result()
        else:
            self.finish_battle_result()
        self.measure("battle_and_settlement", started)

    def finish_battle_result(self):
        self.wait(lambda: self.templates.find(self.image, "battle_next") is not None
                  or self.templates.find(self.image, "battle_exit") is not None
                  or self.has("下一步") or self.has("退出"), "战斗结算按钮", 35)
        self.save_evidence("battle-result")
        button = self.templates.find(self.image, "battle_next")
        if button is not None or self.has("下一步"):
            def next_page():
                button = self.templates.find(self.image, "battle_next")
                if button:
                    self.tap(button.x, button.y)
                else:
                    self.click_text("下一步", (1400, 870, 1900, 1080))
            self.menu_transition(next_page,
                                 lambda: self.templates.find(self.image, "battle_next") is not None,
                                 lambda: self.templates.find(self.image, "battle_exit") is not None,
                                 "战斗人员结算页")
            self.save_evidence("battle-exit")
        def exit_page():
            button = self.templates.find(self.image, "battle_exit")
            if button:
                self.tap(button.x, button.y)
            else:
                self.click_text("^退出$", (1400, 870, 1900, 1080))
        self.menu_transition(exit_page,
                             lambda: self.templates.find(self.image, "battle_exit") is not None,
                             lambda: self.has("查看全部", "愿望") or self.has("危险区域"),
                             "退出战斗结算")

    def is_raid_list(self):
        return re.search(r"危险区域(?:4|IV|Ⅳ)(?![0-9])", self.text((190, 160, 600, 280))) is not None \
            and not any(self.has(word) for word in ("出击", "CLEAR", "GetItem", "点击屏幕继续"))

    @staticmethod
    def raid_name_matches(target, boxes):
        labels = [(compact(box.name).replace("於", "于"), box) for box in boxes]
        matches = [box for name, box in labels if name == target]
        if target == "被囚禁于海底的鱼人侵夺者":
            for name, upper in labels:
                if name != "被囚禁于海底的鱼":
                    continue
                for suffix, lower in labels:
                    if suffix == "人侵夺者" and 20 <= lower.y+lower.height/2-upper.y-upper.height/2 <= 75 \
                            and abs(lower.x+lower.width/2-upper.x-upper.width/2) <= 45:
                        matches.append(upper)
        return matches

    def raid_card(self, target):
        boxes = [b for b in self.words
                 if 250 <= b.x and b.x+b.width <= 1880 and 725 <= b.y+b.height/2 <= 800]
        cards = self.raid_name_matches(target, boxes)
        return cards[0] if len(cards) == 1 else None

    def raid_detail(self, target=None):
        target = self.option("讨伐目标") if target is None else target
        if target not in RAID_TARGETS:
            self.fail(f"设置中的讨伐目标无效：{target}", recoverable=True)
        self.observe()
        if not self.is_raid_list():
            self.stages()
            self.menu_transition(lambda: self.click_text("^讨伐$", (500, 500, 850, 800)),
                                 lambda: self.has("剧情", "讨伐"),
                                 lambda: self.has("危险等级"), "讨伐难度")
            self.menu_transition(lambda: self.tap(1605, 710), lambda: self.has("危险等级"),
                                 self.is_raid_list, "危险区域IV")

        def open_card():
            card = self.raid_card(target)
            if card is None:
                self.fail(f"当前列表未确认{target}卡片", recoverable=True)
            self.tap(card.x+card.width/2, card.y+card.height/2)

        # A previous run can leave the list scrolled. Scan in both directions.
        for start, end in ((.85, .35), (.35, .85)):
            for step in range(9):
                if not self.is_raid_list():
                    self.fail("当前已不是危险区域IV讨伐列表，停止拖动", recoverable=True)
                if self.raid_card(target) is not None:
                    self.menu_transition(open_card, lambda: self.is_raid_list() and self.raid_card(target) is not None,
                                         lambda: self.is_raid_detail(target), f"{target}详情")
                    if not self.raid_level_confirmed():
                        self.fail(f"{target}讨伐等级未确认为Lv.60", recoverable=True)
                    return
                if step == 8:
                    break
                before = self.text((250, 730, 1880, 795))
                height, width = self.frame.shape[:2]
                self.swipe(int(width*start), int(height*.55), int(width*end), int(height*.55), duration=.5)
                self.wait(self.is_raid_list, "讨伐列表拖动后稳定", stable_seconds=1.0, recoverable=True)
                if before and before == self.text((250, 730, 1880, 795)):
                    break
        self.fail(f"未找到危险区域IV目标：{target}", recoverable=True)

    def raid_level_confirmed(self):
        return re.search(r"推荐等级[:：]?Lv\.60(?!\d)", self.text((880, 80, 1340, 160)), re.IGNORECASE) is not None

    def has_raid_detail_target(self, target):
        boxes = [b for b in self.words
                 if 190 <= b.x+b.width/2 <= 810 and 610 <= b.y+b.height/2 <= 725]
        return self.has("怪物讨伐") and len(self.raid_name_matches(target, boxes)) == 1

    def is_raid_detail(self, target=None):
        target = self.option("讨伐目标") if target is None else target
        return target in RAID_TARGETS and self.has_raid_detail_target(target) and self.has("出击") \
            and not any(self.has(word) for word in ("CLEAR", "是否使用扫荡功能", "GetItem", "点击屏幕继续"))

    def raid_result_target(self):
        if not self.has("怪物讨伐", "CLEAR", "奖励列表") or "确认" not in self.text((600, 850, 1250, 1080)):
            return None
        boxes = [b for b in self.words
                 if 650 <= b.x+b.width/2 <= 1250 and 420 <= b.y+b.height/2 <= 545]
        known = [target for target in RAID_TARGETS if self.raid_name_matches(target, boxes)]
        return known[0] if len(known) == 1 else None

    def is_sweep_result(self, target=None):
        found = self.raid_result_target()
        return found is not None and (target is None or found == target)

    def finish_sweep_result(self, target=None):
        target = self.raid_result_target() if target is None else target
        if target is None:
            self.fail("扫荡结算的讨伐目标未确认")
        self.menu_transition(lambda: self.click_text("^确认$", (600, 850, 1250, 1080)),
                             lambda: self.is_sweep_result(target),
                             lambda: self.is_raid_detail(target), "关闭扫荡结算")

    def raids(self):
        target = self.option("讨伐目标")
        self.info["讨伐目标"] = target
        self.raid_detail(target)
        self.observe()
        if not self.is_raid_detail(target) or not self.raid_level_confirmed():
            self.fail("出击前未确认所选讨伐目标及等级", recoverable=True)
        before = self.attempts_detail()
        if before == 0:
            return
        # A partially completed day resumes sweeps instead of fighting again.
        remaining = before
        if before == 3:
            self.verified_action(lambda: self.click_text("^出击$", (1450, 920, 1790, 1080)),
                                 lambda: self.is_raid_detail(target) and self.raid_level_confirmed() and
                                 self.attempts_detail() == before,
                                 lambda: self.templates.find(self.image, "battle_pause") is not None,
                                 f"{target}进入战斗", seconds=100)
            self.battle()
            self.wait(self.is_raid_list, "返回讨伐列表", 80)
            self.raid_detail(target)
            if self.attempts_detail() != before-1:
                self.fail("讨伐完成次数没有减少")
            remaining -= 1
        sweep_rect = (1400, 820, 1800, 1010)

        for expected in range(remaining, 0, -1):
            self.observe()
            if not self.is_raid_detail(target) or not self.raid_level_confirmed():
                self.fail("扫荡前未确认所选讨伐目标及等级", recoverable=True)
            if self.attempts_detail() != expected:
                self.fail("扫荡前剩余次数与上次确认不一致")
            if "扫荡" not in self.text(sweep_rect):
                self.fail(f"{target}详情未确认扫荡按钮，跳过剩余讨伐", recoverable=True)

            def can_open_sweep():
                return self.is_raid_detail(target) and self.raid_level_confirmed() \
                    and "扫荡" in self.text(sweep_rect)

            opened_from_target = False

            def open_sweep():
                nonlocal opened_from_target
                if not can_open_sweep():
                    self.fail("扫荡前未确认讨伐目标和扫荡按钮", recoverable=True)
                self.click_text("^扫荡$", sweep_rect)
                opened_from_target = True

            # The dialog covers the target name. Tie it to this attempt's verified detail.
            self.menu_transition(open_sweep, can_open_sweep,
                                 lambda: opened_from_target and self.is_raid_sweep_dialog(), "打开扫荡确认")
            if not self.raid_sweep_cost_matches(expected):
                self.fail("扫荡弹窗未确认扣除一张讨伐请求书，取消本次扫荡", recoverable=True)
            self.verified_action(lambda: self.click_text("^确认$", (1250, 735, 1490, 835)),
                                 lambda: self.raid_sweep_cost_matches(expected),
                                 lambda: self.is_sweep_result(target), f"{target}扫荡结算")
            self.finish_sweep_result(target)
            if self.attempts_detail() != expected-1:
                self.fail("扫荡后剩余次数未减少，停止重复扫荡")

    def raid_sweep_cost_matches(self, expected):
        return self.is_raid_sweep_dialog() \
            and self.text((928, 585, 977, 653)) == str(expected) \
            and self.text((1019, 585, 1069, 653)) == str(expected-1) \
            and self.text((1250, 735, 1490, 835)) == "确认"

    def attempts_detail(self):
        # Detail page uses remaining/1; list uses remaining/3.
        words = self.ocr(frame=cv2.resize(self.image[965:1015, 1345:1430],
                                          None, fx=3, fy=3), threshold=0.7)
        text = compact("".join(box.name for box in words))
        match = re.fullmatch(r"([0-3])/1", text)
        if not match:
            self.fail("无法确认出击剩余次数")
        return int(match[1])

    def claim_daily(self):
        self.daily_page()
        if self.score() < 100:
            self.verified_action(lambda: self.click_text("^全部领取$", (1450, 940, 1850, 1080)),
                                 self.is_daily,
                                 lambda: self.has("点击屏幕继续") or self.has("GetItem"),
                                 "每日任务奖励回执")
            self.dismiss_reward()
        self.wait(self.is_daily, "每日积分页面")
        if self.score() < 100:
            self.fail("所选步骤完成后不足100积分，请检查任务开关；未追加已禁用任务")
        for index, center in enumerate((1044, 1224, 1404, 1584, 1764)):
            self.observe()
            status = self.chests()[index]
            if status == "claimed":
                continue
            if status == "unknown":
                self.fail(f"第{index+1}个积分宝箱状态不确定")
            self.verified_action(lambda: self.tap(center, 280),
                                 lambda: self.is_daily() and self.chests()[index] == "available",
                                 lambda: self.has("GetItem") or self.has("点击屏幕继续"),
                                 f"领取第{index+1}个积分宝箱")
            self.dismiss_reward()
            self.wait(self.is_daily, "返回每日积分")
            if self.chests()[index] != "claimed":
                self.fail(f"第{index+1}个积分宝箱领取未确认")
        self.save_evidence("daily-complete")


class TributeTask(DailyTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "仅领取贡品"
        self.visible = False
        self.default_config = {key: DEFAULTS[key] for key in ("运行速度", "安全导航重试次数")}
        self.description = "只领取首页累计贡品并确认返回首页，不执行其他每日步骤"

    @record_run
    def run(self):
        self.stage = "tribute"
        self.collect_tribute()
        self.save_evidence("tribute-final-home")
        self.completed = True


class RecoveryMailTask(DailyTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "仅复原作战与邮件"
        self.visible = False
        self.default_config = {key: DEFAULTS[key] for key in ("复原作战", "邮件", "运行速度", "安全导航重试次数")}
        self.description = "检查复原奖励、原队伍重新任命与邮件，不重复其他每日步骤"

    @record_run
    def run(self):
        self.observe()
        if self.has("CLEAR") and self.templates.find(self.image, "recovery_exit") is not None:
            self.finish_recovery_result()
            self.wait(self.is_recovery_map, "恢复复原战斗结算", 80)
        self.post_raid_actions()
        self.home()
        self.save_evidence("extras-final-home")
        self.completed = True


class EventDailyTask(DailyTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "仅活动每日"
        self.visible = False
        self.default_config = {key: DEFAULTS[key] for key in
                               ("活动扫荡上限", "运行速度", "安全导航重试次数")}
        self.description = "按已适配活动类型处理签到、日程表奖励及可选扫荡"

    @record_run
    def run(self):
        self.observe()
        if self.is_event_result():
            self.finish_event_result()
        if self.has("GetItem") or self.has("点击屏幕继续"):
            self.dismiss_reward()
        self.run_stage("event", self.activity_daily)
        self.save_evidence("event-final-home")
        self.completed = True
