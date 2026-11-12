import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { documentRow } from "../test/fixtures";
import { diffRecipients, type Preview, Recipients } from "./Recipients";
import { Tracking, TrackingLegend } from "./Tracking";

const kim = {
  login: "kim",
  name: "김사원",
  department: "개발팀",
  role: "사원",
  clearance_level: 1,
};
const lee = {
  login: "lee",
  name: "이팀장",
  department: "개발팀",
  role: "팀장",
  clearance_level: 2,
};
const park = {
  login: "park",
  name: "박인사",
  department: "인사팀",
  role: "사원",
  clearance_level: 1,
};
const ready = (users: Preview["users"]) =>
  ({ state: "ready", preview: { count: users.length, total_users: 6, users } }) as const;

describe("받는 사람 증감 (최종 검토: 권한 설정이 불안하지 않게)", () => {
  it("기준과 비교해 새로 보게 되는 사람과 더 이상 못 보는 사람을 고른다", () => {
    const diff = diffRecipients(ready([kim, lee]), ready([lee, park]));

    expect(diff?.added.map((u) => u.login)).toEqual(["park"]);
    expect(diff?.removed.map((u) => u.login)).toEqual(["kim"]);
    expect(diffRecipients(undefined, ready([kim]))).toBeNull();
    expect(diffRecipients({ state: "loading" }, ready([kim]))).toBeNull();
  });

  it("명단에 글자와 기호로 표시한다 (색만 쓰지 않는다)", () => {
    render(<Recipients baseline={ready([kim, lee])} preview={ready([lee, park])} />);

    expect(screen.getByText(/2/).closest("p")).toHaveTextContent("2명이 볼 수 있습니다");
    expect(screen.getByText("새로 봄").parentElement).toHaveTextContent("+ 박인사(사원)새로 봄");
    expect(screen.getByText("더 이상 못 봄").parentElement).toHaveTextContent("− 김사원(사원)");
  });

  it("기준이 없으면(새 문서) 증감 표시 없이 명단만", () => {
    render(<Recipients preview={ready([kim])} />);

    expect(screen.queryByText("새로 봄")).not.toBeInTheDocument();
    expect(screen.queryByText("더 이상 못 봄")).not.toBeInTheDocument();
    expect(screen.getByText("김사원(사원)")).toBeInTheDocument();
  });
});

describe("배송조회 범례와 요약", () => {
  it("점 셋의 뜻을 한 번 보여 준다", () => {
    render(<TrackingLegend />);

    expect(screen.getByText(/접수\(폴더 수집·올림\)/)).toBeInTheDocument();
    expect(screen.getByText(/권한 지정/)).toBeInTheDocument();
  });

  it("관리 화면 변경이 없는 폴더 문서는 점만, 변경이 있으면 누가 했는지", () => {
    const { container, rerender } = render(<Tracking document={documentRow()} />);
    // 점의 접근 가능한 이름("폴더 수집 완료")은 남고, 모든 행에 같던 요약 글자는 없다
    expect(screen.queryByText("폴더 수집")).not.toBeInTheDocument();
    expect(screen.getByText(/폴더 수집 완료/)).toBeInTheDocument();

    rerender(
      <Tracking
        document={documentRow({
          origin: "upload",
          last_change: { action: "access", actor_login: "lee", created_at: "2026-11-12T00:00:00Z" },
        })}
      />,
    );
    expect(container).toHaveTextContent("권한 변경 · lee");
  });
});
