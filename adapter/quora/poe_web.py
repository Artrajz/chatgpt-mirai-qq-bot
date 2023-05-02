import time
from enum import Enum
from typing import Generator, Optional, Any

import asyncio
from loguru import logger

from accounts import AccountInfoBaseModel, account_manager
from poe import Client as PoeClient

from adapter.botservice import BotAdapter


class PoeCookieAuth(AccountInfoBaseModel):
    p_b: str
    """登陆 poe.com 后 Cookie 中 p_b 的值"""

    _client: Optional[PoeClient] = None

    def __init__(self, **data: Any):
        super().__init__(**data)
        self._client = PoeClient(self.p_b)

    def get_client(self) -> PoeClient:
        return self._client

    async def check_alive(self) -> bool:
        return self._client.ws_connected


class BotType(Enum):
    """Poe 支持的机器人：{'capybara': 'Sage', 'beaver': 'GPT-4', 'a2_2': 'Claude+','a2': 'Claude', 'chinchilla': 'ChatGPT',
    'nutria': 'Dragonfly'} """
    Sage = "capybara"
    GPT4 = "beaver"
    Claude2 = "a2_2"
    Claude = "a2"
    ChatGPT = "chinchilla"
    Dragonfly = "nutria"

    @staticmethod
    def parse(bot_name: str):
        tmp_name = bot_name.lower()
        return next(
            (
                bot
                for bot in BotType
                if str(bot.name).lower() == tmp_name
                   or str(bot.value).lower() == tmp_name
                   or f"poe-{str(bot.name).lower()}" == tmp_name
            ),
            None,
        )

class PoeAdapter(BotAdapter):

    account: PoeCookieAuth

    def __init__(self, session_id: str = "unknown", bot_type: BotType = None):
        """获取内部队列"""
        super().__init__(session_id)
        self.session_id = session_id
        self.bot_name = bot_type.value
        self.account = account_manager.pick("poe-token")
        self.client = self.account.get_client()
        self.custom_bot = False
        if self.bot_name in [BotType.ChatGPT, BotType.Claude]:
            # Create new bot or use default one?
            self.custom_bot = {
                "handle": self.bot_name,
                "base_model": bot_type.value,
                "prompt": r"You're a helpful assistant.",
                "prompt_public": False,
                "description": f"ChatGPT for Bot: session_id={session_id}, base_model={bot_type.value}",
                "suggested_replies": False,
                "private": False
            }
            self.client.create_bot(**self.custom_bot)

    async def ask(self, msg: str) -> Generator[str, None, None]:
        """向 AI 发送消息"""
        # 覆盖 PoeClient 内部的锁逻辑
        while None in self.client.active_messages.values():
            await asyncio.sleep(0.01)
        for final_resp in self.client.send_message(chatbot=self.bot_name.value, message=msg):
            yield final_resp["text"]

    async def rollback(self):
        """回滚对话"""
        self.client.purge_conversation(self.bot_name.value, 2)

    async def on_destoryed(self):
        """当会话被重置时，此函数被调用"""
        self.client.send_chat_break(self.bot_name.value)
        if self.custom_bot:
            # TODO: delete the bot
            pass

    async def preset_ask(self, role: str, text: str):
        if role.endswith('bot') or role in {'assistant', 'poe'}:
            logger.debug(f"[预设] 响应：{text}")
            yield text
        else:
            if role == 'system' and self.custom_bot:
                self.custom_bot['prompt'] = text
                self.client.edit_bot(**self.custom_bot)
                return
            logger.debug(f"[预设] 发送：{text}")
            item = None
            async for item in self.ask(text): ...
            if item:
                logger.debug(f"[预设] Chatbot 回应：{item}")

