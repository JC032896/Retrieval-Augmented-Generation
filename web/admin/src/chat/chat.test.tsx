import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UiConfig } from "../api/types";
import { fakeServer } from "../test/server";
import { Workspace } from "./ChatApp";
import type { ChatSession } from "./session";
import { NewConversation, SavedConversation } from "./Turn";
import type { Answer, ChatMe, Conversation } from "./types";
import { WorkspaceProvider } from "./workspace";

const config: UiConfig = {
  auth_mode: "dev_header",
  oidc: null,
  company_name: "한빛소프트",
  company_logo_url: "",
};

function me(overrides: Partial<ChatMe> = {}): ChatMe {
  return {
    login: "kim",
    name: "김사원",
    department: "개발팀",
    admin_roles: [],
    history_days: 90,
    ...overrides,
  };
}

const ANSWER: Answer = {
  text: "재택은 주 2회까지입니다. [1] 전날 6시까지 신청합니다. [2]",
  refused: false,
  reason: null,
  citations: [
    {
      number: 1,
      chunk_id: 11,
      file: "rules.md",
      title: "취업규칙",
      section: "제12조의3",
      page: null,
    },
    {
      number: 2,
      chunk_id: 12,
      file: "remote.md",
      title: "재택근무 가이드",
      section: "신청 방법",
      page: 3,
    },
  ],
  invalid_citations: [],
  verification: { verified: true, problems: [] },
};

function sse(answer: Answer, conversation?: number): Response {
  const body = [
    'event: delta\ndata: {"text":"재택은 주 2회까지입니다. [1] "}\n\n',
    `event: done\ndata: ${JSON.stringify(answer)}\n\n`,
  ].join("");
  const headers: Record<string, string> = { "Content-Type": "text/event-stream" };
  if (conversation !== undefined) headers["X-Conversation-Id"] = String(conversation);
  return new Response(body, { status: 200, headers });
}

const passage = (chunk: number, content: string, status = "current") => ({
  chunk_id: chunk,
  file: "x.md",
  title: "x",
  section: null,
  page: null,
  content,
  status,
});

const BASE_ROUTES = {
  "GET /api/usage": { questions_left: 187, daily_questions: 200 },
  "GET /api/conversations": { items: [], next_before: null },
  "GET /api/passages/11": passage(11, "재택근무는 주 2회를 한도로 하며 팀장의 승인을 받아야 한다."),
  "GET /api/passages/12": passage(12, "재택근무 전날 오후 6시까지 신청해야 한다.", "superseded"),
};

function show(routes: Record<string, unknown>, options: { user?: ChatMe; path?: string } = {}) {
  const server = fakeServer({ ...BASE_ROUTES, ...routes });
  const user = options.user ?? me();
  const session = {
    state: "signed-in",
    config,
    me: user,
    headers: async () => ({ "X-User-Id": user.login }),
    signOut: vi.fn(),
  } satisfies ChatSession;
  render(
    <WorkspaceProvider me={user} headers={session.headers} fetcher={server.fetcher}>
      <MemoryRouter initialEntries={[options.path ?? "/"]}>
        <Routes>
          <Route path="/" element={<Workspace session={session} />}>
            <Route index element={<NewConversation />} />
            <Route path="history/:id" element={<SavedConversation />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </WorkspaceProvider>,
  );
  return { sent: server.sent, session };
}

async function ask(question: string) {
  const box = screen.getByRole("textbox", { name: "질문" });
  await userEvent.type(box, question);
  await userEvent.keyboard("{Enter}");
}

/** 답의 문장 하나 (형광펜 색은 문장 묶음의 data-marker에 있다). */
const isSentence = (text: string) => (_: string, element: Element | null) =>
  element instanceof HTMLElement &&
  element.dataset.sentence !== undefined &&
  (element.textContent ?? "").startsWith(text);
const findSentence = (text: string) => screen.findByText(isSentence(text));
const getSentence = (text: string) => screen.getByText(isSentence(text));

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe("묻고 답 받기", () => {
  it("답이 끝나면 근거 있는 문장에 번호별 형광펜을 긋고 근거 문단을 보여 준다", async () => {
    const { sent } = show({ "POST /ask": () => sse(ANSWER) });
    expect(
      await screen.findByRole("heading", { name: "김사원 님, 무엇이 궁금한가요?" }),
    ).toBeVisible();
    expect(await screen.findByText("187")).toBeInTheDocument();

    await ask("재택근무는 일주일에 몇 번까지 돼?");

    expect(
      await screen.findByRole("heading", { name: "재택근무는 일주일에 몇 번까지 돼?" }),
    ).toBeVisible();
    const first = await findSentence("재택은 주 2회까지입니다.");
    expect(first).toHaveAttribute("data-marker", "yellow");
    expect(getSentence("전날 6시까지 신청합니다.")).toHaveAttribute("data-marker", "mint");
    expect(screen.getByText(/근거 2건 · 인용 확인됨/)).toBeInTheDocument();

    const sources = screen.getByRole("complementary", { name: /근거 문단/ });
    expect(await within(sources).findByText(/주 2회를 한도로/)).toBeInTheDocument();
    expect(within(sources).getByText("제12조의3 · 현행")).toBeInTheDocument();
    expect(
      await within(sources).findByText("폐지되었거나 새 판으로 바뀐 문서"),
    ).toBeInTheDocument();
    expect(within(sources).getByText(/신청 방법 · 3쪽/)).toBeInTheDocument();

    expect(sent.find((s) => s.path === "/ask")?.json).toEqual({
      question: "재택근무는 일주일에 몇 번까지 돼?",
    });
    // 답이 끝나면 남은 질문 수와 기록 목록을 다시 읽는다
    await waitFor(() => expect(sent.filter((s) => s.path === "/api/usage")).toHaveLength(2));
    expect(sent.filter((s) => s.path === "/api/conversations")).toHaveLength(2);
  });

  it("번호표를 누르면 같은 번호의 근거 문단으로 가고, 마우스를 올리면 함께 진해진다", async () => {
    show({ "POST /ask": () => sse(ANSWER) });
    await ask("재택 질문");

    const tag = await screen.findByRole("button", { name: "근거 2: 재택근무 가이드" });
    const card = screen.getByRole("article", { name: "2 재택근무 가이드" });
    await userEvent.click(tag);

    expect(card).toHaveFocus();
    expect(card.className).toMatch(/active/);
    fireEvent.mouseOver(getSentence("재택은 주 2회까지입니다."));
    expect(screen.getByRole("article", { name: "1 취업규칙" }).className).toMatch(/active/);
    expect(card.className).not.toMatch(/active/);
  });

  it("근거로 확인되지 않은 문장은 형광펜 대신 점선 밑줄과 안내를 받는다", async () => {
    const unverified: Answer = {
      ...ANSWER,
      verification: {
        verified: false,
        problems: [
          { text: "전날 6시까지 신청합니다. [2]", status: "low_overlap", unsupported_numbers: [] },
        ],
      },
    };
    show({ "POST /ask": () => sse(unverified) });
    await ask("재택 질문");

    const sentence = await findSentence("전날 6시까지 신청합니다.");
    expect(sentence).not.toHaveAttribute("data-marker");
    expect(screen.getByText(/근거 문단에서 확인되지 않은/)).toBeInTheDocument();
    expect(screen.getByText(/확인 안 된 문장 있음/)).toBeInTheDocument();
  });

  it("거절한 답은 안내를 붙이고 근거 칸은 비어 있다고 말한다", async () => {
    const refused: Answer = {
      ...ANSWER,
      text: "문서에서 찾을 수 없습니다.",
      refused: true,
      reason: "not_in_documents",
      citations: [],
      verification: null,
    };
    show({ "POST /ask": () => sse(refused) });
    await ask("해외 출장비는?");

    expect(await screen.findByText(/근거를 찾지 못해 답하지 않았습니다/)).toBeInTheDocument();
    expect(screen.getByText("이 답에는 인용한 근거 문단이 없습니다.")).toBeInTheDocument();
    expect(screen.getByText(/근거를 찾지 못함/)).toBeInTheDocument();
  });

  it("한도에 걸리면 서버의 설명과 다시 묻기를 보여 준다", async () => {
    let calls = 0;
    show({
      "POST /ask": () => {
        calls += 1;
        return calls === 1
          ? new Response(JSON.stringify({ detail: "오늘 질문 한도(200회)를 모두 썼습니다." }), {
              status: 429,
            })
          : sse(ANSWER);
      },
    });
    await ask("재택 질문");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("오늘 질문 한도(200회)를 모두 썼습니다.");
    await userEvent.click(within(alert).getByRole("button", { name: "다시 묻기" }));
    expect(await findSentence("재택은 주 2회까지입니다.")).toBeInTheDocument();
  });

  it("한글을 조합하는 중의 Enter로는 묻지 않고, 오늘 질문을 다 쓰면 입력을 막는다", async () => {
    const { sent } = show({ "GET /api/usage": { questions_left: 3, daily_questions: 200 } });
    const box = screen.getByRole("textbox", { name: "질문" });
    await userEvent.type(box, "재택");
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(sent.some((s) => s.path === "/ask")).toBe(false);
  });

  it("오늘 질문을 모두 쓰면 입력창을 막는다", async () => {
    show({ "GET /api/usage": { questions_left: 0, daily_questions: 200 } });

    const box = screen.getByRole("textbox", { name: "질문" });
    await waitFor(() => expect(box).toBeDisabled());
    expect(box).toHaveAttribute("placeholder", "오늘 질문을 모두 썼습니다");
  });

  it("볼 수 없게 된 근거 문단은 이유를 말한다", async () => {
    show({
      "POST /ask": () => sse(ANSWER),
      "GET /api/passages/12": new Response(JSON.stringify({ detail: "없음" }), { status: 404 }),
    });
    await ask("재택 질문");

    expect(await screen.findByText(/문서가 바뀌었거나 지금 볼 수 없어/)).toBeInTheDocument();
  });
});

const TODAY = new Date().toISOString();
const SAVED: Conversation = {
  id: 5,
  title: "재택근무는 일주일에 몇 번까지 돼?",
  turns: [
    {
      id: 41,
      created_at: TODAY,
      question: "재택근무는 일주일에 몇 번까지 돼?",
      search_question: null,
      outcome: "answered",
      hidden: false,
      answer: ANSWER,
    },
  ],
};
const FOLLOW_UP: Answer = {
  ...ANSWER,
  text: "계약직도 주 2회까지입니다. [1]",
  citations: ANSWER.citations.slice(0, 1),
  search_question: "계약직의 재택근무는 주 몇 회까지 가능한가?",
};

async function askAndWait(question: string, sentence: string) {
  await ask(question);
  await findSentence(sentence);
}

describe("한 대화에서 이어 묻기", () => {
  it("첫 질문은 질문만 보내고, 이어 묻는 질문은 대화 id와 앞 질문을 함께 보낸다", async () => {
    const answers = [sse(ANSWER, 9), sse(FOLLOW_UP, 9)];
    const { sent } = show({ "POST /ask": () => answers.shift() });

    await askAndWait("재택근무는 일주일에 몇 번까지 돼?", "재택은 주 2회까지입니다.");
    await askAndWait("그럼 계약직은?", "계약직도 주 2회까지입니다.");

    const bodies = sent.filter((s) => s.path === "/ask").map((s) => s.json);
    expect(bodies).toEqual([
      { question: "재택근무는 일주일에 몇 번까지 돼?" },
      {
        question: "그럼 계약직은?",
        conversation_id: 9,
        previous: ["재택근무는 일주일에 몇 번까지 돼?"],
      },
    ]);
    // 두 질문이 한 대화에 쌓이고, 서버가 다시 쓴 질문을 보여 준다
    const questions = document.querySelectorAll("article[aria-busy] h2");
    expect([...questions].map((h) => h.textContent)).toEqual([
      "재택근무는 일주일에 몇 번까지 돼?",
      "그럼 계약직은?",
    ]);
    expect(screen.getByText(/2번째 질문 ·/)).toBeInTheDocument();
    expect(
      screen.getByText("계약직의 재택근무는 주 몇 회까지 가능한가?", { selector: "q" }),
    ).toBeInTheDocument();
  });

  it("근거 칸은 마지막 답을 보여 주고, 앞 답의 번호표를 누르면 그 답의 근거로 바뀐다", async () => {
    const answers = [sse(ANSWER, 9), sse(FOLLOW_UP, 9)];
    show({ "POST /ask": () => answers.shift() });
    await askAndWait("재택근무는 일주일에 몇 번까지 돼?", "재택은 주 2회까지입니다.");
    await askAndWait("그럼 계약직은?", "계약직도 주 2회까지입니다.");

    const sources = () => screen.getByRole("complementary", { name: /근거 문단/ });
    expect(sources()).toHaveTextContent("근거 문단 1 · 2번째 질문");
    await userEvent.click(screen.getByRole("button", { name: "근거 2: 재택근무 가이드" }));

    expect(sources()).toHaveTextContent("근거 문단 2 · 1번째 질문");
  });

  it("기록을 두지 않는 설치에서도 앞 질문을 보내 이어 물을 수 있다", async () => {
    const answers = [sse(ANSWER), sse(FOLLOW_UP)];
    const { sent } = show(
      { "POST /ask": () => answers.shift() },
      { user: me({ history_days: 0 }) },
    );
    await askAndWait("재택근무는 일주일에 몇 번까지 돼?", "재택은 주 2회까지입니다.");
    await askAndWait("그럼 계약직은?", "계약직도 주 2회까지입니다.");

    expect(sent.filter((s) => s.path === "/ask").map((s) => s.json)).toEqual([
      { question: "재택근무는 일주일에 몇 번까지 돼?" },
      { question: "그럼 계약직은?", previous: ["재택근무는 일주일에 몇 번까지 돼?"] },
    ]);
  });
});

describe("대화 기록", () => {
  it("목록은 대화 단위로 오늘과 이전으로 나누고, 대화를 열면 질문과 답들을 쌓아 보여 준다", async () => {
    const old = new Date();
    old.setDate(old.getDate() - 10);
    const opened: Conversation = {
      ...SAVED,
      turns: [
        ...SAVED.turns,
        {
          id: 42,
          created_at: TODAY,
          question: "그럼 계약직은?",
          search_question: "계약직의 재택근무는 주 몇 회까지 가능한가?",
          outcome: "answered",
          hidden: false,
          answer: FOLLOW_UP,
        },
      ],
    };
    show(
      {
        "GET /api/conversations": {
          items: [
            { id: 5, title: SAVED.title, updated_at: TODAY, turns: 2 },
            { id: 3, title: "해외 출장비는?", updated_at: old.toISOString(), turns: 1 },
          ],
          next_before: old.toISOString(),
        },
        "GET /api/conversations?before=*": {
          items: [{ id: 1, title: "첫 질문", updated_at: old.toISOString(), turns: 1 }],
          next_before: null,
        },
        "GET /api/conversations/5": opened,
      },
      { path: "/history/5" },
    );

    const today = await screen.findByRole("region", { name: "오늘" });
    const link = within(today).getByRole("link", { name: /재택근무는/ });
    expect(link).toHaveAttribute("aria-current", "page");
    expect(link).toHaveTextContent("질문 2개");
    expect(screen.getByRole("region", { name: "이전" })).toHaveTextContent("해외 출장비는?");
    expect(await findSentence("재택은 주 2회까지입니다.")).toHaveAttribute("data-marker", "yellow");
    expect(getSentence("계약직도 주 2회까지입니다.")).toBeInTheDocument();
    expect(screen.getByText(/이렇게 이해하고 찾았습니다/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "더 보기" }));
    expect(await screen.findByRole("link", { name: /첫 질문/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "더 보기" })).not.toBeInTheDocument();
  });

  it("저장된 대화에 이어 물으면 그 대화 id와 앞 질문들을 보낸다", async () => {
    const { sent } = show(
      { "GET /api/conversations/5": SAVED, "POST /ask": () => sse(FOLLOW_UP, 5) },
      { path: "/history/5" },
    );
    await findSentence("재택은 주 2회까지입니다.");
    await askAndWait("그럼 계약직은?", "계약직도 주 2회까지입니다.");

    expect(sent.find((s) => s.path === "/ask")?.json).toEqual({
      question: "그럼 계약직은?",
      conversation_id: 5,
      previous: ["재택근무는 일주일에 몇 번까지 돼?"],
    });
  });

  it("권한이 바뀌어 가려진 답은 이유를 말하고, 다시 물으면 같은 대화에서 다시 답한다", async () => {
    const hidden: Conversation = {
      ...SAVED,
      turns: SAVED.turns.map((turn) => ({ ...turn, hidden: true, answer: null })),
    };
    const { sent } = show(
      { "GET /api/conversations/5": hidden, "POST /ask": () => sse(ANSWER, 5) },
      { path: "/history/5" },
    );

    expect(await screen.findByText(/지금은 볼 수 없어/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "다시 묻기" }));

    expect(await findSentence("재택은 주 2회까지입니다.")).toBeInTheDocument();
    expect(sent.find((s) => s.path === "/ask")?.json).toEqual({
      question: SAVED.title,
      conversation_id: 5,
      previous: [SAVED.title],
    });
  });

  it("대화 하나를 확인한 뒤 지우고 첫 화면으로 돌아간다", async () => {
    const { sent } = show(
      { "GET /api/conversations/5": SAVED, "DELETE /api/conversations/5": undefined },
      { path: "/history/5" },
    );

    await userEvent.click(await screen.findByRole("button", { name: "이 대화 지우기" }));
    await userEvent.click(screen.getByRole("button", { name: "지우기" }));

    expect(await screen.findByRole("heading", { name: /무엇이 궁금한가요/ })).toBeInTheDocument();
    expect(sent.some((s) => s.method === "DELETE" && s.path === "/api/conversations/5")).toBe(true);
  });

  it("기록 모두 지우기는 감사 기록이 남는다는 확인을 거친다", async () => {
    let deleted = false;
    const { sent } = show({
      "GET /api/conversations": () => ({
        items: deleted ? [] : [{ id: 5, title: SAVED.title, updated_at: TODAY, turns: 1 }],
        next_before: null,
      }),
      "DELETE /api/history": () => {
        deleted = true;
        return { deleted: 1 };
      },
    });

    await userEvent.click(await screen.findByRole("button", { name: "기록 모두 지우기" }));
    expect(screen.getByText(/회사 감사 기록은 그대로 남습니다/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "취소" }));
    await userEvent.click(screen.getByRole("button", { name: "기록 모두 지우기" }));
    await userEvent.click(screen.getByRole("button", { name: "모두 지우기" }));

    await waitFor(() =>
      expect(sent.some((s) => s.method === "DELETE" && s.path === "/api/history")).toBe(true),
    );
    expect(await screen.findByText("아직 물어본 질문이 없습니다.")).toBeInTheDocument();
  });

  it("없는 대화는 지웠거나 기간이 지났다고 말한다", async () => {
    show({}, { path: "/history/77" });

    expect(
      await screen.findByText("이미 지웠거나 보관 기간이 지난 대화입니다."),
    ).toBeInTheDocument();
  });

  it("기록을 저장하지 않는 회사에서는 목록을 읽지 않는다", async () => {
    const { sent } = show({}, { user: me({ history_days: 0 }) });

    expect(await screen.findByText(/대화 기록을 저장하지 않도록/)).toBeInTheDocument();
    expect(sent.some((s) => s.path.startsWith("/api/conversations"))).toBe(false);
    expect(screen.queryByText(/일 동안 나만 볼 수 있게/)).not.toBeInTheDocument();
  });
});

describe("목록칸 아래", () => {
  it("관리 역할이 있는 사람에게만 관리 화면 링크를 보이고, 로그아웃을 부른다", async () => {
    const { session } = show({}, { user: me({ admin_roles: ["doc_manager"] }) });

    expect(screen.getByRole("link", { name: "관리 화면" })).toHaveAttribute("href", "/admin/");
    expect(screen.getByText("기록은 90일 동안 나만 볼 수 있게 보관됩니다.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    expect(session.signOut).toHaveBeenCalled();
  });

  it("관리 역할이 없으면 링크가 없고, 좁은 화면의 목록 단추가 열고 닫는다", async () => {
    show({});

    expect(screen.queryByRole("link", { name: "관리 화면" })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "지난 질문" });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent("닫기");
  });
});
