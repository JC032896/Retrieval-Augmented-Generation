import { describe, expect, it } from "vitest";
import { fakeFetch } from "../test/fixtures";
import { ApiError, createApi } from "./client";

const headers = async () => ({ Authorization: "Bearer t" });

describe("API 클라이언트", () => {
  it("로그인 머리글을 붙여 JSON을 받는다", async () => {
    const { fetcher, calls } = fakeFetch({ "/admin/api/me": { login: "han" } });

    const body = await createApi(headers, fetcher).get<{ login: string }>("/admin/api/me");

    expect(body.login).toBe("han");
    expect(calls[0]?.headers.Authorization).toBe("Bearer t");
  });

  it("서버가 준 오류 문장을 그대로 쓰고, 없으면 상태 코드로 설명한다", async () => {
    const { fetcher } = fakeFetch({
      "/a": new Response(JSON.stringify({ detail: "이 화면을 볼 권한이 없습니다" }), {
        status: 403,
      }),
      "/b": new Response("<html>", { status: 503 }),
      "/c": new Response("", { status: 418 }),
    });
    const api = createApi(headers, fetcher);

    await expect(api.get("/a")).rejects.toMatchObject({
      status: 403,
      message: "이 화면을 볼 권한이 없습니다",
    });
    await expect(api.get("/b")).rejects.toMatchObject({
      status: 503,
      message: expect.stringContaining("준비"),
    });
    await expect(api.get("/c")).rejects.toMatchObject({ message: "요청이 실패했습니다 (418)." });
  });

  it("연결이 안 되면 상태 0의 오류", async () => {
    const offline = async () => {
      throw new TypeError("Failed to fetch");
    };

    const error = await createApi(headers, offline)
      .get("/x")
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 0, message: expect.stringContaining("연결") });
  });

  it("204는 본문 없이 끝난다", async () => {
    const { fetcher } = fakeFetch({ "/d": new Response(null, { status: 204 }) });

    await expect(createApi(headers, fetcher).get("/d")).resolves.toBeUndefined();
  });
});
