import argparse
import os
import httpx
import uvicorn
from fastapi import FastAPI, Request
import re
from datetime import datetime, timezone, timedelta
import time
import asyncio
import http.client
import json
import sys
import requests

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
class PigStatus:
    def __init__(self, line: int = -1, pos: str = "未知"):
        self.line = line
        self.pos = pos
        self.lineBusy = False
        self.alive = True
        self.changed = True  # 状态是否有变更
        self.pig_wave = False
    
    def consumeUpdateFlag(self):
        """判断当前状态是否需要更新"""
        needs_update = self.changed or (not self.alive) or self.lineBusy
        self.changed = False
        return needs_update
    
    def changePos(self, new_pos: str):
        """更改位置并标记为已变更"""
        if self.pos != new_pos:
            self.pos = new_pos
            self.changed = True

    def isDead(self):
        """判断当前状态是否已经死亡"""
        return not self.alive or self.lineBusy

class PigLineController:
    def __init__(self):
        self.is_test = False
        self.pig_wave = False
        self.target_group = 940409582
        self.source_groups = {940409582, 875329843, 1011106510, 827630428, 232883592}
        if self.is_test:
            self.target_group = 691859318
            self.source_groups = {691859318}
        self.backend_url = "http://127.0.0.1:5000/line"  # 后端服务地址
        self.pigs = []
        self.pattern = re.compile(r"^(\d+)\s*([A-Za-z]+|[\u4e00-\u9fff]+)$")
        # r"^([1-9]\d*)\s*([A-Za-z]+|[\u4e00-\u9fff]+)$"

        self.last_send_time = 0
        self.cooldown = 1.0  # 秒
        self.pending_send = False

        self.token = os.getenv("BOT_TOKEN")

        self.alias_map = {
            "z": "左上",
            "zuo": "左上",
            "侦察左": "左上",
            "侦察左上": "左上",
            "左": "左上",
            "左上": "左上",
            "ys": "右上",
            "原神": "右上",
            "侦察右上": "右上",
            "右上": "右上",
            "侦察右": "右",
            "you": "右",
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
            "牙": "崖之遗迹",
            "崖": "崖之遗迹",
            "遗迹": "崖之遗迹",
            "崖之": "崖之遗迹",
            "涯": "崖之遗迹",
            "崖之遗迹": "崖之遗迹",
            "k": "卡",
            "ka": "卡",
            "卡": "卡",
            "卡尼曼": "卡",
            "s": "s",
            "假": "s",
            "无": "s",
            "没有": "s",
            "死": "s",
            "b": "b",
            "爆满": "b",
            "爆": "b",
        }
    
    def hasPigs(self, line):
        """检查是否有指定线路的 PigStatus"""
        for p in self.pigs:
            if p.line == line:
                return True
        return False

    def trySendMsg(self):
        pig_change = False
        for pig in self.pigs:
            needs_update = pig.consumeUpdateFlag()
            pig_change = pig_change or needs_update
        if pig_change:
            self.sendMsg()
    
    def deleteOldPigs(self):
        """删除所有死亡的 PigStatus 并发送更新消息"""
        self.pigs = [p for p in self.pigs if not p.isDead()]
    
    def _schedule_send(self):
        now = time.time()
        if now - self.last_send_time >= self.cooldown:
            # 冷却已过，可以立刻发
            self.trySendMsg()
            self.deleteOldPigs()
            self.last_send_time = now
        else:
            # 冷却中，只标记一次待发送
            if not self.pending_send:
                self.pending_send = True
                delay = 0.1 + self.cooldown - (now - self.last_send_time)
                asyncio.create_task(self._delayed_send(delay))

    async def _delayed_send(self, delay: float):
        """冷却时间过后再补发一次"""
        await asyncio.sleep(delay)
        self.pending_send = False
        self._schedule_send()

    def receiveMsg(self, data):
        msg = data.get("raw_message", "").strip()
        self.parseMsg(msg)
        # 消息解析完毕后，尝试节流发送
        self._schedule_send()
       
    def parseMsg(self, msg: str):
        # 忽略图片 CQ 码
        msg = re.sub(r"\[CQ:image[^\]]*\]", "", msg).strip()
        # 忽略指定关键词
        ignore_words = ['一手', '1手', '金猪', "世界"]
        ignore_pattern = re.compile("|".join(map(re.escape, ignore_words)))
        msg = re.sub(ignore_pattern, "", msg).strip()
        msg = msg.strip()
        
        # 分割 token，可以拆开空格、制表符、以及'-'，保留数字+字母组合
        if self.pig_wave:
            tokens = re.split(r"[- \t]+", msg)
            if len(tokens) > 1:
                left = 0
                right = 0
                length = len(tokens)
                while right < length:
                    token = tokens[right]
                    if token.isdigit():
                        right += 1
                        continue
                    text = ''
                    if token.lower() in self.alias_map:
                        text = self.alias_map[token.lower()]
                    else:
                        match = self.pattern.match(token)
                        if match:
                            number = match.group(1)   # 数字部分
                            line = int(number)
                            text = match.group(2).lower()     # 英文或中文部分
                    if text and text in self.alias_map:
                        for t in tokens[left:right+1]:
                            if t.isdigit():
                                line = int(t)
                                if line > 0 and line <= 200:
                                    pos = self.alias_map[text]
                                    self.processLineAndPos(line, pos)
                            else:
                                self.processMsg(t)
                    left = right+1    
                    right += 1
                        
                return

        # 否则进入正常处理
        self.processMsg(msg)
        
    
    def processMsg(self, msg):
        match = self.pattern.match(msg)
        if match:
            number = match.group(1)   # 数字部分
            line = int(number)
            if line<=0 or line>200:
                return
            text = match.group(2).lower()     # 英文或中文部分
            if not text or text not in self.alias_map:
                return
            self.processLineAndPos(line, self.alias_map[text])
    
    def processLineAndPos(self, line: int, pos: str):
        pig = self.get(line)
        if pos == "s":
            if pig:
                pig.alive = False
        elif pos == "b":
            if pig:
                pig.lineBusy = True
        else:
            self.add(PigStatus(line, pos))

    def recordFirstMsg(self, data):
        # 时间戳转北京时间
        ts = data.get("time", 0)
        dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        # 消息 & 昵称
        msg = data.get("raw_message", "").strip()
        sender = data.get("sender", {})
        nickname = sender.get("nickname", "未知").replace("\n", " ").strip()

        # 日志目录 & 文件
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{date_str}.log")

        # 写入日志
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{time_str}] {nickname}: {msg}\n")
        

    def add(self, pig: PigStatus):
        """添加一个 PigStatus"""
        curr_pig = self.get(pig.line)
        if not curr_pig:
            self.pigs.append(pig)
            if not self.pig_wave:
                asyncio.create_task(self._auto_delete(pig.line, 120*len(self.pigs)))
            asyncio.create_task(self.post_to_backend(pig))
        else:
            if curr_pig.pos != pig.pos:
                curr_pig.changePos(pig.pos)
                asyncio.create_task(self.post_to_backend(pig))

    async def post_to_backend(self, pig: PigStatus):
        payload = {"line": pig.line, "pos": pig.pos}
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                await client.post(self.backend_url, json=payload)
        except Exception as e:
            pass

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
        asyncio.create_task(self.send_to_group(msg))

    async def send_to_group(self, msg: str):
        """把消息发送到 QQ 群 (使用 httpx 异步版)"""
        try:
            payload = {
                "group_id": self.target_group,
                "message": [
                    {
                        "type": "text",
                        "data": {
                            "text": msg
                        }
                    }
                ]
            }
            headers = {
                "Authorization": f"Bearer {self.token}"
            }
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "http://127.0.0.1:3000/send_group_msg",
                    json=payload,
                    headers=headers,
                    timeout=5
                )
                r.raise_for_status()
                # 可选：调试时打印返回
                # print(r.json())
        except Exception as e:
            print(f"⚠️ 发送群消息失败: {e}")

# 🔹 在全局初始化 controller
controller = PigLineController()
app = FastAPI()

@app.post("/")
async def root(request: Request):
    data = await request.json()  # 获取事件数据
    # 过滤非群聊消息
    if data.get("message_type") != "group":
        return {}
    group_id = data.get("group_id")
    # 判断是不是目标群
    if group_id in controller.source_groups:
        controller.receiveMsg(data) 
    return {}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    # 🔹 参数解析
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--pig-wave",
        action="store_true",
        help="启用猪潮模式"
    )
    args = parser.parse_args()
    pig_wave = args.pig_wave
    controller.pig_wave = pig_wave
    log(f"pig_wave: {pig_wave}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        access_log=False  # 关闭 uvicorn 的请求日志
    )
