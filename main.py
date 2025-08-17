import uvicorn
from fastapi import FastAPI, Request
import re
from datetime import datetime, timezone, timedelta
import asyncio
import time
import http.client
import json


class PigStatus:
    def __init__(self, line: int = -1, pos: str = "未知"):
        self.line = line
        self.pos = pos
        self.lineBusy = False
        self.alive = True

class PigLineController:
    def __init__(self):
        self.target_group = 940409582
        self.pigs = []
        self.pattern = re.compile(r"^(\d+)([A-Za-z]+|[\u4e00-\u9fff]+)$")
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
            "崖": "崖之遗迹",
            "遗迹": "崖之遗迹",
            "崖之": "崖之遗迹",
            "涯": "崖之遗迹",
            "崖之遗迹": "崖之遗迹",
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
    
    def receiveMsg(self, msg):
        match = self.pattern.match(msg)
        if match:
            number = match.group(1)   # 数字部分
            line = int(number)
            text = match.group(2)     # 英文或中文部分
            if line>200:
                return
            if text in self.alias_map:
                text = self.alias_map[text]
                if text == "s":
                    self.delete(line)
                elif text == "b":
                    pig = self.get(line)
                    if pig:
                        pig.lineBusy = True
                        self.delete(line)
                else:
                    self.add(PigStatus(line, text))
    
    def add(self, pig: PigStatus):
        """添加一个 PigStatus"""
        # 如果该 line 已经存在，就不重复添加
        if not any(p.line == pig.line for p in self.pigs):
            self.pigs.append(pig)
            self.sendMsg()
            asyncio.create_task(self._auto_delete(pig.line, 120))

    async def _auto_delete(self, line: int, ttl: int):
        """延时 ttl 秒后删除指定线路"""
        await asyncio.sleep(ttl)
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
                p.alive = False
                self.sendMsg()
                del self.pigs[i]  # 删除目标
                return True
        return False  # 没有找到要删除的线路

    def all(self):
        """返回所有 PigStatus"""
        return self.pigs
    
    def sendMsg(self):
        """把当前所有 PigStatus 发到QQ群"""
        if not self.pigs:
            return  # 没有数据就不发
        # 格式化信息，比如每条线路显示 line + busy 状态
        lines_info = []
        for p in self.pigs:
            status = "❌" if p.lineBusy or not p.alive else "✅"
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
TARGET_GROUPS = {875329843}
# 正则：数字+英文 或 数字+中文
pattern = re.compile(r"^\d+(?:[A-Za-z]+|[\u4e00-\u9fff]+)$")

@app.post("/")
async def root(request: Request):
    data = await request.json()  # 获取事件数据
    # 过滤非群聊消息
    if data.get("message_type") != "group":
        return {}
    group_id = data.get("group_id")
    # 判断是不是目标群
    if group_id in TARGET_GROUPS:
        # 转换为 datetime，并加上时区 UTC+8
        raw_message = data.get("raw_message", "").strip()
        # 判断是否是有效信息
        if pattern.match(raw_message):
            controller.receiveMsg(raw_message)
            ts = data.get("time")
            dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
            print(f"[{dt.strftime("%Y-%m-%d %H:%M:%S")}]: {raw_message}")
            
    return {}

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        access_log=False  # 关闭 uvicorn 的请求日志
    )
