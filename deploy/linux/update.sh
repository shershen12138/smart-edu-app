#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
SITE=/opt/coursejudge
[[ -f "$SITE/.env" && -f "$SITE/scripts/common.sh" ]] || { echo '未找到 /opt/coursejudge 的原 Linux 部署，请先核对目录。'; exit 1; }
source "$SITE/scripts/common.sh"
need_root; need_os; need_engine; load_config
version=$(git -C "$SOURCE" rev-parse --short=12 HEAD 2>/dev/null || date +%Y%m%d%H%M%S)
web_base=$(dc config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["web"]["image"])')
worker_base=$(dc config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["worker"]["image"])')
web_image="coursejudge-web:campus-$version"
worker_image="coursejudge-worker:campus-$version"
printf '先构建新镜像，构建期间原网站继续运行。\n'
docker image inspect "$web_base" "$worker_base" >/dev/null
docker build --pull=false --build-arg "BASE_IMAGE=$web_base" --build-arg RUN_USER=10001:10001 -t "$web_image" -f "$SOURCE/deploy/linux/Dockerfile.update" "$SOURCE"
docker build --pull=false --build-arg "BASE_IMAGE=$worker_base" --build-arg RUN_USER=0 -t "$worker_image" -f "$SOURCE/deploy/linux/Dockerfile.update" "$SOURCE"
lock_run
load_config
network_state current >/dev/null
dc up -d --pull never --wait --wait-timeout 240 db redis
umask 077
backup="$ROOT/backups/update-$(date +%Y%m%d-%H%M%S)-$version"
mkdir -p "$backup"
touch "$ROOT/.paused"
trap 'printf "升级未完成，网站保持暂停，避免继续写入。备份（如已完成）在：%s\n请保留完整报错，不要重新初始化数据库。\n" "$backup" >&2' ERR
dc stop -t 60 web worker beat
dc exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -ucoursejudge --single-transaction --no-tablespaces --set-gtid-purged=OFF coursejudge' > "$backup/database.sql"
[[ -s "$backup/database.sql" ]]
docker run --rm --network none --user 0 -v "${STACK_NAME}_private:/data:ro" -v "$backup:/backup" python:3.12-slim tar czf /backup/private.tar.gz -C /data .
cp "$ROOT/.env" "$ROOT/compose.yaml" "$ROOT/VERSION.txt" "$backup/"
(cd "$backup" && sha256sum database.sql private.tar.gz .env compose.yaml VERSION.txt > SHA256SUMS)
printf '备份完成：%s\n' "$backup"
cp "$SOURCE/deploy/linux/compose.yaml" "$ROOT/compose.yaml"
python3 - "$ROOT/.env" "$web_image" "$worker_image" <<'PY'
import os, sys, tempfile
from pathlib import Path
p = Path(sys.argv[1])
lines = [line for line in p.read_text().splitlines() if not line.startswith(('COURSEJUDGE_WEB_IMAGE=', 'COURSEJUDGE_WORKER_IMAGE='))]
lines += ['COURSEJUDGE_WEB_IMAGE=' + sys.argv[2], 'COURSEJUDGE_WORKER_IMAGE=' + sys.argv[3]]
fd, name = tempfile.mkstemp(dir=p.parent)
with os.fdopen(fd, 'w') as f:
    f.write('\n'.join(lines) + '\n')
os.chmod(name, 0o600)
os.replace(name, p)
PY
dc run --rm --no-deps --user 0 web python manage.py migrate --noinput
dc run --rm --no-deps --user 0 web python manage.py check
dc run --rm --no-deps --user 0 web python manage.py purge_deleted_data --apply --offline
python3 - "$SOURCE" "$ROOT" "$version" <<'PY'
import hashlib, json, shutil, sys
from pathlib import Path
source, site = map(Path, sys.argv[1:3])
for name in ('config', 'school', 'templates', 'static'):
    shutil.copytree(source / name, site / 'app' / name, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
shutil.copy2(source / 'manage.py', site / 'app' / 'manage.py')
(site / 'VERSION.txt').write_text('Ubuntu campus update ' + sys.argv[3] + '\nPreserves the existing network, accounts and data volumes.\n')
# Refresh only the package's existing manifest entries; runtime data is never included.
manifest = site / 'SHA256SUMS'
if manifest.exists():
    rows = []
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = site / name
        if path.is_file():
            rows.append((hashlib.sha256(path.read_bytes()).hexdigest(), name))
    known = {name for _, name in rows}
    for name in ('config', 'school', 'templates', 'static'):
        for path in (site / 'app' / name).rglob('*'):
            rel = path.relative_to(site).as_posix()
            if path.is_file() and '__pycache__' not in path.parts and rel not in known:
                rows.append((hashlib.sha256(path.read_bytes()).hexdigest(), rel))
    manifest.write_text(''.join(digest + '  ' + name + '\n' for digest, name in sorted(rows, key=lambda row: row[1])))
    (site / 'SHA256SUMS.json').write_text(json.dumps([
        {'path': name, 'bytes': (site / name).stat().st_size, 'sha256': digest}
        for digest, name in sorted(rows, key=lambda row: row[1])
    ], ensure_ascii=False, indent=2) + '\n')
PY
start_site
trap - ERR
printf '升级完成；账号、密码和在用数据保留。旧版标记删除的记录已清理；归档内容仍保留。\n'
