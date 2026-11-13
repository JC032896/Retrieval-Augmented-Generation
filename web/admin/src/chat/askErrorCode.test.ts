import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { askQuestion } from "./ask";

const headers = async () => ({ "X-User-Id": "kim" });
const operatorText = "답변 LLM이 설정되지 않았습니다 (ANTHROPIC_API_KEY)";

function reply(status: number, extra: Record<string, string> = {}): typeof fetch {
  return async () =>
    new Response(JSON.stringify({ detail: operatorText }), {
      status,
      headers: { "Content-Type": "application/json", ...extra },
    });
}

describe("질문 API 오류 종류 머리글", () => {
  it("답변 LLM이 없다는 코드가 오면 설정 이름 대신 관리자에게 알리라고 말한다", async () => {
    const fetcher = reply(503, { "X-Error-Code": "llm_not_configured" });

    await expect(askQuestion("q", { headers, onDelta: () => {}, fetcher })).rejects.toEqual(
      new ApiError(503, "답변 기능이 아직 설정되지 않았습니다. 관리자에게 알려 주세요."),
    );
  });

  it("모르는 코드나 코드가 없으면 서버 설명을 그대로 보인다", async () => {
    const unknown = reply(503, { "X-Error-Code": "something_else" });
    const none = reply(503);

    await expect(
      askQuestion("q", { headers, onDelta: () => {}, fetcher: unknown }),
    ).rejects.toThrow(operatorText);
    await expect(askQuestion("q", { headers, onDelta: () => {}, fetcher: none })).rejects.toThrow(
      operatorText,
    );
  });
});
