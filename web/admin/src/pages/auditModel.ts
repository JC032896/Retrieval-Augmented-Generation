// 감사 기록 화면의 표시 규칙과 거르기 → 요청 주소 (화면과 나눠서 시험한다).
export const OUTCOMES = {
  answered: { label: "답변", tone: "ok" },
  refused: { label: "거절", tone: "pending" },
  error: { label: "오류", tone: "blocked" },
  cancelled: { label: "중단", tone: "muted" },
} as const;

export function outcomeLabel(outcome: string): string {
  return OUTCOMES[outcome as keyof typeof OUTCOMES]?.label ?? outcome;
}

export type AuditFilter = {
  login: string;
  outcome: "" | keyof typeof OUTCOMES;
  since: string; // YYYY-MM-DD (그날 0시부터)
  until: string; // YYYY-MM-DD (그날까지 포함)
};

export const EMPTY_FILTER: AuditFilter = { login: "", outcome: "", since: "", until: "" };

/** 날짜는 서버 기준 시간대와 같게 한국 시간(+09:00)으로 보낸다. until은 다음 날 0시 직전까지. */
export function auditQuery(filter: AuditFilter, beforeId?: number, limit = 50): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (filter.login.trim()) params.set("login", filter.login.trim());
  if (filter.outcome) params.set("outcome", filter.outcome);
  if (filter.since) params.set("since", `${filter.since}T00:00:00+09:00`);
  if (filter.until) {
    const next = new Date(`${filter.until}T00:00:00+09:00`);
    next.setUTCDate(next.getUTCDate() + 1);
    params.set("until", next.toISOString());
  }
  if (beforeId !== undefined) params.set("before_id", String(beforeId));
  return `/admin/api/audit?${params}`;
}

export function money(value: number | null): string {
  return value === null ? "-" : `$${value.toFixed(4)}`;
}

export function seconds(ms: number | null): string {
  return ms === null ? "-" : `${(ms / 1000).toFixed(1)}초`;
}
