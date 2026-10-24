import csv
import io
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse
from django.shortcuts import redirect

from school.services import audit

from .common_views import safe_csv, work_for
from .parsers import parse_manual_submission_archive
from .reporting_services import roster_rows


def filename_part(value):
    return re.sub(r'[^\w\-\u4e00-\u9fff]', '_', str(value))[:60] or 'student'


def _student_directory(student, entry):
    number = student.student_no or student.username
    return f'{filename_part(number)}_{filename_part(student.full_name)}_第{entry.sequence}次'


def _manual_members(archive, path, directory, entry):
    required = entry.snapshot.get('required_files') or [
        f'{number}.py' for number in range(1001, 1006)
    ]
    parsed = parse_manual_submission_archive(path.read_bytes(), path.name, required)
    members = []
    for name in required:
        source_name = Path(name).name
        member = (
            f'{directory}/{filename_part(Path(source_name).stem)}{Path(source_name).suffix.lower()}'
        )
        archive.writestr(member, parsed['sources'][name])
        members.append(member)
    return members


@login_required
def submissions_download(request, pk):
    work = work_for(request.user, pk, 'export')
    rows, _ = roster_rows(work)
    if not any(row['entry'] for row in rows):
        messages.info(request, '本班尚无学生提交，暂时没有可下载的文件。')
        return redirect('work_results', pk=pk)
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115 -- FileResponse owns it
    root = settings.PRIVATE_STORAGE.resolve()
    report = io.StringIO()
    writer = csv.writer(report)
    writer.writerow(['学号', '姓名', '提交次数序号', '批阅状态', '打包结果', '包内文件'])
    directories = set()
    try:
        with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
            for row in rows:
                student, entry = row['student'], row['entry']
                members, status = [], '未提交'
                if entry:
                    path = (root / entry.source_path).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        status = '文件缺失，请联系管理员'
                    else:
                        directory = _student_directory(student, entry)
                        base_directory = directory
                        suffix = 0
                        while directory.casefold() in directories:
                            suffix += 1
                            directory = f'{base_directory}_id{student.pk}_{suffix}'
                        directories.add(directory.casefold())
                        if work.grading_mode == 'manual':
                            try:
                                members = _manual_members(archive, path, directory, entry)
                                status = '已展开并打包'
                            except (OSError, ValidationError):
                                status = '答案ZIP损坏或结构无效，请联系管理员'
                        else:
                            source_name = filename_part(student.student_no or student.username)
                            member = f'{directory}/{source_name}.py'
                            archive.write(path, member)
                            members = [member]
                            status = '已打包'
                writer.writerow(
                    [
                        safe_csv(value)
                        for value in [
                            student.student_no,
                            student.full_name,
                            entry.sequence if entry else '',
                            entry.get_status_display() if entry else '未提交',
                            status,
                            '；'.join(members),
                        ]
                    ]
                )
            archive.writestr('打包结果.csv', '\ufeff' + report.getvalue())
            archive.writestr(
                '下载说明.txt',
                '本包收集当前在班学生各自最后一次提交。\n'
                '人工批阅答案ZIP已展开，机器批阅源码以.py文件保存。\n'
                '未提交、文件缺失或答案ZIP损坏会在打包结果中标明。\n',
            )
        output.seek(0)
        audit(request.user, 'portal.submissions.download', str(pk))
        response = FileResponse(
            output,
            as_attachment=True,
            filename=f'{filename_part(work.classroom.code)}_{filename_part(work.title)}_学生作业.zip',
        )
        response['Cache-Control'] = 'no-store'
        return response
    except Exception:
        output.close()
        raise
