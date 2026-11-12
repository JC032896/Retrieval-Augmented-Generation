// 문서 한 건: 작업 영역 전체를 이 문서가 차지한다 (방향 계약).
// 권한 바꾸기(받는 사람 확인 후 저장), 배송조회 이력, 파일 교체, 삭제.
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import type { DocumentRow } from "../api/types";
import { errorText, useLoad } from "../api/useApi";
import { useApiClient } from "../auth/session";
import { AccessEditor } from "../ui/AccessEditor";
import { type AccessDraft, changes, draftOf, draftProblem, sameDraft } from "../ui/access";
import { ConfirmRecipients } from "../ui/ConfirmRecipients";
import c from "../ui/controls.module.css";
import { Field } from "../ui/Field";
import { audience, dateTime, levelName, registeredNumber } from "../ui/format";
import { Level } from "../ui/Level";
import { Recipients, usePreview } from "../ui/Recipients";
import { type Change, Timeline } from "../ui/Timeline";
import styles from "./DocumentDetail.module.css";

type Org = { departments: string[]; roles: string[] };

function AccessSection({ document, onSaved }: { document: DocumentRow; onSaved: () => void }) {
  const api = useApiClient();
  const org = useLoad(useCallback(() => api.get<Org>("/admin/api/org"), [api]));
  const saved = draftOf(document);
  const [draft, setDraft] = useState<AccessDraft>(saved);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "blocked"; text: string } | null>(null);
  const preview = usePreview(api, draft);
  const unchanged = sameDraft(saved, draft);
  const problem = draftProblem(draft);

  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/admin/api/documents/${document.id}/access`, {
        title: draft.title.trim(),
        security_level: draft.security_level,
        departments: draft.departments,
        roles: draft.roles,
        status: draft.status,
      });
      setMessage({ tone: "ok", text: "권한을 바꿨습니다. 다음 질문부터 바로 적용됩니다." });
      setConfirming(false);
      onSaved();
    } catch (error) {
      setMessage({ tone: "blocked", text: `저장하지 못했습니다. ${errorText(error).message}` });
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  const review = (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    if (!problem && !unchanged) setConfirming(true);
  };

  return (
    <form className={styles.access} onSubmit={review}>
      <section className={c.panel} aria-labelledby="edit-title">
        <h2 id="edit-title">볼 수 있는 사람</h2>
        {org.state === "ready" ? (
          <fieldset disabled={confirming} className={styles.plain}>
            <AccessEditor
              draft={draft}
              onChange={setDraft}
              departments={org.data.departments}
              roles={org.data.roles}
              showStatus
            />
          </fieldset>
        ) : org.state === "error" ? (
          <p className={c.message} data-tone="blocked" role="alert">
            부서와 역할 목록을 불러오지 못했습니다. {org.message}
          </p>
        ) : (
          <p className={c.hint}>부서와 역할 목록을 불러오는 중입니다…</p>
        )}
      </section>
      <aside className={styles.side} aria-label="받는 사람">
        <section className={c.panel}>
          <h2>받는 사람</h2>
          <Recipients preview={preview} />
        </section>
        {message ? (
          <p
            className={c.message}
            data-tone={message.tone}
            role={message.tone === "blocked" ? "alert" : "status"}
          >
            {message.text}
          </p>
        ) : null}
        {confirming ? (
          <ConfirmRecipients
            preview={preview}
            lines={changes(saved, draft, levelName)}
            busy={busy}
            confirmLabel="이 명단으로 저장"
            onConfirm={save}
            onBack={() => setConfirming(false)}
          />
        ) : (
          <div className={styles.next}>
            {unchanged ? (
              <p className={c.hint}>바뀐 것이 없습니다.</p>
            ) : problem ? (
              <p className={c.hint}>{problem}</p>
            ) : null}
            <div className={c.actions}>
              <button
                type="submit"
                className={c.button}
                data-kind="primary"
                disabled={unchanged || !!problem}
              >
                받는 사람 확인
              </button>
              {!unchanged ? (
                <button type="button" className={c.button} onClick={() => setDraft(saved)}>
                  되돌리기
                </button>
              ) : null}
            </div>
          </div>
        )}
      </aside>
    </form>
  );
}

function ReplaceFile({ document }: { document: DocumentRow }) {
  const api = useApiClient();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const suffix = document.source_path.slice(document.source_path.lastIndexOf("."));

  const replace = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setBusy(true);
    setFailure(null);
    try {
      const replaced = await api.put<DocumentRow>(`/admin/api/documents/${document.id}/file`, form);
      navigate(`/documents/${replaced.id}`, { replace: true, state: { replaced: true } });
    } catch (error) {
      setFailure(errorText(error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className={c.panel} onSubmit={replace} aria-labelledby="replace-title" aria-busy={busy}>
      <h2 id="replace-title">파일 교체</h2>
      <Field
        label={`새 판 (${suffix} 파일)`}
        hint="권한과 제목은 그대로 두고 원문만 바꿉니다. 본문이 같은 부분은 다시 계산하지 않습니다."
      >
        <input
          className={c.input}
          type="file"
          accept={suffix}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </Field>
      {failure ? (
        <p
          className={c.message}
          data-tone="blocked"
          role="alert"
          style={{ marginTop: "var(--space-3)" }}
        >
          교체하지 못했습니다. {failure}
        </p>
      ) : null}
      <div className={c.actions} style={{ marginTop: "var(--space-4)" }}>
        <button type="submit" className={c.button} disabled={!file || busy}>
          {busy ? "교체하는 중…" : "새 판으로 교체"}
        </button>
      </div>
    </form>
  );
}

function DeleteDocument({ document }: { document: DocumentRow }) {
  const api = useApiClient();
  const navigate = useNavigate();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const number = registeredNumber(document);

  const remove = async () => {
    setBusy(true);
    try {
      await api.delete(`/admin/api/documents/${document.id}`);
      navigate("/documents", { replace: true });
    } catch (error) {
      setFailure(errorText(error).message);
      setBusy(false);
    }
  };

  return (
    <section className={`${c.panel} ${styles.danger}`} aria-labelledby="delete-title">
      <h2 id="delete-title">문서 삭제</h2>
      <p className={c.hint}>문서와 검색 조각, 원문 파일을 지웁니다. 변경 이력은 남습니다.</p>
      {failure ? (
        <p className={c.message} data-tone="blocked" role="alert">
          지우지 못했습니다. {failure}
        </p>
      ) : null}
      <div className={c.actions} style={{ marginTop: "var(--space-4)" }}>
        {asking ? (
          <>
            <button
              type="button"
              className={c.button}
              data-kind="danger"
              onClick={remove}
              disabled={busy}
            >
              {busy ? "지우는 중…" : `${number} 삭제 확인`}
            </button>
            <button
              type="button"
              className={c.button}
              onClick={() => setAsking(false)}
              disabled={busy}
            >
              취소
            </button>
          </>
        ) : (
          <button
            type="button"
            className={c.button}
            data-kind="danger"
            onClick={() => setAsking(true)}
          >
            삭제
          </button>
        )}
      </div>
    </section>
  );
}

export function DocumentDetail() {
  const { id } = useParams();
  const location = useLocation();
  const api = useApiClient();
  const document = useLoad(
    useCallback(() => api.get<DocumentRow>(`/admin/api/documents/${id}`), [api, id]),
  );
  const history = useLoad(
    useCallback(() => api.get<Change[]>(`/admin/api/documents/${id}/changes`), [api, id]),
  );
  const notice = (location.state as { created?: boolean; replaced?: boolean } | null) ?? {};
  const { reload: reloadDocument } = document;
  const { reload: reloadHistory } = history;
  const reload = useCallback(() => {
    reloadDocument();
    reloadHistory();
  }, [reloadDocument, reloadHistory]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, []);

  if (document.state === "loading") {
    return (
      <p className={c.message} data-tone="muted">
        문서를 불러오는 중입니다…
      </p>
    );
  }
  if (document.state === "error") {
    return (
      <div className={styles.page}>
        <p className={c.message} data-tone="blocked" role="alert">
          {document.status === 404
            ? "문서가 없거나 볼 권한이 없습니다."
            : `문서를 불러오지 못했습니다. ${document.message}`}
        </p>
        <Link to="/documents">문서 목록으로</Link>
      </div>
    );
  }
  const doc = document.data;
  return (
    <div className={styles.page}>
      <nav aria-label="위치" className={styles.crumb}>
        <Link to="/documents">문서</Link> / {registeredNumber(doc)}
      </nav>
      <header className={styles.head}>
        <span className={styles.number}>{registeredNumber(doc)}</span>
        <h1>{doc.title}</h1>
        <div className={styles.badges}>
          <Level level={doc.security_level} />
          {doc.status === "superseded" ? <span className={styles.superseded}>폐지</span> : null}
        </div>
      </header>

      {notice.created ? (
        <p className={c.message} data-tone="ok" role="status">
          올렸습니다. 지금부터 볼 수 있는 사람이 질문하면 이 문서에서 답을 찾습니다.
        </p>
      ) : null}
      {notice.replaced ? (
        <p className={c.message} data-tone="ok" role="status">
          새 판으로 바꿨습니다. 등기번호가 새로 붙었습니다.
        </p>
      ) : null}

      <dl className={c.facts}>
        <div>
          <dt>출처</dt>
          <dd>{doc.origin === "upload" ? "관리 화면에서 올림" : "문서 폴더 (acl.yaml)"}</dd>
        </div>
        <div>
          <dt>관리 부서</dt>
          <dd>{doc.owner_department ?? "문서 폴더 담당"}</dd>
        </div>
        <div>
          <dt>볼 수 있는 사람</dt>
          <dd>{audience(doc)}</dd>
        </div>
        <div>
          <dt>검색 조각</dt>
          <dd>{doc.chunks}개</dd>
        </div>
        <div>
          <dt>원문</dt>
          <dd>{doc.source_path}</dd>
        </div>
        <div>
          <dt>마지막 수집</dt>
          <dd>{doc.synced_at ? dateTime(doc.synced_at) : dateTime(doc.created_at)}</dd>
        </div>
      </dl>

      {doc.editable ? (
        <AccessSection key={doc.id} document={doc} onSaved={reload} />
      ) : (
        <p className={c.message} data-tone="muted">
          {doc.origin === "folder"
            ? "문서 폴더에서 수집한 문서입니다. 권한과 원문은 문서 폴더의 acl.yaml과 원문 파일에서 바꾸고, 다음 수집 때 반영됩니다."
            : "이 문서를 바꿀 권한이 없습니다."}
        </p>
      )}

      <div className={styles.lower}>
        <section className={c.panel} aria-labelledby="history-title">
          <h2 id="history-title">배송조회 이력</h2>
          {history.state === "ready" ? (
            <Timeline items={history.data} origin={doc.origin} />
          ) : history.state === "error" ? (
            <p className={c.message} data-tone="blocked" role="alert">
              이력을 불러오지 못했습니다. {history.message}
            </p>
          ) : (
            <p className={c.hint}>이력을 불러오는 중입니다…</p>
          )}
        </section>
        {doc.editable ? (
          <div className={styles.tools}>
            <ReplaceFile document={doc} />
            <DeleteDocument document={doc} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
