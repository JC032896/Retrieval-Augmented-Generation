// 문서 올리기: 파일 → 제목·등급·볼 수 있는 사람 → 받는 사람 확인 → 올림.
// 기본 권한은 좁게 둔다 (관리 부서만, 사내 등급).
import { type FormEvent, useCallback, useState } from "react";
import { Link, useNavigate } from "react-router";
import type { DocumentRow, Me } from "../api/types";
import { errorText, useLoad } from "../api/useApi";
import { useApiClient } from "../auth/session";
import { AccessEditor } from "../ui/AccessEditor";
import { type AccessDraft, draftProblem, narrowDraft } from "../ui/access";
import { ConfirmRecipients } from "../ui/ConfirmRecipients";
import c from "../ui/controls.module.css";
import { Field } from "../ui/Field";
import { levelName } from "../ui/format";
import { Recipients, usePreview } from "../ui/Recipients";
import styles from "./DocumentForm.module.css";

const ACCEPT = ".pdf,.docx,.md,.hwp,.hwpx";

type Org = { departments: string[]; roles: string[] };

function titleFrom(fileName: string): string {
  return fileName
    .replace(/\.[^.]+$/, "")
    .replace(/[_-]+/g, " ")
    .trim();
}

export function DocumentNew({ me }: { me: Me }) {
  const api = useApiClient();
  const navigate = useNavigate();
  const org = useLoad(useCallback(() => api.get<Org>("/admin/api/org"), [api]));
  const isAdmin = me.roles.includes("admin");
  const [file, setFile] = useState<File | null>(null);
  const [owner, setOwner] = useState(me.department);
  const [draft, setDraft] = useState<AccessDraft>(() => narrowDraft(me.department));
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const preview = usePreview(api, draft);
  const problem = file ? draftProblem(draft) : "올릴 파일을 골라 주세요.";

  const review = (event: FormEvent) => {
    event.preventDefault();
    if (!problem) setConfirming(true);
  };

  const upload = async () => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("title", draft.title.trim());
    form.append("security_level", String(draft.security_level));
    for (const name of draft.departments) form.append("departments", name);
    for (const name of draft.roles) form.append("roles", name);
    if (isAdmin) form.append("owner_department", owner);
    setBusy(true);
    setFailure(null);
    try {
      const created = await api.post<DocumentRow>("/admin/api/documents", form);
      navigate(`/documents/${created.id}`, { state: { created: true } });
    } catch (error) {
      setFailure(errorText(error).message);
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.page}>
      <header className={c.pageHead}>
        <div>
          <h1>문서 올리기</h1>
          <p>
            PDF, DOCX, HWP(한글), Markdown을 올리면 바로 검색에 들어갑니다. 볼 수 있는 사람은 저장
            전에 확인합니다.
          </p>
        </div>
        <Link to="/documents" className={c.button}>
          목록으로
        </Link>
      </header>

      {org.state === "error" ? (
        <p className={c.message} data-tone="blocked" role="alert">
          부서와 역할 목록을 불러오지 못했습니다. {org.message}
        </p>
      ) : null}

      <form className={styles.columns} onSubmit={review} aria-busy={busy}>
        <div className={styles.main}>
          <section className={c.panel} aria-labelledby="file-title">
            <h2 id="file-title">파일</h2>
            <Field
              label="올릴 파일"
              hint='같은 이름의 문서가 이미 있으면 그 문서 화면에서 "파일 교체"를 쓰세요. 스캔한 PDF(글자 없는 그림)는 글자 인식(OCR)으로 읽어서 한 쪽에 몇 초씩 더 걸립니다.'
            >
              <input
                className={c.input}
                type="file"
                accept={ACCEPT}
                disabled={confirming}
                onChange={(event) => {
                  const chosen = event.target.files?.[0] ?? null;
                  setFile(chosen);
                  if (chosen && !draft.title) setDraft({ ...draft, title: titleFrom(chosen.name) });
                }}
              />
            </Field>
            {isAdmin && org.state === "ready" ? (
              <Field
                label="관리 부서"
                hint="이 부서의 문서 담당이 나중에 이 문서를 바꿀 수 있습니다."
                className={styles.spaced}
              >
                <select
                  className={c.select}
                  value={owner}
                  disabled={confirming}
                  onChange={(event) => setOwner(event.target.value)}
                >
                  {org.data.departments.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}
          </section>

          <section className={c.panel} aria-labelledby="access-title">
            <h2 id="access-title">볼 수 있는 사람</h2>
            {org.state === "ready" ? (
              <fieldset disabled={confirming} className={styles.plain}>
                <AccessEditor
                  draft={draft}
                  onChange={setDraft}
                  departments={org.data.departments}
                  roles={org.data.roles}
                />
              </fieldset>
            ) : (
              <p className={c.hint}>부서와 역할 목록을 불러오는 중입니다…</p>
            )}
          </section>
        </div>

        <aside className={styles.side} aria-label="받는 사람">
          <section className={c.panel}>
            <h2>받는 사람</h2>
            <Recipients preview={preview} />
          </section>
          {failure ? (
            <p className={c.message} data-tone="blocked" role="alert">
              올리지 못했습니다. {failure}
            </p>
          ) : null}
          {confirming ? (
            <ConfirmRecipients
              preview={preview}
              lines={[
                `파일: ${file?.name ?? ""}`,
                `등급: ${draft.security_level} ${levelName(draft.security_level)}`,
                ...(isAdmin ? [`관리 부서: ${owner}`] : []),
              ]}
              busy={busy}
              confirmLabel="이 명단으로 올리기"
              onConfirm={upload}
              onBack={() => setConfirming(false)}
            >
              {busy ? (
                <p className={c.hint}>
                  문서를 읽고 검색 색인에 넣는 중입니다. 큰 문서는 수십 초 걸립니다.
                </p>
              ) : null}
            </ConfirmRecipients>
          ) : (
            <div className={styles.next}>
              {problem ? <p className={c.hint}>{problem}</p> : null}
              <button type="submit" className={c.button} data-kind="primary" disabled={!!problem}>
                받는 사람 확인
              </button>
            </div>
          )}
        </aside>
      </form>
    </div>
  );
}
