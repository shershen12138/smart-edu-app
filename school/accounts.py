from django.conf import settings
from django.contrib.auth.models import UserManager


class AccountManager(UserManager):
    def _create_user_object(self, username, email, password, **extra_fields):
        user = super()._create_user_object(username, email, password, **extra_fields)
        user.recovery_password = (password or '') if settings.STORE_RECOVERY_PASSWORDS else ''
        return user
