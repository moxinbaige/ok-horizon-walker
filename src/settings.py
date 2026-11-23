"""User-facing task options; consuming safeguards are never configurable."""
from ok.util.config import Config


RAID_TARGETS = (
    "织造的神格", "树枝的契约者", "天空盗贼变异体", "军团兵变异体",
    "火焰术士变异体", "雷电的神格", "冰霜宝珠", "巨大破坏机械",
    "变质的奥尔克射手", "黑影骑士", "虚妄之梦的神灵", "被囚禁于海底的鱼人侵夺者",
    "沉溺于悲叹的野兽", "月蚀巨兽",
)

DEFAULTS = {
    "贡品": True, "累计资源": True,
    "免费金币": True, "金币愿望": True,
    "讨伐": True, "讨伐目标": "黑影骑士", "复原作战": True, "邮件": True,
    "活动每日": False, "活动扫荡上限": "4",
    "运行速度": "标准", "安全导航重试次数": "3",
}
COUNT_CHOICES = {"活动扫荡上限": range(5), "安全导航重试次数": range(1, 4)}
ACTIVITY_SCORE_NOTE = "本期活动没有可扫荡的战斗时，每日活动积分可能无法拿满。"
DESCRIPTIONS = {
    "讨伐": "开启后按下方选择的目标执行。",
    "讨伐目标": "每轮处理一个危险区域 IV 目标。当天首次先完成战斗，再扫荡剩余次数。",
    "金币愿望": "只做金币奖励的愿望，最多三次。",
    "复原作战": "处理三处奖励并沿用原队伍任命；空队伍停止。",
    "活动每日": "自动识别已适配活动。执行签到与任务领奖，带战斗活动按上限扫荡；默认关闭。",
    "活动扫荡上限": "每个游戏日可选 0–4 次。选 0 时仍执行活动签到和领奖。",
    "运行速度": "标准优先及时检查页面；保守增加页面稳定等待。两者都校验操作结果。",
    "安全导航重试次数": "可选 1–3 次，包含首次操作。仅用于可安全重试的页面导航。",
}
TYPES = {
    "讨伐目标": {"type": "drop_down", "options": list(RAID_TARGETS)},
    "运行速度": {"type": "drop_down", "options": ["标准", "保守"]},
    **{key: {"type": "drop_down", "options": list(map(str, choices))}
       for key, choices in COUNT_CHOICES.items()},
}


class DailyConfig(Config):
    def verify_config(self, current, default_config):
        original = current
        if "黑影骑士" in current and "讨伐" not in current:
            # Leave the legacy key in place for Config to discard and save.
            current = {**current, "讨伐": current["黑影骑士"]}
        for key, choices in COUNT_CHOICES.items():
            if key not in current or key not in default_config:
                continue
            value = current[key]
            try:
                count = int(str(value))
            except ValueError:
                replacement = default_config[key]
            else:
                replacement = str(max(choices.start, min(choices.stop-1, count)))
            if value != replacement:
                current = {**current, key: replacement}
        modified = super().verify_config(current, default_config)
        return modified or current != original


def task_option(task, key):
    config = getattr(task, "config", None) or {}
    snapshot = getattr(task, "run_options", None)
    return (snapshot if snapshot is not None else config).get(key, DEFAULTS[key])
