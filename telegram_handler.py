import telegram
import asyncio
import logging
from telegram.error import TelegramError
from config import TELEGRAM_API_URL

class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.logger = logging.getLogger(__name__)
        
        try:
            self.bot = telegram.Bot(token=self.token)
            # Verify bot token
            asyncio.get_event_loop().run_until_complete(self.bot.get_me())
        except TelegramError as e:
            self.logger.error(f"Telegram bot initialization failed: {e}")
            raise ValueError("Invalid Telegram bot token")
            
    async def send_message_async(self, message):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
            return True
        except TelegramError as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False
            
    def send_message(self, message):
        """Send message through Telegram bot"""
        return asyncio.get_event_loop().run_until_complete(
            self.send_message_async(message)
        )
        
    def send_price_alert(self, product_data, threshold_price):
        """Send formatted price alert message"""
        message = (
            f"🔔 <b>Price Alert!</b>\n\n"
            f"Product: {product_data['title']}\n"
            f"Current Price: ₹{product_data['price']}\n"
            f"Threshold Price: ₹{threshold_price}\n"
            f"Time: {product_data['timestamp']}\n\n"
            f"🔗 <a href='{product_data['url']}'>View Product</a>"
        )
        return self.send_message(message)
