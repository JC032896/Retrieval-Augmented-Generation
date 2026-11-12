// 화면 문구와 표시 규칙. 화면 코드는 여기 함수로만 번호, 등급, 역할을 표시한다.
import type { AdminRole, DocumentRow } from "../api/types";

export const LEVELS = [
  { level: 0, name: "공개" },
  { level: 1, name: "사내" },
  { level: 2, name: "대외비" },
  { level: 3, name: "기밀" },
] as const;

export function levelName(level: number): string {
  return LEVELS.find((item) => item.level === level)?.name ?? `등급 ${level}`;
}

export const ROLE_NAMES: Record<AdminRole, string> = {
  admin: "중앙 관리자",
  doc_manager: "부서 문서 담당",
  auditor: "감사 담당",
};

/** 문서의 등기번호: 폴더 문서 FD, 올린 문서 UP + 4자리 번호. */
export function registeredNumber(document: Pick<DocumentRow, "id" | "origin">): string {
  const prefix = document.origin === "upload" ? "UP" : "FD";
  return `${prefix}-${String(document.id).padStart(4, "0")}`;
}

const ACTIONS: Record<string, string> = {
  upload: "올림",
  replace: "파일 교체",
  access: "권한 변경",
  delete: "삭제",
};

export type TrackStep = { label: string; done: boolean };

/** 배송조회 단계: 접수(폴더 수집 또는 올림) → 권한 지정 → 그 뒤의 변경. */
export function trackingSteps(document: Pick<DocumentRow, "origin" | "last_change">): {
  steps: TrackStep[];
  summary: string;
} {
  const received = document.origin === "upload" ? "올림" : "폴더 수집";
  const change = document.last_change;
  const changedLater =
    change !== null && (change.action === "access" || change.action === "replace");
  const summary = change
    ? `${ACTIONS[change.action] ?? change.action} · ${change.actor_login}`
    : received;
  return {
    steps: [
      { label: received, done: true },
      { label: "권한 지정", done: true },
      {
        label: changedLater ? (ACTIONS[change.action] ?? "변경") : "변경 없음",
        done: changedLater,
      },
    ],
    summary,
  };
}

/** 볼 수 있는 사람: "개발팀, 인사팀 · 3명". 부서와 역할을 모두 적는다. */
export function audience(document: Pick<DocumentRow, "departments" | "roles" | "viewers">): string {
  const who = [...document.departments, ...document.roles].join(", ");
  return `${who || "없음"} · ${document.viewers}명`;
}

const TIME = new Intl.DateTimeFormat("ko-KR", {
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function dateTime(value: string | Date): string {
  return TIME.format(typeof value === "string" ? new Date(value) : value);
}
