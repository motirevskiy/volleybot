from typing import List

class ForumManager:
    def update_participants_list(self, training: Training, participants: List[str], topic_id: int, trainer_db: TrainerDB) -> None:
        """Обновляет список участников в теме"""
        print(f"[DEBUG] Updating participants list. Total participants: {len(participants)}")
        message = f"Список участников ({len(participants)}/{training.max_participants}):\n\n"
        
        for username in participants:
            # Получаем статус участника
            status = trainer_db.get_participant_status(username, training.id)
            print(f"[DEBUG] User {username} status: {status}")
            status_emoji = "⏳" if status == "PENDING" else "✅"
            message += f"{status_emoji} @{username}\n"
        
        print(f"[DEBUG] Final message: {message}")
        
        # Добавляем резервный список
        reserve_list = trainer_db.get_reserve_list(training.id)
        if reserve_list:
            message += "\nРезервный список:\n"
            for username, position, _ in reserve_list:
                message += f"{position}. @{username}\n"
        
        try:
            self.bot.edit_message_text(
                message,
                chat_id=self.chat_id,
                message_id=topic_id,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[ERROR] Error updating participants list: {e}") 