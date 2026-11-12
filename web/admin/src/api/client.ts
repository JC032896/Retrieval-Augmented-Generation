// 관리 API 호출. 로그인 머리글을 붙이고, 실패를 사람이 읽을 문장으로 바꾼다.

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type HeaderSource = () => Promise<Record<string, string>>;

const FALLBACK: Record<number, string> = {
  401: "로그인이 필요합니다.",
  403: "이 화면을 볼 권한이 없습니다.",
  404: "찾는 항목이 없습니다.",
  503: "서버가 아직 준비되지 않았습니다. 잠시 뒤 다시 시도해 주세요.",
};

async function detail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // 본문이 JSON이 아니면 상태 코드로 설명한다
  }
  return FALLBACK[response.status] ?? `요청이 실패했습니다 (${response.status}).`;
}

export function createApi(headers: HeaderSource, fetcher: typeof fetch = fetch) {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetcher(path, {
        ...init,
        headers: { Accept: "application/json", ...(await headers()), ...init.headers },
      });
    } catch {
      throw new ApiError(0, "서버에 연결할 수 없습니다. 네트워크와 서버 상태를 확인해 주세요.");
    }
    if (!response.ok) {
      throw new ApiError(response.status, await detail(response));
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  return {
    get: <T>(path: string) => request<T>(path),
  };
}

export type Api = ReturnType<typeof createApi>;
