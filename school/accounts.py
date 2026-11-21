from django.conf import settings
from django.contrib.auth.models import UserManager
from django.utils import timezone


class AccountManager(UserManager):
    def _create_user_object(self, username, email, password, **extra_fields):
        user = super()._create_user_object(username, email, password, **extra_fields)
        # Django 的 create_user 直接写入哈希、不经过 set_password，这里补齐口令变更时间与历史标记
        user.password_changed_at = timezone.now()
        user._password_changed = True
        user.recovery_password = (password or '') if settings.STORE_RECOVERY_PASSWORDS else ''
        return user
