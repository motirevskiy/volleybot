from typing import List
from telebot.types import Message
from new_bot.config import CHANNEL_ID
from new_bot.types import Training
from new_bot.utils.messages import format_participant
from new_bot.database.trainer import TrainerDB

class ForumManager:
    def __init__(self, bot):
        self.bot = bot
        self.chat_id = CHANNEL_ID  # ID группового чата

    def create_training_topic(self, training: Training, admin_username: str) -> int:
        """Создает новую тему для тренировки в форуме"""
        topic_name = (
            f"🏋️‍♂️ {training.kind} | "
            f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')} | "
            f"📍 {training.location}"
        )
        # Создаем новую тему в форуме
        result = self.bot.create_forum_topic(
            self.chat_id,
            name=topic_name,
            icon_color=0x6FB9F0  # Голубой цвет для тем
        )
        return result.message_thread_id

    def send_training_announcement(self, training: Training, admin_username: str, topic_id: int) -> None:
        """Отправляет объявление о тренировке в тему"""
        message = (
            f"🆕 Новая тренировка от @{admin_username}!\n\n"
            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🏋️‍♂️ Тип: {training.kind}\n"
            f"⏱ Длительность: {training.duration} минут\n"
            f"📍 Место: {training.location}\n"
            f"💰 Стоимость: {training.price}₽\n"
            f"👥 Максимум участников: {training.max_participants}\n"
            f"📝 Статус: {'Открыта' if training.status == 'OPEN' else 'Закрыта'}"
        )
        self.bot.send_message(
            self.chat_id,
            message,
            message_thread_id=topic_id
        )

    def update_participants_list(self, training: Training, participants: List[str], topic_id: int, trainer_db) -> None:
        """Обновляет список участников в теме"""
        message = (
            f"Список участников тренировки:\n"
            f"Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"Тип: {training.kind}\n"
            f"Место: {training.location}\n\n"
            f"Участники ({len(participants)}/{training.max_participants}):\n"
        )
        
        for i, username in enumerate(participants, 1):
            paid_status = trainer_db.get_payment_status(username, training.id)
            invite_status = trainer_db.get_invite_status(username, training.id)
            # Проверяем статус приглашения
            invite = trainer_db.fetch_one('''
                SELECT status FROM invites 
                WHERE username = ? AND training_id = ? 
                AND status = 'PENDING'
                AND invite_timestamp > datetime('now', '-1 hour')
                ORDER BY invite_timestamp DESC
                LIMIT 1
            ''', (username, training.id))
            
            # Определяем статус
            if invite:  # Если есть активное приглашение
                status = "⏳"  # Ожидается подтверждение приглашения или предложения из резерва
            elif paid_status == 2:
                status = "✅"  # Оплачено
            else:
                status = ""   # Нет пометки
            
            message += f"{i}. {status} @{username}\n"
            
        # Добавляем список резерва
        reserve_list = trainer_db.get_reserve_list(training.id)
        if reserve_list:
            message += "\n📋 Резерв:\n"
            for username, position, status in reserve_list:
                status_emoji = {
                    'WAITING': "",
                    'OFFERED': "⏳",
                    'DECLINED': ""
                }
                message += f"{position}. {status_emoji[status]} @{username}\n"
        
        # Отправляем сообщение в канал
        try:
            self.bot.send_message(
                self.chat_id,
                message,
                message_thread_id=topic_id
            )
        except Exception as e:
            print(f"Ошибка при обновлении списка участников: {e}")

    def send_training_update(self, training: Training, topic_id: int, update_type: str) -> None:
        """Отправляет уведомление об изменении тренировки"""
        if update_type == "open":
            message = "🟢 Открыта запись на тренировку!"
            # При открытии обновляем название без [ЗАКРЫТО]
            new_topic_name = (
                f"🏋️‍♂️ {training.kind} | "
                f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')} | "
                f"📍 {training.location}"
            )
            try:
                self.bot.edit_forum_topic(
                    self.chat_id,
                    topic_id,
                    name=new_topic_name
                )
            except Exception as e:
                print(f"Ошибка при обновлении названия темы: {e}")
                
        elif update_type == "close":
            message = "🔴 Запись на тренировку закрыта"
            # При закрытии добавляем [ЗАКРЫТО]
            new_topic_name = (
                f"[ЗАКРЫТО] 🏋️‍♂️ {training.kind} | "
                f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')} | "
                f"📍 {training.location}"
            )
            try:
                self.bot.edit_forum_topic(
                    self.chat_id,
                    topic_id,
                    name=new_topic_name
                )
            except Exception as e:
                print(f"Ошибка при обновлении названия темы: {e}")
                
        elif update_type == "edit":
            # При редактировании используем статус тренировки
            new_topic_name = (
                f"🏋️‍♂️ {training.kind} | "
                f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')} | "
                f"📍 {training.location}"
            )
            if training.status != 'OPEN':
                new_topic_name = f"[ЗАКРЫТО] {new_topic_name}"
                
            try:
                self.bot.edit_forum_topic(
                    self.chat_id,
                    topic_id,
                    name=new_topic_name
                )
            except Exception as e:
                print(f"Ошибка при обновлении названия темы: {e}")
            
            message = (
                f"📝 Тренировка была изменена:\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"⏱ Длительность: {training.duration} минут\n"
                f"📍 Место: {training.location}\n"
                f"👥 Максимум участников: {training.max_participants}"
            )
        
        self.bot.send_message(
            self.chat_id,
            message,
            message_thread_id=topic_id
        )

    def format_participant(self, username: str, training_id: int, trainer_db: TrainerDB) -> str:
        """Форматирует строку участника для списка"""
        paid_status = trainer_db.get_payment_status(username, training_id)
        invite_status = trainer_db.get_invite_status(username, training_id)
        # Проверяем статус приглашения
        invite = trainer_db.fetch_one('''
            SELECT status FROM invites 
            WHERE username = ? AND training_id = ? 
            AND status = 'PENDING'
            AND invite_timestamp > datetime('now', '-1 hour')
            ORDER BY invite_timestamp DESC
            LIMIT 1
        ''', (username, training_id))
        
        # Определяем статус
        if invite:  # Если есть активное приглашение
            status = "⏳"  # Ожидается подтверждение приглашения или предложения из резерва
        elif paid_status == 2:
            status = "✅"  # Оплачено
        else:
            status = ""   # Нет пометки
        
        return (
            f"{status} @{username}"
        )