// 화면 테스트용 가짜 서버: 메서드와 경로로 응답을 고르고, 받은 요청(본문 포함)을 기록한다.
export type Sent = {
  method: string;
  path: string;
  json: unknown;
  form: Record<string, string[]> | null;
};

type Reply = unknown | Response | ((sent: Sent) => unknown | Response);

export function fakeServer(routes: Record<string, Reply>) {
  const sent: Sent[] = [];
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = String(input);
    let json: unknown = null;
    let form: Record<string, string[]> | null = null;
    if (init?.body instanceof FormData) {
      form = {};
      for (const [key, value] of init.body.entries()) {
        const text = typeof value === "string" ? value : `file:${value.name}`;
        form[key] = [...(form[key] ?? []), text];
      }
    } else if (typeof init?.body === "string") {
      json = JSON.parse(init.body);
    }
    const request: Sent = { method, path, json, form };
    sent.push(request);
    const key = Object.keys(routes).find((route) => {
      const [m, p] = route.split(" ", 2);
      return m === method && (p === path || (p?.endsWith("*") && path.startsWith(p.slice(0, -1))));
    });
    if (!key)
      return new Response(JSON.stringify({ detail: `없는 경로 ${method} ${path}` }), {
        status: 404,
      });
    const reply = routes[key];
    const body = typeof reply === "function" ? (reply as (s: Sent) => unknown)(request) : reply;
    if (body instanceof Response) return body;
    if (body === undefined) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { fetcher, sent };
}
