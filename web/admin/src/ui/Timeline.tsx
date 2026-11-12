// 배송조회 타임라인: 문서 한 건의 올리기·교체·권한 변경 이력을 최근 것부터 세로로 보여 준다.
import type { components } from "../api/schema";
import { type AccessDraft, changes } from "./access";
import { dateTime, levelName } from "./format";
import styles from "./Timeline.module.css";

export type Change = components["schemas"]["ChangeOut"];

const ACTION: Record<string, string> = {
  upload: "올림",
  replace: "파일 교체",
  access: "권한 변경",
  delete: "삭제",
};

function asDraft(value: Record<string, unknown> | null | undefined): AccessDraft | null {
  if (!value || typeof value.title !== "string") return null;
  const list = (v: unknown) => (Array.isArray(v) ? v.filter((x) => typeof x === "string") : []);
  return {
    title: value.title,
    security_level: typeof value.security_level === "number" ? value.security_level : 0,
    departments: list(value.departments),
    roles: list(value.roles),
    status: value.status === "superseded" ? "superseded" : "current",
  };
}

export function describe(change: Change): string[] {
  const after = asDraft(change.after);
  const before = asDraft(change.before);
  if (change.action === "upload" && after) {
    const who = [...after.departments, ...after.roles].join(", ");
    return [`등급 ${after.security_level} ${levelName(after.security_level)} · ${who}`];
  }
  if (change.action === "access" && after && before) return changes(before, after, levelName);
  if (change.action === "replace") return ["권한은 그대로, 원문만 새 판으로"];
  return [];
}

export function Timeline({ items, origin }: { items: Change[]; origin: string }) {
  if (items.length === 0) {
    return (
      <p className={styles.empty}>
        {origin === "folder"
          ? "문서 폴더(acl.yaml)에서 수집한 문서라 관리 화면의 변경 이력이 없습니다."
          : "아직 기록된 변경이 없습니다."}
      </p>
    );
  }
  return (
    <ol className={styles.timeline} aria-label="배송조회 이력">
      {items.map((change, index) => (
        <li key={change.id} data-latest={index === 0}>
          <div className={styles.head}>
            <strong>{ACTION[change.action] ?? change.action}</strong>
            <span>
              {change.actor_login} ·{" "}
              <time dateTime={change.created_at}>{dateTime(change.created_at)}</time>
            </span>
          </div>
          {describe(change).map((line) => (
            <p key={line} className={styles.line}>
              {line}
            </p>
          ))}
        </li>
      ))}
    </ol>
  );
}
