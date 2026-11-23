"""Recorded activity identities and layout differences, in normalized pixels."""

TRICK_OR_TWIN = {
    "id": "trick_or_twin", "title": "虚假之夜", "entry": "event_phone",
    "workflow": "combat", "chapters": (1, 2), "reset_hour_cst": 9,
    "home_labels": ("进入剧情", "日程表", "活动签到"),
    "signin": {"label": "领取", "button": (1480, 850, 1680, 940),
               "brightness": (1520, 870, 1640, 920), "checks": (640, 230, 1720, 800)},
    "panels": (("日程表", "每日任务"), ("活动任务", "活动任务")),
    "panel_links": (320, 950, 1400, 1040),
    "reward_button": (1280, 850, 1700, 950),
    "daily_close": "event_schedule_close", "signin_close": "event_panel_close",
    "daily_all": "event_daily_all", "missions_all": "event_missions_all",
    "score": (480, 270, 610, 330),
    "chests": (788, 968, 1148, 1328, 1508),
}

DOPAMINE_CHANNEL = {
    **TRICK_OR_TWIN,
    "id": "dopamine_channel", "title": "拉莉娜的多巴胺频道", "entry": "event_dopamine_phone",
    "workflow": "sign_in_tasks", "chapters": (),
    "home_labels": ("日程表", "活动签到", "兑换所"),
    "signin": {"label": "全部领取", "button": (1450, 830, 1740, 940),
               "brightness": (1530, 870, 1640, 910), "checks": (950, 280, 1740, 750)},
    "panels": (("日程表", "每日任务"),),
    "signin_close": "event_dopamine_signin_close", "daily_close": "event_dopamine_daily_close",
}

EVENT_PROFILES = (DOPAMINE_CHANNEL, TRICK_OR_TWIN)
