"""도메인 지식 문서를 공급하는 소스. 문서는 비신뢰 참고 데이터로 취급한다."""

import json
import pathlib

MAX_DOC_CHARS = 20000
MAX_TOTAL_CHARS = 60000
SUFFIXES = (".json", ".md")


class NullKnowledge:
    def load(self, context):
        return []


class DirectoryKnowledge:
    """폴더 아래의 .json, .md 파일을 읽는다. 어떤 PR에 어떤 문서가 해당하는지는 아직 가리지 않는다."""

    def __init__(self, roots, max_doc_chars=MAX_DOC_CHARS, max_total_chars=MAX_TOTAL_CHARS):
        self.roots = [pathlib.Path(r).expanduser() for r in roots]
        self.max_doc_chars = max_doc_chars
        self.max_total_chars = max_total_chars

    def load(self, context):
        docs = []
        total = 0
        for root in self.roots:
            if not root.is_dir():
                continue
            for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in SUFFIXES):
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if path.suffix == ".json":
                    try:
                        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                    except json.JSONDecodeError:
                        continue
                text = text[: self.max_doc_chars]
                if total + len(text) > self.max_total_chars:
                    return docs
                total += len(text)
                docs.append({"id": str(path.relative_to(root)), "title": path.stem, "text": text})
        return docs
