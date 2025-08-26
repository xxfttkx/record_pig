import uvicorn
from fastapi import FastAPI, Request
import re
from datetime import datetime, timezone, timedelta
import asyncio
import http.client
import json
import sys
import requests

class PigStatus:
    def __init__(self, line: int = -1, pos: str = "未知"):
        self.line = line
        self.pos = pos
        self.lineBusy = False
        self.alive = True
    
    def isDead(self):
        """判断当前状态是否已经死亡"""
        return not self.alive or self.lineBusy

class PigLineController:
    def __init__(self):
        self.target_group = 940409582
        # self.target_group = 691859318
        self.backend_url = "http://127.0.0.1:5000/line"  # 后端服务地址
        self.pigs = []
        self.pattern = re.compile(r"^(\d+)\s*([A-Za-z]+|[\u4e00-\u9fff]+)$")
        self.alias_map = {
            "左": "左上",
            "左上": "左上",
            "ys": "右上",
            "原神": "右上",
            "右上": "右上",
            "右": "右",
            "m": "麦田",
            "mai": "麦田",
            "麦": "麦田",
            "麦田": "麦田",
            "zp": "帐篷",
            "帐篷": "帐篷",
            "yz": "驿站",
            "玉足": "驿站",
            "驿站": "驿站",
            "y": "崖之遗迹",
            "ya": "崖之遗迹",
            "崖": "崖之遗迹",
            "遗迹": "崖之遗迹",
            "崖之": "崖之遗迹",
            "涯": "崖之遗迹",
            "崖之遗迹": "崖之遗迹",
            "k": "卡",
            "ka": "卡",
            "卡": "卡",
            "s": "s",
            "假": "s",
            "无": "s",
            "没有": "s",
            "死": "s",
            "b": "b",
            "爆满": "b",
            "爆": "b",
        }
    
    def receiveMsg(self, data):
        ts = data.get("time")
        dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
        msg = data.get("raw_message", "").strip()
        # 忽略图片 CQ 码
        msg = re.sub(r"\[CQ:image[^\]]*\]", "", msg).strip()
        # 忽略指定关键词
        ignore_words = ['一手', '1手', '金猪']
        ignore_pattern = re.compile("|".join(map(re.escape, ignore_words)))
        msg = re.sub(ignore_pattern, "", msg).strip()
        match = self.pattern.match(msg)
        if match:
            print(f"[{dt.strftime("%Y-%m-%d %H:%M:%S")}]: {msg}")
            number = match.group(1)   # 数字部分
            line = int(number)
            text = match.group(2).lower()     # 英文或中文部分
            if line>200:
                return
            if text in self.alias_map:
                text = self.alias_map[text]
                if text == "s":
                    pig = self.get(line)
                    if pig:
                        pig.alive = False
                        self.sendMsg()
                        self.delete(line)
                elif text == "b":
                    pig = self.get(line)
                    if pig:
                        pig.lineBusy = True
                        self.sendMsg()
                        self.delete(line)
                else:
                    self.add(PigStatus(line, text))
    
    def add(self, pig: PigStatus):
        """添加一个 PigStatus"""
        curr_pig = self.get(pig.line)
        if not curr_pig:
            self.pigs.append(pig)
            self.sendMsg()
            asyncio.create_task(self._auto_delete(pig.line, 120*len(self.pigs)))
            self.post_to_backend(pig)
        else:
            if curr_pig.pos != pig.pos:
                curr_pig.pos = pig.pos
                self.sendMsg()

    def post_to_backend(self, pig: PigStatus):
        """把 pig 信息发往后端"""
        try:
            payload = {
                "line": pig.line,
                "pos": pig.pos,
            }
            requests.post(self.backend_url, json=payload, timeout=1)
        except Exception as e:
            print(f"⚠️ 后端请求失败: {e}")


    async def _auto_delete(self, line: int, ttl: int):
        """延时 ttl 秒后删除指定线路"""
        await asyncio.sleep(ttl)
        pig = self.get(line)
        if pig:
            pig.alive = False
            self.sendMsg()
            self.delete(line)

    def get(self, line: int):
        """根据线路号获取 PigStatus"""
        for p in self.pigs:
            if p.line == line:
                return p
        return None

    def delete(self, line: int) -> bool:
        """根据线路号删除 PigStatus，删除成功就发送消息"""
        for i, p in enumerate(self.pigs):
            if p.line == line:
                del self.pigs[i]  # 删除目标
                return True
        return False  # 没有找到要删除的线路
    
    def sendMsg(self):
        """把当前所有 PigStatus 发到QQ群"""
        if not self.pigs:
            return  # 没有数据就不发
        # 格式化信息，比如每条线路显示 line + busy 状态
        lines_info = []
        for p in self.pigs:
            if not p.alive:
                status = "❌"  # Not alive
            elif p.lineBusy:
                status = "💥"  # Line is busy
            else:
                status = "✅"  # All good
            lines_info.append(f"{p.line}{p.pos}: {status}")

        msg = "\n".join(lines_info)
        # 调用你的 QQ 群发送函数
        self.send_to_group(msg)

    def send_to_group(self, msg: str):
        """示例：把消息发送到 QQ 群
        这里你需要接入 LLOneBot 或 OneBot API
        """
        conn = http.client.HTTPConnection("127.0.0.1", 3000)
        payload = json.dumps({
            "group_id": self.target_group,
            "message": [
                {
                    "type": "text",
                    "data": {
                        "text": msg
                    }
                }
            ]
        })
        headers = {
            'Content-Type': 'application/json'
        }
        conn.request("POST", "/send_group_msg", payload, headers)
        # res = conn.getresponse()
        # data = res.read()
        # print(data.decode("utf-8"))

# 🔹 在全局初始化 controller
controller = PigLineController()
app = FastAPI()
TARGET_GROUPS = {875329843, 1011106510, 827630428}

@app.post("/")
async def root(request: Request):
    data = await request.json()  # 获取事件数据
    # 过滤非群聊消息
    if data.get("message_type") != "group":
        return {}
    group_id = data.get("group_id")
    # 判断是不是目标群
    if group_id in TARGET_GROUPS:
        controller.receiveMsg(data) 
    return {}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        access_log=False  # 关闭 uvicorn 的请求日志
    )
