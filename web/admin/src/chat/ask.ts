// 질문 API(POST /ask) 호출. 답은 SSE(Server-Sent Events)로 흘러온다:
//   delta {text}   답 조각 (이어 붙여 보여 준다)
//   done  {...}    마지막. 최종 답, 인용, 검증 (delta를 대신한다)
//   error {code, message}  답을 만들지 못함. 스트림이 끝난다
// 스트림을 열기 전의 실패(401, 422, 429 한도, 503 준비 중)는 ApiError로 던진다.
// EventSource는 POST와 로그인 머리글을 못 보내므로 fetch 스트림을 직접 읽는다.
import { ApiError, type HeaderSource } from "../api/client";
import type { Answer } from "./types";

export type SseEvent = { event: string; data: string };

/** 받은 글자를 쌓아 두었다가 빈 줄로 끝난 이벤트만 꺼낸다 (조각이 이벤트 중간에서 끊겨도 된다). */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const events: SseEvent[] = [];
    let end = this.buffer.indexOf("\n\n");
    while (end >= 0) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length > 0) events.push({ event, data: data.join("\n") });
      end = this.buffer.indexOf("\n\n");
    }
    return events;
  }
}

export type AskOutcome = { kind: "done"; answer: Answer } | { kind: "failed"; message: string };

const BEFORE_STREAM: Record<number, string> = {
  401: "로그인이 끝났습니다. 다시 로그인해 주세요.",
  422: "질문을 1,000자 안으로 써 주세요.",
  429: "지금은 질문할 수 없습니다. 잠시 뒤 다시 시도해 주세요.",
  503: "서비스가 아직 준비 중입니다. 잠시 뒤 다시 시도해 주세요.",
};

// 서버가 머리글로 알려 주는 오류 종류. 서버 문장은 운영자용(설정 이름 등)이라 직원에게는 이 문장을 보인다
const BY_CODE: Record<string, string> = {
  llm_not_configured: "답변 기능이 아직 설정되지 않았습니다. 관리자에게 알려 주세요.",
};

async function detail(response: Response): Promise<string> {
  const code = response.headers.get("X-Error-Code");
  if (code && BY_CODE[code]) return BY_CODE[code];
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // 본문이 JSON이 아니면 상태 코드로 설명한다
  }
  return BEFORE_STREAM[response.status] ?? `질문을 보내지 못했습니다 (${response.status}).`;
}

export async function askQuestion(
  question: string,
  options: {
    headers: HeaderSource;
    onDelta: (text: string) => void;
    fetcher?: typeof fetch;
    signal?: AbortSignal;
  },
): Promise<AskOutcome> {
  const fetcher = options.fetcher ?? fetch;
  let response: Response;
  try {
    response = await fetcher("/ask", {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        ...(await options.headers()),
      },
      body: JSON.stringify({ question }),
      ...(options.signal ? { signal: options.signal } : {}),
    });
  } catch {
    throw new ApiError(0, "서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.");
  }
  if (!response.ok) throw new ApiError(response.status, await detail(response));
  if (!response.body) return { kind: "failed", message: "답을 받지 못했습니다." };

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { value, done } = await reader.read();
    const events = parser.push(
      done ? `${decoder.decode()}\n\n` : decoder.decode(value, { stream: true }),
    );
    for (const { event, data } of events) {
      const payload: unknown = JSON.parse(data);
      if (event === "delta") {
        options.onDelta((payload as { text: string }).text);
      } else if (event === "done") {
        return { kind: "done", answer: payload as Answer };
      } else if (event === "error") {
        const message = (payload as { message?: string }).message;
        return { kind: "failed", message: message ?? "답을 만들지 못했습니다." };
      }
    }
    if (done) return { kind: "failed", message: "답이 끝나기 전에 연결이 끊겼습니다." };
  }
}
