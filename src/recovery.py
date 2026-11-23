"""Approved recovery-operation and mailbox steps, using the existing task I/O."""
import re

import cv2

from src.vision import compact

REGIONS = ("阿吾地矿山", "咸兴地区", "春川自治市")


class RecoveryMixin:
    def is_recovery_map(self):
        return self.has("复原作战", *REGIONS) and not self.has("WARNING") \
            and "通知" not in self.text((650, 200, 1300, 400)) \
            and "警戒结果报告" not in self.text((650, 100, 1300, 250))

    def region_rect(self, region):
        titles = [b for b in self.words if compact(b.name) == region]
        if len(titles) != 1:
            self.fail("复原区域名称不唯一："+region)
        title = titles[0]
        return (max(0, title.x-150), max(140, title.y-80),
                min(1920, title.x+450), min(1080, title.y+300))

    def region_state(self, region):
        text = self.text(self.region_rect(region))
        if "警戒结果报告" in text:
            return "report"
        if "出动" in text:
            return "battle"
        if "任命" in text:
            return "assign"
        if "警戒中" in text and re.search(r"剩余时间\d{1,2}:\d{2}:\d{2}", text):
            return "patrolling"
        return "unknown"

    def recovery_operations(self):
        self.stages()
        self.menu_transition(lambda: self.click_text("^复原作战$", (1350, 650, 1850, 1000)),
                             lambda: self.has("剧情", "讨伐"), self.is_recovery_map,
                             "打开复原作战")
        for region in REGIONS:
            self.wait(self.is_recovery_map, "复原作战地图")
            state = self.region_state(region)
            self.save_evidence("recovery-"+str(REGIONS.index(region))+"-"+state)
            if state == "patrolling":
                self.info[region] = "已确认警戒中，跳过"
                continue
            if state == "report":
                self.verified_action(lambda: self.click_text("^警戒结果报告$", self.region_rect(region)),
                                     lambda: self.is_recovery_map() and self.region_state(region) == "report",
                                     lambda: "警戒结果报告" in self.text((650, 100, 1300, 250))
                                     and self.has("防卫队报告警戒结果"), "警戒奖励报告")
                self.save_evidence("recovery-report")
                self.menu_transition(lambda: self.click_text("^关闭$", (320, 800, 970, 930)),
                                     lambda: self.has("防卫队报告警戒结果"),
                                     lambda: self.is_recovery_map() and self.region_state(region) == "assign",
                                     "报告领取后可重新任命")
            elif state == "battle":
                self.recovery_battle(region)
            elif state != "assign":
                self.fail("复原区域状态不确定："+region)
            self.assign_recovery_squad(region)
        self.home()

    def recovery_battle(self, region):
        self.menu_transition(lambda: self.click_text("^出动$", self.region_rect(region)),
                             lambda: self.is_recovery_map() and self.region_state(region) == "battle",
                             lambda: self.has("通知", "请求紧急出动", "归还命令"), "复原出动通知")
        self.menu_transition(lambda: self.click_text("^出动$", (1200, 650, 1760, 800)),
                             lambda: self.has("通知", "请求紧急出动", "归还命令"),
                             lambda: self.has("复原作战", region, "出击", "预计遭遇"), "复原战斗出击页")
        self.save_evidence("recovery-deployment")
        self.verified_action(lambda: self.click_text("^出击$", (1350, 940, 1750, 1080)),
                             lambda: self.has("复原作战", region, "出击", "预计遭遇"),
                             lambda: self.templates.find(self.image, "battle_pause") is not None,
                             "复原进入战斗", seconds=100)
        self.battle(recovery=True)
        self.wait(lambda: self.is_recovery_map() and self.region_state(region) == "assign",
                  "复原胜利后可重新任命", 80)

    def finish_recovery_result(self):
        self.wait(lambda: self.has("CLEAR", "奖励列表") and
                  self.templates.find(self.image, "recovery_exit") is not None,
                  "复原专用退出按钮", 35)
        self.save_evidence("recovery-battle-result")
        def source():
            return self.has("CLEAR", "奖励列表") and \
                self.templates.find(self.image, "recovery_exit") is not None
        def click_exit():
            button = self.templates.find(self.image, "recovery_exit")
            if not source() or button is None:
                self.fail("复原胜利退出页已变化，停止点击")
            self.tap(button.x, button.y)
        self.menu_transition(click_exit, source, self.is_recovery_map, "退出复原胜利结算")

    def assign_recovery_squad(self, region):
        self.menu_transition(lambda: self.click_text("^任命$", self.region_rect(region)),
                             lambda: self.is_recovery_map() and self.region_state(region) == "assign",
                             lambda: self.has("开始警戒", "护卫列表") and
                             (self.has("护卫队编成") or self.has("任命防卫队")),
                             "打开复原任命队伍")
        self.save_evidence("recovery-squad")
        # The selected leader's level is inside the left roster, not the available list.
        def selected_squad():
            if not self.has("开始警戒", "护卫列表"):
                return False
            words = self.ocr(frame=cv2.resize(self.image[220:355, 205:555], None, fx=2, fy=2),
                             threshold=0.7)
            selected = compact("".join(b.name for b in words))
            if re.search(r"Lv\.?[1-9]\d?", selected, re.IGNORECASE) is None:
                self.fail("复原原队伍为空或未确认，未使用自动编队："+region)
            return True
        if not selected_squad():
            self.fail("当前不是已识别的原队伍任命页："+region)
        self.verified_action(lambda: self.click_text("^开始警戒$", (1250, 940, 1870, 1070)),
                             selected_squad,
                             lambda: self.is_recovery_map() and self.region_state(region) == "patrolling",
                             "重新任命后警戒中及剩余时间")
        self.save_evidence("recovery-reassigned")
        self.info[region] = "奖励已处理，原队伍已重新任命并确认警戒中"

    def is_mailbox(self):
        return "收件箱" in self.text((150, 0, 650, 130)) \
            and not self.has("GetItem") and not self.has("点击屏幕继续")

    def mail_claimable(self):
        return self.templates.find(self.image, "mail_all") is not None \
            or "全部领取" in self.text((100, 940, 550, 1080))

    def mail_finished(self):
        return self.is_mailbox() and not self.mail_claimable() and (
            any(self.has(word) for word in ("没有邮件", "暂无邮件", "没有可领取"))
            or self.templates.find(self.image, "mail_claimed") is not None)

    def claim_mail(self):
        self.home()
        def click_mail():
            icon = self.templates.find(self.image, "phone_mail")
            if icon is None:
                self.fail("首页邮件图标未识别")
            self.tap(icon.x, icon.y)
        self.menu_transition(click_mail, self.is_home, self.is_mailbox, "打开收件箱")
        self.save_evidence("mail-before")
        if self.mail_finished():
            self.info["邮件"] = "已确认无可领取奖励"
        elif self.mail_claimable():
            def click_all():
                button = self.templates.find(self.image, "mail_all")
                if button:
                    self.tap(button.x, button.y)
                else:
                    self.click_text("^全部领取$", (100, 940, 550, 1080))
            self.verified_action(click_all, lambda: self.is_mailbox() and self.mail_claimable(),
                                 lambda: self.has("GetItem") or self.has("点击屏幕继续"), "邮件奖励回执")
            self.dismiss_reward()
            self.wait(self.mail_finished, "邮件奖励已全部领取")
            self.info["邮件"] = "已确认奖励回执及无剩余可领取状态"
        else:
            self.fail("邮件领取状态不确定")
        self.save_evidence("mail-after")
        self.home()

    def post_raid_actions(self):
        for stage, action in (("recovery", self.recovery_operations), ("mail", self.claim_mail)):
            if self.option("复原作战" if stage == "recovery" else "邮件"):
                self.run_stage(stage, action)
