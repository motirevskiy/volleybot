from typing import Optional
from new_bot.database.admin import AdminDB
from new_bot.database.trainer import TrainerDB

admin_db = AdminDB()

def find_training_admin(training_id: int) -> Optional[str]:
    """Находит админа, создавшего тренировку"""
    for admin in admin_db.get_all_admins():
        trainer_db = TrainerDB(admin[0])
        if trainer_db.get_training_details(training_id):
            return admin[0]
    return None 