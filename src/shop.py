"""Updated FAIRY-MALL branch: only the recorded free 10000-coin order."""
import re

from src.vision import compact


class NewShopMixin:
    def is_new_shop(self):
        return self.has("限量商品") and self.templates.find(self.image, "shop_new_home") is not None \
            and not self.has("订单", "光辉币") and not self.has("点击屏幕继续")

    def new_free_order(self):
        item = self.text((1090, 260, 1290, 400))
        price = self.text((800, 820, 1120, 905))
        return "订单" in self.text((850, 120, 1100, 240)) \
            and "光辉币" in item and re.search(r"[xX×]10000(?!\d)", item) is not None \
            and re.fullmatch(r"总价[:：]?免费[!！]?", price) is not None

    def new_free_card(self):
        if not self.is_new_shop():
            return None
        titles = [b for b in self.words if compact(b.name) == "妖精网支援金"
                  and 320 <= b.x+b.width/2 <= 1880 and 300 <= b.y+b.height/2 <= 950]
        if len(titles) != 1:
            return None
        title = titles[0]
        x, y = title.x+title.width/2, title.y+title.height/2
        return title, (max(320, x-170), max(250, y-355), min(1880, x+170), min(1050, y+105))

    def claim_new_free_coins(self):
        if not self.option("免费金币"):
            self.home()
            return
        self.menu_transition(lambda: self.click_text("^限量商品$", (0, 480, 310, 720)),
                             self.is_new_shop,
                             lambda: self.new_free_card() is not None, "新版限量商品")

        def sold_out():
            found = self.new_free_card()
            if found is None:
                return False
            card = self.text(found[1])
            return re.search(r"Sold[.·]*Out", card, re.IGNORECASE) is not None and "0/1" in card

        def available():
            found = self.new_free_card()
            if found is None:
                return False
            title, (x1, y1, x2, y2) = found
            price = self.text((x1, title.y+title.height/2+20, x2, y2))
            stocked = any(compact(b.name) == "1/1" and x1 <= b.x+b.width/2 <= x2
                          and y1 <= b.y+b.height/2 <= y2 for b in self.words)
            return stocked and re.fullmatch(r"免费[!！]?", price) is not None

        def open_card():
            if not available():
                self.fail("免费金币商品卡片、库存或免费价格未确认", recoverable=True)
            title, _ = self.new_free_card()
            self.tap(title.x+title.width/2, title.y+title.height/2-160)

        if not sold_out():
            self.menu_transition(open_card, available,
                                 self.new_free_order, "新版免费金币订单")
            self.verified_action(lambda: self.click_text("^购买$", (700, 890, 1200, 1000)),
                                 self.new_free_order,
                                 lambda: self.has("PURCHASE") or self.has("GetItem")
                                 or self.has("点击屏幕继续"), "新版免费金币领取回执")
            self.dismiss_reward()
            self.wait(sold_out, "免费金币领取后售罄状态")
        self.info["免费金币"] = "已确认免费10000金币商品售罄"
        self.home()
