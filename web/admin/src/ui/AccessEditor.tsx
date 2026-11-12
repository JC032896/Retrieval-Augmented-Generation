// 문서의 제목·보안 등급·볼 수 있는 부서와 역할·상태를 고르는 칸.
import { useId } from "react";
import type { AccessDraft, DocumentStatus } from "./access";
import c from "./controls.module.css";
import { Field } from "./Field";
import { LEVELS } from "./format";

function toggle(list: string[], value: string, on: boolean): string[] {
  return on ? [...list, value] : list.filter((item) => item !== value);
}

export function AccessEditor({
  draft,
  onChange,
  departments,
  roles,
  showStatus = false,
}: {
  draft: AccessDraft;
  onChange: (draft: AccessDraft) => void;
  departments: readonly string[];
  roles: readonly string[];
  showStatus?: boolean;
}) {
  const id = useId();
  const set = (patch: Partial<AccessDraft>) => onChange({ ...draft, ...patch });
  return (
    <div className={c.stack}>
      <Field label="제목" hint="답변의 인용과 문서 목록에 이 제목이 보입니다.">
        <input
          className={c.input}
          value={draft.title}
          onChange={(event) => set({ title: event.target.value })}
          maxLength={200}
          required
        />
      </Field>

      <fieldset className={c.field}>
        <legend>보안 등급</legend>
        <div className={c.choices}>
          {LEVELS.map((item) => (
            <label key={item.level} className={c.choice}>
              <input
                type="radio"
                name={`${id}-level`}
                checked={draft.security_level === item.level}
                onChange={() => set({ security_level: item.level })}
              />
              {item.level} {item.name}
            </label>
          ))}
        </div>
        <span className={c.hint}>사용자의 열람 등급이 이 등급 이상이어야 볼 수 있습니다.</span>
      </fieldset>

      <fieldset className={c.field}>
        <legend>볼 수 있는 부서</legend>
        <div className={c.choices}>
          {departments.map((name) => (
            <label key={name} className={c.choice}>
              <input
                type="checkbox"
                checked={draft.departments.includes(name)}
                onChange={(event) =>
                  set({ departments: toggle(draft.departments, name, event.target.checked) })
                }
              />
              {name}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className={c.field}>
        <legend>볼 수 있는 역할</legend>
        <div className={c.choices}>
          {roles.map((name) => (
            <label key={name} className={c.choice}>
              <input
                type="checkbox"
                checked={draft.roles.includes(name)}
                onChange={(event) =>
                  set({ roles: toggle(draft.roles, name, event.target.checked) })
                }
              />
              {name}
            </label>
          ))}
        </div>
        <span className={c.hint}>
          부서나 역할 중 하나에 맞으면 됩니다. 예: 인사팀 + 임원이면 인사팀 전원과 다른 부서 임원.
        </span>
      </fieldset>

      {showStatus ? (
        <fieldset className={c.field}>
          <legend>문서 상태</legend>
          <div className={c.choices}>
            {(
              [
                ["current", "현행"],
                ["superseded", "폐지 (기록으로만 남김)"],
              ] as [DocumentStatus, string][]
            ).map(([value, label]) => (
              <label key={value} className={c.choice}>
                <input
                  type="radio"
                  name={`${id}-status`}
                  checked={draft.status === value}
                  onChange={() => set({ status: value })}
                />
                {label}
              </label>
            ))}
          </div>
          <span className={c.hint}>폐지한 문서는 기본 검색에서 빠집니다.</span>
        </fieldset>
      ) : null}
    </div>
  );
}
