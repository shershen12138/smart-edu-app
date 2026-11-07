"""parsers.py 的单元测试：上传文档/批阅包/人工批阅材料的静态解析。"""

import io
import tempfile
import zipfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from school.portal import parsers
from school.tests.tests_helpers_docx import build_docx_bytes


def build_docx(paragraphs):
    return build_docx_bytes(paragraphs)
    """构造一个最小可读的 .docx（zip + word/document.xml）。"""
    body = ''.join(f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}</w:body></w:document>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', xml)
    return output.getvalue()


def build_package_zip(chapter='01基础'):
    """构造一个合法的自动批阅包 ZIP。"""
    docx = build_docx(['题目一', '将代码写入函数func301'])
    manifest = 'func301 100 data/func301.txt\n'
    cases = '[1, 2]\n[3, 4]\n'
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(f'{chapter}/题.docx', docx)
        archive.writestr(f'{chapter}/sample.py', 'def func301(a, b):\n    pass\n')
        archive.writestr(
            f'{chapter}/gold.py', 'def func301(a, b):\n    return a + b\n'
        )
        archive.writestr(f'{chapter}/func_info_list.txt', manifest)
        archive.writestr(f'{chapter}/data/func301.txt', cases)
    return output.getvalue()


class DecodeTextTests(TestCase):
    def test_utf8(self):
        self.assertEqual(parsers.decode_text('中文'.encode('utf-8')), '中文')

    def test_gb18030(self):
        self.assertEqual(parsers.decode_text('中文'.encode('gb18030')), '中文')

    def test_undecodable_raises(self):
        with self.assertRaisesMessage(ValidationError, '编码无法识别'):
            parsers.decode_text(b'\xff\xfe\xfa')


class DocumentTextTests(TestCase):
    def test_txt_and_md(self):
        self.assertEqual(parsers.document_text('你好'.encode(), 'a.txt'), '你好')
        self.assertEqual(parsers.document_text('说明'.encode(), 'a.md'), '说明')

    def test_docx_paragraphs(self):
        self.assertEqual(parsers.document_text(build_docx(['段一', '段二']), '题.docx'), '段一\n段二')

    def test_oversized_document_rejected(self):
        with self.assertRaisesMessage(ValidationError, '2 MB'):
            parsers.document_text(b'x' * (2 * 1024 * 1024 + 1), 'a.txt')

    def test_null_char_rejected(self):
        with self.assertRaisesMessage(ValidationError, '无效字符'):
            parsers.document_text('a\x00b'.encode(), 'a.txt')

    def test_unsupported_suffix(self):
        with self.assertRaisesMessage(ValidationError, '.txt、.md 或 .docx'):
            parsers.document_text(b'x', 'a.pdf')

    def test_docx_with_doctype_rejected(self):
        xml = b'<!DOCTYPE document><w:document/>' + b'<w:body/>' * 0
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('word/document.xml', xml)
        with self.assertRaisesMessage(ValidationError, 'XML 声明'):
            parsers.document_text(output.getvalue(), 'a.docx')

    def test_invalid_docx_rejected(self):
        with self.assertRaisesMessage(ValidationError, '无法读取 Word'):
            parsers.document_text(b'not a zip', 'a.docx')


class SafeZipTests(TestCase):
    def test_bad_zip_rejected(self):
        with self.assertRaisesMessage(ValidationError, '无法读取'):
            parsers._safe_zip_files(b'junk', '无法读取 ZIP 批阅包。', 10, 1000, 1000)

    def test_empty_archive_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w'):
            pass
        with self.assertRaisesMessage(ValidationError, '数量不符合要求'):
            parsers._safe_zip_files(
                output.getvalue(), 'msg', 10, 1000, 1000
            )

    def test_path_traversal_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('../evil.txt', 'x')
        with self.assertRaisesMessage(ValidationError, '不安全'):
            parsers._safe_zip_files(output.getvalue(), 'msg', 10, 1000, 1000)

    def test_pycache_and_pyc_skipped(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('__pycache__/a.pyc', b'x')
            archive.writestr('a.py', b'print(1)')
        files = parsers._safe_zip_files(output.getvalue(), 'msg', 10, 1000, 1000)
        self.assertEqual(list(files), ['a.py'])

    def test_duplicate_path_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('a.txt', b'1')
            archive.writestr('a.txt', b'2')
        with self.assertRaisesMessage(ValidationError, '重复路径'):
            parsers._safe_zip_files(output.getvalue(), 'msg', 10, 1000, 1000)

    def test_oversized_member_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('big.txt', b'x' * 2000)
        with self.assertRaisesMessage(ValidationError, '超大文件'):
            parsers._safe_zip_files(output.getvalue(), 'msg', 10, 100000, 1000)


class ManualArchiveTests(TestCase):
    def _zip(self, layout='root'):
        docx = build_docx(['人工批阅'])
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            if layout == 'root':
                archive.writestr('题目.docx', docx)
                archive.writestr('附件.txt', b'file')
            else:
                archive.writestr(f'{layout}/题目.docx', docx)
                archive.writestr(f'{layout}/附件.txt', b'file')
        return output.getvalue()

    def test_requires_exactly_one_docx(self):
        with self.assertRaisesMessage(ValidationError, '无法读取人工批阅作业ZIP'):
            parsers.manual_archive_files(b'junk')

    def test_files_must_share_chapter_root(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('a/题目.docx', build_docx(['x']))
            archive.writestr('b/其他.txt', b'y')
        with self.assertRaisesMessage(ValidationError, '同一个章节目录'):
            parsers.manual_archive_files(output.getvalue())

    def test_member_choices_relative_to_root(self):
        files, root, _document = parsers.manual_archive_files(self._zip('第一章'))
        choices = parsers.manual_member_choices(self._zip('第一章'))
        self.assertIn('第一章/附件.txt', [path for path, _rel in choices])
        self.assertEqual(root.name, '第一章')

    def test_replace_member_rewrites_archive(self):
        data = self._zip('root')
        replaced = parsers.replace_manual_member(data, '附件.txt', b'new-content')
        files, _root, _doc = parsers.manual_archive_files(replaced)
        self.assertEqual(files['附件.txt'], b'new-content')

    def test_replace_missing_member_rejected(self):
        with self.assertRaisesMessage(ValidationError, '请刷新后重试'):
            parsers.replace_manual_member(self._zip('root'), 'nope.txt', b'x')

    def test_parse_manual_materials(self):
        result = parsers.parse_manual_materials_archive(self._zip('第一章'), '材料.zip')
        self.assertEqual(result['name'], '第一章')
        self.assertEqual(result['description'], '人工批阅')
        self.assertEqual(result['document_name'], '题目.docx')

    def test_parse_manual_materials_requires_zip(self):
        with self.assertRaisesMessage(ValidationError, 'zip'):
            parsers.parse_manual_materials_archive(b'x', '材料.rar')

    def test_parse_manual_submission_missing_file(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('src/1001.py', b'print(1)')
        with self.assertRaisesMessage(ValidationError, '缺少'):
            parsers.parse_manual_submission_archive(
                output.getvalue(), '答案.zip', ['1001.py', '1002.py']
            )

    def test_parse_manual_submission_duplicate_file(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('src/1001.py', b'print(1)')
            archive.writestr('src/sub/1001.py', b'print(2)')
        with self.assertRaisesMessage(ValidationError, '重复文件'):
            parsers.parse_manual_submission_archive(
                output.getvalue(), '答案.zip', ['1001.py']
            )

    def test_parse_manual_submission_different_dirs_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('a/1001.py', b'print(1)')
            archive.writestr('b/1002.py', b'print(2)')
        with self.assertRaisesMessage(ValidationError, '同一目录'):
            parsers.parse_manual_submission_archive(
                output.getvalue(), '答案.zip', ['1001.py', '1002.py']
            )

    def test_parse_manual_submission_ok(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('src/1001.py', 'print(1)')
            archive.writestr('src/1002.py', 'print(2)')
        result = parsers.parse_manual_submission_archive(
            output.getvalue(), '答案.zip', ['1001.py', '1002.py']
        )
        self.assertEqual(result['sources']['1001.py'], 'print(1)')
        self.assertEqual(len(result['digest']), 64)

    def test_parse_manual_submission_rejects_empty_source(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('src/1001.py', '   \n')
        with self.assertRaisesMessage(ValidationError, '不能为空'):
            parsers.parse_manual_submission_archive(output.getvalue(), '答案.zip', ['1001.py'])


class PackageArchiveTests(TestCase):
    def test_valid_package_parses(self):
        data = build_package_zip()
        result = parsers.parse_package_archive(data, '章节.zip')
        self.assertEqual(result['name'], '01基础')
        self.assertEqual(result['description'], '题目一\n将代码写入函数func301')
        self.assertEqual(len(result['spec']), 1)
        spec = result['spec'][0]
        self.assertEqual(spec['function'], 'func301')
        self.assertEqual(spec['argc'], 2)
        self.assertEqual(spec['points'], 100)
        self.assertEqual(spec['inputs'], ['[1, 2]', '[3, 4]'])

    def test_non_zip_suffix_rejected(self):
        with self.assertRaisesMessage(ValidationError, '.zip'):
            parsers.parse_package_archive(b'x', '章节.rar')

    def test_missing_required_files(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('ch/题.docx', build_docx(['x']))
        with self.assertRaisesMessage(ValidationError, 'func_info_list.txt'):
            parsers.parse_package_archive(output.getvalue(), '章节.zip')

    def test_gold_syntax_error_rejected(self):
        docx = build_docx(['题'])
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('ch/题.docx', docx)
            archive.writestr('ch/sample.py', 'pass\n')
            archive.writestr('ch/gold.py', 'def broken(:\n')
            archive.writestr('ch/func_info_list.txt', '')
        with self.assertRaisesMessage(ValidationError, '语法错误'):
            parsers.parse_package_archive(output.getvalue(), '章节.zip')

    def test_manifest_line_with_bad_field_count(self):
        data = self._package_with_manifest('func301 100\n')
        with self.assertRaisesMessage(ValidationError, '函数名 分值 用例路径'):
            parsers.parse_package_archive(data, '章节.zip')

    def test_manifest_unknown_function(self):
        data = self._package_with_manifest('ghost 100 data/func301.txt\n')
        with self.assertRaisesMessage(ValidationError, '无效'):
            parsers.parse_package_archive(data, '章节.zip')

    def test_manifest_non_integer_points(self):
        data = self._package_with_manifest('func301 many data/func301.txt\n')
        with self.assertRaisesMessage(ValidationError, '不是整数'):
            parsers.parse_package_archive(data, '章节.zip')

    def test_manifest_out_of_range_points(self):
        data = self._package_with_manifest('func301 0 data/func301.txt\n')
        with self.assertRaisesMessage(ValidationError, '1～1000'):
            parsers.parse_package_archive(data, '章节.zip')

    def test_manifest_bad_case_literal(self):
        docx = build_docx(['题'])
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('ch/题.docx', docx)
            archive.writestr('ch/sample.py', 'def func301(a, b):\n    pass\n')
            archive.writestr('ch/gold.py', 'def func301(a, b):\n    return a + b\n')
            archive.writestr('ch/func_info_list.txt', 'func301 100 data/func301.txt\n')
            archive.writestr('ch/data/func301.txt', 'not a literal\n')
        with self.assertRaisesMessage(ValidationError, '不是安全的 Python 字面量'):
            parsers.parse_package_archive(output.getvalue(), '章节.zip')

    def test_manifest_argc_mismatch(self):
        docx = build_docx(['题'])
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('ch/题.docx', docx)
            archive.writestr('ch/sample.py', 'def func301(a, b):\n    pass\n')
            archive.writestr('ch/gold.py', 'def func301(a, b):\n    return a + b\n')
            archive.writestr('ch/func_info_list.txt', 'func301 100 data/func301.txt\n')
            archive.writestr('ch/data/func301.txt', '[1, 2, 3]\n')
        with self.assertRaisesMessage(ValidationError, '参数数目不匹配'):
            parsers.parse_package_archive(output.getvalue(), '章节.zip')

    def test_manifest_empty_cases_rejected(self):
        data = self._package_with_manifest('func301 100 data/func301.txt\n')
        # 用例文件缺失会命中“用例路径无效”；空用例文件命中“没有测试用例”
        docx = build_docx(['题'])
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('ch/题.docx', docx)
            archive.writestr('ch/sample.py', 'def func301(a, b):\n    pass\n')
            archive.writestr('ch/gold.py', 'def func301(a, b):\n    return a + b\n')
            archive.writestr('ch/func_info_list.txt', 'func301 100 data/empty.txt\n')
            archive.writestr('ch/data/empty.txt', '\n \n')
        with self.assertRaisesMessage(ValidationError, '没有测试用例'):
            parsers.parse_package_archive(output.getvalue(), '章节.zip')
        del data

    def test_duplicate_function_rejected(self):
        docx = build_docx(['题'])
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('ch/题.docx', docx)
            archive.writestr('ch/sample.py', 'def func301(a, b):\n    pass\n')
            archive.writestr('ch/gold.py', 'def func301(a, b):\n    return a + b\n')
            archive.writestr(
                'ch/func_info_list.txt',
                'func301 100 data/a.txt\nfunc301 50 data/b.txt\n',
            )
            archive.writestr('ch/data/a.txt', '[1, 2]\n')
            archive.writestr('ch/data/b.txt', '[3, 4]\n')
        with self.assertRaisesMessage(ValidationError, '无效'):
            parsers.parse_package_archive(output.getvalue(), '章节.zip')

    def _package_with_manifest(self, manifest):
        docx = build_docx(['题'])
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('ch/题.docx', docx)
            archive.writestr('ch/sample.py', 'def func301(a, b):\n    pass\n')
            archive.writestr('ch/gold.py', 'def func301(a, b):\n    return a + b\n')
            archive.writestr('ch/func_info_list.txt', manifest)
            archive.writestr('ch/data/func301.txt', '[1, 2]\n')
        return output.getvalue()


class LoadPackageTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_STORAGE=Path(directory.name))
        storage.enable()
        self.addCleanup(storage.disable)

    def _write_chapter(self, root, name='01基础'):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / '题.docx').write_bytes(build_docx(['题目一']))
        (folder / 'sample.py').write_text('def func301(a, b):\n    pass\n', encoding='utf-8')
        (folder / 'gold.py').write_text('def func301(a, b):\n    return a + b\n', encoding='utf-8')
        (folder / 'func_info_list.txt').write_text('func301 100 data/func301.txt\n', encoding='utf-8')
        (folder / 'data').mkdir()
        (folder / 'data' / 'func301.txt').write_text('[1, 2]\n[3, 4]\n', encoding='utf-8')
        return folder

    def test_load_package_from_directory(self):
        with tempfile.TemporaryDirectory() as name:
            folder = self._write_chapter(Path(name))
            data = parsers.load_package(folder)
        self.assertEqual(data['spec'][0]['function'], 'func301')
        self.assertTrue(data['template_path'])
        self.assertTrue(data['reference_path'])
        self.assertEqual(data['note'], '')

    def test_load_package_without_manifest_marks_note(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / '02占位'
            folder.mkdir()
            data = parsers.load_package(folder)
        self.assertEqual(data['spec'], [])
        self.assertIn('待接入', data['note'])
