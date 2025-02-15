from .admin import register_admin_handlers
from .user import register_user_handlers
from .common import register_common_handlers

__all__ = [
    'register_admin_handlers',
    'register_user_handlers',
    'register_common_handlers'
] 