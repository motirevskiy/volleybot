import uuid
import os
from typing import List, Optional, Dict
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from new_bot.config import SUPERADMIN_USERNAME
from new_bot.database.admin import AdminDB
from new_bot.database.trainer import TrainerDB
from new_bot.utils.keyboards import (
    get_trainings_keyboard,
    get_admin_list_keyboard,
    get_confirm_keyboard
)
from new_bot.utils.messages import (
    create_training_message,
    create_open_training_message,
    format_participant
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
ADMIN_KEY = ""

def register_admin_handlers(bot: BotType) -> None:
    # Создаем экземпляр ForumManager
    forum_manager = ForumManager(bot)
    
    @bot.message_handler(commands=["admin"])
    def admin_menu(message: Message):
        """Показывает меню администратора"""
        if not admin_db.is_admin(message.from_user.username):
            bot.reply_to(message, "❌ У вас нет прав администратора")
            return
        show_admin_menu(message)
    
    @bot.callback_query_handler(func=lambda call: call.data == "get_admin")
    def request_admin_key(call: CallbackQuery):
        username = call.from_user.username
        if admin_db.is_admin(username):
            bot.send_message(call.message.chat.id, "Вы уже администратор!")
            return

        if not ADMIN_KEY:
            bot.send_message(call.message.chat.id, "Сейчас нет активных ключей. Запросите у супер-админа.")
            return

        msg = bot.send_message(call.message.chat.id, "Введите ключ администратора:")
        bot.register_next_step_handler(msg, process_admin_key)

    def process_admin_key(message: Message):
        username = message.from_user.username
        global ADMIN_KEY
        if message.text == str(ADMIN_KEY):
            # Добавляем админа в таблицу users
            admin_db.execute_query(
                "INSERT OR IGNORE INTO users (username, user_id) VALUES (?, ?)",
                (username, message.from_user.id)
            )
            admin_db.add_admin(username)
            TrainerDB(username)
            bot.send_message(message.chat.id, "Поздравляю, теперь вы администратор!")
            ADMIN_KEY = ""
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
        if message.from_user.username != SUPERADMIN_USERNAME:
            return
        admins = admin_db.get_all_admins()
        if not admins:
            bot.send_message(message.chat.id, "Нет администраторов для удаления.")
            return

        markup = get_admin_list_keyboard(admins)
        bot.send_message(message.chat.id, "Выберите администратора для удаления:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("remadm_"))
    def remove_admin(call: CallbackQuery):
        admin_id = call.data.split("_")[1]
        admin_db.remove_admin(admin_id)
        bot.send_message(call.message.chat.id, f"Администратор @{admin_id} удалён.")

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
        msg = bot.send_message(call.message.chat.id, "Введите данные тренировки!")
        training_creation_data[call.from_user.id] = TrainingData()
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
        
        if not training_data.is_complete():
            return
        
        try:
            trainer_db = TrainerDB(message.from_user.username)
            
            if action == "edit" and training_id:
                success = update_existing_training(trainer_db, training_id, training_data, message)
            else:
                success = create_new_training(trainer_db, training_data, message)
            
            if success:
                del training_creation_data[user_id]
            
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
                        
                        # Отправляем уведомление участнику
                        if user_id := admin_db.get_user_id(username):
                            notification = (
                                "⚠️ В связи с изменением количества мест на тренировке, "
                                f"вы были перемещены в резервный список (позиция: {position})\n\n"
                                f"📅 Дата: {training_data.date_time}\n"
                                f"🏋️‍♂️ Тип: {training_data.kind}\n"
                                f"📍 Место: {training_data.location}"
                            )
                            try:
                                bot.send_message(user_id, notification)
                            except Exception as e:
                                print(f"Ошибка отправки уведомления пользователю {username}: {e}")
            
            # Если количество мест увеличилось
            elif new_max_participants > old_max_participants:
                # Определяем, сколько человек можно добавить из резерва
                available_spots = new_max_participants - len(current_participants)
                if available_spots > 0 and current_reserve:
                    # Добавляем людей из резерва в основной список
                    for i in range(min(available_spots, len(current_reserve))):
                        username = current_reserve[i]
                        trainer_db.remove_from_reserve(username, training_id)
                        trainer_db.add_participant(username, training_id)
                        
                        # Отправляем уведомление участнику
                        if user_id := admin_db.get_user_id(username):
                            notification = (
                                "🎉 Освободилось место на тренировке! "
                                "Вы перемещены из резерва в основной список.\n\n"
                                f"📅 Дата: {training_data.date_time}\n"
                                f"🏋️‍♂️ Тип: {training_data.kind}\n"
                                f"📍 Место: {training_data.location}"
                            )
                            try:
                                bot.send_message(user_id, notification)
                            except Exception as e:
                                print(f"Ошибка отправки уведомления пользователю {username}: {e}")
            
            # Получаем обновленные данные и обновляем форум
            updated_training = trainer_db.get_training_details(training_id)
            notify_about_training_update(trainer_db, updated_training, training_id, message)
            
            # Обновляем список в форуме
            if topic_id := trainer_db.get_topic_id(training_id):
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(updated_training, participants, topic_id, trainer_db)
            
            bot.reply_to(message, "✅ Тренировка успешно обновлена!")
            return True
        
        except Exception as e:
            print(f"Error in update_existing_training: {e}")
            return False

    def create_new_training(trainer_db: TrainerDB, training_data: TrainingData, message: Message) -> bool:
        """Создает новую тренировку"""
        try:
            new_training_id = trainer_db.add_training(
                training_data.date_time,
                training_data.duration,
                training_data.kind,
                training_data.location,
                training_data.max_participants,
                "CLOSED",  # Меняем статус на CLOSED при создании
                training_data.price
            )
            
            if new_training_id:
                # Получаем созданную тренировку
                training = trainer_db.get_training_details(new_training_id)
                if training:
                    # Создаем тему в форуме
                    topic_id = forum_manager.create_training_topic(training, message.from_user.username)
                    if topic_id:
                        trainer_db.set_topic_id(new_training_id, topic_id)
                        # Отправляем объявление в тему
                        forum_manager.send_training_announcement(
                            training, 
                            message.from_user.username,
                            topic_id
                        )
                        
                bot.reply_to(message, "✅ Тренировка успешно создана!")
                return True
            return False
        except Exception as e:
            print(f"Error in create_new_training: {e}")
            return False

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
    def edit_training(call: CallbackQuery):
        """Показывает список тренировок для изменения"""
        if not admin_db.is_admin(call.from_user.username):
            return
            
        trainer_db = TrainerDB(call.from_user.username)
        trainings = []
        training_ids = trainer_db.get_training_ids()
        
        for training_id in training_ids:
            if training := trainer_db.get_training_details(training_id[0]):
                trainings.append(training)
        
        if not trainings:
            bot.send_message(call.message.chat.id, "У вас нет активных тренировок")
            return
            
        markup = get_trainings_keyboard(trainings, "edit")
        bot.send_message(
            call.message.chat.id,
            "Выберите тренировку для изменения:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_"))
    def start_edit_training(call: CallbackQuery):
        """Начинает процесс изменения выбранной тренировки"""
        training_id = int(call.data.split("_")[1])
        trainer_db = TrainerDB(call.from_user.username)
        training = trainer_db.get_training_details(training_id)
        
        if not training:
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
            
        msg = bot.send_message(call.message.chat.id, "Введите новые данные тренировки")
        edit_or_create_training(msg, "edit", training_id)

    @bot.callback_query_handler(func=lambda call: call.data == "remove_training")
    def show_trainings_for_deletion(call: CallbackQuery):
        """Показывает список тренировок для удаления"""
        if not admin_db.is_admin(call.from_user.username):
            return
        
        trainer_db = TrainerDB(call.from_user.username)
        trainings = []
        training_ids = trainer_db.get_training_ids()
        
        for training_id in training_ids:
            if training := trainer_db.get_training_details(training_id[0]):
                trainings.append(training)
        
        if not trainings:
            bot.send_message(call.message.chat.id, "Нет доступных тренировок")
            return

        markup = get_trainings_keyboard(trainings, "delete")
        bot.send_message(
            call.message.chat.id, 
            "Выберите тренировку для удаления:", 
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
    def apply_remove(call: CallbackQuery):
        """Обработчик удаления тренировки"""
        try:
            training_id = int(call.data.split("_")[1])
            trainer_db = TrainerDB(call.from_user.username)
            
            # Получаем информацию о тренировке и topic_id перед удалением
            training = trainer_db.get_training_details(training_id)
            topic_id = trainer_db.get_topic_id(training_id)
            
            if not training:
                bot.answer_callback_query(call.id, "Тренировка не найдена")
                return
            
            # Получаем список участников для уведомления
            participants = trainer_db.get_participants_by_training_id(training_id)
            
            # Удаляем тренировку
            if trainer_db.delete_training(training_id):
                # Удаляем тему в форуме
                if topic_id:
                    try:
                        bot.delete_forum_topic(forum_manager.chat_id, topic_id)
                    except Exception as e:
                        print(f"Ошибка при удалении темы: {e}")
                        try:
                            bot.edit_forum_topic(
                                forum_manager.chat_id,
                                topic_id,
                                name=f"[УДАЛЕНА] {training.date_time.strftime('%d.%m.%Y %H:%M')} {training.kind}"
                            )
                        except Exception as e:
                            print(f"Ошибка при обновлении названия темы: {e}")
                
                # Отправляем уведомления участникам
                notification = (
                    "❌ Тренировка была отменена:\n\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ Тип: {training.kind}\n"
                    f"📍 Место: {training.location}"
                )
                
                for username in participants:
                    if user_id := admin_db.get_user_id(username):
                        try:
                            bot.send_message(user_id, notification)
                        except Exception as e:
                            print(f"Ошибка отправки уведомления пользователю {username}: {e}")
                
                bot.answer_callback_query(call.id, "✅ Тренировка успешно удалена")
                bot.delete_message(call.message.chat.id, call.message.message_id)
            else:
                bot.answer_callback_query(call.id, "❌ Не удалось удалить тренировку")
        except Exception as e:
            print(f"Error in apply_remove: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка при удалении тренировки")

    @bot.callback_query_handler(func=lambda call: call.data == "open_training_sign_up")
    def open_training_sign_up(call: CallbackQuery):
        """Показывает список закрытых тренировок для открытия записи"""
        print(f"Вызван обработчик open_training_sign_up с данными: {call.data}")  # Отладка
        
        if not admin_db.is_admin(call.from_user.username):
            print(f"Пользователь {call.from_user.username} не является админом")  # Отладка
            return
            
        trainer_db = TrainerDB(call.from_user.username)
        # Получаем список закрытых тренировок
        training_ids = trainer_db.get_training_ids()
        closed_trainings = []
        
        for training_id in training_ids:
            if training := trainer_db.get_training_details(training_id[0]):
                if training.status != "OPEN":
                    closed_trainings.append(training)
        
        print(f"Найдено закрытых тренировок: {len(closed_trainings)}")  # Отладка
        
        if not closed_trainings:
            bot.send_message(call.message.chat.id, "Нет тренировок для открытия записи")
            return
            
        markup = get_trainings_keyboard(closed_trainings, "open_sign_up")
        print(f"Создана клавиатура с кнопками")  # Отладка
        
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
            admin_username = call.from_user.username
            trainer_db = TrainerDB(admin_username)
            
            
            # Получаем данные тренировки
            training = trainer_db.get_training_details(training_id)
            if not training:
                bot.answer_callback_query(call.id, "Ошибка: тренировка не найдена")
                return
                
            
            # Получаем список автозаписей
            auto_signup_users = trainer_db.get_auto_signup_requests(training_id)
            max_auto_slots = training.max_participants // 2
            
            # Обрабатываем автозаписи
            for username in auto_signup_users[:max_auto_slots]:
                # Проверяем, не записан ли уже пользователь
                if trainer_db.is_participant(username, training_id):
                    continue
                
                # Добавляем участника
                if trainer_db.add_participant(username, training_id):
                    
                    # Проверяем, действительно ли пользователь добавлен
                    if trainer_db.is_participant(username, training_id):
                        print(f"[DEBUG] Verified {username} is now a participant")
                    else:
                        print(f"[DEBUG] WARNING: {username} was not properly added as participant")
                    
                    # Уменьшаем количество автозаписей
                    user_db = TrainerDB(username)
                    old_balance = user_db.get_auto_signups_balance(username)
                    
                    if user_db.decrease_auto_signups(username):
                        new_balance = user_db.get_auto_signups_balance(username)
                        print(f"[DEBUG] Successfully decreased balance for {username}: {old_balance} -> {new_balance}")
                    else:
                        print(f"[DEBUG] Failed to decrease balance for {username}")
                    
                    # Удаляем запрос автозаписи
                    if trainer_db.remove_auto_signup_request(username, training_id):
                        print(f"[DEBUG] Successfully removed auto signup request for {username}")
                    else:
                        print(f"[DEBUG] Failed to remove auto signup request for {username}")
                    
                    # Отправляем уведомление пользователю
                    if user_id := admin_db.get_user_id(username):
                        notification = (
                            "✅ Сработала автозапись!\n\n"
                            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                            f"🏋️‍♂️ Тип: {training.kind}\n"
                            f"📍 Место: {training.location}\n"
                            f"💰 Стоимость: {training.price}₽"
                        )
                        try:
                            bot.send_message(user_id, notification)
                        except Exception as e:
                            print(f"[DEBUG] Error notifying user {username}: {e}")
                else:
                    print(f"[DEBUG] Failed to add {username} as participant")
            
            # Проверяем список участников после автозаписи
            participants = trainer_db.get_participants_by_training_id(training_id)
            
            # Открываем запись
            trainer_db.set_training_open(training_id)
            
            # Обновляем тему в форуме
            topic_id = trainer_db.get_topic_id(training_id)
            if topic_id:
                forum_manager.send_training_update(training, topic_id, "open")
                # Обновляем список участников
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
            
            # Отправляем уведомления остальным пользователям
            users = admin_db.get_all_users()
            payment_details = admin_db.get_payment_details(call.from_user.username)
            
            notification = (
                f"🟢 Открыта запись на тренировку!\n\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"⏱ Длительность: {training.duration} минут\n"
                f"📍 Место: {training.location}\n"
                f"💰 Стоимость: {training.price}₽\n"
                f"👥 Максимум участников: {training.max_participants}\n"
                f"\n💳 Реквизиты для оплаты:\n{payment_details}"
            )
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Записаться", callback_data=f"signup_{training_id}"))
            
            # Отправляем уведомления всем пользователям, кроме тех, кто уже записан через автозапись
            for user in users:
                us = admin_db.get_user_info(user[0])

                try:
                    if us.username not in auto_signup_users and us.is_admin == False:
                        bot.send_message(user[0], notification, reply_markup=markup)
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {user[0]}: {e}")
            
            bot.answer_callback_query(call.id, "Запись успешно открыта!")
            
        except Exception as e:
            import traceback
            bot.answer_callback_query(call.id, "Произошла ошибка при открытии записи")

    @bot.message_handler(commands=["stats"])
    def show_statistics(message: Message):
        username = message.from_user.username
        if not username:
            bot.send_message(message.chat.id, "Не удалось определить ваш username")
            return
            
        # Определяем, является ли пользователь админом
        is_admin = admin_db.is_admin(username)
        
        # Если это админ, собираем статистику из его базы данных
        if is_admin:
            trainer_db = TrainerDB(username)
            # Получаем статистику всех пользователей из базы данных админа
            all_participants = trainer_db.fetch_all('''
                SELECT DISTINCT username FROM participants
            ''')
            
            total_stats = {
                'total_trainings': len(trainer_db.get_training_ids()),
                'total_participants': 0,
                'active_trainings': 0,
                'participants_by_training': {}
            }
            
            # Подсчитываем статистику по тренировкам
            trainings = trainer_db.fetch_all('''
                SELECT training_id, date_time, kind, status 
                FROM schedule
            ''')
            
            for training in trainings:
                training_id = training[0]
                participants = trainer_db.get_participants_by_training_id(training_id)
                total_stats['participants_by_training'][training_id] = len(participants)
                total_stats['total_participants'] += len(participants)
                if training[3] == 'OPEN':
                    total_stats['active_trainings'] += 1
            
            stats_message = (
                f"📊 Статистика администратора @{username}:\n\n"
                f"Всего создано тренировок: {total_stats['total_trainings']}\n"
                f"Активных тренировок: {total_stats['active_trainings']}\n"
                f"Всего участников на тренировках: {total_stats['total_participants']}\n\n"
                "Последние тренировки:\n"
            )
            
            # Получаем последние 5 тренировок
            recent_trainings = trainer_db.fetch_all('''
                SELECT training_id, date_time, kind, status 
                FROM schedule 
                ORDER BY date_time DESC 
                LIMIT 5
            ''')
            
            for training in recent_trainings:
                training_id, date_time, kind, status = training
                participants_count = total_stats['participants_by_training'].get(training_id, 0)
                status_text = "Открыта" if status == "OPEN" else "Закрыта"
                stats_message += (
                    f"- {kind} ({datetime.strptime(date_time, '%Y-%m-%d %H:%M').strftime('%d.%m.%Y %H:%M')})\n"
                    f"  Статус: {status_text}, Участников: {participants_count}\n"
                )
        else:
            # Для обычного пользователя показываем его личную статистику
            trainer_db = TrainerDB(None)  # Используем None, так как нам нужна только статистика
            stats = trainer_db.get_user_statistics(username)
            
            stats_message = (
                f"📊 Статистика пользователя @{username}:\n\n"
                f"Всего записей на тренировки: {stats['total_signups']}\n"
                f"Всего отмен записей: {stats['total_cancellations']}\n\n"
                "Последние действия:\n"
            )
            
            for action, timestamp, training_kind, date_time in stats['recent_activities']:
                action_text = "Запись" if action == "signup" else "Отмена"
                stats_message += (
                    f"- {action_text} на тренировку {training_kind} "
                    f"({datetime.strptime(date_time, '%Y-%m-%d %H:%M').strftime('%d.%m.%Y %H:%M')})\n"
                )
            
        bot.send_message(message.chat.id, stats_message)

    # Обновляем обработчик записи на тренировку
    @bot.callback_query_handler(func=lambda call: call.data.startswith("signup_"))
    def process_training_signup(call: CallbackQuery):
        training_id = int(call.data.split("_")[1])
        username = call.from_user.username
        
        # Убедимся, что пользователь добавлен в таблицу users
        admin_db.execute_query(
            "INSERT OR IGNORE INTO users (username, user_id) VALUES (?, ?)",
            (username, call.from_user.id)
        )
        
        # Получаем имя админа, создавшего тренировку
        admin_username = find_training_admin(training_id)
        if not admin_username:
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
            
        trainer_db = TrainerDB(admin_username)
        if trainer_db.add_participant(username, training_id):
            bot.send_message(call.message.chat.id, "Вы успешно записались на тренировку!")
            
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
                message = "Вы уже записаны на эту тренировку!"
            else:
                # Добавляем в резерв
                position = trainer_db.add_to_reserve(username, training_id)
                message = f"Вы добавлены в резерв на позицию {position}"
                
                # Обновляем список в теме
                if topic_id := trainer_db.get_topic_id(training_id):
                    training = trainer_db.get_training_details(training_id)
                    participants = trainer_db.get_participants_by_training_id(training_id)
                    forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
                
            bot.send_message(call.message.chat.id, message)

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

    @bot.callback_query_handler(func=lambda call: call.data.startswith(("confirm_payment_", "reject_payment_")))
    def handle_payment_verification(call: CallbackQuery):
        parts = call.data.split("_")
        action = parts[0]
        training_id = int(parts[2])  # payment_id находится на позиции 2
        username = parts[3]  # username находится на позиции 3
        is_confirmed = action == "confirm"
        
        admin_username = call.from_user.username
        trainer_db = TrainerDB(admin_username)
        
        # Обновляем статус оплаты
        new_status = 2 if is_confirmed else 0
        trainer_db.set_payment_status(username, training_id, new_status)
        
        # Отправляем уведомление пользователю
        user_id = AdminDB().get_user_id(username)
        if user_id:
            message = (
                "✅ Оплата подтверждена администратором"
                if is_confirmed else
                "❌ Оплата не подтверждена, пожалуйста, проверьте платеж"
            )
            bot.send_message(user_id, message)
        
        # Обновляем сообщение админа
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=f"Скриншот оплаты от @{username}\nСтатус: {'✅ Подтверждено' if is_confirmed else '❌ Отклонено'}"
        )
        
        # Обновляем список участников в форуме
        if topic_id := trainer_db.get_topic_id(training_id):
            training = trainer_db.get_training_details(training_id)
            participants = trainer_db.get_participants_by_training_id(training_id)
            forum_manager.update_participants_list(training, participants, topic_id, trainer_db)

    def process_payment_details(message: Message):
        """Обрабатывает полученные реквизиты"""
        admin_db.set_payment_details(message.from_user.username, message.text)
        bot.reply_to(message, "✅ Реквизиты успешно обновлены")

    @bot.callback_query_handler(func=lambda call: call.data == "set_payment_details")
    def set_payment_details_callback(call: CallbackQuery):
        """Обработчик нажатия кнопки установки реквизитов"""
        if not admin_db.is_admin(call.from_user.username):
            return
            
        msg = bot.send_message(call.message.chat.id, "Отправьте реквизиты для оплаты:")
        bot.register_next_step_handler(msg, process_payment_details)

    @bot.message_handler(commands=["create_test_training"])
    def create_test_training(message: Message):
        """Создает тестовую тренировку с 17 тестовыми участниками"""
        if not admin_db.is_admin(message.from_user.username):
            return
            
        trainer_db = TrainerDB(message.from_user.username)
        # Создаем тренировку через час от текущего времени
        test_time = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
        
        training_id = trainer_db.add_training(
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
            trainer_db.update_topic_id(training_id, topic_id)
            
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
        if not admin_db.is_admin(call.from_user.username):
            return
            
        current_limit = admin_db.get_invite_limit(call.from_user.username)
        msg = bot.send_message(
            call.message.chat.id,
            f"Текущий лимит приглашений: {current_limit}\n"
            "Введите новый лимит приглашений для одного пользователя (0 - без ограничений):"
        )
        bot.register_next_step_handler(msg, process_invite_limit)

    def process_invite_limit(message: Message):
        try:
            limit = int(message.text.strip())
            if limit < 0:
                raise ValueError("Лимит не может быть отрицательным")
                
            admin_db.set_invite_limit(message.from_user.username, limit)
            bot.reply_to(
                message,
                f"✅ Установлен {'безлимитный' if limit == 0 else f'лимит в {limit}'} приглашений на пользователя"
            )
        except ValueError:
            bot.reply_to(message, "❌ Введите корректное число")

    def show_admin_menu(message: Message):
        """Показывает меню администратора"""
        markup = InlineKeyboardMarkup()
        
        # Управление тренировками (создание, редактирование, удаление)
        markup.row(
            InlineKeyboardButton("➕ Создать", callback_data="create_training"),
            InlineKeyboardButton("✏️ Изменить", callback_data="edit_training"),
            InlineKeyboardButton("🗑 Удалить", callback_data="remove_training")
        )
        
        # Управление записью на тренировки
        markup.row(
            InlineKeyboardButton("🔓 Открыть запись", callback_data="open_training_sign_up"),
            InlineKeyboardButton("🔒 Закрыть запись", callback_data="close_training")
        )
        
        # Управление участниками
        markup.row(
            InlineKeyboardButton("❌ Удалить участника", callback_data="remove_participant"),
            InlineKeyboardButton("👥 Лимит приглашений", callback_data="set_invite_limit")
        )
        
        # Настройки и информация
        markup.row(
            InlineKeyboardButton("💰 Реквизиты", callback_data="set_payment_details"),
            InlineKeyboardButton("📊 Расписание", callback_data="get_schedule")
        )
        
        # Управление администраторами
        markup.add(
            InlineKeyboardButton("👮‍♂️ Список администраторов", callback_data="admin_list")
        )
        
        bot.send_message(
            message.chat.id,
            "🎛 <b>Панель управления администратора</b>\n\n"
            "📝 <i>Управление тренировками</i>\n"
            "🔐 <i>Управление записью</i>\n"
            "👥 <i>Управление участниками</i>\n"
            "⚙️ <i>Настройки</i>",
            parse_mode="HTML",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_list")
    def show_admin_list(call: CallbackQuery):
        """Показывает список администраторов"""
        if not admin_db.is_admin(call.from_user.username):
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
        if not admin_db.is_admin(call.from_user.username):
            return
        
        trainer_db = TrainerDB(call.from_user.username)
        trainings = []
        training_ids = trainer_db.get_training_ids()
        
        for training_id in training_ids:
            if training := trainer_db.get_training_details(training_id[0]):
                # Проверяем, есть ли участники в тренировке
                if trainer_db.get_participants_by_training_id(training_id[0]):  # Используем training_id[0] вместо training_id
                    trainings.append(training)
        
        if not trainings:
            bot.send_message(call.message.chat.id, "Нет тренировок с участниками")
            return
        
        markup = get_trainings_keyboard(trainings, "remove_from")
        bot.send_message(
            call.message.chat.id,
            "Выберите тренировку, из которой нужно удалить участника:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("remove_from_"))
    def show_participants_for_removal(call: CallbackQuery):
        """Показывает список участников для удаления в виде кнопок"""
        training_id = int(call.data.split("_")[-1])
        trainer_db = TrainerDB(call.from_user.username)
        
        # Получаем список участников
        participants = trainer_db.get_participants_by_training_id(training_id)
        if not participants:
            bot.answer_callback_query(call.id, "На эту тренировку никто не записан")
            return
        
        # Получаем информацию о тренировке для отображения
        training = trainer_db.get_training_details(training_id)
        if not training:
            bot.answer_callback_query(call.id, "Тренировка не найдена")
            return
            
        # Создаем клавиатуру с участниками
        markup = InlineKeyboardMarkup(row_width=1)
        for username in participants:
            button_text = f"@{username}"
            callback_data = f"remove_participant_{training_id}_{username}"
            markup.add(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        # Добавляем кнопку отмены с более специфичным callback_data
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_participant_removal_{training_id}"))
        
        message_text = (
            f"Выберите участника для удаления:\n\n"
            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🏋️‍♂️ Тип: {training.kind}\n"
            f"📍 Место: {training.location}"
        )
        
        # Редактируем существующее сообщение со списком тренировок
        bot.edit_message_text(
            message_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("remove_participant_"))
    def ask_removal_reason(call: CallbackQuery):
        """Запрашивает причину удаления участника"""
        parts = call.data.split("_")
        training_id = int(parts[2])
        username = parts[3]
        
        trainer_db = TrainerDB(call.from_user.username)
            
        # Проверяем, есть ли такой участник
        if not trainer_db.is_participant(username, training_id):
            bot.answer_callback_query(call.id, "❌ Этот пользователь уже не записан на тренировку")
            return
        
        # Удаляем сообщение со списком участников
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        msg = bot.send_message(
            call.message.chat.id,
            f"Введите причину удаления участника @{username}:"
        )
        bot.register_next_step_handler(msg, process_participant_removal, training_id, username)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_participant_removal_"))
    def cancel_participant_removal(call: CallbackQuery):
        """Отменяет процесс удаления участника"""
        try:
            # Возвращаемся к списку тренировок
            trainer_db = TrainerDB(call.from_user.username)
            trainings = []
            training_ids = trainer_db.get_training_ids()
            
            for training_id in training_ids:
                if training := trainer_db.get_training_details(training_id[0]):
                    # Проверяем, есть ли участники в тренировке
                    if trainer_db.get_participants_by_training_id(training_id[0]):
                        trainings.append(training)
            
            if not trainings:
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.answer_callback_query(call.id, "Нет тренировок с участниками")
                return
            
            markup = get_trainings_keyboard(trainings, "remove_from")
            bot.edit_message_text(
                "Выберите тренировку, из которой нужно удалить участника:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            bot.answer_callback_query(call.id, "Отменено")
            
        except Exception as e:
            print(f"Error in cancel_participant_removal: {e}")
            bot.answer_callback_query(call.id, "Произошла ошибка")

    @bot.callback_query_handler(func=lambda call: call.data == "close_training")
    def show_trainings_for_closing(call: CallbackQuery):
        """Показывает список открытых тренировок для закрытия записи"""
        if not admin_db.is_admin(call.from_user.username):
            return
            
        trainer_db = TrainerDB(call.from_user.username)
        # Получаем список открытых тренировок
        training_ids = trainer_db.get_training_ids()
        open_trainings = []
        
        for training_id in training_ids:
            if training := trainer_db.get_training_details(training_id[0]):
                if training.status == "OPEN":
                    open_trainings.append(training)
        
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
            
            # Получаем информацию о тренировке и участниках до закрытия
            training = trainer_db.get_training_details(training_id)
            if not training:
                bot.answer_callback_query(call.id, "Тренировка не найдена")
                return
            
            # Получаем список участников до закрытия
            participants = trainer_db.get_participants_by_training_id(training_id)
            
            # Закрываем запись (это также очистит списки участников)
            trainer_db.set_training_closed(training_id)
            
            # Отправляем уведомление в канал
            topic_id = trainer_db.get_topic_id(training_id)
            if topic_id:
                forum_manager.send_training_update(training, topic_id, "close")
                # Обновляем список участников (теперь пустой) в форуме
                forum_manager.update_participants_list(training, [], topic_id, trainer_db)
            
            # Отправляем уведомления бывшим участникам
            notification = (
                "🔒 Запись на тренировку закрыта:\n\n"
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
            
            bot.answer_callback_query(call.id, "✅ Запись закрыта, список участников очищен")
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
            
        # Удаляем участника
        if trainer_db.remove_participant(username, training_id):
            # Отправляем уведомление удаленному участнику
            if user_id := admin_db.get_user_id(username):
                notification = (
                    "❌ Вы были удалены с тренировки:\n\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ Тип: {training.kind}\n"
                    f"📍 Место: {training.location}\n\n"
                    f"Причина: {reason}"
                )
                try:
                    bot.send_message(user_id, notification)
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {username}: {e}")
            
            bot.reply_to(message, f"✅ Участник @{username} успешно удален")
            
            # Предлагаем место следующему в резерве
            if next_username := trainer_db.offer_spot_to_next_in_reserve(training_id):
                if user_id := admin_db.get_user_id(next_username):
                    markup = InlineKeyboardMarkup()
                    markup.row(
                        InlineKeyboardButton("✅ Принять", callback_data=f"accept_reserve_{training_id}"),
                        InlineKeyboardButton("❌ Отказаться", callback_data=f"decline_reserve_{training_id}")
                    )
                    
                    reserve_notification = (
                        "🎉 Освободилось место на тренировке!\n\n"
                        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                        f"🏋️‍♂️ Тип: {training.kind}\n"
                        f"📍 Место: {training.location}\n\n"
                        "У вас есть 2 часа, чтобы подтвердить участие."
                    )
                    try:
                        bot.send_message(
                            user_id,
                            reserve_notification,
                            reply_markup=markup
                        )
                    except Exception as e:
                        print(f"Ошибка отправки уведомления пользователю из резерва {next_username}: {e}")
            
            # Обновляем список в форуме
            if topic_id := trainer_db.get_topic_id(training_id):
                training = trainer_db.get_training_details(training_id)
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

    # ... остальные обработчики ... 