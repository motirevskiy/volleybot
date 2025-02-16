import threading
import schedule
import time
from telebot.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from new_bot.database.admin import AdminDB
from new_bot.database.trainer import TrainerDB
from new_bot.database.channel import ChannelDB
from new_bot.utils.messages import create_schedule_message
from new_bot.utils.keyboards import get_trainings_keyboard
from new_bot.types import Training, BotType
from typing import List, Tuple, Optional
from new_bot.utils.forum_manager import ForumManager
from datetime import datetime, timedelta
from new_bot.utils.reserve import offer_spot_to_reserve

# Создаем экземпляры баз данных
admin_db = AdminDB()
channel_db = ChannelDB()

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

        bot.delete_message(call.message.chat.id, call.message.message_id)

        
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
            offer_spot_to_reserve(training_id, admin_username, bot)
            
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
        
        # Получаем информацию о группе
        group = channel_db.get_channel(training.channel_id)
        if not group:
            bot.reply_to(message, "❌ Ошибка: группа не найдена")
            return
        
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
                
                notification = (
                    f"🎟 @{admin_username} приглашает вас на тренировку!\n\n"
                    f"👥 Группа: {group[1]}\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ Тип: {training.kind}\n"
                    f"📍 Место: {training.location}\n\n"
                    "У вас есть 2 часа, чтобы принять приглашение"
                )
                
                bot.send_message(friend_id, notification, reply_markup=markup)
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
        """Показывает список доступных групп"""
        # Получаем список всех групп
        groups = channel_db.get_all_channels()
        if not groups:
            bot.send_message(call.message.chat.id, "Нет доступных групп с тренировками")
            return

        # Создаем клавиатуру с группами
        markup = InlineKeyboardMarkup()
        for group_id, title in groups:
            markup.add(InlineKeyboardButton(
                title,
                callback_data=f"schedule_group_{group_id}"
            ))

        bot.send_message(
            call.message.chat.id,
            "Выберите группу для просмотра расписания:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("schedule_group_"))
    def show_group_schedule(call: CallbackQuery):
        """Показывает расписание тренировок выбранной группы"""
        group_id = int(call.data.split("_")[2])
        
        # Получаем информацию о группе
        group = channel_db.get_channel(group_id)
        if not group:
            bot.answer_callback_query(call.id, "Группа не найдена")
            return

        # Получаем список администраторов группы
        admins = admin_db.get_channel_admins(group_id)
        
        all_trainings = []
        for admin in admins:
            trainer_db = TrainerDB(admin)
            trainings = trainer_db.get_trainings_for_channel(group_id)
            all_trainings.extend(trainings)

        if not all_trainings:
            bot.send_message(
                call.message.chat.id,
                f"В группе {group[1]} пока нет тренировок"
            )
            return

        # Сортируем тренировки по дате
        all_trainings.sort(key=lambda x: x.date_time)
        
        message = f"Расписание тренировок группы {group[1]}:\n\n"
        for training in all_trainings:
            message += (
                f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ {training.kind}\n"
                f"⏱ {training.duration} минут\n"
                f"📍 {training.location}\n"
                f"💰 {training.price}₽\n"
                f"👥 Участники: {len(trainer_db.get_participants_by_training_id(training.id))}/{training.max_participants}\n"
                f"📝 Статус: {'Открыта' if training.status == 'OPEN' else 'Закрыта'}\n"
                "➖➖➖➖➖➖➖➖➖➖\n"
            )

        bot.send_message(call.message.chat.id, message)

    @bot.callback_query_handler(func=lambda call: call.data == "sign_up_training")
    def show_groups_for_signup(call: CallbackQuery):
        """Показывает список групп для записи на тренировку"""
        groups = channel_db.get_all_channels()
        if not groups:
            bot.send_message(call.message.chat.id, "Нет доступных групп с тренировками")
            return

        markup = InlineKeyboardMarkup()
        for group_id, title in groups:
            # Проверяем, есть ли открытые тренировки в группе
            has_open_trainings = False
            admins = admin_db.get_channel_admins(group_id)
            for admin in admins:
                trainer_db = TrainerDB(admin)
                trainings = trainer_db.get_trainings_for_channel(group_id)
                if any(t.status == "OPEN" for t in trainings):
                    has_open_trainings = True
                    break

            if has_open_trainings:
                markup.add(InlineKeyboardButton(
                    title,
                    callback_data=f"signup_group_{group_id}"
                ))

        if not markup.keyboard:
            bot.send_message(call.message.chat.id, "Нет групп с открытыми тренировками")
            return

        bot.send_message(
            call.message.chat.id,
            "Выберите группу для записи на тренировку:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("signup_group_"))
    def show_group_trainings_for_signup(call: CallbackQuery):
        """Показывает список тренировок для записи в выбранной группе"""
        group_id = int(call.data.split("_")[2])
        
        # Получаем информацию о группе
        group = channel_db.get_channel(group_id)
        if not group:
            bot.answer_callback_query(call.id, "Группа не найдена")
            return
        
        # Получаем список открытых тренировок для группы
        open_trainings = []
        admins = admin_db.get_channel_admins(group_id)
        
        for admin in admins:
            trainer_db = TrainerDB(admin)
            trainings = trainer_db.get_trainings_for_channel(group_id)
            for training in trainings:
                if training.status == "OPEN":
                    open_trainings.append((training, admin))
        
        if not open_trainings:
            bot.send_message(
                call.message.chat.id,
                f"В группе {group[1]} нет открытых тренировок"
            )
            return
        
        # Создаем клавиатуру с тренировками
        markup = InlineKeyboardMarkup()
        for training, admin in open_trainings:
            participants = trainer_db.get_participants_by_training_id(training.id)
            button_text = (
                f"{training.date_time.strftime('%d.%m %H:%M')} | "
                f"{training.kind} | "
                f"{len(participants)}/{training.max_participants}"
            )
            markup.add(InlineKeyboardButton(
                button_text,
                callback_data=f"signup_training_{admin}_{training.id}"
            ))
        
        bot.edit_message_text(
            f"Доступные тренировки в группе {group[1]}:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("signup_training_"))
    def process_training_signup(call: CallbackQuery):
        """Обрабатывает запись на тренировку"""
        parts = call.data.split("_")
        admin_username = parts[2]
        training_id = int(parts[3])
        
        # Остальной код обработки записи...

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
        
        # Получаем все группы
        groups = channel_db.get_all_channels()
        all_trainings = []
        all_reserve_trainings = []
        
        for group in groups:
            group_id, group_title = group
            admins = admin_db.get_channel_admins(group_id)
            
            for admin in admins:
                trainer_db = TrainerDB(admin)
                
                # Основные записи
                trainings = trainer_db.get_trainings_for_channel(group_id)
                for training in trainings:
                    if trainer_db.is_participant(username, training.id):
                        all_trainings.append((group_title, admin, training))
                
                # Записи в резерве
                reserve = trainer_db.fetch_all('''
                    SELECT s.training_id, s.date_time, s.duration, 
                    s.kind, s.location, s.status, s.max_participants, 
                    r.position, r.status
                    FROM schedule s
                    JOIN reserve r ON s.training_id = r.training_id
                    WHERE r.username = ? AND s.channel_id = ?
                ''', (username, group_id))
                
                for r in reserve:
                    training = Training.from_db_row(r[1:7])
                    training.id = r[0]
                    training.channel_id = group_id
                    all_reserve_trainings.append((group_title, admin, training, r[7], r[8]))
        
        if not all_trainings and not all_reserve_trainings:
            bot.send_message(call.message.chat.id, "У вас нет активных записей на тренировки")
            return
        
        # Отправляем список основных записей
        if all_trainings:
            bot.send_message(call.message.chat.id, "Ваши записи на тренировки:")
            for group_title, admin_username, training in all_trainings:
                message = (
                    f"👥 Группа: {group_title}\n"
                    f"🏋️‍♂️ Тренировка: {training.kind}\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📍 Место: {training.location}\n"
                    f"⏱ Длительность: {training.duration} минут\n"
                    f"👤 Тренер: @{admin_username}"
                )
                
                trainer_db = TrainerDB(admin_username)
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
        if all_reserve_trainings:
            bot.send_message(call.message.chat.id, "\nВаши записи в резерве:")
            for group_title, admin_username, training, position, status in all_reserve_trainings:
                status_text = (
                    "⏳ В ожидании" if status == 'WAITING' 
                    else "❓ Предложено место" if status == 'OFFERED' 
                    else "❌ Отказано"
                )
                message = (
                    f"👥 Группа: {group_title}\n"
                    f"🏋️‍♂️ Тренировка: {training.kind}\n"
                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"📍 Место: {training.location}\n"
                    f"⏱ Длительность: {training.duration} минут\n"
                    f"👤 Тренер: @{admin_username}\n"
                    f"📋 Позиция в резерве: {position}\n"
                    f"📝 Статус: {status_text}"
                )
                
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton(
                    "Отменить резерв", 
                    callback_data=f"cancel_reserve_{admin_username}_{training.id}"
                ))
                
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
    def show_groups_for_invite(call: CallbackQuery):
        """Показывает список групп для приглашения друга"""
        groups = channel_db.get_all_channels()
        if not groups:
            bot.send_message(call.message.chat.id, "Нет доступных групп с тренировками")
            return

        markup = InlineKeyboardMarkup()
        for group_id, title in groups:
            # Проверяем, есть ли открытые тренировки в группе
            has_open_trainings = False
            admins = admin_db.get_channel_admins(group_id)
            for admin in admins:
                trainer_db = TrainerDB(admin)
                trainings = trainer_db.get_trainings_for_channel(group_id)
                if any(t.status == "OPEN" for t in trainings):
                    has_open_trainings = True
                    break

            if has_open_trainings:
                markup.add(InlineKeyboardButton(
                    title,
                    callback_data=f"invite_group_{group_id}"
                ))

        if not markup.keyboard:
            bot.send_message(call.message.chat.id, "Нет групп с открытыми тренировками")
            return

        bot.send_message(
            call.message.chat.id,
            "Выберите группу для приглашения друга:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("invite_group_"))
    def show_group_trainings_for_invite(call: CallbackQuery):
        """Показывает список тренировок в группе для приглашения"""
        group_id = int(call.data.split("_")[2])
        
        # Получаем информацию о группе
        group = channel_db.get_channel(group_id)
        if not group:
            bot.answer_callback_query(call.id, "Группа не найдена")
            return

        # Получаем список открытых тренировок
        admins = admin_db.get_channel_admins(group_id)
        open_trainings = []
        
        for admin in admins:
            trainer_db = TrainerDB(admin)
            trainings = trainer_db.get_trainings_for_channel(group_id)
            for training in trainings:
                if training.status == "OPEN":
                    # Добавляем информацию об админе к тренировке
                    open_trainings.append((training, admin))

        if not open_trainings:
            bot.send_message(
                call.message.chat.id,
                f"В группе {group[1]} нет открытых тренировок"
            )
            return

        # Создаем клавиатуру с тренировками
        markup = InlineKeyboardMarkup()
        for training, admin in open_trainings:
            button_text = (
                f"{training.date_time.strftime('%d.%m.%Y %H:%M')} | "
                f"{training.kind} | {training.location}"
            )
            markup.add(InlineKeyboardButton(
                button_text,
                callback_data=f"invite_training_{training.id}_{admin}"
            ))

        bot.send_message(
            call.message.chat.id,
            f"Выберите тренировку в группе {group[1]} для приглашения друга:",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("invite_training_"))
    def process_training_invite_request(call: CallbackQuery):
        """Обрабатывает выбор тренировки для приглашения"""
        parts = call.data.split("_")
        training_id = int(parts[2])
        admin_username = parts[3]
        username = call.from_user.username
        
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
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        # Отвечаем на callback query, чтобы убрать состояние загрузки
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "auto_signup")
    def show_auto_signup_info(call: CallbackQuery):
        """Показывает информацию об автозаписях и список доступных групп"""
        username = call.from_user.username
        if not username:
            bot.answer_callback_query(call.id, "Не удалось определить ваш username")
            return
        
        # Создаем TrainerDB для работы с балансом пользователя
        user_db = TrainerDB(username)
        balance = user_db.get_auto_signups_balance(username)
        
        # Получаем текущие автозаписи пользователя по всем группам
        message_text = f"🎫 Ваш баланс автозаписей: {balance}\n\nТекущие автозаписи:\n"
        
        # Получаем все группы
        groups = channel_db.get_all_channels()
        current_auto_signups = []
        
        for group in groups:
            group_id, group_title = group
            admins = admin_db.get_channel_admins(group_id)
            
            for admin in admins:
                trainer_db = TrainerDB(admin)
                trainings = trainer_db.get_trainings_for_channel(group_id)
                for training in trainings:
                    if trainer_db.has_auto_signup_request(username, training.id):
                        current_auto_signups.append((group_title, training))
        
        if current_auto_signups:
            for group_title, training in current_auto_signups:
                message_text += (
                    f"👥 Группа: {group_title}\n"
                    f"📅 {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"🏋️‍♂️ {training.kind}\n"
                    f"📍 {training.location}\n\n"
                )
        else:
            message_text += "У вас нет активных автозаписей\n\n"
        
        # Создаем клавиатуру с группами для новой автозаписи
        markup = InlineKeyboardMarkup()
        for group_id, title in groups:
            # Проверяем наличие закрытых тренировок с доступными слотами для автозаписи
            has_available_trainings = False
            admins = admin_db.get_channel_admins(group_id)
            
            for admin in admins:
                trainer_db = TrainerDB(admin)
                trainings = trainer_db.get_trainings_for_channel(group_id)
                for training in trainings:
                    if (training.status == "CLOSED" and 
                        trainer_db.get_available_auto_signup_slots(training.id) > 0 and
                        not trainer_db.has_auto_signup_request(username, training.id)):
                        has_available_trainings = True
                        break
            if has_available_trainings:
                markup.add(InlineKeyboardButton(
                    title,
                    callback_data=f"auto_signup_group_{group_id}"
                ))
        
        if markup.keyboard:
            message_text += "Выберите группу для новой автозаписи:"
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

    @bot.callback_query_handler(func=lambda call: call.data.startswith("auto_signup_group_"))
    def show_group_trainings_for_auto_signup(call: CallbackQuery):
        """Показывает список тренировок для автозаписи в выбранной группе"""
        group_id = int(call.data.split("_")[3])
        username = call.from_user.username
        
        # Получаем информацию о группе
        group = channel_db.get_channel(group_id)
        if not group:
            bot.answer_callback_query(call.id, "Группа не найдена")
            return
        
        # Получаем список тренировок для автозаписи
        available_trainings = []
        admins = admin_db.get_channel_admins(group_id)
        
        for admin in admins:
            trainer_db = TrainerDB(admin)
            trainings = trainer_db.get_trainings_for_channel(group_id)
            for training in trainings:
                if (training.status == "CLOSED" and 
                    trainer_db.get_available_auto_signup_slots(training.id) > 0 and
                    not trainer_db.has_auto_signup_request(username, training.id)):
                    available_trainings.append((training, admin))
        
        if not available_trainings:
            bot.send_message(
                call.message.chat.id,
                f"В группе {group[1]} нет доступных тренировок для автозаписи"
            )
            return
        
        # Отправляем заголовок
        bot.edit_message_text(
            f"Доступные тренировки для автозаписи в группе {group[1]}:",
            call.message.chat.id,
            call.message.message_id
        )
        
        # Отправляем информацию о каждой тренировке отдельным сообщением
        for training, admin in available_trainings:
            current_requests = len(trainer_db.get_auto_signup_requests(training.id))
            available_slots = training.max_participants // 2
            
            # Создаем клавиатуру для конкретной тренировки
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(
                "🎫 Добавить автозапись",
                callback_data=f"request_auto_signup_{admin}_{training.id}"
            ))
            
            # Формируем сообщение с информацией о тренировке
            message = (
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"⏱ Длительность: {training.duration} минут\n"
                f"📍 Место: {training.location}\n"
                f"👥 Автозаписи: {current_requests}/{available_slots}\n"
            )
            
            bot.send_message(
                call.message.chat.id,
                message,
                reply_markup=markup
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
        admin_username = parts[3]  # username админа
        training_id = int(parts[4])  # id тренировки
        
        # Используем TrainerDB админа для работы с тренировкой
        trainer_db = TrainerDB(admin_username)
        
        # Получаем информацию о тренировке
        training = trainer_db.get_training_details(training_id)
        if not training:
            bot.answer_callback_query(call.id, "Тренировка не найдена", show_alert=True)
            return
        
        # Получаем информацию о группе
        group = channel_db.get_channel(training.channel_id)
        if not group:
            bot.answer_callback_query(call.id, "Группа не найдена", show_alert=True)
            return
        
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
            bot.answer_callback_query(call.id, "✅ Автозапись успешно добавлена", show_alert=True)
            
            confirmation = (
                "✅ Вы добавили автозапись на тренировку:\n\n"
                f"👥 Группа: {group[1]}\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"📍 Место: {training.location}\n\n"
                "Вы будете автоматически записаны при открытии записи"
            )
            
            # Обновляем сообщение с информацией об автозаписях
            show_auto_signup_info(call)
            
            # Отправляем отдельное сообщение с подтверждением
            bot.send_message(call.message.chat.id, confirmation)
        else:
            bot.answer_callback_query(call.id, "Не удалось добавить автозапись", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith(("accept_reserve_", "decline_reserve_")))
    def handle_reserve_response(call: CallbackQuery):
        """Обрабатывает ответ на предложение места из резерва"""
        parts = call.data.split("_")
        action = parts[0]  # "accept" или "decline"
        training_id = int(parts[2])
        username = call.from_user.username
        
        # Находим админа тренировки
        admin_username = find_training_admin(training_id)
        if not admin_username:
            bot.answer_callback_query(call.id, "Тренировка не найдена")
            return
        
        trainer_db = TrainerDB(admin_username)
        
        if action == "accept":
            if trainer_db.accept_reserve_spot(username, training_id):
                message = "✅ Вы подтвердили участие в тренировке!"
            else:
                message = "❌ Не удалось подтвердить участие"
        else:
            trainer_db.remove_from_reserve(username, training_id)
            message = "Вы отказались от участия в тренировке"
        
        # Обновляем список в форуме
        if topic_id := trainer_db.get_topic_id(training_id):
            training = trainer_db.get_training_details(training_id)
            participants = trainer_db.get_participants_by_training_id(training_id)
            forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
        
        # Отправляем сообщение и удаляем исходное сообщение с кнопками
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, message)
        bot.delete_message(call.message.chat.id, call.message.message_id)
