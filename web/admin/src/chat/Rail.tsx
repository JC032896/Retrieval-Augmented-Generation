// 왼쪽 목록칸: 회사 이름, 새 질문, 지난 질문(오늘/이전), 아래에 로그인한 사람과 관리 화면 링크.
import { useEffect, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router";
import styles from "./Rail.module.css";
import type { HistoryPage, TurnSummary } from "./types";
import { useWorkspace } from "./workspace";

function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

export function whenText(iso: string, now = new Date()): string {
  const at = new Date(iso);
  const time = at.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  if (sameDay(at, now)) return time;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(at, yesterday)) return `어제 ${time}`;
  return at.toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
}

function useHistory() {
  const { api, me, historyRound } = useWorkspace();
  const [items, setItems] = useState<TurnSummary[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    if (me.history_days === 0) return;
    let alive = true;
    void historyRound;
    api
      .get<HistoryPage>("/api/history")
      .then((page) => {
        if (!alive) return;
        setItems(page.items);
        setNext(page.next_before);
        setFailed(null);
      })
      .catch((error: unknown) => alive && setFailed(error instanceof Error ? error.message : ""));
    return () => {
      alive = false;
    };
  }, [api, me.history_days, historyRound]);
  const more = async () => {
    if (next === null) return;
    const page = await api.get<HistoryPage>(`/api/history?before=${next}`);
    setItems((current) => [...current, ...page.items]);
    setNext(page.next_before);
  };
  return { items, next, failed, more, setItems };
}

function ClearAll({ onCleared }: { onCleared: () => void }) {
  const { api } = useWorkspace();
  const [asking, setAsking] = useState(false);
  const navigate = useNavigate();
  if (!asking) {
    return (
      <button type="button" className={styles.quiet} onClick={() => setAsking(true)}>
        기록 모두 지우기
      </button>
    );
  }
  return (
    <fieldset className={styles.confirm}>
      <legend className="visually-hidden">기록 모두 지우기 확인</legend>
      <p>내 대화 기록을 모두 지울까요? 회사 감사 기록은 그대로 남습니다.</p>
      <div className={styles.confirmButtons}>
        <button
          type="button"
          className={styles.danger}
          onClick={async () => {
            await api.delete("/api/history");
            setAsking(false);
            onCleared();
            navigate("/");
          }}
        >
          모두 지우기
        </button>
        <button type="button" className={styles.quiet} onClick={() => setAsking(false)}>
          취소
        </button>
      </div>
    </fieldset>
  );
}

export function Rail({
  companyName,
  logo,
  onSignOut,
}: {
  companyName: string;
  logo: string;
  onSignOut: () => void;
}) {
  const { me, reset, refreshHistory } = useWorkspace();
  const { items, next, failed, more, setItems } = useHistory();
  const now = new Date();
  const today = items.filter((item) => sameDay(new Date(item.created_at), now));
  const earlier = items.filter((item) => !sameDay(new Date(item.created_at), now));
  const group = (title: string, list: TurnSummary[]) =>
    list.length === 0 ? null : (
      <section className={styles.group} aria-label={title}>
        <h2 className={styles.groupTitle}>{title}</h2>
        <ul>
          {list.map((item) => (
            <li key={item.id}>
              <NavLink
                to={`/history/${item.id}`}
                className={({ isActive }) => `${styles.item} ${isActive ? styles.current : ""}`}
              >
                <span className={styles.itemText}>{item.question}</span>
                <span className={styles.itemWhen}>
                  {whenText(item.created_at, now)}
                  {item.outcome === "refused" ? " · 근거 없음" : ""}
                </span>
              </NavLink>
            </li>
          ))}
        </ul>
      </section>
    );

  return (
    <nav className={styles.rail} aria-label="채팅">
      <div className={styles.brand}>
        {logo ? <img src={logo} alt="" className={styles.logo} /> : null}
        <span>{companyName || "사내 문서 질의"}</span>
      </div>
      <Link to="/" className={styles.new} onClick={reset}>
        새 질문
      </Link>
      <div className={styles.history}>
        {me.history_days === 0 ? (
          <p className={styles.off}>이 회사는 대화 기록을 저장하지 않도록 설정했습니다.</p>
        ) : (
          <>
            {failed !== null ? (
              <p className={styles.off}>지난 질문을 불러오지 못했습니다.</p>
            ) : null}
            {items.length === 0 && failed === null ? (
              <p className={styles.off}>아직 물어본 질문이 없습니다.</p>
            ) : null}
            {group("오늘", today)}
            {group("이전", earlier)}
            {next !== null ? (
              <button type="button" className={styles.quiet} onClick={() => void more()}>
                더 보기
              </button>
            ) : null}
          </>
        )}
      </div>
      <div className={styles.foot}>
        <p className={styles.who}>
          {me.name} <span>{me.department}</span>
        </p>
        {me.history_days > 0 ? (
          <p className={styles.keep}>기록은 {me.history_days}일 동안 나만 볼 수 있게 보관됩니다.</p>
        ) : null}
        <div className={styles.footActions}>
          {me.admin_roles.length > 0 ? (
            <a href="/admin/" className={styles.quiet}>
              관리 화면
            </a>
          ) : null}
          <button type="button" className={styles.quiet} onClick={onSignOut}>
            로그아웃
          </button>
          {me.history_days > 0 && items.length > 0 ? (
            <ClearAll
              onCleared={() => {
                setItems([]);
                refreshHistory();
              }}
            />
          ) : null}
        </div>
      </div>
    </nav>
  );
}
