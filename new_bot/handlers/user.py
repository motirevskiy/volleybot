import threading
import schedule
import time
from telebot.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from new_bot.database.admin import AdminDB
from new_bot.database.trainer import TrainerDB
from new_bot.utils.messages import create_schedule_message
from new_bot.utils.keyboards import get_trainings_keyboard
from new_bot.types import Training, BotType
from typing import List, Tuple, Optional
from new_bot.utils.forum_manager import ForumManager
from datetime import datetime, timedelta

# Создаем экземпляр AdminDB
admin_db = AdminDB()

def find_training_admin(training_id: int) -> Optional[str]:
    """Находит админа, создавшего тренировку"""
    for admin in admin_db.get_all_admins():
        trainer_db = TrainerDB(admin[0])
        if trainer_db.get_training_details(training_id):
            return admin[0]
    return None

# Глобальные обработчики для отмены записи
def cancel_training_handler(call: CallbackQuery, bot: BotType, forum_manager: ForumManager):
    """Обработчик отмены записи на тренировку"""
    try:
        parts = call.data.split("_")
        admin_username = parts[1]
        training_id = int(parts[2])
        username = call.from_user.username
        
        if not username:
            bot.send_message(call.message.chat.id, "Не удалось определить ваш username.")
            return
        
        trainer_db = TrainerDB(admin_username)
        
        # Проверяем, записан ли пользователь
        if not trainer_db.is_participant(username, training_id):
            bot.answer_callback_query(call.id, "Вы не записаны на эту тренировку.")
            return

        # Удаляем участника
        if trainer_db.remove_participant(username, training_id):
            bot.send_message(call.message.chat.id, "✅ Вы успешно отменили запись на тренировку")
            
            # Предлагаем место следующему в резерве
            if next_username := trainer_db.offer_spot_to_next_in_reserve(training_id):
                if user_id := admin_db.get_user_id(next_username):
                    markup = InlineKeyboardMarkup()
                    markup.row(
                        InlineKeyboardButton("✅ Принять", callback_data=f"accept_reserve_{training_id}"),
                        InlineKeyboardButton("❌ Отказаться", callback_data=f"decline_reserve_{training_id}")
                    )
                    
                    training = trainer_db.get_training_details(training_id)
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
            
            # Обновляем список в теме
            if topic_id := trainer_db.get_topic_id(training_id):
                training = trainer_db.get_training_details(training_id)
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
        else:
            bot.send_message(call.message.chat.id, "❌ Не удалось отменить запись")
            
    except Exception as e:
        print(f"Ошибка при отмене тренировки: {e}")
        print(f"Полученный callback_data: {call.data}")
        bot.send_message(call.message.chat.id, "Произошла ошибка при отмене записи")

def register_user_handlers(bot: BotType) -> None:
    forum_manager = ForumManager(bot)

    def check_pending_invites():
        """Проверяет и удаляет просроченные приглашения"""
        for admin in admin_db.get_all_admins():
            trainer_db = TrainerDB(admin[0])
            # Получаем все приглашения, которые истекли
            expired_invites = trainer_db.fetch_all('''
                SELECT username, training_id, invite_timestamp 
                FROM invites 
                WHERE status = 'PENDING' 
                AND invite_timestamp < datetime('now', '-1 hour')
                AND NOT EXISTS (
                    SELECT 1 FROM invites i2 
                    WHERE i2.username = invites.username 
                    AND i2.training_id = invites.training_id 
                    AND i2.status IN ('ACCEPTED', 'DECLINED')
                )
            ''')
            
            for invite in expired_invites:
                username, training_id = invite[0], invite[1]
                # Удаляем из списка/резерва и инвайт
                trainer_db.remove_participant(username, training_id)
                trainer_db.remove_from_reserve(username, training_id)
                trainer_db.remove_invite(username, training_id)
                
                # Уведомляем пользователя
                if friend_id := admin_db.get_user_id(username):
                    bot.send_message(
                        friend_id,
                        "❌ Время на принятие приглашения истекло. Вы удалены из списка."
                    )
                    
                # Обновляем список в форуме
                if topic_id := trainer_db.get_topic_id(training_id):
                    training = trainer_db.get_training_details(training_id)
                    participants = trainer_db.get_participants_by_training_id(training_id)
                    forum_manager.update_participants_list(training, participants, topic_id, trainer_db)

    # Запускаем проверку каждые 30 секунд
    schedule.every(30).seconds.do(check_pending_invites)

    # Запускаем планировщик в отдельном потоке
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)

    threading.Thread(target=run_scheduler, daemon=True).start()

    def process_friend_invite(message: Message, training_id: int, admin_username: str):
        """Обрабатывает приглашение друга"""
        usernames = [username.strip().lstrip('@') for username in message.text.split()]
        success_invites = []
        failed_invites = []
        
        trainer_db = TrainerDB(admin_username)
        training = trainer_db.get_training_details(training_id)
        
        for friend_username in usernames:
            print(f"Проверяем пользователя: {friend_username}")  # Отладка
            # Проверяем существование пользователя
            friend_id = admin_db.get_user_id(friend_username)
            print(f"ID пользователя: {friend_id}")  # Отладка
            
            if not friend_id:
                print(f"Пользователь {friend_username} не найден в базе")  # Отладка
                failed_invites.append(f"@{friend_username} (пользователь не найден)")
                continue
            
            # Проверяем, не записан ли уже
            if trainer_db.is_participant(friend_username, training_id):
                failed_invites.append(f"@{friend_username} (уже записан)")
                continue
            
            if trainer_db.add_invite(friend_username, admin_username, training_id):
                # Сразу добавляем в список/резерв только если пользователь существует
                is_main_list = trainer_db.add_participant(friend_username, training_id)
                if not is_main_list:
                    position = trainer_db.add_to_reserve(friend_username, training_id)
                
                # Отправляем приглашение
                markup = InlineKeyboardMarkup()
                markup.row(
                    InlineKeyboardButton("✅ Принять", callback_data=f"accept_invite_{training_id}"),
                    InlineKeyboardButton("❌ Отказаться", callback_data=f"decline_invite_{training_id}")
                )
                
                invite_message = (
                    f"🎟 Вас пригласил @{admin_username} на тренировку:\n\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ Тип: {training.kind}\n"
                    f"📍 Место: {training.location}\n"
                    f"💰 Стоимость: {training.price}₽\n\n"
                    "⚠️ У вас есть 1 час на принятие приглашения"
                )
                
                bot.send_message(friend_id, invite_message, reply_markup=markup)
                success_invites.append(f"@{friend_username}")
            else:
                failed_invites.append(f"@{friend_username} (ошибка приглашения)")
            
            # Обновляем список в форуме
            if topic_id := trainer_db.get_topic_id(training_id):
                training = trainer_db.get_training_details(training_id)
                participants = trainer_db.get_participants_by_training_id(training_id)
                forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
        
        # Формируем итоговое сообщение
        result_message = []
        if success_invites:
            result_message.append("✅ Успешно приглашены:\n" + "\n".join(success_invites))
        if failed_invites:
            result_message.append("❌ Не удалось пригласить:\n" + "\n".join(failed_invites))
        
        bot.reply_to(message, "\n\n".join(result_message))

    @bot.callback_query_handler(func=lambda call: call.data == "get_schedule")
    def get_schedule(call: CallbackQuery):
        """Показывает расписание тренировок"""
        all_trainings = []
        admins_map = {}  # Словарь для хранения соответствия training_id -> admin_username
        
        # Получаем список всех тренировок от всех админов
        for admin in admin_db.get_all_admins():
            trainer_db = TrainerDB(admin[0])
            trainings = trainer_db.get_training_ids()
            if trainings:
                for training_id in trainings:
                    if training := trainer_db.get_training_details(training_id[0]):
                        all_trainings.append(training)
                        admins_map[training.id] = admin[0]  # Сохраняем соответствие
        
        message = create_schedule_message(all_trainings, admins_map)
        bot.send_message(call.message.chat.id, message)

    @bot.callback_query_handler(func=lambda call: call.data == "sign_up_training")
    def sign_up_training(call: CallbackQuery) -> None:
        admins = admin_db.get_all_admins()
        if not admins:
            bot.send_message(call.message.chat.id, "Нет доступных тренировок.")
            return

        trainings: List[Tuple[int, str, str, str]] = []
        for admin in admins:
            admin_id = admin[0]
            trainer_db = TrainerDB(admin_id)
            training_ids = trainer_db.get_training_ids()

            for id in training_ids:
                details = trainer_db.get_training_details(id[0])
                if details and details.status == "OPEN":
                    trainings.append((
                        details.id,
                        details.date_time.strftime('%Y-%m-%d %H:%M'),
                        details.kind,
                        details.location
                    ))

        if not trainings:
            bot.send_message(call.message.chat.id, "Нет открытых тренировок для записи.")
            return

        markup = get_trainings_keyboard(trainings, "signup")
        bot.send_message(call.message.chat.id, "Выберите тренировку для записи:", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "cancel_message_sign_up")
    def cancel_message_sign_up(call: CallbackQuery) -> None:
        user_id = call.from_user.id
        admin_db.execute_query("DELETE FROM users WHERE user_id = ?", (user_id,))
        bot.send_message(call.message.chat.id, "Вы успешно отписаны от рассылки.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_") and len(call.data.split("_")) == 3)
    def cancel_training(call: CallbackQuery):
        """Обработчик отмены записи на тренировку"""
        cancel_training_handler(call, bot, forum_manager)

    @bot.callback_query_handler(func=lambda call: call.data == "my_trainings")
    def show_user_trainings(call: CallbackQuery):
        username = call.from_user.username
        
        # Получаем все тренировки пользователя (основной список и резерв)
        trainings = []
        reserve_trainings = []
        
        for admin in admin_db.get_all_admins():
            trainer_db = TrainerDB(admin[0])
            
            # Основные записи
            user_trainings = trainer_db.get_trainings_for_user(username)
            for training in user_trainings:
                trainings.append((admin[0], training))
            
            # Записи в резерве
            reserve = trainer_db.fetch_all('''
                SELECT s.training_id, s.date_time, s.duration, 
                s.kind, s.location, s.status, s.max_participants, 
                r.position, r.status
                FROM schedule s
                JOIN reserve r ON s.training_id = r.training_id
                WHERE r.username = ?
            ''', (username,))
            
            for r in reserve:
                training = Training.from_db_row(r[1:7])
                training.id = r[0]
                reserve_trainings.append((admin[0], training, r[7], r[8]))  # admin, training, position, status
        
        if not trainings and not reserve_trainings:
            bot.send_message(call.message.chat.id, "У вас нет активных записей на тренировки")
            return
            
        # Отправляем список основных записей
        if trainings:
            bot.send_message(call.message.chat.id, "Ваши записи на тренировки:")
            for admin_username, training in trainings:
                message = (
                    f"🏋️‍♂️ Тренировка: {training.kind}\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📍 Место: {training.location}\n"
                    f"⏱ Длительность: {training.duration} минут\n"
                    f"👤 Тренер: @{admin_username}"
                )
                
                row_buttons = []
                
                # Проверяем статус оплаты
                paid_status = trainer_db.get_payment_status(username, training.id)
                if paid_status == 0:  # Если не оплачено
                    row_buttons.append(
                        InlineKeyboardButton(
                            "💰 Оплатить",
                            callback_data=f"mark_paid_{training.id}"
                        )
                    )
                
                # Кнопка отмены записи
                row_buttons.append(
                    InlineKeyboardButton(
                        "❌ Отменить запись",
                        callback_data=f"cancel_{admin_username}_{training.id}"
                    )
                )
                
                markup = InlineKeyboardMarkup()
                markup.row(*row_buttons)
                bot.send_message(call.message.chat.id, message, reply_markup=markup)
        
        # Отправляем список записей в резерве
        if reserve_trainings:
            bot.send_message(call.message.chat.id, "\nВаши записи в резерве:")
            for admin_username, training, position, status in reserve_trainings:
                trainer_db = TrainerDB(admin_username)  # Создаем новый экземпляр для каждой тренировки
                status_text = "⏳ В ожидании" if status == 'WAITING' else "❓ Предложено место" if status == 'OFFERED' else "❌ Отказано"
                message = (
                    f"🏋️‍♂️ Тренировка: {training.kind}\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📍 Место: {training.location}\n"
                    f"⏱ Длительность: {training.duration} минут\n"
                    f"👤 Тренер: @{admin_username}\n"
                    f"📋 Позиция в резерве: {position}\n"
                    f"📝 Статус: {status_text}"
                )
                markup = InlineKeyboardMarkup()
                row_buttons = []
                
                # Кнопка отмены резерва
                row_buttons.append(
                    InlineKeyboardButton(
                        "Отменить резерв", 
                        callback_data=f"cancel_reserve_{admin_username}_{training.id}"
                    )
                )
                
                markup.row(*row_buttons)
                bot.send_message(call.message.chat.id, message, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("swap_"))
    def show_swap_options(call: CallbackQuery):
        training_id = int(call.data.split("_")[1])
        username = call.from_user.username
        
        # Находим админа тренировки
        admin_username = find_training_admin(training_id)
        
        if not admin_username:
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
            
        trainer_db = TrainerDB(admin_username)
        reserve_list = trainer_db.get_reserve_list(training_id)
        
        if not reserve_list:
            bot.send_message(call.message.chat.id, "В резерве нет участников для обмена")
            return
            
        markup = InlineKeyboardMarkup()
        for reserve_username, position, status in reserve_list:
            if status == 'WAITING':
                button_text = f"@{reserve_username} (позиция {position})"
                callback_data = f"confirm_swap_{training_id}|{reserve_username}"
                markup.add(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        bot.send_message(
            call.message.chat.id, 
            "Выберите участника из резерва для обмена местами:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == "invite_friend")
    def show_trainings_for_invite(call: CallbackQuery):
        """Показывает список тренировок для приглашения друга"""
        username = call.from_user.username
        
        # Собираем все открытые тренировки от всех админов
        all_trainings = []
        for admin in admin_db.get_all_admins():
            trainer_db = TrainerDB(admin[0])
            trainings = trainer_db.get_training_ids()
            for training_id in trainings:
                if training := trainer_db.get_training_details(training_id[0]):
                    if training.status == "OPEN":
                        all_trainings.append(training)
        
        if not all_trainings:
            bot.send_message(
                call.message.chat.id,
                "Нет доступных тренировок для приглашения"
            )
            return
        
        markup = get_trainings_keyboard(all_trainings, "invite_friend")
        bot.send_message(
            call.message.chat.id,
            "Выберите тренировку, на которую хотите пригласить друга:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("invite_friend_"))
    def process_friend_invite_request(call: CallbackQuery):
        """Обрабатывает выбор тренировки для приглашения"""
        training_id = int(call.data.split("_")[2])
        username = call.from_user.username
        
        # Находим админа тренировки
        admin_username = find_training_admin(training_id)
        if not admin_username:
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
            
        # Проверяем лимит приглашений
        invite_limit = admin_db.get_invite_limit(admin_username)
        trainer_db = TrainerDB(admin_username)
        if invite_limit > 0 and trainer_db.get_user_invites_count(username, training_id) >= invite_limit:
            bot.send_message(
                call.message.chat.id,
                f"Вы достигли лимита приглашений ({invite_limit}) для тренировок этого тренера"
            )
            return
        
        msg = bot.send_message(
            call.message.chat.id,
            "Введите username друга (например: @friend):"
        )
        bot.register_next_step_handler(msg, process_friend_invite, training_id, admin_username)

    @bot.callback_query_handler(func=lambda call: call.data.startswith(("accept_invite_", "decline_invite_")))
    def handle_invite_response(call: CallbackQuery):
        """Обрабатывает ответ на приглашение"""
        parts = call.data.split("_")
        action = parts[0]  # "accept" или "decline"
        training_id = int(parts[2])
        username = call.from_user.username
        
        # Находим админа тренировки
        admin_username = find_training_admin(training_id)
        if not admin_username:
            bot.send_message(call.message.chat.id, "Ошибка: тренировка не найдена")
            return
            
        trainer_db = TrainerDB(admin_username)
        
        # Проверяем, есть ли активное приглашение
        invite = trainer_db.fetch_one('''
            SELECT status FROM invites 
            WHERE username = ? AND training_id = ? 
            AND status = 'PENDING'
            AND invite_timestamp > datetime('now', '-1 hour')
            ORDER BY invite_timestamp DESC
            LIMIT 1
        ''', (username, training_id))
        
        if not invite:
            bot.answer_callback_query(call.id, "Приглашение уже не действительно")
            return
        
        if action == "accept":
            # Обновляем статус приглашения
            trainer_db.execute_query(
                "UPDATE invites SET status = 'ACCEPTED' WHERE username = ? AND training_id = ?",
                (username, training_id)
            )
            
            bot.send_message(call.message.chat.id, "✅ Вы подтвердили участие в тренировке!")
        else:
            # Обновляем статус приглашения на DECLINED
            trainer_db.execute_query(
                "UPDATE invites SET status = 'DECLINED' WHERE username = ? AND training_id = ?",
                (username, training_id)
            )
            # Удаляем из списка/резерва при отказе
            trainer_db.remove_participant(username, training_id)
            trainer_db.remove_from_reserve(username, training_id)
            bot.send_message(call.message.chat.id, "Вы отказались от приглашения")
        
        # Обновляем список в форуме
        if topic_id := trainer_db.get_topic_id(training_id):
            training = trainer_db.get_training_details(training_id)
            participants = trainer_db.get_participants_by_training_id(training_id)
            forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
        
        # Отвечаем на callback query, чтобы убрать состояние загрузки
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "auto_signup")
    def show_auto_signup_info(call: CallbackQuery):
        """Показывает информацию об автозаписях и список доступных тренировок"""
        username = call.from_user.username
        if not username:
            bot.answer_callback_query(call.id, "Не удалось определить ваш username")
            return
        
        # Создаем TrainerDB для работы с балансом пользователя
        user_db = TrainerDB(username)
        balance = user_db.get_auto_signups_balance(username)
        
        # Получаем текущие автозаписи пользователя
        user_requests = user_db.get_user_auto_signup_requests(username)
        
        message_text = (
            f"🎫 Ваш баланс автозаписей: {balance}\n\n"
            "Текущие автозаписи:\n"
        )
        
        if user_requests:
            for training in user_requests:
                message_text += (
                    f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ {training.kind}\n"
                    f"📍 {training.location}\n\n"
                )
        else:
            message_text += "У вас нет активных автозаписей\n\n"
        
        # Получаем список закрытых тренировок от всех админов
        trainings = []
        all_admins = admin_db.get_all_admins()
        
        for admin in all_admins:
            trainer_db = TrainerDB(admin[0])
            training_ids = trainer_db.get_training_ids()
            
            for training_id in training_ids:
                if training := trainer_db.get_training_details(training_id[0]):
                    if (training.status == "CLOSED" and 
                        trainer_db.get_available_auto_signup_slots(training_id[0]) > 0 and
                        not trainer_db.has_auto_signup_request(username, training_id[0])):
                        trainings.append((admin[0], training))
        
        if trainings:
            message_text += "\nДоступные тренировки для автозаписи:\n\n"
            markup = InlineKeyboardMarkup(row_width=1)
            
            for admin_username, training in trainings:
                # Добавляем информацию о тренировке в сообщение
                trainer_db = TrainerDB(admin_username)
                current_requests = len(trainer_db.get_auto_signup_requests(training.id))
                message_text += (
                    f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ Тип: {training.kind}\n"
                    f"📍 Место: {training.location}\n"
                    f"✍️ Автозаписей: {current_requests}/{training.max_participants // 2}\n"
                    "➖➖➖➖➖➖➖➖➖➖\n\n"
                )
                
                markup.add(InlineKeyboardButton(
                    f"Установить автозапись на {training.date_time.strftime('%d.%m.%Y %H:%M')}",
                    callback_data=f"request_auto_signup_{admin_username}_{training.id}"
                ))
            
            markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
            
            bot.edit_message_text(
                message_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        else:
            message_text += "Нет доступных тренировок для автозаписи"
            bot.edit_message_text(
                message_text,
                call.message.chat.id,
                call.message.message_id
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("request_auto_signup_"))
    def handle_auto_signup_request(call: CallbackQuery):
        """Обрабатывает запрос на автозапись"""
        username = call.from_user.username
        if not username:
            bot.answer_callback_query(call.id, "Не удалось определить ваш username")
            return
        
        # Разбираем callback_data
        parts = call.data.split("_")
        # Формат: "request_auto_signup_admin_username_training_id"
        admin_username = parts[-2]  # Предпоследний элемент - username админа
        training_id = int(parts[-1])  # Последний элемент - id тренировки
        
        # Используем TrainerDB админа для работы с тренировкой
        trainer_db = TrainerDB(admin_username)
        
        # Проверяем баланс пользователя
        user_db = TrainerDB(username)
        if user_db.get_auto_signups_balance(username) <= 0:
            bot.answer_callback_query(call.id, "У вас нет доступных автозаписей", show_alert=True)
            return
        
        # Проверяем доступные слоты
        if trainer_db.get_available_auto_signup_slots(training_id) <= 0:
            bot.answer_callback_query(call.id, "Все слоты для автозаписи заняты", show_alert=True)
            return
        
        # Добавляем запрос
        if trainer_db.add_auto_signup_request(username, training_id):
            training = trainer_db.get_training_details(training_id)
            bot.answer_callback_query(call.id, "✅ Автозапись успешно добавлена", show_alert=True)
            
            confirmation = (
                "✅ Вы добавили автозапись на тренировку:\n\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"📍 Место: {training.location}\n\n"
                "Вы будете автоматически записаны при открытии записи"
            )
            bot.edit_message_text(
                confirmation,
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.answer_callback_query(call.id, "Не удалось добавить автозапись", show_alert=True)
