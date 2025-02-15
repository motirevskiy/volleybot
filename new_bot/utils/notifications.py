from datetime import datetime, timedelta
from typing import List, Optional
from new_bot.types import Training
from new_bot.database.admin import AdminDB

class NotificationManager:
    def __init__(self, bot):
        self.bot = bot
        self.admin_db = AdminDB()

    def notify_about_changes(
        self, 
        training: Training, 
        old_training: Training, 
        participants: List[str]
    ) -> None:
        """Уведомляет участников об изменениях в тренировке"""
        changes = []
        if training.date_time != old_training.date_time:
            changes.append(f"Время: {old_training.date_time.strftime('%Y-%m-%d %H:%M')} → {training.date_time.strftime('%Y-%m-%d %H:%M')}")
        if training.location != old_training.location:
            changes.append(f"Место: {old_training.location} → {training.location}")
        if training.kind != old_training.kind:
            changes.append(f"Тип: {old_training.kind} → {training.kind}")
        if training.duration != old_training.duration:
            changes.append(f"Длительность: {old_training.duration} → {training.duration} минут")

        if changes:
            message = "🔄 Тренировка была изменена:\n" + "\n".join(changes)
            self._send_to_participants(participants, message)

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

    def notify_about_opening(self, training: Training, admin_username: str) -> None:
        """Отправляет уведомление об открытии записи на тренировку"""
        payment_details = self.admin_db.get_payment_details(admin_username)
        message = (
            f"🟢 Открыта запись на тренировку!\n\n"
            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🏋️‍♂️ Тип: {training.type}\n"
            f"⏱ Длительность: {training.duration} минут\n"
            f"📍 Место: {training.location}\n"
            f"💰 Стоимость: {training.price}₽\n"
            f"👥 Максимум участников: {training.max_participants}\n"
            f"\n💳 Реквизиты для оплаты:\n{payment_details}"
        )
        self._send_to_participants(self.admin_db.fetch_all("SELECT username FROM users"), message)

    def send_training_notification(self, training: Training, user_id: int) -> None:
        message = (
            f"🔔 Напоминание о тренировке:\n"
            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🏋️‍♂️ Тип: {training.kind}\n"
            f"📍 Место: {training.location}"
        ) 