import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { askQuestion, SseParser } from "./ask";

const DONE = {
  text: "7일 이내입니다. [1]",
  refused: false,
  reason: null,
  citations: [],
  invalid_citations: [],
  verification: null,
};

function stream(chunks: string[], status = 200): typeof fetch {
  return async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
    return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
  };
}

const headers = async () => ({ "X-User-Id": "kim" });

describe("SSE 읽기", () => {
  it("이벤트 중간에서 끊긴 조각과 CRLF 줄바꿈을 이어 붙인다", () => {
    const parser = new SseParser();

    expect(parser.push('event: delta\r\ndata: {"text":"7일')).toEqual([]);
    expect(parser.push(' 이내"}\r\n\r\nevent: done\ndata: {}\n')).toEqual([
      { event: "delta", data: '{"text":"7일 이내"}' },
    ]);
    expect(parser.push("\n: 주석\n\n")).toEqual([{ event: "done", data: "{}" }]);
  });

  it("delta를 차례로 넘기고 done의 답을 돌려준다", async () => {
    const deltas: string[] = [];
    const outcome = await askQuestion("정산 기한은?", {
      headers,
      onDelta: (text) => deltas.push(text),
      fetcher: stream([
        'event: delta\ndata: {"text":"7일 "}\n\n',
        'event: delta\ndata: {"text":"이내입니다. [1]"}\n\nevent: done\n',
        `data: ${JSON.stringify(DONE)}\n\n`,
      ]),
    });

    expect(deltas).toEqual(["7일 ", "이내입니다. [1]"]);
    expect(outcome).toEqual({ kind: "done", answer: DONE });
  });

  it("error 이벤트와 done 없이 끝난 스트림은 실패로 돌려준다", async () => {
    const failed = await askQuestion("q", {
      headers,
      onDelta: () => {},
      fetcher: stream([
        'event: error\ndata: {"code":"generation_failed","message":"답변을 만들지 못했습니다."}\n\n',
      ]),
    });
    const cut = await askQuestion("q", {
      headers,
      onDelta: () => {},
      fetcher: stream(['event: delta\ndata: {"text":"7일"}\n\n']),
    });

    expect(failed).toEqual({ kind: "failed", message: "답변을 만들지 못했습니다." });
    expect(cut).toEqual({ kind: "failed", message: "답이 끝나기 전에 연결이 끊겼습니다." });
  });

  it("스트림을 열기 전의 실패는 서버 설명을 담은 ApiError다", async () => {
    const limited: typeof fetch = async () =>
      new Response(JSON.stringify({ detail: "오늘 질문 한도(200회)를 모두 썼습니다." }), {
        status: 429,
      });
    const bare: typeof fetch = async () => new Response("busy", { status: 503 });
    const offline: typeof fetch = async () => {
      throw new TypeError("network");
    };

    await expect(
      askQuestion("q", { headers, onDelta: () => {}, fetcher: limited }),
    ).rejects.toEqual(new ApiError(429, "오늘 질문 한도(200회)를 모두 썼습니다."));
    await expect(askQuestion("q", { headers, onDelta: () => {}, fetcher: bare })).rejects.toThrow(
      "서비스가 아직 준비 중입니다",
    );
    await expect(
      askQuestion("q", { headers, onDelta: () => {}, fetcher: offline }),
    ).rejects.toThrow("서버에 연결할 수 없습니다");
  });

  it("질문과 로그인 머리글을 보낸다", async () => {
    let sent: RequestInit | undefined;
    const capture: typeof fetch = async (_input, init) => {
      sent = init;
      return stream([`event: done\ndata: ${JSON.stringify(DONE)}\n\n`])("/ask");
    };

    await askQuestion("정산 기한은?", { headers, onDelta: () => {}, fetcher: capture });

    expect(sent?.method).toBe("POST");
    expect(sent?.body).toBe(JSON.stringify({ question: "정산 기한은?" }));
    expect(sent?.headers).toMatchObject({ "X-User-Id": "kim", Accept: "text/event-stream" });
  });
});
