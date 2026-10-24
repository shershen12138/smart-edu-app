from django.apps import AppConfig


class SchoolConfig(AppConfig):
    name = 'school'

    def ready(self):
        from . import cleanup  # noqa: F401
