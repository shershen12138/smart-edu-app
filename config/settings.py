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
    'school.sql_guard.SqlInjectionGuardMiddleware',
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
# 三级等保：口令至少 8 位，且包含大写字母、小写字母、数字、特殊字符中的至少三类。
# 修改密码、管理员重置、批量导入和命令行建号共用这一套校验器。
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {
        'NAME': 'school.password_policy.PasswordComplexityValidator',
        'OPTIONS': {'min_length': 8, 'min_character_classes': 3},
    },
]
# 三级等保 8.1.4.1 a)b)：口令有效期、历史口令、登录失败阈值与长期未登录停用。
PASSWORD_MAX_AGE_DAYS = int(os.getenv('PASSWORD_MAX_AGE_DAYS', '90'))
PASSWORD_HISTORY_COUNT = int(os.getenv('PASSWORD_HISTORY_COUNT', '5'))
LOGIN_FAIL_LIMIT = int(os.getenv('LOGIN_FAIL_LIMIT', '5'))
LOGIN_FAIL_WINDOW = int(os.getenv('LOGIN_FAIL_WINDOW', '600'))
INACTIVE_ACCOUNT_DAYS = int(os.getenv('INACTIVE_ACCOUNT_DAYS', '90'))
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
# 会话空闲 30 分钟自动失效（每次请求刷新有效期），关闭浏览器即失效。
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', '1800'))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = (
    os.getenv('SESSION_EXPIRE_AT_BROWSER_CLOSE', 'true').lower() == 'true'
)
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
# 三级等保 8.1.4.4：GET 查询串中的 SQL 注入特征检测；排障时可临时设为 false。
# 表单与代码内容不参与判断，正常的 SQL 关键字检索不会被拦截。
SQL_GUARD_ENABLED = os.getenv('SQL_GUARD_ENABLED', 'true').lower() == 'true'
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

# 大模型：不再保存项目级端点与密钥。每位用户在“大模型配置”弹窗里
# 填写自己的服务商、接口地址、模型与 API Key（存 UserLLMConfig），
# 未配置时只能走规则兜底并在结果中标明来源。
LLM_TIMEOUT = float(os.getenv('LLM_TIMEOUT', '60'))
# 保存大模型配置前先发一次最小请求，确认接口地址与 API Key 可用；
# 失败时不落库，教师端弹出错误弹窗。离线/自动化测试可用环境变量关闭。
LLM_VERIFY_ON_SAVE = os.getenv('LLM_VERIFY_ON_SAVE', 'true').lower() == 'true'
LLM_VERIFY_TIMEOUT = float(os.getenv('LLM_VERIFY_TIMEOUT', '20'))
# 个性化训练：知识点得分率低于该阈值视为弱项，触发训练题智能体出题。
PRACTICE_WEAK_THRESHOLD = float(os.getenv('PRACTICE_WEAK_THRESHOLD', '0.6'))
# 口令恢复副本默认不保存（8.1.4.7 鉴别数据保密性）；确需开启时按字段加密落库。
STORE_RECOVERY_PASSWORDS = os.getenv('STORE_RECOVERY_PASSWORDS', '0') == '1'
# 字段级加密密钥；留空则由 SECRET_KEY 派生，生产建议独立配置并纳入密钥管理。
FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY', '')
# 审计日志外发文件（JSON Lines，供日志平台集中收集）；留空表示只写数据库。
AUDIT_LOG_FILE = os.getenv('AUDIT_LOG_FILE', '')
# 双因素：开启后管理员/教师未绑定动态口令将被引导到绑定页（8.1.4.1 b)）。
TOTP_ENFORCE = os.getenv('TOTP_ENFORCE', '0') == '1'
TOTP_REQUIRED_ROLES = tuple(
    role.strip()
    for role in os.getenv(
        'TOTP_REQUIRED_ROLES', 'admin,security_admin,audit_admin,teacher'
    ).split(',')
    if role.strip()
)
REDIS_URL = os.getenv('REDIS_URL', '')
CELERY_BROKER_URL = REDIS_URL or 'redis://127.0.0.1:6379/0'
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BEAT_SCHEDULE = {
    'dispatch-pending': {'task': 'school.tasks.dispatch_pending', 'schedule': 15.0},
    # 每日停用长期未登录的普通账号（8.1.4.2 a)）
    'deactivate-stale-accounts': {
        'task': 'school.tasks.deactivate_stale_accounts',
        'schedule': 86400.0,
    },
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
