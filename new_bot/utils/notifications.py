from datetime import datetime, timedelta
from typing import List
from new_bot.types import Training
from new_bot.database.admin import AdminDB

class NotificationManager:
    def __init__(self, bot):
        self.bot = bot
        self.admin_db = AdminDB()

    def send_reminder(self, training: Training, participants: List[str], hours_before: int = 24) -> None:
        """Отправляет напоминание о тренировке"""
        message = (
            f"⏰ Напоминание о тренировке через {hours_before} часов:\n"
            f"Дата: {training.date_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Тип: {training.type}\n"
            f"Место: {training.location}"
        )
        self._send_to_participants(participants, message)

    def _send_to_participants(self, participants: List[str], message: str) -> None:
        """Отправляет сообщение всем участникам"""
        for username in participants:
            user = self.admin_db.fetch_one(
                "SELECT user_id FROM users WHERE username = ?",
                (username,)
            )
            if user:
                try:
                    self.bot.send_message(user[0], message)
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {username}: {e}")