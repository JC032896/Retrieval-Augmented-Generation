// 보안 등급 표시. 등급 색은 여기서만 쓴다 (방향 계약: 등급 네 색은 등급에만).
import { levelName } from "./format";
import styles from "./Level.module.css";

export function Level({ level }: { level: number }) {
  return (
    <span className={styles.level} data-level={level}>
      {level} {levelName(level)}
    </span>
  );
}
