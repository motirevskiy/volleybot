from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from new_bot.database.trainer import TrainerDB
from new_bot.database.admin import AdminDB
from new_bot.database.channel import ChannelDB

admin_db = AdminDB()
channel_db = ChannelDB()

def offer_spot_to_reserve(training_id: int, admin_username: str, bot):
    """Предлагает место следующему в резерве"""
    trainer_db = TrainerDB(admin_username)
    
    # Получаем следующего в резерве
    if next_username := trainer_db.offer_spot_to_next_in_reserve(training_id):
        if user_id := admin_db.get_user_id(next_username):
            # Получаем информацию о тренировке
            training = trainer_db.get_training_details(training_id)
            if not training:
                return
                
            # Получаем информацию о группе
            group = channel_db.get_channel(training.channel_id)
            if not group:
                return
            
            # Удаляем из резерва и добавляем в основной список
            trainer_db.remove_from_reserve(next_username, training_id)
            trainer_db.execute_query('''
                INSERT INTO participants (username, training_id, status, signup_time)
                VALUES (?, ?, 'RESERVE_PENDING', datetime('now'))
            ''', (next_username, training_id))
            
            markup = InlineKeyboardMarkup()
            markup.row(
                InlineKeyboardButton("✅ Принять", callback_data=f"accept_reserve_{training_id}"),
                InlineKeyboardButton("❌ Отказаться", callback_data=f"decline_reserve_{training_id}")
            )
            
            notification = (
                "🎉 Освободилось место на тренировке!\n\n"
                f"👥 Группа: {group[1]}\n"
                f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏋️‍♂️ Тип: {training.kind}\n"
                f"📍 Место: {training.location}\n\n"
                "У вас есть 2 часа, чтобы подтвердить участие"
            )
            try:
                bot.send_message(user_id, notification, reply_markup=markup)
                
                # Обновляем список в форуме
                if topic_id := trainer_db.get_topic_id(training_id):
                    from new_bot.utils.forum_manager import ForumManager
                    forum_manager = ForumManager(bot)
                    participants = trainer_db.get_participants_by_training_id(training_id)
                    forum_manager.update_participants_list(training, participants, topic_id, trainer_db)
                
                return True
            except Exception as e:
                print(f"Error notifying reserve user {next_username}: {e}")
                # В случае ошибки отправки возвращаем в резерв
                trainer_db.execute_query(
                    "DELETE FROM participants WHERE username = ? AND training_id = ?",
                    (next_username, training_id)
                )
                trainer_db.add_to_reserve(next_username, training_id)
    return False 