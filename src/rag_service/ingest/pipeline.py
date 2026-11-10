"""코퍼스(samples/ 형식)를 DB에 저장한다.

- 문서는 source_path(acl.yaml의 file)로 식별한다. 다시 수집하면 기존 문서와 조각을
  지우고 새로 넣는다 (ON DELETE CASCADE).
- 코퍼스에서 빠진 문서는 DB에서도 지운다.
- 권한 정보(부서, 역할, 보안 등급)는 document_acl에 원본을, chunks에 사본을 저장한다.
- 문서 수명(현행/폐지)과 시행일은 documents에만 저장한다.
- 수명 관리 정보: 원문 파일 해시·수정 시각·임베딩 모델(documents), 조각 키·본문 해시(chunks).
- 사용자(org.yaml의 users)는 users 테이블에 login으로 맞춘다. 있으면 갱신, 없으면 추가하고,
  코퍼스에서 빠진 사용자는 지운다. API는 이 테이블로 요청한 사용자의 권한을 판단한다.
- 커밋은 호출하는 쪽에서 한다. 전체를 한 트랜잭션으로 묶으면 중간에 실패해도 DB가
  반쯤 바뀐 상태로 남지 않는다.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import cast, delete, select
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, DocumentEntry
from rag_service.db.models import Chunk, Document, DocumentAcl, User
from rag_service.ingest.chunker import DEFAULT_MAX_CHARS, chunk_document, chunk_keys
from rag_service.ingest.embedder import Embedder, embedding_model_name
from rag_service.ingest.tokenizer import KoreanTokenizer, to_tsvector_literal


@dataclass(frozen=True)
class IngestStats:
    documents: int
    chunks: int
    removed: int
    users: int = 0


def ingest_corpus(
    session: Session,
    corpus: Corpus,
    *,
    embedder: Embedder,
    tokenizer: KoreanTokenizer,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> IngestStats:
    listed = [document.file for document in corpus.documents]
    # Session.execute의 반환 타입에는 rowcount가 없어서 Connection(CursorResult)으로 실행한다
    removed = session.connection().execute(
        delete(Document).where(Document.source_path.not_in(listed))
    )

    chunk_count = 0
    for entry in corpus.documents:
        chunk_count += ingest_document(
            session, corpus, entry, embedder=embedder, tokenizer=tokenizer, max_chars=max_chars
        )
    return IngestStats(
        documents=len(corpus.documents),
        chunks=chunk_count,
        removed=removed.rowcount,
        users=sync_users(session, corpus),
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


def ingest_document(
    session: Session,
    corpus: Corpus,
    entry: DocumentEntry,
    *,
    embedder: Embedder,
    tokenizer: KoreanTokenizer,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> int:
    """문서 하나를 (다시) 저장하고 조각 개수를 돌려준다."""
    path = corpus.doc_path(entry)
    pieces = chunk_document(path, max_chars=max_chars)
    keys = chunk_keys(entry.file, pieces)
    vectors = embedder.embed([piece.text for piece in pieces])
    if len(vectors) != len(pieces):
        raise ValueError(f"{entry.file}: 조각 {len(pieces)}개에 벡터 {len(vectors)}개가 왔습니다")

    session.execute(delete(Document).where(Document.source_path == entry.file))
    document = Document(
        title=entry.title,
        source_path=entry.file,
        security_level=entry.security_level,
        status=entry.status,
        content_sha256=file_sha256(path),
        source_mtime=datetime.fromtimestamp(path.stat().st_mtime, UTC),
        embedding_model=embedding_model_name(embedder),
        effective_from=entry.effective_from,
        effective_to=entry.effective_to,
    )
    session.add(document)
    session.flush()  # document.id를 받아온다

    session.add_all(
        [
            DocumentAcl(document_id=document.id, kind="department", value=d)
            for d in entry.departments
        ]
        + [DocumentAcl(document_id=document.id, kind="role", value=r) for r in entry.roles]
    )
    session.add_all(
        Chunk(
            document_id=document.id,
            chunk_index=piece.index,
            content=piece.text,
            page=piece.page,  # PDF만 페이지가 있다
            section=piece.section or None,
            tokens=cast(to_tsvector_literal(tokenizer.tokenize(piece.text)), TSVECTOR),
            embedding=vector,
            allowed_departments=list(entry.departments),
            allowed_roles=list(entry.roles),
            security_level=entry.security_level,
            chunk_key=key,
            content_sha256=text_sha256(piece.text),
        )
        for piece, vector, key in zip(pieces, vectors, keys, strict=True)
    )
    session.flush()
    return len(pieces)


def file_sha256(path: Path) -> str:
    """원문 파일 바이트 그대로의 해시 (줄바꿈은 .gitattributes가 LF로 고정한다)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
