import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
RUNTIME = BASE_DIR / '.runtime'
RUNTIME.mkdir(exist_ok=True)
DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('生产模式必须配置 SECRET_KEY')
    key_path = RUNTIME / 'dev-secret-key'
    if not key_path.exists():
        from django.core.management.utils import get_random_secret_key

        key_path.write_text(get_random_secret_key(), encoding='utf-8')
    SECRET_KEY = key_path.read_text(encoding='utf-8')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(',')
CSRF_TRUSTED_ORIGINS = [v for v in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if v]
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'school',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'school.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'school.context.common',
            ]
        },
    }
]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {
    'default': dj_database_url.parse(
        os.getenv('DATABASE_URL') or f'sqlite:///{RUNTIME / "db.sqlite3"}', conn_max_age=60
    )
}
if DATABASES['default']['ENGINE'].endswith('mysql'):
    DATABASES['default']['OPTIONS'] = {
        'charset': 'utf8mb4',
        'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
    }
else:
    DATABASES['default']['OPTIONS'] = {'timeout': 30}
AUTH_USER_MODEL = 'school.User'
# 暂按试用要求取消密码复杂度校验，首次登录改密与确认密码检查仍保留。
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG and os.getenv('HTTPS_REDIRECT', 'true') == 'true'
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
if os.getenv('TRUST_PROXY', 'false') == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
PRIVATE_STORAGE = Path(os.getenv('PRIVATE_STORAGE', str(RUNTIME / 'private'))).resolve()
PRIVATE_STORAGE.mkdir(parents=True, exist_ok=True)
JUDGE_HOST_STORAGE = os.getenv('JUDGE_HOST_STORAGE', str(PRIVATE_STORAGE))
JUDGE_IMAGE = os.getenv('JUDGE_IMAGE', 'python:3.12-slim')
JUDGE_CONTAINER_START_GRACE_SECONDS = float(
    os.getenv('JUDGE_CONTAINER_START_GRACE_SECONDS', '10')
)
COURSEWORK_CASE_TIME_MS = int(os.getenv('COURSEWORK_CASE_TIME_MS', '2000'))
COURSEWORK_SUBMISSION_TIME_MS = int(os.getenv('COURSEWORK_SUBMISSION_TIME_MS', '30000'))

# 题目分析智能体：OpenAI 兼容的对话补全端点。
# 未配置时必须走规则兜底并在结果中标注来源，不能把兜底结果当成模型结论。
LLM_BASE_URL = os.getenv('LLM_BASE_URL', '').rstrip('/')
LLM_API_KEY = os.getenv('LLM_API_KEY', '')
LLM_MODEL = os.getenv('LLM_MODEL', '')
LLM_TIMEOUT = float(os.getenv('LLM_TIMEOUT', '60'))
# 个性化训练：知识点得分率低于该阈值视为弱项，触发训练题智能体出题。
PRACTICE_WEAK_THRESHOLD = float(os.getenv('PRACTICE_WEAK_THRESHOLD', '0.6'))
STORE_RECOVERY_PASSWORDS = os.getenv('STORE_RECOVERY_PASSWORDS', '1' if DEBUG else '0') == '1'
REDIS_URL = os.getenv('REDIS_URL', '')
CELERY_BROKER_URL = REDIS_URL or 'redis://127.0.0.1:6379/0'
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BEAT_SCHEDULE = {
    'dispatch-pending': {'task': 'school.tasks.dispatch_pending', 'schedule': 15.0}
}
if REDIS_URL:
    CACHES = {
        'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
            'LOCATION': RUNTIME / 'cache',
        }
    }

# 日志：项目与智能体模块的告警统一输出到控制台（运行时重定向到 .runtime 下的日志文件）。
# DEBUG 环境默认 INFO 便于开发排查，生产用环境变量 LOG_LEVEL 调整。
# ERROR 及以上级别（含 Django 未捕获异常的完整堆栈）额外写入轮转的异常日志文件
# .runtime/logs/exception.log，便于事后排查判题、批阅与大模型调用中的未预期异常。
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO' if DEBUG else 'WARNING')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'console'},
    },
    'loggers': {
        'school': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'tools': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}

try:
    _LOG_DIR = RUNTIME / 'logs'
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOGGING['handlers']['exception_file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': str(_LOG_DIR / 'exception.log'),
        'maxBytes': 10 * 1024 * 1024,
        'backupCount': 5,
        'encoding': 'utf-8',
        'level': 'ERROR',
        'formatter': 'console',
    }
    for _logger_name in ('school', 'tools', 'django'):
        # django.request 以 ERROR 记录视图里的未捕获异常，同样落盘
        if _logger_name not in LOGGING['loggers']:
            LOGGING['loggers'][_logger_name] = {
                'handlers': [], 'level': 'ERROR', 'propagate': False
            }
        LOGGING['loggers'][_logger_name]['handlers'].append('exception_file')
except OSError:
    # 文件系统只读等情况下降级为仅控制台输出。
    pass
