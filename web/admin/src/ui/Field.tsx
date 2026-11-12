// 입력 칸 하나: 이름(label)과 도움말을 나눈다. 도움말은 aria-describedby로 이어 화면 낭독기가
// 이름 다음에 따로 읽는다 (이름 안에 넣으면 칸 이름이 길어진다).
import { cloneElement, type ReactElement, type ReactNode, useId } from "react";
import c from "./controls.module.css";

type Control = ReactElement<{ id?: string; "aria-describedby"?: string }>;

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  children: Control;
  className?: string | undefined;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const control = cloneElement(children, {
    id,
    ...(hint ? { "aria-describedby": hintId } : {}),
  });
  return (
    <div className={className ? `${c.field} ${className}` : c.field}>
      <label className={c.label} htmlFor={id}>
        {label}
      </label>
      {control}
      {hint ? (
        <span id={hintId} className={c.hint}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}
