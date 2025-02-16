from telebot.types import Message
from new_bot.database.admin import AdminDB
from new_bot.database.trainer import TrainerDB
from new_bot.database.channel import ChannelDB

admin_db = AdminDB()
channel_db = ChannelDB()

def show_user_statistics(message: Message, bot):
    """Показывает статистику пользователя"""
    username = message.from_user.username
    if not username:
        bot.send_message(message.chat.id, "Не удалось определить ваш username")
        return
    
    # Получаем все группы
    groups = channel_db.get_all_channels()
    
    stats = {
        'total_trainings': 0,
        'active_trainings': 0,
        'reserve_count': 0,
        'total_spent': 0,
        'favorite_group': None,
        'favorite_kind': None,
        'group_stats': {},
        'kind_stats': {},
        'auto_signups_balance': 0
    }
    
    # Создаем TrainerDB для работы с балансом пользователя
    user_db = TrainerDB(username)
    stats['auto_signups_balance'] = user_db.get_auto_signups_balance(username)
    
    for group in groups:
        group_id, group_title = group
        admins = admin_db.get_channel_admins(group_id)
        group_trainings = 0
        
        for admin in admins:
            trainer_db = TrainerDB(admin)
            trainings = trainer_db.get_trainings_for_channel(group_id)
            
            for training in trainings:
                if trainer_db.is_participant(username, training.id):
                    stats['total_trainings'] += 1
                    group_trainings += 1
                    if training.status == 'OPEN':
                        stats['active_trainings'] += 1
                    
                    # Подсчет потраченных денег
                    if trainer_db.get_payment_status(username, training.id) == 2:
                        stats['total_spent'] += training.price
                    
                    # Статистика по видам тренировок
                    stats['kind_stats'][training.kind] = stats['kind_stats'].get(training.kind, 0) + 1
                
                # Проверяем резерв
                reserve = trainer_db.get_reserve_list(training.id)
                if any(r[0] == username for r in reserve):
                    stats['reserve_count'] += 1
        
        if group_trainings > 0:
            stats['group_stats'][group_title] = group_trainings
    
    # Определяем любимую группу и вид тренировок
    if stats['group_stats']:
        stats['favorite_group'] = max(stats['group_stats'].items(), key=lambda x: x[1])[0]
    if stats['kind_stats']:
        stats['favorite_kind'] = max(stats['kind_stats'].items(), key=lambda x: x[1])[0]
    
    # Формируем сообщение
    message_text = (
        f"📊 Ваша статистика, @{username}:\n\n"
        f"📅 Тренировки:\n"
        f"▫️ Всего посещений: {stats['total_trainings']}\n"
        f"▫️ Активных записей: {stats['active_trainings']}\n"
        f"▫️ В резерве: {stats['reserve_count']}\n"
        f"🎫 Баланс автозаписей: {stats['auto_signups_balance']}\n\n"
    )
    
    if stats['favorite_group']:
        message_text += (
            f"⭐️ Любимая группа: {stats['favorite_group']}\n"
            f"🏋️‍♂️ Любимый тип: {stats['favorite_kind']}\n"
            f"💰 Всего потрачено: {stats['total_spent']}₽\n\n"
        )
    
    if stats['group_stats']:
        message_text += "📈 Статистика по группам:\n"
        for group, count in sorted(stats['group_stats'].items(), key=lambda x: x[1], reverse=True):
            message_text += f"▫️ {group}: {count}\n"
    
    if stats['kind_stats']:
        message_text += "\n📊 Статистика по видам:\n"
        for kind, count in sorted(stats['kind_stats'].items(), key=lambda x: x[1], reverse=True):
            message_text += f"▫️ {kind}: {count}\n"
    
    bot.send_message(message.chat.id, message_text) 