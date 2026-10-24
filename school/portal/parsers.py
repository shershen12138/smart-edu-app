"""Read uploaded text and trusted local exercise packages without executing Python."""

import ast
import hashlib
import io
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from django.core.exceptions import ValidationError

from school.storage import save_private

MAX_PACKAGE_FILES = 300
MAX_PACKAGE_EXPANDED = 20 * 1024 * 1024
MAX_PACKAGE_MEMBER = 4 * 1024 * 1024
MAX_MANUAL_SUBMISSION_FILES = 100
MAX_MANUAL_SUBMISSION_EXPANDED = 2 * 1024 * 1024


def decode_text(data):
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError('文件编码无法识别，请另存为 UTF-8。')


def document_text(data, name):
    if len(data) > 2 * 1024 * 1024:
        raise ValidationError('题目说明文件不能超过 2 MB。')
    suffix = Path(name).suffix.lower()
    if suffix in ('.txt', '.md'):
        result = decode_text(data)
    elif suffix == '.docx':
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo('word/document.xml')
                if info.file_size > 4 * 1024 * 1024:
                    raise ValidationError('文档展开后的文本过大。')
                xml = archive.read(info)
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                    raise ValidationError('文档含有不支持的 XML 声明。')
                root = ElementTree.fromstring(xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            result = '\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns))
        except (
            BadZipFile,
            KeyError,
            ElementTree.ParseError,
            EOFError,
            NotImplementedError,
            RuntimeError,
            ZlibError,
        ) as exc:
            raise ValidationError('无法读取 Word 文件，请使用 .docx 格式。') from exc
    else:
        raise ValidationError('说明支持 .txt、.md 或 .docx 文件。')
    if len(result) > 120000 or '\x00' in result:
        raise ValidationError('说明内容过长或含无效字符。')
    return result.strip()


def _safe_zip_files(data, invalid_message, max_files, max_expanded, max_member):
    try:
        archive = ZipFile(io.BytesIO(data))
    except BadZipFile as exc:
        raise ValidationError(invalid_message) from exc
    with archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        if not entries or len(entries) > max_files:
            raise ValidationError('ZIP 文件数量不符合要求。')
        if sum(entry.file_size for entry in entries) > max_expanded:
            raise ValidationError('ZIP 解压后的内容过大。')
        files = {}
        for entry in entries:
            normalized = entry.filename.replace('\\', '/')
            path = PurePosixPath(normalized)
            if (
                path.is_absolute()
                or not path.parts
                or any(part in ('', '.', '..') for part in path.parts)
                or entry.file_size > max_member
                or entry.flag_bits & 1
                or (entry.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValidationError('ZIP 包含不安全的路径、链接、加密文件或超大文件。')
            if path.parts[0] == '__MACOSX' or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            key = path.as_posix()
            if key in files:
                raise ValidationError('ZIP 包含重复路径。')
            try:
                files[key] = archive.read(entry)
            except (BadZipFile, EOFError, NotImplementedError, RuntimeError, ZlibError) as exc:
                raise ValidationError(invalid_message + ' 文件损坏或压缩格式不受支持。') from exc
    return files


def manual_archive_files(data):
    files = _safe_zip_files(
        data,
        '无法读取人工批阅作业ZIP。',
        MAX_PACKAGE_FILES,
        MAX_PACKAGE_EXPANDED,
        MAX_PACKAGE_MEMBER,
    )
    docs = [
        PurePosixPath(path)
        for path in files
        if Path(path).suffix.lower() == '.docx' and not PurePosixPath(path).name.startswith('~$')
    ]
    shallowest = min((len(path.parts) for path in docs), default=0)
    docs = [path for path in docs if len(path.parts) == shallowest]
    if len(docs) != 1:
        raise ValidationError('人工批阅作业ZIP必须且只能包含一份题目DOCX。')
    document = docs[0]
    root = document.parent
    for key in files:
        try:
            PurePosixPath(key).relative_to(root)
        except ValueError as exc:
            raise ValidationError('人工批阅作业ZIP中的文件必须位于同一个章节目录。') from exc
    return files, root, document


def manual_member_choices(data):
    files, root, _ = manual_archive_files(data)
    return [(path, PurePosixPath(path).relative_to(root).as_posix()) for path in sorted(files)]


def replace_manual_member(data, member, replacement):
    files, _, _ = manual_archive_files(data)
    if member not in files:
        raise ValidationError('选择的文件不在当前作业材料中，请刷新后重试。')
    files[member] = replacement
    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        for path, raw in files.items():
            archive.writestr(path, raw)
    return output.getvalue()


def parse_manual_materials_archive(data, name):
    """Read a manual assignment's statement and downloadable resources."""
    if Path(name).suffix.lower() != '.zip':
        raise ValidationError('人工批阅作业材料必须是 .zip 文件。')
    files, root, document = manual_archive_files(data)
    document_raw = files[document.as_posix()]
    document_name = document.name
    description = document_text(document_raw, document_name)
    return {
        'name': root.name if root.name not in ('', '.') else Path(document_name).stem,
        'description': description,
        'document_name': document_name,
        'document_raw': document_raw,
        'digest': hashlib.sha256(data).hexdigest(),
    }


def parse_manual_submission_archive(data, name, required_files):
    """Validate a manual submission and return only the required UTF-8 sources."""
    if Path(name).suffix.lower() != '.zip':
        raise ValidationError('人工批阅作业必须提交 ZIP 文件。')
    files = _safe_zip_files(
        data,
        '无法读取答案ZIP。',
        MAX_MANUAL_SUBMISSION_FILES,
        MAX_MANUAL_SUBMISSION_EXPANDED,
        256 * 1024,
    )
    required = {filename.lower(): filename for filename in required_files}
    matches = {filename: [] for filename in required}
    for path, raw in files.items():
        basename = PurePosixPath(path).name.lower()
        if basename in matches:
            matches[basename].append((PurePosixPath(path), raw))
    missing = [required[key] for key, values in matches.items() if not values]
    duplicates = [required[key] for key, values in matches.items() if len(values) > 1]
    if missing:
        raise ValidationError('答案ZIP缺少：' + '、'.join(missing) + '。')
    if duplicates:
        raise ValidationError('答案ZIP包含重复文件：' + '、'.join(duplicates) + '。')
    parents = {values[0][0].parent.as_posix() for values in matches.values()}
    if len(parents) != 1:
        raise ValidationError('1001.py 至 1005.py 请放在同一目录中。')
    sources = {}
    for key, values in matches.items():
        raw = values[0][1]
        if len(raw) > 128 * 1024:
            raise ValidationError(f'{required[key]} 不能超过 128 KB。')
        source = decode_text(raw)
        if not source.strip() or '\x00' in source:
            raise ValidationError(f'{required[key]} 不能为空或包含无效字符。')
        sources[required[key]] = source
    return {'raw': data, 'sources': sources, 'digest': hashlib.sha256(data).hexdigest()}


def package_archive_files(data):
    """Return safe package files, its chapter root, and paths relative to that root."""
    files = _safe_zip_files(
        data,
        '无法读取 ZIP 批阅包。',
        MAX_PACKAGE_FILES,
        MAX_PACKAGE_EXPANDED,
        MAX_PACKAGE_MEMBER,
    )
    manifests = [
        PurePosixPath(path) for path in files if PurePosixPath(path).name == 'func_info_list.txt'
    ]
    shallowest = min((len(path.parts) for path in manifests), default=0)
    manifests = [path for path in manifests if len(path.parts) == shallowest]
    if len(manifests) != 1:
        raise ValidationError('批阅包必须且只能包含一个 func_info_list.txt。')
    root = manifests[0].parent
    local = {}
    for key, value in files.items():
        path = PurePosixPath(key)
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise ValidationError('批阅包中的文件必须位于同一个章节目录。') from exc
        local[relative.as_posix()] = value
    return files, root, local


def package_member_choices(data):
    files, root, _ = package_archive_files(data)
    return [(path, PurePosixPath(path).relative_to(root).as_posix()) for path in sorted(files)]


def replace_package_member(data, member, replacement):
    files, _, _ = package_archive_files(data)
    if member not in files:
        raise ValidationError('选择的文件不在当前批阅包中，请刷新后重试。')
    files[member] = replacement
    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        for path, raw in files.items():
            archive.writestr(path, raw)
    return output.getvalue()


def parse_package_archive(data, name):
    """Statically parse a teacher ZIP package. Uploaded Python is never executed here."""
    if Path(name).suffix.lower() != '.zip':
        raise ValidationError('自动批阅包必须是 .zip 文件。')
    _, root, local = package_archive_files(data)

    docs = sorted(
        path for path in local if '/' not in path and Path(path).suffix.lower() == '.docx'
    )
    samples = sorted(
        path
        for path in local
        if '/' not in path
        and Path(path).name.lower().startswith('sample')
        and Path(path).suffix.lower() == '.py'
    )
    required = ['gold.py', 'func_info_list.txt']
    if len(docs) != 1 or len(samples) != 1 or any(item not in local for item in required):
        raise ValidationError(
            '批阅包根目录需包含一个题目 DOCX、一个 sample*.py、gold.py 和 func_info_list.txt。'
        )

    document_name = Path(docs[0]).name
    document_raw = local[docs[0]]
    description = document_text(document_raw, document_name)
    sample = decode_text(local[samples[0]])
    reference = decode_text(local['gold.py'])
    try:
        tree = ast.parse(reference)
        signatures = {
            node.name: len(node.args.posonlyargs) + len(node.args.args)
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
    except SyntaxError as exc:
        raise ValidationError('gold.py 存在语法错误。') from exc

    spec = []
    seen = set()
    for number, line in enumerate(decode_text(local['func_info_list.txt']).splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValidationError(f'函数清单第 {number} 行必须是“函数名 分值 用例路径”。')
        function, points, relative = fields
        case_path = PurePosixPath(relative.replace('\\', '/'))
        case_key = case_path.as_posix()
        if (
            case_path.is_absolute()
            or any(part in ('', '.', '..') for part in case_path.parts)
            or case_key not in local
            or function not in signatures
            or not function.isidentifier()
            or function in seen
        ):
            raise ValidationError(f'函数清单第 {number} 行的函数或用例路径无效。')
        try:
            score = int(points)
        except ValueError as exc:
            raise ValidationError(f'函数清单第 {number} 行的分值不是整数。') from exc
        if not 1 <= score <= 1000:
            raise ValidationError('题目分值需为 1～1000。')
        inputs = []
        argc = signatures[function]
        for case_number, raw in enumerate(decode_text(local[case_key]).splitlines(), 1):
            if not raw.strip():
                continue
            try:
                value = ast.literal_eval(raw)
            except (ValueError, SyntaxError, MemoryError, RecursionError) as exc:
                raise ValidationError(
                    f'{function} 第 {case_number} 条用例不是安全的 Python 字面量。'
                ) from exc
            if argc != 1 and (not isinstance(value, (tuple, list)) or len(value) != argc):
                raise ValidationError(f'{function} 第 {case_number} 条用例参数数目不匹配。')
            inputs.append(raw.strip())
        if not inputs:
            raise ValidationError(f'{function} 没有测试用例。')
        spec.append(
            {
                'function': function,
                'points': score,
                'argc': argc,
                'inputs': inputs,
            }
        )
        seen.add(function)
    if not spec:
        raise ValidationError('函数清单不能为空。')

    digest_source = hashlib.sha256()
    for path in sorted(local):
        digest_source.update(path.encode('utf-8'))
        digest_source.update(b'\0')
        digest_source.update(local[path])
        digest_source.update(b'\0')
    digest = digest_source.hexdigest()
    return {
        'name': root.name if root.name not in ('', '.') else Path(document_name).stem,
        'description': description,
        'document_name': document_name,
        'document_raw': document_raw,
        'document_digest': hashlib.sha256(document_raw).hexdigest(),
        'sample': sample,
        'reference': reference,
        'spec': spec,
        'digest': digest,
    }


def load_package(folder):
    """Manifest score column defines each function's full points; inputs are literals."""
    folder = Path(folder).resolve()
    docs = sorted(folder.glob('*.docx'))
    description = document_text(docs[0].read_bytes(), docs[0].name) if docs else ''
    samples = sorted(folder.glob('sample*.py'))
    sample = decode_text(samples[0].read_bytes()) if samples else ''
    reference = (
        decode_text((folder / 'gold.py').read_bytes()) if (folder / 'gold.py').exists() else ''
    )
    manifest = folder / 'func_info_list.txt'
    spec = []
    if manifest.exists() and reference:
        tree = ast.parse(reference)
        signatures = {
            n.name: len(n.args.posonlyargs) + len(n.args.args)
            for n in tree.body
            if isinstance(n, ast.FunctionDef)
        }
        for line in decode_text(manifest.read_bytes()).splitlines():
            if not line.strip():
                continue
            name, points, relative = line.split()
            path = (folder / relative.replace('\\', '/')).resolve()
            if not path.is_relative_to(folder) or name not in signatures or not name.isidentifier():
                raise ValidationError('无效的函数清单或用例路径。')
            inputs = []
            for raw in decode_text(path.read_bytes()).splitlines():
                if not raw.strip():
                    continue
                value = ast.literal_eval(raw)
                argc = signatures[name]
                if argc != 1 and (not isinstance(value, (tuple, list)) or len(value) != argc):
                    raise ValidationError(f'{name} 用例参数数目不匹配。')
                inputs.append(raw)
            if not inputs or not 1 <= int(points) <= 1000:
                raise ValidationError('用例不能为空，分值需为 1～1000。')
            spec.append(
                {
                    'function': name,
                    'points': int(points),
                    'argc': signatures[name],
                    'inputs': inputs,
                }
            )
    digest = hashlib.sha256((description + sample + reference + repr(spec)).encode()).hexdigest()
    return {
        'description': description,
        'spec': spec,
        'digest': digest,
        'document_digest': hashlib.sha256(docs[0].read_bytes()).hexdigest() if docs else '',
        'template_path': save_private(sample, '.py') if sample else '',
        'reference_path': save_private(reference, '.py') if reference else '',
        'note': '' if spec else '本章暂未提供自动批阅配置，可提交文件，批阅结果待接入。',
    }
