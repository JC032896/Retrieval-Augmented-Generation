// 한 문단짜리 안내 화면: 권한 없음, 오류, 아직 만들지 않은 화면.
import type { ReactNode } from "react";
import styles from "./Notice.module.css";

export function Notice({
  title,
  children,
  tone = "neutral",
}: {
  title: string;
  children: ReactNode;
  tone?: "neutral" | "blocked";
}) {
  return (
    <section className={styles.notice} data-tone={tone} aria-labelledby="notice-title">
      <h1 id="notice-title">{title}</h1>
      <div className={styles.body}>{children}</div>
    </section>
  );
}
