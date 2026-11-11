"""samples를 임시 폴더에 복사해 원문과 acl.yaml을 바꿔 보는 수집 테스트용 도우미."""

import shutil
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

import yaml

from tests.fixtures.embedding import FakeEmbedder

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def copy_samples(target: Path) -> Path:
    shutil.copytree(SAMPLES, target)
    return target


def _edit_acl(root: Path, edit: Any) -> None:
    path = root / "acl.yaml"
    acl = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(acl["documents"])
    path.write_text(yaml.safe_dump(acl, allow_unicode=True), encoding="utf-8")


def drop_documents(root: Path, files: Collection[str]) -> None:
    """acl.yaml에서 files를 빼고 원문 파일도 지운다 (원문 삭제)."""

    def edit(documents: list[dict[str, Any]]) -> None:
        documents[:] = [d for d in documents if d["file"] not in files]

    _edit_acl(root, edit)
    for file in files:
        (root / "docs" / file).unlink()


def set_acl(root: Path, file: str, **values: Any) -> None:
    """acl.yaml에서 file 항목의 값을 바꾼다 (원문은 그대로)."""

    def edit(documents: list[dict[str, Any]]) -> None:
        [entry] = [d for d in documents if d["file"] == file]
        entry.update(values)

    _edit_acl(root, edit)


def append_text(root: Path, file: str, text: str) -> None:
    path = root / "docs" / file
    path.write_bytes(path.read_bytes() + text.encode("utf-8"))


def write_small_corpus(root: Path, docs: dict[str, str]) -> Path:
    """사원 한 명, 문서 docs(파일 이름 → 마크다운)로 된 작은 코퍼스를 만든다."""
    (root / "docs").mkdir(parents=True)
    (root / "org.yaml").write_text(
        "departments: [개발팀]\nroles: [사원]\n"
        "users: [{id: kim, name: 김사원, department: 개발팀, role: 사원, clearance_level: 1}]\n",
        encoding="utf-8",
    )
    entries = [{"file": f, "title": f, "security_level": 1, "roles": ["사원"]} for f in docs]
    (root / "acl.yaml").write_text(
        yaml.safe_dump({"documents": entries}, allow_unicode=True), encoding="utf-8"
    )
    for name, text in docs.items():
        (root / "docs" / name).write_text(text, encoding="utf-8")
    return root


class OtherModelEmbedder(FakeEmbedder):
    """FakeEmbedder와 다른 모델인 척한다. 벡터도 달라서 다시 임베딩했는지 확인할 수 있다."""

    model_name = "other-model"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector[1:] + vector[:1] for vector in super().embed(texts)]
