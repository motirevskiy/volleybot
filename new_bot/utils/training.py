from typing import Optional
from new_bot.database.admin import AdminDB
from new_bot.database.trainer import TrainerDB
from new_bot.types import Training

admin_db = AdminDB()

def find_training_admin(training_id: int) -> Optional[str]:
    """Находит админа, создавшего тренировку"""
    for admin in admin_db.get_all_admins():
        trainer_db = TrainerDB(admin[0])
        if trainer_db.get_training_details(training_id):
            return admin[0]
    return None 

def format_training_info(training: Training) -> str:
    return (
        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
        f"🏋️‍♂️ Тип: {training.kind}\n"
        f"⏱ Длительность: {training.duration} минут\n"
        f"📍 Место: {training.location}"
    ) 