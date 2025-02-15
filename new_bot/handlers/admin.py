import uuid
import os
from typing import List, Optional, Dict
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from new_bot.config import SUPERADMIN_USERNAME
from new_bot.database.admin import AdminDB
from new_bot.database.trainer import TrainerDB
from new_bot.database.channel import ChannelDB
from new_bot.utils.keyboards import (
    get_trainings_keyboard,
    get_admin_list_keyboard,
    get_confirm_keyboard
)
from new_bot.types import Training, TrainingData, HandlerType, BotType
from new_bot.utils.validators import (
    validate_datetime,
    validate_duration,
    validate_kind,
    validate_location,
    ValidationError
)
from datetime import datetime, timedelta
from new_bot.utils.forum_manager import ForumManager
from new_bot.utils.training import find_training_admin

# Словарь для хранения данных при создании тренировки
training_creation_data: Dict[int, TrainingData] = {}

admin_db = AdminDB()
channel_db = ChannelDB()
ADMIN_KEY = ""
admin_selection = {}

def register_admin_handlers(bot: BotType) -> None:
    # Создаем экземпляр ForumManager
    forum_manager = ForumManager(bot)
    
    @bot.message_handler(commands=["admin"])
    def admin_menu(message: Message):
        """Показывает меню администратора"""
        username = message.from_user.username
        
        # Проверяем, является ли пользователь администратором хотя бы одной группы
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.reply_to(message, "❌ У вас нет прав администратора")
            return
        
        show_admin_menu(message)
    
    @bot.callback_query_handler(func=lambda call: call.data == "get_admin")
    def request_admin_key(call: CallbackQuery):
        username = call.from_user.username
        if admin_db.get_admin_channel(username):
            bot.send_message(call.message.chat.id, "Вы уже являетесь администратором группы!")
            return

        # Получаем список доступных групп
        groups = channel_db.get_all_channels()
        if not groups:
            bot.send_message(
                call.message.chat.id,
                "Нет доступных групп. Сначала добавьте бота в группу и выполните команду /init"
            )
            return

        # Создаем клавиатуру с группами
        markup = InlineKeyboardMarkup()
        for group_id, title in groups:
            markup.add(InlineKeyboardButton(
                title,
                callback_data=f"select_group_{group_id}"
            ))

        bot.send_message(
            call.message.chat.id,
            "Выберите группу для получения прав администратора:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("select_group_"))
    def group_selected(call: CallbackQuery):
        group_id = int(call.data.split("_")[2])
        username = call.from_user.username

        # Проверяем, является ли пользователь администратором группы
        try:
            chat_member = bot.get_chat_member(group_id, call.from_user.id)
            if chat_member.status not in ['creator', 'administrator']:
                bot.answer_callback_query(
                    call.id,
                    "❌ Вы должны быть администратором группы",
                    show_alert=True
                )
                return
        except Exception as e:
            print(f"Error checking admin rights: {e}")
            bot.answer_callback_query(
                call.id,
                "❌ Ошибка проверки прав администратора",
                show_alert=True
            )
            return

        if not ADMIN_KEY:
            bot.send_message(call.message.chat.id, "Сейчас нет активных ключей. Запросите у супер-админа.")
            return

        # Сохраняем выбранную группу во временное хранилище
        admin_selection[username] = group_id

        msg = bot.send_message(call.message.chat.id, "Введите ключ администратора:")
        bot.register_next_step_handler(msg, process_admin_key)

    def process_admin_key(message: Message):
        username = message.from_user.username
        if username not in admin_selection:  # admin_selection содержит выбранный channel_id
            bot.reply_to(message, "❌ Сначала выберите группу")
            return

        channel_id = admin_selection[username]
        global ADMIN_KEY

        if message.text == str(ADMIN_KEY):
            # Добавляем админа в таблицу users
            admin_db.execute_query(
                "INSERT OR IGNORE INTO users (username, user_id) VALUES (?, ?)",
                (username, message.from_user.id)
            )
            # Добавляем админа для конкретного канала
            admin_db.add_admin(username, channel_id)  # Теперь передаем channel_id
            TrainerDB(username)
            bot.send_message(message.chat.id, "Поздравляю, теперь вы администратор группы!")
            ADMIN_KEY = ""
            del admin_selection[username]  # Очищаем временное хранилище
        else:
            bot.send_message(message.chat.id, "Неверный ключ!")

    @bot.message_handler(commands=["generate_admin_key"])
    def generate_admin_key(message: Message):
        if message.from_user.username != SUPERADMIN_USERNAME:
            bot.send_message(message.chat.id, "Доступ запрещён.")
            return
        global ADMIN_KEY
        ADMIN_KEY = uuid.uuid4()
        bot.send_message(message.chat.id, f"Ключ администратора: {ADMIN_KEY}")

    @bot.message_handler(commands=["remove_admin"])
    def remove_admin_request(message: Message):
        """Запрашивает список администраторов для удаления"""
        if message.from_user.username != SUPERADMIN_USERNAME:
            return
            
        # Получаем список всех групп и их администраторов
        groups = channel_db.get_all_channels()
        if not groups:
            bot.send_message(message.chat.id, "Нет инициализированных групп")
            return
            
        markup = InlineKeyboardMarkup()
        for group_id, title in groups:
            admins = admin_db.get_channel_admins(group_id)
            if admins:
                # Добавляем заголовок группы
                markup.add(InlineKeyboardButton(f"📢 {title}", callback_data="group_header"))
                # Добавляем администраторов группы
                for admin in admins:
                    markup.add(InlineKeyboardButton(
                        f"❌ Удалить @{admin}",
                        callback_data=f"remadm_{admin}_{group_id}"
                    ))
                markup.add(InlineKeyboardButton("➖➖➖➖➖", callback_data="separator"))
        
        if not markup.keyboard:
            bot.send_message(message.chat.id, "Нет администраторов для удаления")
            return
            
        bot.send_message(
            message.chat.id,
            "Выберите администратора для удаления:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("remadm_"))
    def remove_admin(call: CallbackQuery):
        """Удаляет администратора из группы"""
        parts = call.data.split("_")
        admin_username = parts[1]
        group_id = int(parts[2])
        
        # Получаем информацию о группе
        group = channel_db.get_channel(group_id)
        if not group:
            bot.answer_callback_query(call.id, "Группа не найдена")
            return
        
        # Удаляем администратора
        admin_db.remove_admin(admin_username, group_id)
        bot.send_message(
            call.message.chat.id,
            f"✅ Администратор @{admin_username} удалён из группы {group[1]}"
        )
        
        # Обновляем сообщение со списком администраторов
        remove_admin_request(call.message)

    @bot.message_handler(commands=["clear_database"])
    def clear_database_request(message: Message):
        if message.from_user.username != SUPERADMIN_USERNAME:
            return
        
        markup = get_confirm_keyboard()
        bot.send_message(message.chat.id, "Очистить базу данных?", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "confirm_clear")
    def confirm_clear_database(call: CallbackQuery):
        admin_db.execute_query("DELETE FROM admins")
        
        # Путь к директории с базами данных
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        
        # Удаляем все файлы баз данных тренировок
        for file in os.listdir(data_dir):
            if file.endswith("_trainings.db"):
                os.remove(os.path.join(data_dir, file))
                
        bot.send_message(call.message.chat.id, "База данных администраторов и все базы данных тренировок удалены.")

    @bot.callback_query_handler(func=lambda call: call.data == "cancel")
    def cancel_action(call: CallbackQuery):
        bot.send_message(call.message.chat.id, "Действие отменено.")

    # Обработчики для работы с тренировками
    @bot.callback_query_handler(func=lambda call: call.data == "create_training")
    def create_training(call: CallbackQuery) -> None:
        """Начинает процесс создания тренировки"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        # Сохраняем channel_id в данных создания тренировки
        training_creation_data[call.from_user.id] = TrainingData(channel_id=channel_id)
        
        msg = bot.send_message(call.message.chat.id, "Введите данные тренировки!")
        edit_or_create_training(msg, "create", None)

    def edit_or_create_training(message: Message, action: str, training_id: Optional[int] = None) -> None:
        msg = bot.send_message(
            message.chat.id,
            "Введите дату и время тренировки (формат: 'YYYY-MM-DD HH:MM')"
        )
        bot.register_next_step_handler(msg, get_training_details, action, training_id)

    def get_training_details(message: Message, action: str, training_id: Optional[int]) -> None:
        user_id = message.from_user.id
        if user_id not in training_creation_data:
            training_creation_data[user_id] = TrainingData()
        
        try:
            validate_datetime(message.text)
            training_creation_data[user_id].date_time = message.text
            msg = bot.send_message(message.chat.id, "Введите максимальное количество участников:")
            bot.register_next_step_handler(msg, get_max_participants, action, training_id)
        except ValidationError as e:
            bot.send_message(message.chat.id, f"Ошибка: {str(e)}")
            edit_or_create_training(message, action, training_id)

    def get_max_participants(message: Message, action: str, training_id: Optional[int]) -> None:
        user_id = message.from_user.id
        try:
            max_participants = int(message.text.strip())
            if max_participants <= 0:
                raise ValueError("Количество участников должно быть положительным числом")
            if max_participants > 50:  # Максимальное ограничение
                raise ValueError("Слишком много участников (максимум 50)")
                
            training_creation_data[user_id].max_participants = max_participants
            msg = bot.send_message(message.chat.id, "Введите длительность тренировки (в минутах):")
            bot.register_next_step_handler(msg, get_training_duration, action, training_id)
        except ValueError as e:
            bot.send_message(message.chat.id, f"Ошибка: {str(e)}")
            msg = bot.send_message(message.chat.id, "Введите максимальное количество участников:")
            bot.register_next_step_handler(msg, get_max_participants, action, training_id)

    def get_training_price(message: Message, action: str, training_id: Optional[int]) -> None:
        """Обрабатывает ввод цены тренировки и передает данные в save_training_data"""
        user_id = message.from_user.id
        try:
            price = int(message.text.strip())
            training_creation_data[user_id].price = price
            
            # Проверяем все данные и сохраняем тренировку
            save_training_data(message, action, training_id)
            
        except ValueError:
            bot.send_message(message.chat.id, "Ошибка: введите число")
            msg = bot.send_message(message.chat.id, "Введите стоимость тренировки (в рублях):")
            bot.register_next_step_handler(msg, get_training_price, action, training_id)

    def save_training_data(message: Message, action: str, training_id: Optional[int]) -> None:
        """Сохраняет или обновляет данные тренировки"""
        user_id = message.from_user.id
        training_data = training_creation_data[user_id]
        
        try:
            trainer_db = TrainerDB(message.from_user.username)
            
            if action == "edit" and training_id:
                success = update_existing_training(trainer_db, training_id, training_data, message)
            else:
                # Создаем новую тренировку с channel_id
                training_id = trainer_db.add_training(
                    channel_id=training_data.channel_id,
                    date_time=training_data.date_time,
                    duration=training_data.duration,
                    kind=training_data.kind,
                    location=training_data.location,
                    max_participants=training_data.max_participants,
                    status="CLOSED",
                    price=training_data.price
                )
                
                if training_id:
                    # Получаем созданную тренировку
                    training = trainer_db.get_training_details(training_id)
                    if training:
                        # Создаем тему в форуме
                        topic_id = forum_manager.create_training_topic(training, message.from_user.username)
                        if topic_id:
                            trainer_db.set_topic_id(training_id, topic_id)
                            # Отправляем объявление в тему
                            forum_manager.send_training_announcement(
                                training, 
                                message.from_user.username,
                                topic_id
                            )
                    
                    bot.send_message(message.chat.id, "✅ Тренировка успешно создана!")
                    success = True
                else:
                    success = False
            
            if success:
                del training_creation_data[user_id]
                show_admin_menu(message)
            
        except Exception as e:
            print(f"Error in save_training_data: {e}")
            bot.reply_to(message, "❌ Произошла ошибка при сохранении тренировки")

    def update_existing_training(trainer_db: TrainerDB, training_id: int, 
                               training_data: TrainingData, message: Message) -> bool:
        """Обновляет существующую тренировку"""
        try:
            # Получаем текущий статус и данные тренировки перед обновлением
            current_training = trainer_db.get_training_details(training_id)
            if not current_training:
                return False
            
            # Получаем информацию о группе
            group = channel_db.get_channel(current_training.channel_id)
            if not group:
                bot.reply_to(message, "❌ Ошибка: группа не найдена")
                return False
            
            current_status = current_training.status
            old_max_participants = current_training.max_participants
            new_max_participants = training_data.max_participants
            
            # Получаем текущих участников
            current_participants = trainer_db.get_participants_by_training_id(training_id)
            current_reserve = trainer_db.get_reserve_list(training_id)
            
            # Обновляем тренировку
            trainer_db.update_training(
                training_id,
                training_data.date_time,
                training_data.duration,
                training_data.kind,
                training_data.location,
                training_data.max_participants,
                training_data.price,
                current_status
            )
            
            # Если количество мест уменьшилось
            if new_max_participants < old_max_participants:
                # Определяем, сколько человек нужно переместить в резерв
                overflow = len(current_participants) - new_max_participants
                if overflow > 0:
                    # Перемещаем последних участников в резерв
                    participants_to_reserve = current_participants[-overflow:]
                    for username in participants_to_reserve:
                        trainer_db.remove_participant(username, training_id)
                        position = trainer_db.add_to_reserve(username, training_id)
                        
                        # Отправляем уведомление
                        if user_id := admin_db.get_user_id(username):
                            notification = (
                                "⚠️ Вы перемещены в резерв из-за уменьшения количества мест:\n\n"
                                f"👥 Группа: {group[1]}\n"
                                f"📅 Дата: {current_training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                f"🏋️‍♂️ Тип: {current_training.kind}\n"
                                f"📍 Место: {current_training.location}\n"
                                f"📋 Ваша позиция в резерве: {position}"
                            )
                            try:
                                bot.send_message(user_id, notification)
                            except Exception as e:
                                print(f"Error notifying user {username}: {e}")
            
            # Обновляем тему в форуме
            topic_id = trainer_db.get_topic_id(training_id)
            if topic_id:
                training = trainer_db.get_training_details(training_id)
                forum_manager.send_training_update(training, topic_id, "edit")
                # Обновляем список участников
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
            
            # Отправляем уведомление всем участникам
            notification = (
                "📝 Тренировка была изменена:\n\n"
                f"👥 Группа: {group[1]}\n"
                f"📅 Дата: {training_data.date_time}\n"
                f"🏋️‍♂️ Тип: {training_data.kind}\n"
                f"⏱ Длительность: {training_data.duration} минут\n"
                f"📍 Место: {training_data.location}\n"
                f"💰 Стоимость: {training_data.price}₽\n"
                f"👥 Максимум участников: {training_data.max_participants}"
            )
            
            for username in current_participants:
                if user_id := admin_db.get_user_id(username):
                    try:
                        bot.send_message(user_id, notification)
                    except Exception as e:
                        print(f"Error notifying user {username}: {e}")
            
            bot.reply_to(message, "✅ Тренировка успешно обновлена!")
            return True
        
        except Exception as e:
            print(f"Error in update_existing_training: {e}")
            bot.reply_to(message, "❌ Произошла ошибка при обновлении тренировки")
            return False

    # def create_new_training(trainer_db: TrainerDB, training_data: TrainingData, message: Message) -> bool:
    #     """Создает новую тренировку"""
    #     try:
    #         new_training_id = trainer_db.add_training(
    #             training_data.date_time,
    #             training_data.duration,
    #             training_data.kind,
    #             training_data.location,
    #             training_data.max_participants,
    #             "CLOSED",  # Меняем статус на CLOSED при создании
    #             training_data.price
    #         )
            
    #         if new_training_id:
    #             # Получаем созданную тренировку
    #             training = trainer_db.get_training_details(new_training_id)
    #             if training:
    #                 # Создаем тему в форуме
    #                 topic_id = forum_manager.create_training_topic(training, message.from_user.username)
    #                 if topic_id:
    #                     trainer_db.set_topic_id(new_training_id, topic_id)
    #                     # Отправляем объявление в тему
    #                     forum_manager.send_training_announcement(
    #                         training, 
    #                         message.from_user.username,
    #                         topic_id
    #                     )
                        
    #             bot.reply_to(message, "✅ Тренировка успешно создана!")
    #             return True
    #         return False
    #     except Exception as e:
    #         print(f"Error in create_new_training: {e}")
    #         return False

    def notify_about_training_update(trainer_db: TrainerDB, training: Training, 
                                   training_id: int, message: Message) -> None:
        """Отправляет уведомления об изменении тренировки"""
        # Обновляем тему в форуме
        topic_id = trainer_db.get_topic_id(training_id)
        if topic_id:
            forum_manager.send_training_update(training, topic_id, "edit")
        
        # Отправляем уведомления участникам
        participants = trainer_db.get_participants_by_training_id(training_id)
        notification_message = create_update_notification(training)
        
        for username in participants:
            user_id = admin_db.get_user_id(username)
            if user_id and user_id != message.from_user.id:
                try:
                    bot.send_message(user_id, notification_message)
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {username}: {e}")

    def create_update_notification(training: Training) -> str:
        """Создает текст уведомления об изменении тренировки"""
        return (
            "🔄 Тренировка была изменена:\n\n"
            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🏋️‍♂️ Тип: {training.kind}\n"
            f"⏱ Длительность: {training.duration} минут\n"
            f"📍 Место: {training.location}\n"
            f"💰 Стоимость: {training.price}₽"
        )

    @bot.callback_query_handler(func=lambda call: call.data == "edit_training")
    def show_trainings_for_edit(call: CallbackQuery):
        """Показывает список тренировок для редактирования"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        trainer_db = TrainerDB(username)
        # Получаем список тренировок для данной группы
        trainings = trainer_db.get_trainings_for_channel(channel_id)
        
        if not trainings:
            bot.send_message(call.message.chat.id, "У вас нет тренировок для редактирования")
            return
        
        markup = get_trainings_keyboard(trainings, "edit")
        
        bot.send_message(
            call.message.chat.id,
            "Выберите тренировку для редактирования:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_"))
    def start_edit_training(call: CallbackQuery):
        """Начинает процесс изменения выбранной тренировки"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        training_id = int(call.data.split("_")[1])
        trainer_db = TrainerDB(call.from_user.username)
        training = trainer_db.get_training_details(training_id)
        
        if not training:
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
            
        msg = bot.send_message(call.message.chat.id, "Введите новые данные тренировки")
        edit_or_create_training(msg, "edit", training_id)

    @bot.callback_query_handler(func=lambda call: call.data == "delete_training")
    def show_trainings_for_delete(call: CallbackQuery):
        """Показывает список тренировок для удаления"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        trainer_db = TrainerDB(call.from_user.username)
        # Получаем список тренировок для данной группы
        trainings = trainer_db.get_trainings_for_channel(channel_id)
        
        if not trainings:
            bot.send_message(call.message.chat.id, "У вас нет тренировок для удаления")
            return
        
        markup = get_trainings_keyboard(trainings, "delete")
        
        bot.send_message(
            call.message.chat.id,
            "⚠️ Выберите тренировку для удаления:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
    def apply_remove(call: CallbackQuery):
        """Обработчик удаления тренировки"""
        try:
            training_id = int(call.data.split("_")[1])
            trainer_db = TrainerDB(call.from_user.username)
            
            # Получаем информацию о тренировке и топике до удаления
            training = trainer_db.get_training_details(training_id)
            topic_id = trainer_db.get_topic_id(training_id)
            
            if not training:
                bot.answer_callback_query(call.id, "Тренировка не найдена")
                return
            
            # Получаем информацию о группе
            group = channel_db.get_channel(training.channel_id)
            if not group:
                bot.answer_callback_query(call.id, "Группа не найдена")
                return
            
            # Получаем список участников перед удалением
            participants = trainer_db.get_participants_by_training_id(training_id)
            
            # Сначала пробуем удалить тему в форуме
            if topic_id:
                try:
                    print(f"Attempting to delete forum topic {topic_id} in channel {training.channel_id}")
                    try:
                        # Пробуем удалить тему
                        print("Attempting to delete topic...")
                        result = bot.delete_forum_topic(training.channel_id, topic_id)
                        print(f"Delete topic result: {result}")
                    except Exception as e:
                        print(f"Error deleting topic: {e}")
                        # Если не удалось удалить, пробуем закрыть
                        try:
                            print("Attempting to close topic instead...")
                            bot.edit_forum_topic(
                                training.channel_id,
                                topic_id,
                                name=f"[УДАЛЕНО] {training.kind}"
                            )
                            bot.close_forum_topic(training.channel_id, topic_id)
                            print("Topic closed successfully")
                        except Exception as close_error:
                            print(f"Error closing topic: {close_error}")
                except Exception as e:
                    print(f"Error handling forum topic: {e}")
            
            # Затем удаляем тренировку из базы данных
            print("Deleting training from database...")
            if trainer_db.delete_training(training_id):
                # Отправляем уведомления участникам
                notification = (
                    "❌ Тренировка отменена:\n\n"
                    f"👥 Группа: {group[1]}\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ Тип: {training.kind}\n"
                    f"📍 Место: {training.location}"
                )
                
                for username in participants:
                    if user_id := admin_db.get_user_id(username):
                        try:
                            bot.send_message(user_id, notification)
                        except Exception as e:
                            print(f"Error notifying user {username}: {e}")

                for username, _, _ in trainer_db.get_reserve_list(training_id):
                    if user_id := admin_db.get_user_id(username):
                        try:
                            bot.send_message(user_id, notification)
                        except Exception as e:
                            print(f"Error notifying user {username}: {e}")
                
                bot.answer_callback_query(call.id, "✅ Тренировка успешно удалена")
                bot.delete_message(call.message.chat.id, call.message.message_id)
            else:
                print("Error deleting training from database")
                bot.answer_callback_query(call.id, "❌ Ошибка удаления тренировки")
            
        except Exception as e:
            print(f"Error in apply_remove: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка при удалении тренировки")

    @bot.callback_query_handler(func=lambda call: call.data == "open_training_sign_up")
    def show_trainings_for_opening(call: CallbackQuery):
        """Показывает список закрытых тренировок для открытия записи"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        trainer_db = TrainerDB(username)
        # Получаем список закрытых тренировок для данной группы
        trainings = trainer_db.get_trainings_for_channel(channel_id)
        closed_trainings = [t for t in trainings if t.status != "OPEN"]
        
        if not closed_trainings:
            bot.send_message(call.message.chat.id, "Нет тренировок с закрытой записью")
            return
        
        markup = get_trainings_keyboard(closed_trainings, "open_sign_up")
        
        bot.send_message(
            call.message.chat.id,
            "Выберите тренировку для открытия записи:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("open_sign_up_"))
    def open_training(call: CallbackQuery):
        """Обработчик открытия записи на тренировку"""
        try:
            training_id = int(call.data.split("_")[-1])
            username = call.from_user.username
            trainer_db = TrainerDB(username)
            
            # Получаем информацию о тренировке
            training = trainer_db.get_training_details(training_id)
            if not training:
                bot.answer_callback_query(call.id, "Тренировка не найдена")
                return
            
            # Получаем информацию о группе
            group = channel_db.get_channel(training.channel_id)
            if not group:
                bot.answer_callback_query(call.id, "Группа не найдена")
                return
            
            # Обрабатываем автозаписи
            process_auto_signups(trainer_db, training)
            
            # Открываем запись
            trainer_db.set_training_open(training_id)
            
            # Отправляем уведомление в форум
            topic_id = trainer_db.get_topic_id(training_id)
            if topic_id:
                forum_manager.send_training_update(training, topic_id, "open")
                # Обновляем список участников
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
            
            # Получаем реквизиты для оплаты
            payment_details = admin_db.get_payment_details(username)
            
            # Отправляем уведомления всем пользователям
            users = admin_db.get_all_users()
            notification = (
                f"🟢 Открыта запись на тренировку!\n\n"
                f"👥 Группа: {group[1]}\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"⏱ Длительность: {training.duration} минут\n"
                f"📍 Место: {training.location}\n"
                f"💰 Стоимость: {training.price}₽\n"
                f"👥 Максимум участников: {training.max_participants}\n"
                f"\n💳 Реквизиты для оплаты:\n{payment_details}"
            )
            
            # Создаем кнопку записи с правильным форматом callback_data
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(
                "Записаться",
                callback_data=f"signup_training_{username}_{training_id}"  # Обновленный формат
            ))
            
            # Отправляем уведомления всем пользователям, кроме тех, кто уже записан через автозапись
            auto_signup_users = trainer_db.get_auto_signup_requests(training_id)
            print(auto_signup_users)
            for user in users:                
                user_info = admin_db.get_user_info(user[0])
                try:
                    if user_info and user_info.username not in auto_signup_users and not user_info.is_admin:
                        bot.send_message(user[0], notification, reply_markup=markup)
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {user[1]}: {e}")

                if user_info.username in auto_signup_users:
                    trainer_db.remove_auto_signup_request(user_info.username, training.id)
            
            bot.send_message(call.from_user.id, "✅ Запись открыта")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            
        except Exception as e:
            print(f"Error in open_training: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка при открытии записи")

    @bot.message_handler(commands=["stats"])
    def show_statistics(message: Message):
        username = message.from_user.username
        if not username:
            bot.send_message(message.chat.id, "Не удалось определить ваш username")
            return
            
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.reply_to(message, "❌ У вас нет прав администратора")
            return
    
        # Получаем информацию о группе
        group = channel_db.get_channel(channel_id)
        if not group:
            bot.reply_to(message, "❌ Группа не найдена")
            return
    
        trainer_db = TrainerDB(username)
        
        # Получаем статистику тренировок для данной группы
        trainings = trainer_db.get_trainings_for_channel(channel_id)
        
        total_stats = {
            'total_trainings': len(trainings),
            'total_participants': 0,
            'active_trainings': 0,
            'participants_by_training': {}
        }
        
        # Подсчитываем статистику по тренировкам
        for training in trainings:
            participants = trainer_db.get_participants_by_training_id(training.id)
            total_stats['participants_by_training'][training.id] = len(participants)
            total_stats['total_participants'] += len(participants)
            if training.status == 'OPEN':
                total_stats['active_trainings'] += 1
        
        stats_message = (
            f"📊 Статистика группы {group[1]}:\n\n"
            f"Всего создано тренировок: {total_stats['total_trainings']}\n"
            f"Активных тренировок: {total_stats['active_trainings']}\n"
            f"Всего участников на тренировках: {total_stats['total_participants']}\n\n"
            "Последние тренировки:\n"
        )
        
        # Получаем последние 5 тренировок
        recent_trainings = sorted(trainings, key=lambda t: t.date_time, reverse=True)[:5]
        
        for training in recent_trainings:
            participants_count = total_stats['participants_by_training'].get(training.id, 0)
            stats_message += (
                f"\n📅 {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ {training.kind}\n"
                f"👥 Участников: {participants_count}/{training.max_participants}\n"
                f"📝 Статус: {'Открыта' if training.status == 'OPEN' else 'Закрыта'}\n"
                "➖➖➖➖➖➖➖➖➖➖"
            )
        
        bot.send_message(message.chat.id, stats_message)

    # Обновляем обработчик записи на тренировку
    @bot.callback_query_handler(func=lambda call: call.data.startswith("signup_training_"))
    def process_training_signup(call: CallbackQuery):
        """Обрабатывает запись на тренировку"""
        parts = call.data.split("_")
        admin_username = parts[2]
        training_id = int(parts[3])
        username = call.from_user.username
        
        # Убедимся, что пользователь добавлен в таблицу users
        admin_db.execute_query(
            "INSERT OR IGNORE INTO users (username, user_id) VALUES (?, ?)",
            (username, call.from_user.id)
        )
        
        trainer_db = TrainerDB(admin_username)

        if trainer_db.get_training_details(training_id).status == "CLOSED":
            bot.send_message(call.message.chat.id, "❌ Эта тренировка не доступна для записи")
            return

        if trainer_db.add_participant(username, training_id):
            bot.send_message(call.message.chat.id, "✅ Вы успешно записались на тренировку!")
            
            # Обновляем список участников в теме
            if topic_id := trainer_db.get_topic_id(training_id):
                training = trainer_db.get_training_details(training_id)
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
        else:
            # Проверяем, записан ли уже пользователь
            existing = trainer_db.fetch_one('''
                SELECT 1 FROM participants 
                WHERE username = ? AND training_id = ?
            ''', (username, training_id))
            
            if existing:
                message = "❌ Вы уже записаны на эту тренировку!"
            else:
                # Добавляем в резерв
                position = trainer_db.add_to_reserve(username, training_id)
                message = f"ℹ️ Вы добавлены в резерв на позицию {position}"
                
                # Обновляем список в теме
                if topic_id := trainer_db.get_topic_id(training_id):
                    training = trainer_db.get_training_details(training_id)
                    participants = trainer_db.get_participants_by_training_id(training_id)
                    forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
                
            bot.send_message(call.message.chat.id, message)
        
        # Удаляем сообщение с кнопкой
        bot.delete_message(call.message.chat.id, call.message.message_id)

    def offer_spot_to_reserve(training_id: int, admin_username: str):
        """Предлагает место следующему в резерве"""
        trainer_db = TrainerDB(admin_username)
        
        # Получаем следующего в резерве
        if next_user := trainer_db.offer_spot_to_next_in_reserve(training_id):
            training = trainer_db.get_training_details(training_id)
            
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("Принять", callback_data=f"accept_reserve_{training_id}"),
                InlineKeyboardButton("Отказаться", callback_data=f"decline_reserve_{training_id}")
            )
            
            message = (
                "🎉 Освободилось место на тренировке!\n\n"
                f"Вы первый в списке резерва и можете занять освободившееся место.\n\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"📍 Место: {training.location}\n\n"
                "⏰ У вас есть 2 часа, чтобы принять или отказаться от места"
            )
            
            # Получаем user_id пользователя из резерва
            user = admin_db.fetch_one(
                "SELECT user_id FROM users WHERE username = ?",
                (next_user,)
            )
            
            if user:
                try:
                    bot.send_message(user[0], message, reply_markup=markup)
                except Exception as e:
                    print(f"Ошибка отправки предложения пользователю @{next_user}: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith(("accept_reserve_", "decline_reserve_")) and "invite" not in call.data)
    def handle_reserve_response(call: CallbackQuery):
        parts = call.data.split("_")
        action = parts[0]  # "accept" или "decline"
        training_id = int(parts[2])
        username = call.from_user.username
        
        admin_username = find_training_admin(training_id)
        if not admin_username:
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
        
        trainer_db = TrainerDB(admin_username)
        
        if action == "accept":
            if trainer_db.accept_reserve_spot(username, training_id):
                bot.send_message(call.message.chat.id, "✅ Вы успешно записаны на тренировку!")
                
                # Обновляем список в форуме
                if topic_id := trainer_db.get_topic_id(training_id):
                    training = trainer_db.get_training_details(training_id)
                    participants = trainer_db.get_participants_by_training_id(training_id)
                    forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
            else:
                bot.send_message(call.message.chat.id, "❌ Не удалось записаться на тренировку")
        else:
            # Удаляем из списка участников и резерва
            trainer_db.remove_participant(username, training_id)
            trainer_db.remove_from_reserve(username, training_id)
            bot.send_message(call.message.chat.id, "Вы отказались от места в тренировке")
            
            # Предлагаем место следующему
            offer_spot_to_reserve(training_id, admin_username)
            
            # Обновляем список в форуме
            if topic_id := trainer_db.get_topic_id(training_id):
                training = trainer_db.get_training_details(training_id)
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
        bot.delete_message(call.message.chat.id, call.message.message_id)

    def get_training_duration(message: Message, action: str, training_id: Optional[int]) -> None:
        user_id = message.from_user.id
        try:
            duration = validate_duration(message.text)
            training_creation_data[user_id].duration = duration
            msg = bot.send_message(message.chat.id, "Введите тип тренировки:")
            bot.register_next_step_handler(msg, get_training_type, action, training_id)
        except ValidationError as e:
            bot.send_message(message.chat.id, f"Ошибка: {str(e)}")
            msg = bot.send_message(message.chat.id, "Введите длительность тренировки (в минутах):")
            bot.register_next_step_handler(msg, get_training_duration, action, training_id)

    def get_training_type(message: Message, action: str, training_id: Optional[int]) -> None:
        user_id = message.from_user.id
        try:
            training_kind = validate_kind(message.text)
            training_creation_data[user_id].kind = training_kind
            msg = bot.send_message(message.chat.id, "Введите место тренировки:")
            bot.register_next_step_handler(msg, get_training_location, action, training_id)
        except ValidationError as e:
            bot.send_message(message.chat.id, f"Ошибка: {str(e)}")
            msg = bot.send_message(message.chat.id, "Введите тип тренировки:")
            bot.register_next_step_handler(msg, get_training_type, action, training_id)

    def get_training_location(message: Message, action: str, training_id: Optional[int]) -> None:
        user_id = message.from_user.id
        try:
            location = validate_location(message.text)
            training_creation_data[user_id].location = location
            msg = bot.send_message(message.chat.id, "Введите стоимость тренировки (в рублях):")
            bot.register_next_step_handler(msg, get_training_price, action, training_id)
        except ValidationError as e:
            bot.send_message(message.chat.id, f"Ошибка: {str(e)}")
            msg = bot.send_message(message.chat.id, "Введите место тренировки:")
            bot.register_next_step_handler(msg, get_training_location, action, training_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_payment_"))
    def confirm_payment(call: CallbackQuery):
        """Подтверждает оплату тренировки"""
        try:
            parts = call.data.split("_")
            training_id = int(parts[2])
            username = parts[3]
            
            trainer_db = TrainerDB(call.from_user.username)
            
            # Получаем информацию о тренировке
            training = trainer_db.get_training_details(training_id)
            if not training:
                bot.answer_callback_query(call.id, "Тренировка не найдена")
                return
            
            # Получаем информацию о группе
            group = channel_db.get_channel(training.channel_id)
            if not group:
                bot.answer_callback_query(call.id, "Группа не найдена")
                return
            
            # Подтверждаем оплату
            if trainer_db.confirm_payment(username, training_id):
                # Отправляем уведомление пользователю
                if user_id := admin_db.get_user_id(username):
                    notification = (
                        "✅ Оплата подтверждена!\n\n"
                        f"👥 Группа: {group[1]}\n"
                        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                        f"🏋️‍♂️ Тип: {training.kind}\n"
                        f"📍 Место: {training.location}"
                    )
                    try:
                        bot.send_message(user_id, notification)
                    except Exception as e:
                        print(f"Error notifying user {username}: {e}")
                
                # Обновляем список в форуме
                if topic_id := trainer_db.get_topic_id(training_id):
                    participants = trainer_db.get_participants_by_training_id(training_id)
                    forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
                
                bot.answer_callback_query(call.id, "✅ Оплата подтверждена")
                bot.delete_message(call.message.chat.id, call.message.message_id)
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка подтверждения оплаты")
            
        except Exception as e:
            print(f"Error in confirm_payment: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка при подтверждении оплаты")

    def process_payment_details(message: Message):
        """Обрабатывает полученные реквизиты"""
        admin_db.set_payment_details(message.from_user.username, message.text)
        bot.reply_to(message, "✅ Реквизиты успешно обновлены")

    @bot.callback_query_handler(func=lambda call: call.data == "set_payment_details")
    def set_payment_details_callback(call: CallbackQuery):
        """Обработчик нажатия кнопки установки реквизитов"""
        username = call.from_user.username
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            return
        
        msg = bot.send_message(call.message.chat.id, "Отправьте реквизиты для оплаты:")
        bot.register_next_step_handler(msg, process_payment_details)

    @bot.message_handler(commands=["create_test_training"])
    def create_test_training(message: Message):
        """Создает тестовую тренировку с 17 тестовыми участниками"""
        username = message.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.reply_to(message, "❌ Вы не являетесь администратором ни одной группы")
            return
            
        trainer_db = TrainerDB(username)
        # Создаем тренировку через час от текущего времени
        test_time = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
        
        training_id = trainer_db.add_training(
            channel_id=channel_id,  # Добавляем channel_id
            date_time=test_time,
            duration=60,
            kind="Тестовая",
            location="Тестовый зал",
            max_participants=18,
            status="OPEN",
            price=1000
        )
        
        if training_id:
            # Добавляем 17 тестовых участников
            for i in range(17):
                test_username = f"test_user_{i+1}"
                # Добавляем тестового пользователя в базу данных users
                admin_db.execute_query(
                    "INSERT OR IGNORE INTO users (username, user_id) VALUES (?, ?)",
                    (test_username, 1000000 + i)  # Используем фиктивные user_id начиная с 1000000
                )
                trainer_db.add_participant(test_username, training_id)
            
            training = trainer_db.get_training_details(training_id)
            
            # Создаем тему в форуме
            topic_id = forum_manager.create_training_topic(training, message.from_user.username)
            if topic_id:
                trainer_db.set_topic_id(training_id, topic_id)
                # Отправляем объявление в тему
                forum_manager.send_training_announcement(training, message.from_user.username, topic_id)
                
                # Обновляем список участников
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
            
            bot.reply_to(
                message,
                f"✅ Тестовая тренировка создана с 17 участниками из 18 возможных!"
            )
        else:
            bot.reply_to(message, "❌ Не удалось создать тестовую тренировку")
            
    @bot.message_handler(commands=["remove_test_participant"])
    def remove_test_participant(message: Message):
        """Удаляет случайного тестового участника из тренировки"""
        if not admin_db.is_admin(message.from_user.username):
            return
            
        trainer_db = TrainerDB(message.from_user.username)
        
        # Находим тестовую тренировку
        test_trainings = trainer_db.fetch_all('''
            SELECT training_id FROM schedule 
            WHERE kind = 'Тестовая' 
            ORDER BY date_time DESC 
            LIMIT 1
        ''')
        
        if not test_trainings:
            bot.reply_to(message, "❌ Тестовая тренировка не найдена")
            return
            
        training_id = test_trainings[0][0]
        participants = trainer_db.get_participants_by_training_id(training_id)
        test_participants = [p for p in participants if p.startswith("test_user_")]
        
        if test_participants:
            # Удаляем последнего тестового участника
            trainer_db.remove_participant(test_participants[-1], training_id)
            
            # Предлагаем место следующему в резерве
            offer_spot_to_reserve(training_id, message.from_user.username)
            
            # Обновляем список в форуме
            if topic_id := trainer_db.get_topic_id(training_id):
                training = trainer_db.get_training_details(training_id)
                updated_participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, updated_participants, topic_id, trainer_db)
            
            bot.reply_to(message, f"✅ Тестовый участник @{test_participants[-1]} удален")
        else:
            bot.reply_to(message, "❌ Тестовые участники не найдены")

    @bot.message_handler(commands=["add_test_participant"])
    def add_test_participant(message: Message):
        """Добавляет тестового участника в тестовую тренировку"""
        if not admin_db.is_admin(message.from_user.username):
            return
            
        trainer_db = TrainerDB(message.from_user.username)
        
        # Находим тестовую тренировку
        test_trainings = trainer_db.fetch_all('''
            SELECT training_id FROM schedule 
            WHERE kind = 'Тестовая' 
            ORDER BY date_time DESC 
            LIMIT 1
        ''')
        
        if not test_trainings:
            bot.reply_to(message, "❌ Тестовая тренировка не найдена")
            return
            
        training_id = test_trainings[0][0]
        participants = trainer_db.get_participants_by_training_id(training_id)
        
        if len(participants) >= 18:
            bot.reply_to(message, "❌ Тренировка уже заполнена")
            return
            
        # Находим следующий номер для тестового участника
        test_participants = [p for p in participants if p.startswith("test_user_")]
        next_number = len(test_participants) + 1
        new_test_user = f"test_user_{next_number}"
        
        # Добавляем тестового пользователя в базу данных users
        admin_db.execute_query(
            "INSERT OR IGNORE INTO users (username, user_id) VALUES (?, ?)",
            (new_test_user, 1000000 + next_number)
        )
        
        trainer_db.add_participant(new_test_user, training_id)
        
        # Обновляем список в форуме
        if topic_id := trainer_db.get_topic_id(training_id):
            training = trainer_db.get_training_details(training_id)
            updated_participants = trainer_db.get_participants_by_training_id(training_id)
            forum_manager.update_participants_list(training, updated_participants, topic_id, trainer_db)
        
        bot.reply_to(message, f"✅ Добавлен тестовый участник @{new_test_user}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("mark_paid_"))
    def mark_paid(call: CallbackQuery):
        """Обработчик нажатия кнопки 'Оплатил'"""
        training_id = int(call.data.split("_")[2])
        username = call.from_user.username
        
        # Находим админа тренировки
        admin_username = find_training_admin(training_id)
        
        if not admin_username:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
        
        # Получаем реквизиты админа
        payment_details = admin_db.get_payment_details(admin_username)
        
        # Отправляем реквизиты и просим скриншот
        message = (
            "💳 Реквизиты для оплаты:\n"
            f"{payment_details}\n\n"
            "После оплаты, пожалуйста, отправьте скриншот подтверждения."
        )
        bot.send_message(call.message.chat.id, message)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        # Сохраняем состояние ожидания скриншота
        bot.register_next_step_handler(call.message, process_payment_screenshot, training_id, admin_username)

    def process_payment_screenshot(message: Message, training_id: int, admin_username: str):
        """Обрабатывает полученный скриншот оплаты"""
        if not message.photo:
            bot.reply_to(message, "Пожалуйста, отправьте скриншот оплаты")
            return
        
        username = message.from_user.username
        trainer_db = TrainerDB(admin_username)
        
        # Устанавливаем статус "ожидает подтверждения"
        trainer_db.set_payment_status(username, training_id, 1)
        
        # Создаем клавиатуру для админа
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_payment_{training_id}_{username}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment_{training_id}_{username}")
        )
        
        # Получаем user_id админа
        admin_user_id = admin_db.get_user_id(admin_username)
        
        if admin_user_id:
            # Отправляем скриншот админу
            bot.send_photo(
                admin_user_id,
                message.photo[-1].file_id,
                caption=f"Скриншот оплаты от @{username} за тренировку #{training_id}",
                reply_markup=markup
            )
            
            bot.reply_to(message, "✅ Скриншот отправлен администратору на проверку")
            
            # Обновляем список участников в форуме
            if topic_id := trainer_db.get_topic_id(training_id):
                training = trainer_db.get_training_details(training_id)
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)

    @bot.callback_query_handler(func=lambda call: call.data == "set_invite_limit")
    def set_invite_limit_handler(call: CallbackQuery):
        """Обработчик установки лимита приглашений"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        # Получаем информацию о группе
        group = channel_db.get_channel(channel_id)
        if not group:
            bot.answer_callback_query(call.id, "❌ Группа не найдена")
            return
        
        current_limit = admin_db.get_invite_limit(username)
        msg = bot.send_message(
            call.message.chat.id,
            f"Группа: {group[1]}\n"
            f"Текущий лимит приглашений: {current_limit}\n"
            "Введите новый лимит приглашений для одного пользователя (0 - без ограничений):"
        )
        bot.register_next_step_handler(msg, process_invite_limit, channel_id)

    def process_invite_limit(message: Message, channel_id: int):
        try:
            limit = int(message.text.strip())
            if limit < 0:
                raise ValueError("Лимит не может быть отрицательным")
        
            # Получаем информацию о группе
            group = channel_db.get_channel(channel_id)
            if not group:
                bot.reply_to(message, "❌ Группа не найдена")
                return
        
            admin_db.set_invite_limit(message.from_user.username, limit)
            bot.reply_to(
                message,
                f"✅ Для группы {group[1]} установлен "
                f"{'безлимитный' if limit == 0 else f'лимит в {limit}'} "
                "приглашений на пользователя"
            )
        except ValueError:
            bot.reply_to(message, "❌ Введите корректное число")

    def show_admin_menu(message: Message):
        """Показывает меню администратора"""
        username = message.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.reply_to(message, "❌ Вы не являетесь администратором ни одной группы")
            return
        
        # Получаем информацию о группе
        group = channel_db.get_channel(channel_id)
        if not group:
            bot.reply_to(message, "❌ Группа не найдена")
            return
        
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("➕ Создать", callback_data="create_training"),
            InlineKeyboardButton("✏️ Изменить", callback_data="edit_training")
        )
        markup.row(
            InlineKeyboardButton("🔓 Открыть запись", callback_data="open_training_sign_up"),
            InlineKeyboardButton("🔒 Закрыть запись", callback_data="close_training")
        )
        markup.row(
            InlineKeyboardButton("❌ Удалить", callback_data="delete_training"),
            InlineKeyboardButton("📊 Расписание", callback_data="get_schedule")
        )
        markup.add(InlineKeyboardButton("👤 Удалить участника", callback_data="remove_participant"))
        markup.add(InlineKeyboardButton("💳 Установить реквизиты", callback_data="set_payment_details"))
        markup.add(InlineKeyboardButton("👥 Лимит приглашений", callback_data="set_invite_limit"))
        
        bot.send_message(
            message.chat.id,
            f"👥 Группа: {group[1]}\n\n"
            "Выберите действие:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_list")
    def show_admin_list(call: CallbackQuery):
        """Показывает список администраторов"""
        username = call.from_user.username
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            return
        
        admins = admin_db.get_all_admins()
        if not admins:
            bot.send_message(call.message.chat.id, "Список администраторов пуст")
            return
            
        message = "👮‍♂️ Список администраторов:\n\n"
        for admin in admins:
            message += f"@{admin[0]}\n"
            
        bot.send_message(call.message.chat.id, message)

    @bot.callback_query_handler(func=lambda call: call.data == "remove_participant")
    def show_trainings_for_participant_removal(call: CallbackQuery):
        """Показывает список тренировок для удаления участника"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        trainer_db = TrainerDB(call.from_user.username)
        # Получаем список тренировок для данной группы
        trainings = trainer_db.get_trainings_for_channel(channel_id)
        trainings_with_participants = []
        
        for training in trainings:
            if trainer_db.get_participants_by_training_id(training.id):
                trainings_with_participants.append(training)
        
        if not trainings_with_participants:
            bot.send_message(call.message.chat.id, "Нет тренировок с участниками")
            return
        
        markup = get_trainings_keyboard(trainings_with_participants, "select_training_remove_participant")
        
        bot.send_message(
            call.message.chat.id,
            "Выберите тренировку для удаления участника:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("select_training_remove_participant_"))
    def show_participants_for_removal(call: CallbackQuery):
        """Показывает список участников для удаления"""
        training_id = int(call.data.split("_")[-1])
        trainer_db = TrainerDB(call.from_user.username)
        
        # Получаем информацию о тренировке
        training = trainer_db.get_training_details(training_id)
        if not training:
            bot.answer_callback_query(call.id, "Тренировка не найдена")
            return
        
        # Получаем информацию о группе
        group = channel_db.get_channel(training.channel_id)
        if not group:
            bot.answer_callback_query(call.id, "Группа не найдена")
            return
        
        # Получаем список участников
        participants = trainer_db.get_participants_by_training_id(training_id)
        if not participants:
            bot.send_message(call.message.chat.id, "На этой тренировке нет участников")
            return
        
        markup = InlineKeyboardMarkup()
        for username in participants:
            markup.add(InlineKeyboardButton(
                f"❌ @{username}",
                callback_data=f"remove_participant_{training_id}_{username}"
            ))
        
        bot.send_message(
            call.message.chat.id,
            f"Тренировка в группе {group[1]}:\n"
            f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🏋️‍♂️ {training.kind}\n"
            f"📍 {training.location}\n\n"
            "Выберите участника для удаления:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("remove_participant_"))
    def request_removal_reason(call: CallbackQuery):
        """Запрашивает причину удаления участника"""
        parts = call.data.split("_")
        training_id = int(parts[2])
        username = parts[3]
        
        msg = bot.send_message(
            call.message.chat.id,
            f"Укажите причину удаления @{username}:"
        )
        bot.register_next_step_handler(msg, process_participant_removal, training_id, username)

    @bot.callback_query_handler(func=lambda call: call.data == "close_training")
    def show_trainings_for_closing(call: CallbackQuery):
        """Показывает список открытых тренировок для закрытия записи"""
        username = call.from_user.username
        
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.answer_callback_query(
                call.id,
                "❌ Вы не являетесь администратором ни одной группы",
                show_alert=True
            )
            return
        
        trainer_db = TrainerDB(username)
        # Получаем список открытых тренировок для данной группы
        trainings = trainer_db.get_trainings_for_channel(channel_id)
        open_trainings = [t for t in trainings if t.status == "OPEN"]
        
        if not open_trainings:
            bot.send_message(call.message.chat.id, "Нет тренировок с открытой записью")
            return
        
        markup = get_trainings_keyboard(open_trainings, "close_sign_up")
        
        bot.send_message(
            call.message.chat.id,
            "Выберите тренировку для закрытия записи:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("close_sign_up_"))
    def close_training(call: CallbackQuery):
        """Обработчик закрытия записи на тренировку"""
        try:
            training_id = int(call.data.split("_")[-1])
            trainer_db = TrainerDB(call.from_user.username)
            
            # Получаем информацию о тренировке
            training = trainer_db.get_training_details(training_id)
            if not training:
                bot.answer_callback_query(call.id, "Тренировка не найдена")
                return
            
            # Получаем информацию о группе
            group = channel_db.get_channel(training.channel_id)
            if not group:
                bot.answer_callback_query(call.id, "Группа не найдена")
                return
            
            # Получаем список участников до закрытия
            participants = trainer_db.get_participants_by_training_id(training_id)
            
            # Закрываем запись (это также очистит списки участников)
            trainer_db.set_training_closed(training_id)
            
            # Отправляем уведомление в форум
            topic_id = trainer_db.get_topic_id(training_id)
            if topic_id:
                forum_manager.send_training_update(training, topic_id, "close")
                # Обновляем список участников (теперь пустой) в форуме
                forum_manager.update_participants_list(training, [], topic_id, trainer_db)
            
            # Отправляем уведомления бывшим участникам
            notification = (
                "🔒 Запись на тренировку закрыта:\n\n"
                f"👥 Группа: {group[1]}\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"📍 Место: {training.location}\n\n"
                "Список участников очищен. При открытии записи вам нужно будет записаться заново."
            )
            
            for username in participants:
                if user_id := admin_db.get_user_id(username):
                    try:
                        bot.send_message(user_id, notification)
                    except Exception as e:
                        print(f"Ошибка отправки уведомления пользователю {username}: {e}")
            
            bot.send_message(call.from_user.id, "✅ Запись закрыта, список участников очищен")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            
        except Exception as e:
            print(f"Error in close_training: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка при закрытии записи")

    def process_participant_removal(message: Message, training_id: int, username: str):
        """Обрабатывает удаление участника"""
        reason = message.text.strip()
        if not reason:
            bot.reply_to(message, "❌ Необходимо указать причину удаления")
            return
        
        admin_username = message.from_user.username
        trainer_db = TrainerDB(admin_username)
        
        # Получаем информацию о тренировке
        training = trainer_db.get_training_details(training_id)
        if not training:
            bot.reply_to(message, "❌ Тренировка не найдена")
            return
        
        # Получаем информацию о группе
        group = channel_db.get_channel(training.channel_id)
        if not group:
            bot.reply_to(message, "❌ Группа не найдена")
            return
        
        # Удаляем участника
        if trainer_db.remove_participant(username, training_id):
            # Отправляем уведомление удаленному участнику
            if user_id := admin_db.get_user_id(username):
                notification = (
                    "❌ Вы были удалены с тренировки:\n\n"
                    f"👥 Группа: {group[1]}\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ Тип: {training.kind}\n"
                    f"📍 Место: {training.location}\n\n"
                    f"Причина: {reason}"
                )
                try:
                    bot.send_message(user_id, notification)
                except Exception as e:
                    print(f"Error notifying user {username}: {e}")
            
            bot.reply_to(message, f"✅ Участник @{username} успешно удален")
            
            # Обновляем список в форуме
            if topic_id := trainer_db.get_topic_id(training_id):
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
        else:
            bot.reply_to(message, "❌ Не удалось удалить участника")

    @bot.message_handler(commands=['give_auto_signup'])
    def give_auto_signup(message: Message):
        """Начисляет автозаписи пользователю"""
        if message.from_user.username != SUPERADMIN_USERNAME:
            bot.reply_to(message, "❌ У вас нет прав для выполнения этой команды")
            return
            
        args = message.text.split()
        if len(args) != 3:
            bot.reply_to(message, "ℹ️ Использование: /give_auto_signup @username количество")
            return
            
        username = args[1].lstrip('@')
        try:
            amount = int(args[2])
            if amount <= 0:
                bot.reply_to(message, "❌ Количество должно быть положительным числом")
                return
        except ValueError:
            bot.reply_to(message, "❌ Количество должно быть числом")
            return
            
        # Создаем TrainerDB для пользователя, которому начисляем автозаписи
        user_db = TrainerDB(username)
        if user_db.add_auto_signups(username, amount):
            new_balance = user_db.get_auto_signups_balance(username)
            bot.reply_to(
                message, 
                f"✅ Пользователю @{username} начислено {amount} автозаписей\n"
                f"Текущий баланс: {new_balance}"
            )
            
            # Уведомляем пользователя
            if user_id := admin_db.get_user_id(username):
                notification = f"🎁 Вам начислено {amount} автозаписей!\nТекущий баланс: {new_balance}"
                try:
                    bot.send_message(user_id, notification)
                except Exception as e:
                    print(f"Error notifying user about auto signups: {e}")
        else:
            bot.reply_to(message, f"❌ Не удалось начислить автозаписи пользователю @{username}")

    @bot.message_handler(commands=["init"])
    def init_channel(message: Message):
        """Инициализирует чат для работы с ботом"""
        # Проверяем, что команда отправлена в супергруппе
        if message.chat.type != 'supergroup':
            bot.reply_to(message, "❌ Эта команда должна быть выполнена в супергруппе с включенными темами")
            return

        # Проверяем, включены ли темы в чате
        chat_info = bot.get_chat(message.chat.id)
        if not chat_info.is_forum:
            bot.reply_to(
                message, 
                "❌ В этом чате не включены темы. Пожалуйста, включите темы в настройках группы"
            )
            return

        # Проверяем права пользователя
        chat_member = bot.get_chat_member(message.chat.id, message.from_user.id)
        if chat_member.status not in ['creator', 'administrator']:
            bot.reply_to(message, "❌ Только администратор группы может выполнить эту команду")
            return

        # Проверяем, не был ли чат уже инициализирован
        if channel_db.channel_exists(message.chat.id):
            bot.reply_to(message, "❌ Этот чат уже инициализирован")
            return

        # Добавляем чат в базу
        chat_title = message.chat.title or f"Group {message.chat.id}"
        if channel_db.add_channel(message.chat.id, chat_title):
            bot.reply_to(
                message,
                "✅ Чат успешно инициализирован!\n"
                "Теперь администраторы могут получить права для управления тренировками"
            )
        else:
            bot.reply_to(message, "❌ Произошла ошибка при инициализации")

    def process_auto_signups(trainer_db: TrainerDB, training: Training) -> None:
        """Обрабатывает автозаписи при открытии тренировки"""
        # Получаем список запросов на автозапись
        auto_signup_users = trainer_db.get_auto_signup_requests(training.id)
        max_auto_slots = training.max_participants // 2
        
        # Получаем информацию о группе
        group = channel_db.get_channel(training.channel_id)
        if not group:
            print(f"Error: group not found for training {training.id}")
            return
        
        # Обрабатываем автозаписи
        for username in auto_signup_users[:max_auto_slots]:
            # Проверяем, не записан ли уже пользователь
            if trainer_db.is_participant(username, training.id):
                continue
            
            # Добавляем участника
            if trainer_db.add_participant(username, training.id):
                # Уменьшаем количество автозаписей
                user_db = TrainerDB(username)
                user_db.decrease_auto_signups(username)
                
                # # Удаляем запрос автозаписи
                # trainer_db.remove_auto_signup_request(username, training.id)
                
                # Отправляем уведомление пользователю
                if user_id := admin_db.get_user_id(username):
                    notification = (
                        "✅ Сработала автозапись!\n\n"
                        f"👥 Группа: {group[1]}\n"
                        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                        f"🏋️‍♂️ Тип: {training.kind}\n"
                        f"📍 Место: {training.location}\n"
                        f"💰 Стоимость: {training.price}₽"
                    )
                    try:
                        bot.send_message(user_id, notification)
                    except Exception as e:
                        print(f"Error notifying user {username}: {e}")

    @bot.message_handler(commands=["set_payment_details"])
    def set_payment_details(message: Message):
        """Устанавливает реквизиты для оплаты"""
        username = message.from_user.username
        if not admin_db.is_admin(username):
            bot.reply_to(message, "❌ У вас нет прав администратора")
            return
            
        # Получаем channel_id администратора
        channel_id = admin_db.get_admin_channel(username)
        if not channel_id:
            bot.reply_to(message, "❌ Вы не являетесь администратором ни одной группы")
            return
        
        # Получаем информацию о группе
        group = channel_db.get_channel(channel_id)
        if not group:
            bot.reply_to(message, "❌ Группа не найдена")
            return
        
        # Получаем текст после команды
        details = message.text.replace("/set_payment_details", "").strip()
        if not details:
            bot.reply_to(message, "ℹ️ Использование: /set_payment_details <реквизиты>")
            return
        
        admin_db.set_payment_details(username, details)
        bot.reply_to(
            message, 
            f"✅ Реквизиты для группы {group[1]} успешно обновлены:\n\n{details}"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("reject_payment_"))
    def reject_payment(call: CallbackQuery):
        """Отклоняет оплату тренировки"""
        try:
            parts = call.data.split("_")
            training_id = int(parts[2])
            username = parts[3]
            
            trainer_db = TrainerDB(call.from_user.username)
            
            # Получаем информацию о тренировке
            training = trainer_db.get_training_details(training_id)
            if not training:
                bot.answer_callback_query(call.id, "Тренировка не найдена")
                return
            
            # Получаем информацию о группе
            group = channel_db.get_channel(training.channel_id)
            if not group:
                bot.answer_callback_query(call.id, "Группа не найдена")
                return
            
            # Отклоняем оплату (устанавливаем статус 0 - не оплачено)
            if trainer_db.set_payment_status(username, training_id, 0):
                # Отправляем уведомление пользователю
                if user_id := admin_db.get_user_id(username):
                    notification = (
                        "❌ Оплата не подтверждена!\n\n"
                        f"👥 Группа: {group[1]}\n"
                        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                        f"🏋️‍♂️ Тип: {training.kind}\n"
                        f"📍 Место: {training.location}\n\n"
                        "Пожалуйста, проверьте правильность оплаты и отправьте новый скриншот"
                    )
                    try:
                        bot.send_message(user_id, notification)
                    except Exception as e:
                        print(f"Error notifying user {username}: {e}")
                
                # Обновляем список в форуме
                if topic_id := trainer_db.get_topic_id(training_id):
                    participants = trainer_db.get_participants_by_training_id(training_id)
                    forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
                
                bot.answer_callback_query(call.id, "❌ Оплата отклонена")
                bot.delete_message(call.message.chat.id, call.message.message_id)
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка отклонения оплаты")
        
        except Exception as e:
            print(f"Error in reject_payment: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка при отклонении оплаты")
