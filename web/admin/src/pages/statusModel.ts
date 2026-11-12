// 대시보드가 보여 줄 내용을 서버 응답에서 고른다 (화면과 나눠서 시험한다).
import type { AdminRole, DocumentRow, Status } from "../api/types";

export type Tone = "ok" | "blocked" | "pending";

export type StatusLabel = {
  key: string;
  title: string;
  code: string;
  value: string;
  unit?: string;
  note: string;
  tone: Tone;
};

export type Todo = { title: string; detail: string; link?: { to: string; label: string } };

const MODEL_TEXT: Record<string, { value: string; tone: Tone }> = {
  ready: { value: "준비됨", tone: "ok" },
  lazy: { value: "첫 질문 때 읽음", tone: "pending" },
  loading: { value: "읽는 중", tone: "pending" },
  error: { value: "읽지 못함", tone: "blocked" },
};

function number(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export function statusLabels(status: Status): StatusLabel[] {
  const index = status.index;
  const mismatches = number(index.mismatches);
  const indexBroken = status.db !== "ok" || "error" in index;
  const model = MODEL_TEXT[status.models.status ?? ""] ?? MODEL_TEXT.error;
  const llm = status.llm;
  return [
    {
      key: "index",
      title: "문서 색인",
      code: "INDEX",
      value: indexBroken ? "읽지 못함" : String(number(index.documents)),
      ...(indexBroken ? {} : { unit: "건" }),
      note: indexBroken
        ? "DB에 연결하지 못했습니다"
        : mismatches === 0
          ? "원문과 일치"
          : `원문과 ${mismatches}건 어긋남`,
      tone: indexBroken || mismatches > 0 ? "blocked" : "ok",
    },
    {
      key: "models",
      title: "검색 모델",
      code: "MODEL",
      value: model?.value ?? "읽지 못함",
      note: status.models.error ?? "BGE-M3 임베딩과 리랭커",
      tone: model?.tone ?? "blocked",
    },
    {
      key: "llm",
      title: "답변 LLM",
      code: "LLM",
      value: llm.configured ? "준비됨" : "설정 안 됨",
      note: llm.configured
        ? `${llm.provider} · ${llm.model}`
        : "직원 질문이 답변 단계에서 멈춥니다",
      tone: llm.configured ? "ok" : "blocked",
    },
    todayLabel(status),
  ];
}

/** 오늘 질문: 회사 전체 질문 수와 비용을 하루 비용 한도와 함께 (한도에 가까우면 주의, 넘으면 막힘). */
function todayLabel(status: Status): StatusLabel {
  const usage = status.usage;
  const budget = status.limits.daily_budget_usd;
  if (!usage) {
    return {
      key: "today",
      title: "오늘 질문",
      code: "TODAY",
      value: "읽지 못함",
      note: "사용량을 집계하지 못했습니다",
      tone: "pending",
    };
  }
  const cost = `$${usage.cost_usd.toFixed(2)}`;
  const ratio = budget ? usage.cost_usd / budget : 0;
  return {
    key: "today",
    title: "오늘 질문",
    code: "TODAY",
    value: String(usage.requests),
    unit: "건",
    note: `${usage.users}명 · 비용 ${cost}${budget === null ? "" : ` / 하루 $${budget}`}`,
    tone: ratio >= 1 ? "blocked" : ratio >= 0.8 ? "pending" : "ok",
  };
}

export function todos(status: Status, roles: readonly AdminRole[]): Todo[] {
  const items: Todo[] = [];
  const isAdmin = roles.includes("admin");
  const llm = status.llm;
  if (status.db !== "ok") {
    items.push({
      title: "DB에 연결하지 못했습니다",
      detail: "문서 목록과 권한을 읽을 수 없습니다. 서버의 db 컨테이너를 확인해 주세요.",
    });
  }
  if (!llm.configured) {
    items.push({
      title: "답변 LLM 키가 없습니다",
      detail: "직원이 질문하면 답변 단계에서 멈춥니다 (503).",
      ...(isAdmin ? { link: { to: "/settings", label: "설정에서 확인" } } : {}),
    });
  }
  if (status.models.status === "error") {
    items.push({
      title: "검색 모델을 읽지 못했습니다",
      detail: status.models.error ?? "모델 볼륨을 확인해 주세요.",
    });
  }
  const mismatches = number(status.index.mismatches);
  if (mismatches > 0) {
    items.push({
      title: `원문과 색인이 ${mismatches}건 어긋납니다`,
      detail: "바뀐 원문을 다시 수집해야 합니다 (sync).",
      ...(isAdmin ? { link: { to: "/documents", label: "문서 보기" } } : {}),
    });
  }
  const usage = status.usage;
  const budget = status.limits.daily_budget_usd;
  if (usage && budget !== null && usage.cost_usd >= budget * 0.8) {
    items.push({
      title:
        usage.cost_usd >= budget
          ? "오늘 비용 한도에 닿았습니다"
          : `오늘 비용이 한도의 ${Math.floor((usage.cost_usd / budget) * 100)}%입니다`,
      detail: "한도를 넘으면 직원 질문이 내일 0시까지 멈춥니다 (429).",
      ...(isAdmin ? { link: { to: "/settings", label: "한도 확인" } } : {}),
    });
  }
  return items;
}

function activity(document: DocumentRow): string {
  return document.last_change?.created_at ?? document.synced_at ?? document.created_at;
}

/** 최근에 움직인 문서부터. */
export function recentDocuments(documents: readonly DocumentRow[], limit = 6): DocumentRow[] {
  return [...documents].sort((a, b) => activity(b).localeCompare(activity(a))).slice(0, limit);
}
