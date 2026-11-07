"""测试辅助：构造最小可读的 .docx（zip + word/document.xml），供 parsers 等测试使用。"""

import io
import zipfile


def build_docx_bytes(paragraphs):
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
