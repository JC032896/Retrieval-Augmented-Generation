"""코퍼스(samples/ 형식)를 DB에 저장한다.

- 문서는 source_path(acl.yaml의 file)로 식별한다. 다시 수집하면 기존 문서와 조각을
  지우고 새로 넣는다 (ON DELETE CASCADE).
- 코퍼스에서 빠진 문서는 DB에서도 지운다.
- 권한 정보(부서, 역할, 보안 등급)는 document_acl에 원본을, chunks에 사본을 저장한다.
- 커밋은 호출하는 쪽에서 한다. 전체를 한 트랜잭션으로 묶으면 중간에 실패해도 DB가
  반쯤 바뀐 상태로 남지 않는다.
"""

from dataclasses import dataclass

from sqlalchemy import cast, delete
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, DocumentEntry
from rag_service.db.models import Chunk, Document, DocumentAcl
from rag_service.ingest.chunker import DEFAULT_MAX_CHARS, chunk_markdown
from rag_service.ingest.embedder import Embedder
from rag_service.ingest.tokenizer import KoreanTokenizer, to_tsvector_literal


@dataclass(frozen=True)
class IngestStats:
    documents: int
    chunks: int
    removed: int


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
        documents=len(corpus.documents), chunks=chunk_count, removed=removed.rowcount
    )


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
    markdown = corpus.doc_path(entry).read_text(encoding="utf-8")
    pieces = chunk_markdown(markdown, max_chars=max_chars)
    vectors = embedder.embed([piece.text for piece in pieces])
    if len(vectors) != len(pieces):
        raise ValueError(f"{entry.file}: 조각 {len(pieces)}개에 벡터 {len(vectors)}개가 왔습니다")

    session.execute(delete(Document).where(Document.source_path == entry.file))
    document = Document(
        title=entry.title, source_path=entry.file, security_level=entry.security_level
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
            page=None,  # Markdown에는 페이지가 없다
            section=piece.section or None,
            tokens=cast(to_tsvector_literal(tokenizer.tokenize(piece.text)), TSVECTOR),
            embedding=vector,
            allowed_departments=list(entry.departments),
            allowed_roles=list(entry.roles),
            security_level=entry.security_level,
        )
        for piece, vector in zip(pieces, vectors, strict=True)
    )
    session.flush()
    return len(pieces)
