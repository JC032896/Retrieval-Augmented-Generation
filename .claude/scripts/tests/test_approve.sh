#!/usr/bin/env bash
# approve.sh / make_baseline.sh 회귀 테스트.
# 실제 저장소는 건드리지 않는다: 임시 폴더에 복제본을 만들고 그 안에서만 실행한다.
# 사용: bash .claude/scripts/tests/test_approve.sh     (종료 코드: 0 전부 통과, 1 실패 있음)
set -uo pipefail
unset CLAUDE_PROJECT_DIR
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 UV_PYTHON_DOWNLOADS=never

SRC=$(cd "$(dirname "$0")/../../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
NOREPLY="test@users.noreply.github.com"
PASS=0
FAIL=0

ok() { echo "PASS  $1"; PASS=$((PASS + 1)); }
ng() { echo "FAIL  $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | head -8 | sed 's/^/      /'; FAIL=$((FAIL + 1)); }

# 새 복제본: 원본 HEAD + 작업 중인 하네스 스크립트와 pyproject를 커밋한 상태, 보호 기준 없음
new_sandbox() {
  SB="$WORK/$1"
  git clone -q "$SRC" "$SB"
  rm -rf "$SB/.claude/scripts"
  cp -r "$SRC/.claude/scripts" "$SB/.claude/"
  cp "$SRC/pyproject.toml" "$SB/"
  (
    cd "$SB" || exit 1
    git config user.name "Test"
    git config user.email "$NOREPLY"
    git add -A
    git commit -qm "sandbox setup"
    uv sync --frozen --quiet >/dev/null 2>&1
  )
}

approve() { (cd "$SB" && bash .claude/scripts/approve.sh "$@" 2>&1); }
in_sb() { (cd "$SB" && "$@"); }
fp() { [ -f "$SB/$1" ] && sha256sum "$SB/$1" | cut -d' ' -f1 || echo "(없음)"; }
# 저장소에서 바뀔 수 있는 모든 것의 지문: HEAD, index, 작업 트리 상태, 기준 파일 2개, unlock
snapshot() {
  in_sb git rev-parse HEAD
  in_sb git write-tree
  in_sb git status --porcelain --untracked-files=all
  fp .claude/state/protected.sha
  fp .claude/protected.sha.lock
  fp .claude/state/venv_startup.sha
  fp .claude/state/unlock
}

# protected.py는 실제와 같이 시스템 Python -I -S로 실행한다
# shellcheck source=.claude/scripts/_common.sh
. "$SRC/.claude/scripts/_common.sh"
find_sys_python || { echo "시스템 Python 3.11+ 없음"; exit 1; }
protected() { (cd "$SB" && "${SYSPY[@]}" .claude/scripts/protected.py "$@" | tr -d '\r'); }

# ---------------------------------------------------------------- 1. 기준 없음
new_sandbox t1
manifest=$(protected list | cut -c67- | sed 's/#.*//' | sort -u)
changed=$(protected changed | sort -u)
if [ -n "$changed" ] && [ "$changed" = "$manifest" ]; then
  ok "기준 없음: changed가 보호 경로 전체($(printf '%s\n' "$changed" | wc -l)개)를 반환"
else
  ng "기준 없음: changed가 보호 경로 전체를 반환" "$(diff <(echo "$manifest") <(echo "$changed"))"
fi

# ---------------------------------------------------------------- 2. dry-run
mkdir -p "$SB/.claude/state"
echo "1700000000" >"$SB/.claude/state/unlock" # dry-run이 unlock을 지우지 않는지도 확인
before=$(snapshot)
out=$(approve); rc=$?
after=$(snapshot)
if [ "$rc" -eq 0 ] && [ "$before" = "$after" ] && grep -q "dry-run" <<<"$out"; then
  ok "dry-run(기준 없음): 아무것도 쓰지 않음 (HEAD, index, 작업 트리, 기준 파일, unlock 그대로)"
else
  ng "dry-run(기준 없음): 아무것도 쓰지 않음" "rc=$rc"$'\n'"$(diff <(echo "$before") <(echo "$after"))"
fi
DRYRUN_EXAMPLE="$out"

# ---------------------------------------------------------------- 3. --yes 정상 승인
out=$(approve --yes); rc=$?
if [ "$rc" -eq 0 ] && [ "$(fp .claude/state/protected.sha)" = "$(fp .claude/protected.sha.lock)" ] \
  && [ ! -f "$SB/.claude/state/unlock" ] && [ -f "$SB/.claude/state/venv_startup.sha" ] \
  && in_sb git diff --quiet HEAD -- .claude/protected.sha.lock; then
  ok "--yes: 기준 저장, lock 커밋, venv 기준 저장, unlock 해제"
else
  ng "--yes: 기준 저장, lock 커밋, unlock 해제" "rc=$rc"$'\n'"$out"
fi

# 기준이 있는 상태의 dry-run
sed -i 's/== 200/== 201/' "$SB/tests/test_main.py"
before=$(snapshot)
out=$(approve); rc=$?
after=$(snapshot)
if [ "$rc" -eq 0 ] && [ "$before" = "$after" ] && grep -q "tests/test_main.py" <<<"$out"; then
  ok "dry-run(기준 있음): 바뀐 테스트를 보여주고 아무것도 쓰지 않음"
else
  ng "dry-run(기준 있음)" "rc=$rc"$'\n'"$out"
fi
DRYRUN_EXAMPLE2="$out"
in_sb git checkout -q -- tests/test_main.py

# ---------------------------------------------------------------- 4. 하네스 변조
new_sandbox t4
approve --yes >/dev/null
echo "# 변조" >>"$SB/.claude/scripts/quality_gate.sh"
before=$(snapshot)
out=$(approve --yes); rc=$?
after=$(snapshot)
if [ "$rc" -ne 0 ] && [ "$before" = "$after" ] && grep -q "quality_gate.sh" <<<"$out"; then
  ok "하네스 파일 수정 → 중단, 아무것도 쓰지 않음"
else
  ng "하네스 파일 수정 → 중단" "rc=$rc"$'\n'"$out"
fi
in_sb git checkout -q -- .claude/scripts/quality_gate.sh

mkdir -p "$SB/.claude/hooks"
echo "exit 0" >"$SB/.claude/hooks/evil.sh"
before=$(snapshot)
out=$(approve --yes); rc=$?
after=$(snapshot)
if [ "$rc" -ne 0 ] && [ "$before" = "$after" ] && grep -q "evil.sh" <<<"$out"; then
  ok "추적 안 되는 하네스 파일 추가 → 중단 (git diff가 못 보는 경우)"
else
  ng "추적 안 되는 하네스 파일 추가 → 중단" "rc=$rc"$'\n'"$out"
fi

out=$(approve --yes --allow-harness-change); rc=$?
if [ "$rc" -eq 0 ] && in_sb git ls-files --error-unmatch .claude/hooks/evil.sh >/dev/null 2>&1; then
  ok "--allow-harness-change → 진행해서 하네스 변경까지 커밋"
else
  ng "--allow-harness-change → 진행" "rc=$rc"$'\n'"$out"
fi

# ---------------------------------------------------------------- 5. changed 실패
new_sandbox t5
approve --yes >/dev/null
echo "형식이 깨진 줄" >>"$SB/.claude/state/protected.sha" # _parse가 예외를 던지게 만든다
before=$(snapshot)
out=$(approve --yes); rc=$?
after=$(snapshot)
if [ "$rc" -ne 0 ] && [ "$before" = "$after" ] && grep -q "계산에 실패" <<<"$out"; then
  ok "changed 실패 → write 전에 중단, 아무것도 쓰지 않음"
else
  ng "changed 실패 → 중단" "rc=$rc"$'\n'"$out"
fi

# ---------------------------------------------------------------- 6. noreply 아님
new_sandbox t6
approve --yes >/dev/null
in_sb git config user.email "someone@gmail.com"
sed -i 's/== 200/== 201/' "$SB/tests/test_main.py"
before=$(snapshot)
out=$(approve --yes); rc=$?
after=$(snapshot)
if [ "$rc" -ne 0 ] && [ "$before" = "$after" ] && grep -q "noreply" <<<"$out"; then
  ok "user.email이 noreply가 아님 → 쓰기 전에 중단"
else
  ng "user.email이 noreply가 아님 → 중단" "rc=$rc"$'\n'"$out"
fi

# ---------------------------------------------------------------- 7. 커밋 실패 시 복구
in_sb git config user.email "$NOREPLY"
printf '#!/bin/sh\nexit 1\n' >"$SB/.git/hooks/pre-commit"
chmod +x "$SB/.git/hooks/pre-commit"
sha_before=$(fp .claude/state/protected.sha)
lock_before=$(fp .claude/protected.sha.lock)
out=$(approve --yes); rc=$?
if [ "$rc" -ne 0 ] && [ "$(fp .claude/state/protected.sha)" = "$sha_before" ] \
  && [ "$(fp .claude/protected.sha.lock)" = "$lock_before" ] && in_sb git diff --cached --quiet \
  && grep -q "되돌리고" <<<"$out"; then
  ok "git commit 실패 → protected.sha와 lock 복구, staging 취소"
else
  ng "git commit 실패 → 복구" "rc=$rc"$'\n'"$out"
fi
rm -f "$SB/.git/hooks/pre-commit"
in_sb git checkout -q -- tests/test_main.py

# ---------------------------------------------------------------- 8. make_baseline
out=$(cd "$SB" && bash .claude/scripts/make_baseline.sh 2>&1); rc=$?
if [ "$rc" -eq 0 ] && in_sb git ls-files --error-unmatch eval/baseline.json >/dev/null 2>&1 \
  && in_sb git diff --quiet HEAD -- eval/baseline.json; then
  ok "make_baseline → baseline 생성 후 approve --yes로 커밋"
else
  ng "make_baseline → baseline 커밋" "rc=$rc"$'\n'"$(printf '%s\n' "$out" | tail -8)"
fi

in_sb git config user.email "someone@gmail.com"
in_sb git rm -q eval/baseline.json && in_sb git commit -qm "baseline 제거" --no-verify
out=$(cd "$SB" && bash .claude/scripts/make_baseline.sh 2>&1); rc=$?
if [ "$rc" -ne 0 ] && [ ! -f "$SB/eval/baseline.json" ]; then
  ok "make_baseline에서 approve가 중단되면 baseline.json 되돌림"
else
  ng "make_baseline 중단 시 baseline.json 되돌림" "rc=$rc"$'\n'"$(printf '%s\n' "$out" | tail -5)"
fi

# ---------------------------------------------------------------- 9. settings.local.json
new_sandbox t9
approve --yes >/dev/null
# settings.local.json은 승인 대상이 아니다 (권한 규칙 저장 파일). 있어도 approve는 진행하고,
# 승인 목록에도 들어가지 않는다. 내용 검사는 게이트의 훅 설정 검사가 맡는다 (test_gate.sh).
echo '{"permissions": {"allow": ["Bash(ls)"]}}' >"$SB/.claude/settings.local.json"
out=$(approve); rc=$?
if [ "$rc" -eq 0 ] && ! grep -q "settings.local.json" <<<"$out"; then
  ok "settings.local.json이 있어도 approve dry-run 진행, 승인 목록에 없음"
else
  ng "settings.local.json이 있어도 approve dry-run 진행" "rc=$rc"$'\n'"$out"
fi
out=$(approve --yes); rc=$?
if [ "$rc" -eq 0 ] && ! in_sb git ls-files --error-unmatch .claude/settings.local.json >/dev/null 2>&1; then
  ok "settings.local.json이 있어도 approve --yes 진행, 커밋되지 않음"
else
  ng "settings.local.json이 있어도 approve --yes 진행" "rc=$rc"$'\n'"$out"
fi
rm -f "$SB/.claude/settings.local.json"

# ---------------------------------------------------------------- 10. pyproject 안내
sed -i 's/^line-length = 100/line-length = 101/' "$SB/pyproject.toml"
out=$(approve); rc=$?
if [ "$rc" -eq 0 ] && grep -q "pyproject.toml은 일부 섹션만 보호하지만 커밋은 파일 전체" <<<"$out"; then
  ok "dry-run: pyproject.toml이 대상이면 파일 전체 커밋 안내"
else
  ng "dry-run: pyproject.toml 안내" "rc=$rc"$'\n'"$out"
fi
in_sb git checkout -q -- pyproject.toml

# ---------------------------------------------------------------- 11. venv 시작 코드가 실행되지 않음
site=$(cd "$SB" && find .venv -type d -name site-packages | head -1)
marker="$WORK/sitecustomize_ran"
printf 'import pathlib\npathlib.Path(r"%s").write_text("ran")\n' "$(cygpath -w "$marker" 2>/dev/null || echo "$marker")" \
  >"$SB/$site/sitecustomize.py"
(cd "$SB" && uv run --frozen -q python -c "pass")
control=$([ -f "$marker" ] && echo yes || echo no)
rm -f "$marker"
out=$(approve); rc=$?
if [ "$control" = yes ] && [ ! -f "$marker" ] && grep -q "추가됨: $site/sitecustomize.py" <<<"$out"; then
  ok "approve는 venv의 sitecustomize를 실행하지 않음 (대조군: venv python은 실행함) + 변경 표시"
else
  ng "venv sitecustomize 미실행" "control=$control marker=$([ -f "$marker" ] && echo 생김 || echo 없음) rc=$rc"$'\n'"$out"
fi
rm -f "$SB/$site/sitecustomize.py"

# ---------------------------------------------------------------- 결과
echo
echo "결과: 통과 $PASS, 실패 $FAIL"
if [ "${SHOW_EXAMPLE:-0}" = "1" ]; then
  echo
  echo "===== dry-run 출력 예시 (기준 없음)"
  printf '%s\n' "$DRYRUN_EXAMPLE"
  echo "===== dry-run 출력 예시 (기준 있음, 테스트 1개 수정)"
  printf '%s\n' "$DRYRUN_EXAMPLE2"
fi
[ "$FAIL" -eq 0 ]
