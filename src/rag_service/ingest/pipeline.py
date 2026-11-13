"""코퍼스(samples/ 형식)를 DB에 맞춘다 (증분 수집).

- 문서는 source_path(acl.yaml의 file)로 식별하고, 수집한 코퍼스 폴더를 corpus_root에 적는다.
- 원문 파일 해시와 임베딩 모델이 DB와 같으면 건너뛴다(skipped). 원문이 바뀐 문서만 다시 청킹하고
  (changed), 그 안에서도 본문 해시가 같은 조각은 기존 벡터를 다시 쓴다 (모델이 같을 때만).
- 원문은 같고 acl.yaml의 권한·제목·상태·시행일만 바뀌면 재임베딩 없이 그 값만 고친다(updated).
  조각에 복사해 둔 권한도 함께 고친다.
- 임베딩 모델이 바뀌면 이 폴더의 문서를 모두 다시 임베딩하고, 이번 목록에 없는 문서(다른 폴더,
  --prune 없이 남긴 문서)도 DB에 저장된 조각 본문으로 다시 임베딩한다(reembedded). 한 DB에 두
  모델의 벡터가 섞이면 검색 점수를 서로 비교할 수 없기 때문이다.
- 목록에서 빠진 문서는 prune=True일 때만, 이번에 넘긴 폴더(corpus_root가 같은 문서)에서만 지운다.
  prune이 없으면 지우지 않고 unlisted로 알린다. 다른 폴더나 corpus_root가 비어 있는(0006 이전)
  문서는 어느 쪽이든 지우지 않는다.
- dry_run=True면 계획만 세워 돌려주고 DB를 바꾸지 않는다 (임베딩도 하지 않는다).
- 권한 정보(부서, 역할, 보안 등급)는 document_acl에 원본을, chunks에 사본을 저장한다.
- 사용자(org.yaml의 users)는 users 테이블에 login으로 맞춘다. 있으면 갱신, 없으면 추가하고,
  코퍼스에서 빠진 사용자는 지운다. API는 이 테이블로 요청한 사용자의 권한을 판단한다.
- 커밋은 호출하는 쪽에서 한다. 전체를 한 트랜잭션으로 묶으면 중간에 실패해도 DB가
  반쯤 바뀐 상태로 남지 않는다.

알려진 한계: 청킹 방식(max_chars, 파서)만 바뀌고 원문이 그대로면 변경을 알아채지 못한다.
그때는 force=True(`--force`)로 전체를 다시 수집한다.
"""

import hashlib
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, DocumentEntry
from rag_service.db.models import Chunk, Document, DocumentAcl, User
from rag_service.ingest.chunker import DEFAULT_MAX_CHARS, chunk_document, chunk_keys
from rag_service.ingest.embedder import Embedder, embedding_model_name
from rag_service.ingest.tokenizer import KoreanTokenizer, to_tsvector_literal


@dataclass(frozen=True)
class SyncPlan:
    """수집 한 번에 할 일. 각 항목은 source_path 목록 (이름순)."""

    added: tuple[str, ...] = ()  # DB에 없어 새로 넣는다
    changed: tuple[str, ...] = ()  # 원문이나 임베딩 모델이 달라 다시 청킹·임베딩한다
    updated: tuple[str, ...] = ()  # 원문은 같고 권한·제목·상태·시행일·폴더만 고친다
    skipped: tuple[str, ...] = ()  # 그대로 둔다
    deleted: tuple[str, ...] = ()  # --prune: 이 폴더 문서인데 목록에 없어 지운다
    unlisted: tuple[str, ...] = ()  # 이 폴더 문서인데 목록에 없다 (--prune이 없어 남긴다)
    reembedded: tuple[str, ...] = ()  # 목록 밖 문서를 새 모델로 다시 임베딩한다 (저장된 본문으로)


@dataclass(frozen=True)
class IngestStats(SyncPlan):
    documents: int = 0  # 코퍼스 목록의 문서 수
    chunks: int = 0  # 이번에 새로 쓴 조각 수
    embedded: int = 0  # 실제로 임베딩한 텍스트 수 (재사용한 벡터는 빼고)
    users: int = 0
    dry_run: bool = False

    @property
    def removed(self) -> int:
        return len(self.deleted)


def corpus_root_key(root: Path) -> str:
    """documents.corpus_root에 적는 폴더 이름 (절대 경로, / 구분)."""
    return root.resolve().as_posix()


def ingest_corpus(
    session: Session,
    corpus: Corpus,
    *,
    embedder: Embedder,
    tokenizer: KoreanTokenizer,
    max_chars: int = DEFAULT_MAX_CHARS,
    prune: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> IngestStats:
    model = embedding_model_name(embedder)
    plan = plan_sync(session, corpus, model=model, prune=prune, force=force)
    base = {f.name: getattr(plan, f.name) for f in fields(SyncPlan)}
    if dry_run:
        return IngestStats(**base, documents=len(corpus.documents), dry_run=True)

    if plan.deleted:
        session.execute(delete(Document).where(Document.source_path.in_(plan.deleted)))

    entries = {entry.file: entry for entry in corpus.documents}
    chunks = embedded = 0
    root = corpus_root_key(corpus.root)
    for file in plan.added + plan.changed:
        written, used = write_document(
            session,
            entries[file],
            corpus.doc_path(entries[file]),
            root=root,
            embedder=embedder,
            tokenizer=tokenizer,
            max_chars=max_chars,
        )
        chunks += written
        embedded += used
    for file in plan.updated:
        update_metadata(session, entries[file], root)
    # 내용이 같아 다시 수집하지 않은 문서도 저장된 수정 시각을 지금 파일 것으로 맞춘다.
    # /health는 수정 시각만 비교하므로, 복사·백업 되살리기·git checkout으로 시각만 바뀐 파일을
    # 계속 '바뀜'으로 세지 않게 한다
    for file in plan.updated + plan.skipped:
        refresh_mtime(session, file, corpus.doc_path(entries[file]))
    embedded += _reembed_stored(session, plan.reembedded, embedder=embedder, model=model)

    session.execute(
        update(Document).where(Document.source_path.in_(list(entries))).values(synced_at=func.now())
    )
    return IngestStats(
        **base,
        documents=len(corpus.documents),
        chunks=chunks,
        embedded=embedded,
        users=sync_users(session, corpus),
    )


def plan_sync(
    session: Session, corpus: Corpus, *, model: str, prune: bool = False, force: bool = False
) -> SyncPlan:
    """DB와 코퍼스를 비교해 할 일을 정한다 (DB를 바꾸지 않는다)."""
    root = corpus_root_key(corpus.root)
    existing = {d.source_path: d for d in session.scalars(select(Document))}
    acl = acl_by_document(session)

    added: list[str] = []
    changed: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    for entry in corpus.documents:
        document = existing.get(entry.file)
        if document is None:
            added.append(entry.file)
        elif (
            force
            or document.embedding_model != model
            or document.content_sha256 != file_sha256(corpus.doc_path(entry))
        ):
            changed.append(entry.file)
        elif document.corpus_root != root or stored_metadata(document, acl) != wanted_metadata(
            entry
        ):
            updated.append(entry.file)
        else:
            skipped.append(entry.file)

    listed = {entry.file for entry in corpus.documents}
    mine = [p for p, d in existing.items() if p not in listed and d.corpus_root == root]
    deleted = mine if prune else []
    kept = [p for p, d in existing.items() if p not in listed and p not in deleted]
    return SyncPlan(
        added=tuple(sorted(added)),
        changed=tuple(sorted(changed)),
        updated=tuple(sorted(updated)),
        skipped=tuple(sorted(skipped)),
        deleted=tuple(sorted(deleted)),
        unlisted=tuple(sorted([] if prune else mine)),
        reembedded=tuple(sorted(p for p in kept if existing[p].embedding_model != model)),
    )


Acl = tuple[tuple[str, ...], tuple[str, ...]]  # (부서, 역할) 이름순
Metadata = tuple[str, int, str, date | None, date | None, Acl]


def acl_by_document(session: Session) -> dict[int, Acl]:
    values: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for document_id, kind, value in session.execute(
        select(DocumentAcl.document_id, DocumentAcl.kind, DocumentAcl.value)
    ):
        values[document_id][kind].append(value)
    return {
        document_id: (tuple(sorted(kinds["department"])), tuple(sorted(kinds["role"])))
        for document_id, kinds in values.items()
    }


def wanted_metadata(entry: DocumentEntry) -> Metadata:
    acl = (tuple(sorted(entry.departments)), tuple(sorted(entry.roles)))
    return (
        entry.title,
        entry.security_level,
        entry.status,
        entry.effective_from,
        entry.effective_to,
        acl,
    )


def stored_metadata(document: Document, acl: dict[int, Acl]) -> Metadata:
    return (
        document.title,
        document.security_level,
        document.status,
        document.effective_from,
        document.effective_to,
        acl.get(document.id, ((), ())),
    )


def sync_users(session: Session, corpus: Corpus) -> int:
    """users 테이블을 org.yaml의 사용자 목록과 같게 만들고 사용자 수를 돌려준다."""
    entries = {entry.id: entry for entry in corpus.org.users}
    session.execute(delete(User).where(User.login.not_in(list(entries))))
    existing = {user.login: user for user in session.scalars(select(User))}
    for login, entry in entries.items():
        user = existing.get(login) or User(login=login)
        user.name = entry.name
        user.department = entry.department
        user.role = entry.role
        user.clearance_level = entry.clearance_level
        session.add(user)
    session.flush()
    return len(entries)


def write_document(
    session: Session,
    entry: DocumentEntry,
    path: Path,
    *,
    root: str,
    embedder: Embedder,
    tokenizer: KoreanTokenizer,
    max_chars: int = DEFAULT_MAX_CHARS,
    origin: str = "folder",
    owner_department: str | None = None,
) -> tuple[int, int]:
    """문서 하나를 (다시) 저장하고 (조각 수, 새로 임베딩한 텍스트 수)를 돌려준다.

    entry.file이 source_path, path가 원문 파일, root가 corpus_root다. 폴더 수집과 관리 화면
    업로드(origin="upload", ingest/uploads.py)가 함께 쓴다. 같은 source_path의 기존 행은 지우고
    새로 넣으므로 문서 id가 바뀐다.
    """
    pieces = chunk_document(path, max_chars=max_chars)
    keys = chunk_keys(entry.file, pieces)
    hashes = [text_sha256(piece.text) for piece in pieces]
    model = embedding_model_name(embedder)

    vectors = _reusable_vectors(session, entry.file, model)
    missing = list(
        dict.fromkeys(p.text for p, h in zip(pieces, hashes, strict=True) if h not in vectors)
    )
    if missing:
        fresh = embedder.embed(missing)
        if len(fresh) != len(missing):
            raise ValueError(
                f"{entry.file}: 조각 {len(missing)}개에 벡터 {len(fresh)}개가 왔습니다"
            )
        vectors.update(zip((text_sha256(t) for t in missing), fresh, strict=True))

    session.execute(delete(Document).where(Document.source_path == entry.file))
    document = Document(
        title=entry.title,
        source_path=entry.file,
        security_level=entry.security_level,
        status=entry.status,
        content_sha256=file_sha256(path),
        source_mtime=datetime.fromtimestamp(path.stat().st_mtime, UTC),
        embedding_model=model,
        effective_from=entry.effective_from,
        effective_to=entry.effective_to,
        corpus_root=root,
        origin=origin,
        owner_department=owner_department,
    )
    session.add(document)
    session.flush()  # document.id를 받아온다

    session.add_all(_acl_rows(document.id, entry))
    session.add_all(
        Chunk(
            document_id=document.id,
            chunk_index=piece.index,
            content=piece.text,
            page=piece.page,  # PDF만 페이지가 있다
            section=piece.section or None,
            tokens=cast(to_tsvector_literal(tokenizer.tokenize(piece.text)), TSVECTOR),
            embedding=vectors[digest],
            allowed_departments=list(entry.departments),
            allowed_roles=list(entry.roles),
            security_level=entry.security_level,
            chunk_key=key,
            content_sha256=digest,
        )
        for piece, key, digest in zip(pieces, keys, hashes, strict=True)
    )
    session.flush()
    return len(pieces), len(missing)


def _reusable_vectors(session: Session, source_path: str, model: str) -> dict[str, Any]:
    """같은 모델로 임베딩해 둔 이 문서의 조각 벡터 (본문 해시 → 벡터)."""
    rows = session.execute(
        select(Chunk.content_sha256, Chunk.embedding)
        .join(Document)
        .where(Document.source_path == source_path, Document.embedding_model == model)
    )
    return {digest: vector for digest, vector in rows if digest is not None}


def _acl_rows(document_id: int, entry: DocumentEntry) -> list[DocumentAcl]:
    return [
        DocumentAcl(document_id=document_id, kind="department", value=d) for d in entry.departments
    ] + [DocumentAcl(document_id=document_id, kind="role", value=r) for r in entry.roles]


def refresh_mtime(session: Session, source_path: str, path: Path) -> None:
    """원문 내용은 그대로인 문서의 수정 시각만 지금 파일 값으로 고친다 (재임베딩 없음)."""
    mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    session.execute(
        update(Document)
        .where(Document.source_path == source_path, Document.source_mtime.is_distinct_from(mtime))
        .values(source_mtime=mtime)
    )


def update_metadata(session: Session, entry: DocumentEntry, root: str) -> None:
    """원문이 그대로인 문서의 권한·제목·상태·시행일·폴더를 고친다 (재임베딩 없음)."""
    document = session.scalars(select(Document).where(Document.source_path == entry.file)).one()
    document.title = entry.title
    document.security_level = entry.security_level
    document.status = entry.status
    document.effective_from = entry.effective_from
    document.effective_to = entry.effective_to
    document.corpus_root = root
    session.execute(delete(DocumentAcl).where(DocumentAcl.document_id == document.id))
    session.add_all(_acl_rows(document.id, entry))
    session.execute(
        update(Chunk)
        .where(Chunk.document_id == document.id)
        .values(
            allowed_departments=list(entry.departments),
            allowed_roles=list(entry.roles),
            security_level=entry.security_level,
        )
    )
    session.flush()


def _reembed_stored(
    session: Session, paths: Collection[str], *, embedder: Embedder, model: str
) -> int:
    """원문 없이 DB에 저장된 조각 본문으로 다시 임베딩하고, 임베딩한 조각 수를 돌려준다."""
    if not paths:
        return 0
    rows = session.execute(
        select(Chunk.id, Chunk.content)
        .join(Document)
        .where(Document.source_path.in_(paths))
        .order_by(Chunk.id)
    ).all()
    vectors = embedder.embed([content for _, content in rows])
    if len(vectors) != len(rows):
        raise ValueError(f"저장된 조각 {len(rows)}개에 벡터 {len(vectors)}개가 왔습니다")
    session.execute(
        update(Chunk),
        [
            {"id": chunk_id, "embedding": vector}
            for (chunk_id, _), vector in zip(rows, vectors, strict=True)
        ],
    )
    session.execute(
        update(Document).where(Document.source_path.in_(paths)).values(embedding_model=model)
    )
    return len(rows)


def file_sha256(path: Path) -> str:
    """원문 파일 바이트 그대로의 해시 (줄바꿈은 .gitattributes가 LF로 고정한다)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def summarize(stats: IngestStats, elapsed_seconds: float) -> list[str]:
    """수집 결과를 사람이 읽는 줄로 만든다 (CLI 출력용)."""
    head = "[dry-run] 계획만 출력하고 DB는 바꾸지 않았습니다" if stats.dry_run else "수집 완료"
    lines = [
        f"{head}: 문서 {stats.documents}개, 조각 {stats.chunks}개, 사용자 {stats.users}명 저장"
        f" (삭제된 문서 {stats.removed}개)",
        "  "
        + ", ".join(
            [
                f"추가 {len(stats.added)}",
                f"변경 {len(stats.changed)}",
                f"메타데이터 갱신 {len(stats.updated)}",
                f"건너뜀 {len(stats.skipped)}",
                f"삭제 {len(stats.deleted)}",
                f"재임베딩(목록 밖) {len(stats.reembedded)}",
                f"임베딩한 텍스트 {stats.embedded}개",
                f"{elapsed_seconds:.1f}초",
            ]
        ),
    ]
    labels = {
        "added": "추가",
        "changed": "변경",
        "updated": "메타데이터 갱신",
        "deleted": "삭제",
        "reembedded": "재임베딩(목록 밖)",
    }
    for name, label in labels.items():
        lines += [f"  {label}: {path}" for path in getattr(stats, name)]
    if stats.dry_run:
        lines += [f"  건너뜀: {path}" for path in stats.skipped]
    if stats.unlisted:
        lines.append(
            f"경고: 이 폴더에서 수집했지만 목록(acl.yaml)에 없는 문서 {len(stats.unlisted)}개를"
            " 남겼습니다. 지우려면 --prune을 붙이세요."
        )
        lines += [f"  목록에 없음: {path}" for path in stats.unlisted]
    return lines
