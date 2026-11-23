"""Reusable sign-in, rewards and optional combat workflows for recorded activities."""
from datetime import datetime, timedelta, timezone
import json
import re

import cv2
import numpy as np

from src.event_profiles import EVENT_PROFILES, TRICK_OR_TWIN
from src.interaction import UndispatchedClick
from src.vision import ROOT, compact, parse_score


def event_day(now=None, profile=TRICK_OR_TWIN):
    # Recording at 21:50 CST shows 11:09 until reset, i.e. 09:00 CST.
    now = now or datetime.now(timezone(timedelta(hours=8)))
    return (now.astimezone(timezone(timedelta(hours=8)))
            - timedelta(hours=profile["reset_hour_cst"])).date().isoformat()


def battery_change(text):
    values = re.findall(r"\d+", text)
    if len(values) == 2:
        before, after = map(int, values)
        if before > 0 and after == before-1:
            return before, after
    return None


class EventMixin:
    @property
    def event_profile(self):
        header = self.text((150, 0, 900, 110))
        for profile in EVENT_PROFILES:
            if profile["title"] in header:
                return profile
        return getattr(self, "_event_profile", TRICK_OR_TWIN)

    def event_actions(self):
        if not self.option("活动每日"):
            self.info["活动"] = "已按设置跳过"
            return
        self.activity_daily()

    def event_journal(self, state=None):
        path = ROOT / "configs/event_journal.json"
        if state is not None:
            path.parent.mkdir(exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
            return state
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if saved.get("event") != self.event_profile["id"] or saved.get("day") != event_day(profile=self.event_profile):
            if saved.get("pending"):
                self.fail("上个活动日仍有未核对的扫荡，请先核对活动记录，避免重复消耗")
            return {"event": self.event_profile["id"], "day": event_day(profile=self.event_profile), "completed": 0, "pending": None}
        return saved

    def event_overlay(self):
        for title in ("活动签到", "活动任务", "每日任务"):
            if title in self.text((150, 90, 600, 240)):
                return title
        return None

    def is_event_home(self):
        return self.is_event_identity() and self.has(*self.event_profile["home_labels"]) \
            and self.event_overlay() is None and not self.has("点击屏幕继续")

    def event_panel(self, title):
        return self.is_event_identity() and self.event_overlay() == title \
            and not self.has("GetItem") and not self.has("点击屏幕继续")

    def open_event(self):
        self.home()

        def entrances():
            return [(profile, hit) for profile in EVENT_PROFILES
                    if (hit := self.templates.find(self.image, profile["entry"])) is not None]

        def enter():
            matches = entrances()
            if len(matches) != 1:
                self.fail("活动入口未唯一匹配已适配活动", recoverable=True)
            self._event_profile, hit = matches[0]
            self.tap(hit.x, hit.y)

        self.menu_transition(enter, lambda: self.is_home() and len(entrances()) == 1,
                             lambda: self.is_event_home() or self.event_panel("活动签到"), "打开已适配活动")

    def open_event_panel(self, label, title):
        self.menu_transition(lambda: self.click_text("^"+label+"$", self.event_profile["panel_links"]),
                             self.is_event_home, lambda: self.event_panel(title), "打开活动"+label)

    def close_event_panel(self, title):
        def close():
            name = self.event_profile["daily_close" if title == "每日任务" else "signin_close"]
            hit = self.templates.find(self.image, name)
            if hit is None:
                self.fail("活动面板关闭图标未确认："+title, recoverable=True)
            self.tap(hit.x, hit.y)
        self.menu_transition(close, lambda: self.event_panel(title), self.is_event_home, "关闭活动"+title)

    def event_sign_in(self):
        self.open_event_panel("活动签到", "活动签到")
        layout = self.event_profile["signin"]
        def checks():
            return len(self.templates.all(self.image, "event_checked", layout["checks"], .90))
        def state():
            if not self.event_panel("活动签到") or layout["label"] not in self.text(layout["button"]):
                return "unknown"
            x1, y1, x2, y2 = layout["brightness"]
            brightness = float(np.median(cv2.cvtColor(
                self.image[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)[:, :, 2]))
            if brightness >= 115:
                return "ready"
            if brightness <= 85 and checks() > 0:
                return "claimed"
            return "unknown"
        if state() == "ready":
            self.verified_action(lambda: self.click_text("^"+layout["label"]+"$", layout["button"]),
                                 lambda: state() == "ready",
                                 lambda: self.has("GetItem") or self.has("点击屏幕继续"), "活动签到回执")
            self.dismiss_reward()
            # The new checkmark can be below the visible rows.
            self.wait(lambda: state() == "claimed", "活动签到领取后按钮禁用", recoverable=True)
        elif state() != "claimed":
            self.fail("活动签到领取状态不确定", recoverable=True)
        self.info["活动签到"] = "已确认签到勾选及领取按钮禁用"
        self.close_event_panel("活动签到")

    def is_event_map(self):
        return re.search(r"活动第[12]部", self.text((150, 0, 600, 150))) is not None \
            and self.has("普通", "困难") and not self.has("出击") and not self.has("CLEAR")

    def event_nodes(self):
        if not self.is_event_map():
            return []
        red = self.templates.all(self.image, "event_combat", (250, 180, 1920, 850), .92)
        red += [hit for hit in self.templates.all(self.image, "event_combat_idle", (250, 180, 1920, 850), .92)
                if not any(abs(hit.x-h.x) < 30 and abs(hit.y-h.y) < 30 for h in red)]
        stars = self.templates.all(self.image, "event_three_stars", (250, 180, 1920, 850), .93)
        green = self.templates.all(self.image, "event_dialogue", (250, 180, 1920, 850), .90)
        return [hit for hit in sorted(red, key=lambda h: (h.y, h.x))
                if any(abs(hit.x-star.x) <= 25 and 20 <= star.y-hit.y <= 70 for star in stars)
                and not any(abs(hit.x-g.x) < 70 and abs(hit.y-g.y) < 70 for g in green)]

    def event_map_signature(self):
        # Ignore changing art/particles; use map node labels and marker positions.
        return tuple(sorted((compact(b.name), round(b.x/15), round(b.y/15)) for b in self.words
                            if 300 < b.x < 1880 and 200 < b.y < 700))

    def find_event_node(self):
        for chapter in self.event_profile["chapters"]:
            heading = "活动第"+str(chapter)+"部"
            self.menu_transition(lambda: self.click_text("^第"+str(chapter)+"部$", (0, 170, 300, 750)),
                                 self.is_event_map,
                                 lambda: self.is_event_map() and heading in self.text((150, 0, 600, 150)),
                                 "选择活动章节"+str(chapter))
            # Starting scroll position can persist. Scan to each end before claiming absence.
            for start, end in ((.35, .85), (.85, .35)):
                for _ in range(6):
                    node = self.open_visible_event_node()
                    if node:
                        return node
                    before = self.event_map_signature()
                    if not before:
                        self.fail("活动地图标识不足，不能确认不存在三星关卡", recoverable=True)
                    h, w = self.frame.shape[:2]
                    self.swipe(int(w*start), int(h*.55), int(w*end), int(h*.55), duration=.5)
                    self.wait(self.is_event_map, "活动地图拖动后稳定", stable_seconds=1.2)
                    if before == self.event_map_signature():
                        break
                else:
                    self.fail("活动地图扫描达到上限，尚未确认末端；未执行扫荡", recoverable=True)
        self.info["活动扫荡"] = "已检查本期两章可确认的列表范围，无红色三星关卡，跳过扫荡"
        return None

    def open_visible_event_node(self):
        if not self.event_nodes():
            return None

        def open_node():
            choices = self.event_nodes()
            if not choices:
                self.fail("当前画面未确认红色三星图标", recoverable=True)
            hit = choices[0]
            self.tap(hit.x+100, hit.y+25)

        self.menu_transition(open_node, lambda: bool(self.event_nodes()),
                             self.is_event_detail, "打开活动红色三星关卡")
        # The title is needed for the sweep journal, after the icon-led navigation.
        title = self.text((1000, 20, 1670, 100))
        if not title:
            self.fail("活动关卡详情标题无法核对扫荡记录，已跳过扫荡", recoverable=True)
        return title

    def leave_event_scene(self):
        if self.is_event_identity() and self.event_overlay() is not None:
            self.close_event_panel(self.event_overlay())
            return True
        if self.is_event_detail():
            self.menu_transition(lambda: self.click_text("^返回$", (850, 900, 1250, 1080)),
                                 self.is_event_detail, self.is_event_map, "退出活动关卡详情")
            return True
        if self.is_event_map():
            def back():
                hit = self.templates.find(self.image, "event_map_back")
                if hit is None:
                    self.fail("活动地图返回图标未识别")
                self.tap(hit.x, hit.y)
            self.menu_transition(back, self.is_event_map, self.is_event_home, "退出活动地图")
            return True
        return False

    def is_event_detail(self, node=None):
        header = self.text((150, 0, 600, 150))
        return re.search(r"活动第[12]部", header) is not None and self.has("推荐等级", "出击") \
            and (node is None or node == self.text((1000, 20, 1670, 100))) \
            and not any(self.has(t) for t in ("CLEAR", "是否使用扫荡", "GetItem", "点击屏幕继续", "物品已满"))

    def event_battery(self):
        value = re.fullmatch(r"(\d+)/1", self.text((1310, 950, 1430, 1030)))
        if value is None:
            boxes = self.ocr(frame=cv2.resize(self.image[955:1020, 1310:1430], None, fx=3, fy=3), threshold=.7)
            value = re.fullmatch(r"(\d+)/1", compact("".join(b.name for b in boxes)))
        if value is None:
            self.fail("活动导航电池剩余量未确认")
        return int(value[1])

    def event_confirmation(self, before):
        if not self.has("是否使用扫荡", "导航电池"):
            return False
        values = " ".join(b.name for b in self.words if 850 < b.x+b.width/2 < 1100
                          and 590 < b.y+b.height/2 < 660)
        return battery_change(values) == (before, before-1)

    def is_event_result(self, node=None):
        return re.search(r"活动第[12]部", self.text((150, 0, 600, 150))) is not None \
            and self.has("CLEAR", "奖励列表") \
            and (node is None or node in self.text((700, 400, 1200, 530))) \
            and "确认" in self.text((800, 930, 1100, 1050))

    def finish_event_result(self, node=None):
        self.menu_transition(lambda: self.click_text("^确认$", (800, 930, 1100, 1050)),
                             lambda: self.is_event_result(node),
                             lambda: self.is_event_detail(node), "关闭活动扫荡结算")

    def reconcile_event_sweep(self, saved, node, remaining):
        pending = saved.get("pending")
        if not pending:
            return
        if pending["node"] != node:
            self.fail("未确认扫荡记录属于另一关卡，请先核对，停止重复消耗")
        if remaining == pending["before"]-1:
            saved["completed"] += 1
        elif not (pending.get("blocked") and remaining == pending["before"]):
            self.fail("上次活动扫荡结果不确定，未再次消耗导航电池")
        saved["pending"] = None
        self.event_journal(saved)

    def event_sweeps(self):
        saved = self.event_journal()
        cap = max(0, min(4, int(self.option("活动扫荡上限"))))
        if saved["completed"] >= cap and not saved.get("pending"):
            self.info["活动扫荡"] = f"本游戏日已确认{saved['completed']}次，上限{cap}次"
            return
        self.menu_transition(lambda: self.click_text("^进入剧情$", (1400, 850, 1800, 990)),
                             self.is_event_home, self.is_event_map, "进入活动关卡")
        node = self.find_event_node()
        if node is None:
            if saved.get("pending"):
                self.fail("存在未核对的扫荡记录，本轮未找到原关卡")
            return
        if "扫荡" not in self.text((1400, 820, 1650, 940)):
            if saved.get("pending"):
                self.fail("上次活动扫荡待核对，但原关卡没有扫荡按钮，停止重复消耗")
            self.info["活动扫荡"] = "详情没有扫荡按钮，已跳过"
            return
        self.reconcile_event_sweep(saved, node, self.event_battery())
        while saved["completed"] < cap and self.event_battery() > 0:
            before = self.event_battery()
            self.menu_transition(lambda: self.click_text("^扫荡$", (1400, 820, 1650, 940)),
                                 lambda: self.is_event_detail(node),
                                 lambda: self.event_confirmation(before), "活动扫荡确认弹窗")
            def confirm():
                saved["pending"] = {"node": node, "before": before, "blocked": False}
                self.event_journal(saved)
                try:
                    self.click_text("^确认$", (1280, 730, 1480, 840))
                except UndispatchedClick:
                    saved["pending"] = None
                    self.event_journal(saved)
                    raise
            self._event_pending = saved
            try:
                self.verified_action(confirm, lambda: self.event_confirmation(before),
                                     lambda: self.is_event_result(node), "活动扫荡回执", seconds=60)
                self.save_evidence("event-sweep-clear")
                self.finish_event_result(node)
                remaining = self.event_battery()
                if remaining != before-1:
                    self.fail("活动扫荡后导航电池未按预期减少1，停止重复消耗")
                self.reconcile_event_sweep(saved, node, remaining)
            finally:
                self._event_pending = None
        self.info["活动扫荡"] = f"本游戏日已确认{saved['completed']}次，剩余导航电池{self.event_battery()}"

    def event_chests(self):
        states = []
        for x in self.event_profile["chests"]:
            region = (x-65, 200, x+65, 305)
            opened = self.templates.find(self.image, "event_chest_open", region, .83)
            closed = self.templates.find(self.image, "event_chest_closed", region, .88)
            if opened and (not closed or opened.score > closed.score+.025):
                states.append("claimed")
            elif closed and (not opened or closed.score > opened.score+.025):
                states.append("closed")
            else:
                states.append("unknown")
        return states

    def claim_event_panel(self, label, title):
        self.open_event_panel(label, title)
        rect = self.event_profile["reward_button"]
        def all_button():
            name = self.event_profile["daily_all" if title == "每日任务" else "missions_all"]
            return "全部领取" in self.text(rect) or self.templates.find(self.image, name) is not None
        if all_button():
            self.verified_action(lambda: self.click_text("^全部领取$", rect),
                                 lambda: self.event_panel(title) and all_button(),
                                 lambda: self.has("GetItem") or self.has("点击屏幕继续"), "活动"+label+"奖励回执")
            self.dismiss_reward()
            self.wait(lambda: self.event_panel(title) and not all_button(), "活动"+label+"全部领取消失", recoverable=True)
        if title == "每日任务":
            points = parse_score(self.text(self.event_profile["score"]))
            states = self.event_chests()
            if points is None or "unknown" in states:
                self.fail("活动每日积分或宝箱状态未确认")
            for index, state in enumerate(states):
                if (index+1)*20 <= points and state != "claimed":
                    self.fail("活动积分已达标但对应宝箱尚未确认领取")
            self.info["活动日程表"] = {"积分": points, "宝箱": states}
        else:
            if re.search(r"\d+/\d+", self.text((250, 180, 530, 270))) is None \
                    or not any(self.has(t) for t in ("前往", "完成")):
                self.fail("活动累计任务的无可领取状态未确认")
            self.info["活动累计任务"] = "已确认全部领取按钮消失，无当前可领取的累计奖励"
        self.save_evidence("event-"+("daily" if title == "每日任务" else "missions")+"-claimed")
        self.close_event_panel(title)

    def activity_daily(self):
        self.open_event()
        profile = self.event_profile
        if not self.run_stage("event_sign_in", self.event_sign_in):
            self.open_event()
            if self.event_panel("活动签到"):
                self.close_event_panel("活动签到")
        if profile["workflow"] == "combat":
            self.run_stage("event_sweeps", self.event_sweeps)
        else:
            self.info["活动扫荡"] = "本期为签到与任务活动"
        for label, title in profile["panels"]:
            def claim(label=label, title=title):
                self.open_event()
                if self.event_panel("活动签到"):
                    self.close_event_panel("活动签到")
                self.claim_event_panel(label, title)
            self.run_stage("event_rewards", claim)
        self.home()
