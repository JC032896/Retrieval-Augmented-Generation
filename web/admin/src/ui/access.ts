// 문서 권한 초안: 편집 중인 제목·등급·부서·역할·상태와 그 검사.
import type { DocumentRow } from "../api/types";

export type DocumentStatus = "current" | "superseded";

export type AccessDraft = {
  title: string;
  security_level: number;
  departments: string[];
  roles: string[];
  status: DocumentStatus;
};

export function draftOf(document: DocumentRow): AccessDraft {
  return {
    title: document.title,
    security_level: document.security_level,
    departments: [...document.departments],
    roles: [...document.roles],
    status: document.status === "superseded" ? "superseded" : "current",
  };
}

/** 새로 올리는 문서의 기본 권한은 좁게: 관리 부서만, 사내 등급 (PRODUCT.md "권한이 먼저다"). */
export function narrowDraft(department: string, title = ""): AccessDraft {
  return { title, security_level: 1, departments: [department], roles: [], status: "current" };
}

/** 저장할 수 없는 이유. 없으면 null. 서버도 같은 규칙으로 거부한다. */
export function draftProblem(draft: AccessDraft): string | null {
  if (!draft.title.trim()) return "제목을 적어 주세요.";
  if (draft.departments.length === 0 && draft.roles.length === 0) {
    return "볼 수 있는 부서나 역할을 하나 이상 골라 주세요. 아무도 볼 수 없는 문서가 됩니다.";
  }
  return null;
}

const sorted = (values: readonly string[]) => [...values].sort();

export function sameDraft(a: AccessDraft, b: AccessDraft): boolean {
  return (
    a.title.trim() === b.title.trim() &&
    a.security_level === b.security_level &&
    a.status === b.status &&
    sorted(a.departments).join("|") === sorted(b.departments).join("|") &&
    sorted(a.roles).join("|") === sorted(b.roles).join("|")
  );
}

/** 바뀐 항목을 사람이 읽는 문장으로 ("등급 1 사내 → 0 공개" 등). */
export function changes(before: AccessDraft, after: AccessDraft, levelName: (n: number) => string) {
  const lines: string[] = [];
  if (before.title.trim() !== after.title.trim())
    lines.push(`제목: ${before.title} → ${after.title}`);
  if (before.security_level !== after.security_level) {
    lines.push(
      `등급: ${before.security_level} ${levelName(before.security_level)} → ${after.security_level} ${levelName(after.security_level)}`,
    );
  }
  const diff = (label: string, a: readonly string[], b: readonly string[]) => {
    const added = b.filter((v) => !a.includes(v));
    const removed = a.filter((v) => !b.includes(v));
    if (added.length) lines.push(`${label} 추가: ${added.join(", ")}`);
    if (removed.length) lines.push(`${label} 제외: ${removed.join(", ")}`);
  };
  diff("부서", before.departments, after.departments);
  diff("역할", before.roles, after.roles);
  if (before.status !== after.status) {
    lines.push(after.status === "superseded" ? "상태: 폐지로 바꿈" : "상태: 현행으로 바꿈");
  }
  return lines;
}
