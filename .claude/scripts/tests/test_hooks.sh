#!/usr/bin/env bash
# 훅 회귀 테스트: guard(차단/허용/fail-closed), mark-dirty, stop-gate(2-2-2-0, fail-open).
# 실제 저장소는 건드리지 않는다: 임시 폴더에 복제본을 만들고 그 안에서만 실행한다.
# 사용: bash .claude/scripts/tests/test_hooks.sh     (종료 코드: 0 전부 통과, 1 실패 있음)
set -uo pipefail
unset CLAUDE_CODE_SIMPLE CLAUDE_CODE_SAFE_MODE
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 UV_PYTHON_DOWNLOADS=never

SRC=$(cd "$(dirname "$0")/../../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export CLAUDE_CONFIG_DIR="$WORK/claude-config"
mkdir -p "$CLAUDE_CONFIG_DIR"
PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); [ "${VERBOSE:-0}" = 1 ] && echo "PASS  $1"; return 0; }
ng() { echo "FAIL  $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | head -6 | sed 's/^/      /'; FAIL=$((FAIL + 1)); }
win() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

# ---------------------------------------------------------------- 복제본 준비
SB="$WORK/sb"
git clone -q "$SRC" "$SB"
rm -rf "$SB/.claude/scripts" "$SB/.claude/hooks"
cp -r "$SRC/.claude/scripts" "$SRC/.claude/hooks" "$SB/.claude/"
(
  cd "$SB" || exit 1
  git config user.name "Test"
  git config user.email "test@users.noreply.github.com"
  git add -A
  git commit -qm "sandbox setup"
  uv sync --frozen --quiet >/dev/null 2>&1
  bash .claude/scripts/approve.sh --yes --allow-harness-change >/dev/null 2>&1
) || { echo "샌드박스 준비 실패"; exit 1; }
GUARD="$SB/.claude/hooks/guard.sh"
ROOT_ENV=$(win "$SB") # Claude Code가 넘겨줄 수 있는 Windows 형식

bash_json() { jq -cn --arg t "${2:-Bash}" --arg c "$1" '{tool_name:$t, tool_input:{command:$c}}'; }
file_json() { jq -cn --arg t "$1" --arg p "$2" '{tool_name:$t, tool_input:{file_path:$p}}'; }

# expect(allow|block) 설명 JSON [CLAUDE_PROJECT_DIR]
g() {
  local expect="$1" desc="$2" json="$3" root="${4:-$ROOT_ENV}" out rc=0
  out=$(printf '%s' "$json" | CLAUDE_PROJECT_DIR="$root" bash "$GUARD" 2>&1) || rc=$?
  if { [ "$expect" = allow ] && [ "$rc" -eq 0 ]; } || { [ "$expect" = block ] && [ "$rc" -eq 2 ]; }; then
    ok "guard $expect: $desc"
  else
    ng "guard $expect: $desc" "rc=$rc $out"
  fi
}

# ---------------------------------------------------------------- guard: 허용
g allow "ls"                         "$(bash_json 'ls -la')"
g allow "pytest"                     "$(bash_json 'uv run pytest -q tests/test_main.py')"
g allow "grep 안의 rm 문자열"          "$(bash_json 'grep -rn "rm -rf" tests/')"
g allow "git status/diff/log"        "$(bash_json 'git status && git diff && git log --oneline -3')"
g allow "보호되지 않은 곳으로 리다이렉트" "$(bash_json 'uv run pytest -q > /tmp/out.txt 2>&1')"
g allow "rm 단일 파일(-r/-f 아님)"     "$(bash_json 'rm src/old.py')"
g allow "git clean -n (미리 보기)"     "$(bash_json 'git clean -n')"
g allow "PowerShell 조회"            "$(bash_json 'Get-ChildItem -Recurse src' PowerShell)"
g allow "src 수정"                   "$(file_json Edit "$(win "$SB/src/rag_service/main.py")")"
g allow "새 테스트 파일 작성"          "$(file_json Write "$(win "$SB/tests/test_new.py")")"
g allow "settings.local.json 수정"    "$(file_json Edit "$(win "$SB/.claude/settings.local.json")")"
g allow "README 읽기"                 "$(file_json Read "$(win "$SB/README.MD")")"
g allow ".env.example 읽기"           "$(file_json Read "$(win "$SB/.env.example")")"
g allow "POSIX 형식 CLAUDE_PROJECT_DIR" "$(bash_json 'ls')" "$SB"

# ---------------------------------------------------------------- guard: 파괴적 명령
g block "rm -rf"                     "$(bash_json 'rm -rf data')"
g block "rm -fr"                     "$(bash_json 'rm -fr build')"
g block "rm -r -f"                   "$(bash_json 'cd src && rm -r -f x')"
g block "rm --recursive --force"     "$(bash_json 'rm --recursive --force x')"
g block "git push --force"           "$(bash_json 'git push --force origin main')"
g block "git push -f"                "$(bash_json 'git push -f')"
g block "git push +ref"              "$(bash_json 'git push origin +main')"
g block "git reset --hard"           "$(bash_json 'git reset --hard HEAD~1')"
g block "git clean -fd"              "$(bash_json 'git clean -fd')"
g block "git clean -xdf"             "$(bash_json 'git clean -xdf')"
g block "Remove-Item -Recurse"       "$(bash_json 'Remove-Item -Recurse -Force .\data' PowerShell)"
g block "rmdir /s"                   "$(bash_json 'rmdir /s /q data' PowerShell)"

# ---------------------------------------------------------------- guard: 사용자 전용 스크립트, git add/commit
g block "approve.sh 직접"             "$(bash_json 'bash .claude/scripts/approve.sh --yes')"
g block "unlock.sh via sh -c"         "$(bash_json 'sh -c "bash .claude/scripts/unlock.sh"')"
g block "make_baseline.sh via ./"     "$(bash_json './.claude/scripts/make_baseline.sh')"
g block "approve.sh via source"       "$(bash_json 'source .claude/scripts/approve.sh')"
g block "approve.sh via PowerShell"   "$(bash_json 'bash .\.claude\scripts\approve.sh --yes' PowerShell)"
g block "git commit"                  "$(bash_json 'git commit -m "x"')"
g block "git add"                     "$(bash_json 'git add -A')"
g block "git -c ... commit"           "$(bash_json 'git -c user.name=x commit -m y')"

# ---------------------------------------------------------------- guard: 정책 레지스트리
g block "reg add Policies\\ClaudeCode" "$(bash_json 'reg add HKCU\Software\Policies\ClaudeCode /v Settings /t REG_SZ /d "{}"' PowerShell)"
g block "Set-ItemProperty"            "$(bash_json "Set-ItemProperty -Path 'HKCU:\\Software\\Policies\\ClaudeCode' -Name Settings -Value '{}'" PowerShell)"
g block "New-ItemProperty"            "$(bash_json "New-ItemProperty -Path HKCU:/Software/Policies/ClaudeCode -Name Settings" PowerShell)"

# ---------------------------------------------------------------- guard: 보호 경로와 비밀 파일
g block "기존 테스트 Edit"            "$(file_json Edit "$(win "$SB/tests/test_main.py")")"
g block "conftest.py 새로 Write"      "$(file_json Write "$(win "$SB/tests/conftest.py")")"
g block "훅 파일 Write"               "$(file_json Write "$(win "$SB/.claude/hooks/new.sh")")"
g block "settings.json Edit"          "$(file_json Edit "$(win "$SB/.claude/settings.json")")"
g block ".gitignore Edit"             "$(file_json Edit "$(win "$SB/.gitignore")")"
g block "state 파일 Write"            "$(file_json Write "$(win "$SB/.claude/state/retries")")"
g block "사용자 설정 Write"           "$(file_json Write "$(win "$CLAUDE_CONFIG_DIR/settings.json")")"
g block ".env Read"                   "$(file_json Read "$(win "$SB/.env")")"
g block "cat .env"                    "$(bash_json 'cat .env')"
g block "Get-Content .env.local"      "$(bash_json 'Get-Content .env.local' PowerShell)"
g block "sed -i 기존 테스트"          "$(bash_json "sed -i 's/200/201/' tests/test_main.py")"
g block "리다이렉트로 기존 테스트"     "$(bash_json 'echo x > tests/test_main.py')"
g block ">> 하네스 스크립트"          "$(bash_json 'echo x >> .claude/scripts/quality_gate.sh')"
g block "cp로 baseline 덮어쓰기"      "$(bash_json 'cp /tmp/b.json eval/baseline.json')"
g block "Set-Content 기존 테스트"     "$(bash_json 'Set-Content -Path tests\test_main.py -Value x' PowerShell)"
g block "rm state 파일"               "$(bash_json 'rm .claude/state/dirty')"
g block "~ 사용자 설정 리다이렉트"     "$(bash_json 'echo {} > ~/.claude/settings.json')"

# ---------------------------------------------------------------- guard: unlock
date_future=$(($(date +%s) + 600))
echo "$date_future" >"$SB/.claude/state/unlock"
g allow "unlock 중 기존 테스트 Edit"   "$(file_json Edit "$(win "$SB/tests/test_main.py")")"
g allow "unlock 중 sed -i 기존 테스트" "$(bash_json "sed -i 's/200/201/' tests/test_main.py")"
g block "unlock 중에도 state 파일"     "$(file_json Write "$(win "$SB/.claude/state/retries")")"
g block "unlock 중에도 lock 파일"      "$(file_json Edit "$(win "$SB/.claude/protected.sha.lock")")"
g block "unlock 중에도 사용자 설정"     "$(file_json Edit "$(win "$CLAUDE_CONFIG_DIR/settings.json")")"
g block "unlock 중에도 approve.sh 실행" "$(bash_json 'bash .claude/scripts/approve.sh --yes')"
echo "$(($(date +%s) - 1))" >"$SB/.claude/state/unlock"
g block "만료된 unlock"               "$(file_json Edit "$(win "$SB/tests/test_main.py")")"
echo "garbage" >"$SB/.claude/state/unlock"
g block "깨진 unlock 파일"            "$(file_json Edit "$(win "$SB/tests/test_main.py")")"
rm -f "$SB/.claude/state/unlock"

# ---------------------------------------------------------------- guard: fail-closed
path_without() { # 해당 실행 파일이 있는 PATH 항목을 뺀 PATH
  local exe="$1" d out=""
  while IFS= read -r d; do
    if [ -n "$d" ] && { [ -e "$d/$exe" ] || [ -e "$d/$exe.exe" ]; }; then continue; fi
    out="${out:+$out:}$d"
  done < <(tr ':' '\n' <<<"$PATH")
  printf '%s' "$out"
}
rc=0
out=$(printf '%s' "$(bash_json 'ls')" | PATH="$(path_without jq)" CLAUDE_PROJECT_DIR="$ROOT_ENV" bash "$GUARD" 2>&1) || rc=$?
[ "$rc" -eq 2 ] && ok "guard: jq 없음 → 차단" || ng "guard: jq 없음 → 차단" "rc=$rc $out"
rc=0
out=$(printf '%s' "$(bash_json 'ls')" | PATH="$(PATH="$(path_without python)" path_without py)" CLAUDE_PROJECT_DIR="$ROOT_ENV" bash "$GUARD" 2>&1) || rc=$?
[ "$rc" -eq 2 ] && ok "guard: 시스템 Python 없음 → 차단" || ng "guard: Python 없음 → 차단" "rc=$rc $out"
rc=0
out=$(printf 'not json' | CLAUDE_PROJECT_DIR="$ROOT_ENV" bash "$GUARD" 2>&1) || rc=$?
[ "$rc" -eq 2 ] && ok "guard: 잘못된 JSON → 차단" || ng "guard: 잘못된 JSON → 차단" "rc=$rc $out"
rc=0
out=$(printf '%s' "$(bash_json 'ls')" | CLAUDE_PROJECT_DIR="$WORK/없는폴더" bash "$GUARD" 2>&1) || rc=$?
[ "$rc" -eq 2 ] && ok "guard: 프로젝트 폴더 없음 → 차단" || ng "guard: 프로젝트 폴더 없음 → 차단" "rc=$rc $out"

# settings.json과 같은 방식(셸 형식 명령 문자열)으로 실행
rc=0
out=$(printf '%s' "$(bash_json 'rm -rf data')" | CLAUDE_PROJECT_DIR="$ROOT_ENV" \
  bash -c 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/guard.sh"' 2>&1) || rc=$?
[ "$rc" -eq 2 ] && ok "guard: settings.json 명령 문자열 그대로 실행 → 차단 동작" \
  || ng "guard: settings.json 명령 문자열" "rc=$rc $out"

# 소요 시간
s=$(date +%s%N)
for _ in 1 2 3 4 5; do
  printf '%s' "$(bash_json 'sed -i s/a/b/ src/rag_service/main.py tests/test_new.py')" \
    | CLAUDE_PROJECT_DIR="$ROOT_ENV" bash "$GUARD" >/dev/null 2>&1 || true
done
GUARD_MS=$(( ($(date +%s%N) - s) / 5000000 ))

# ---------------------------------------------------------------- mark-dirty
rm -f "$SB/.claude/state/dirty"
rc=0
out=$(printf '%s' "$(file_json Edit "$(win "$SB/src/x.py")")" | CLAUDE_PROJECT_DIR="$ROOT_ENV" \
  bash "$SB/.claude/hooks/mark-dirty.sh" 2>&1) || rc=$?
if [ "$rc" -eq 0 ] && [ -z "$out" ] && [ -f "$SB/.claude/state/dirty" ]; then
  ok "mark-dirty: dirty 생성, 출력 없음, exit 0"
else
  ng "mark-dirty" "rc=$rc out=$out"
fi
rc=0
out=$(printf 'not json' | PATH="$(path_without jq)" CLAUDE_PROJECT_DIR="$ROOT_ENV" \
  bash "$SB/.claude/hooks/mark-dirty.sh" 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && ok "mark-dirty: jq 없음/잘못된 입력에도 exit 0" \
  || ng "mark-dirty: 오류에도 exit 0" "rc=$rc out=$out"

# ---------------------------------------------------------------- stop-gate
STOP="$SB/.claude/hooks/stop-gate.sh"
stop() { printf '{"hook_event_name":"Stop","stop_hook_active":false}' | CLAUDE_PROJECT_DIR="$ROOT_ENV" bash "$STOP"; }

rm -f "$SB/.claude/state/dirty" "$SB/.claude/state/retries"
s=$(date +%s%N); rc=0; out=$(stop 2>&1) || rc=$?; ms=$(( ($(date +%s%N) - s) / 1000000 ))
[ "$rc" -eq 0 ] && [ "$ms" -lt 1500 ] && ok "stop-gate: dirty 없음 → 즉시 exit 0 (${ms}ms)" \
  || ng "stop-gate: dirty 없음 → 즉시 exit 0" "rc=$rc ${ms}ms $out"

: >"$SB/.claude/state/dirty"
rc=0; out=$(stop 2>&1) || rc=$?
if [ "$rc" -eq 0 ] && [ ! -f "$SB/.claude/state/dirty" ]; then
  ok "stop-gate: 게이트 통과 → exit 0, dirty 삭제"
else
  ng "stop-gate: 게이트 통과" "rc=$rc $out"
fi

# 테스트를 깨뜨린 상태에서 4번 연속
sed -i 's|1.0 / (k + rank)|1.0 / (k + rank + 1)|' "$SB/src/rag_service/retrieval/fusion.py"
: >"$SB/.claude/state/dirty"
codes=""
max_lines=0
for n in 1 2 3 4; do
  rc=0
  err=$(stop 2>&1 >"$WORK/stop_stdout_$n") || rc=$?
  codes="$codes$rc,"
  lines=$(printf '%s\n' "$err" | wc -l)
  [ "$lines" -gt "$max_lines" ] && max_lines=$lines
  [ "$n" -eq 1 ] && FIRST_ERR="$err"
  [ "$n" -eq 4 ] && LAST_ERR="$err"
done
if [ "$codes" = "2,2,2,0," ]; then ok "stop-gate: 실패 4연속 → 2,2,2,0"; else ng "stop-gate: 2,2,2,0" "실제: $codes"; fi
[ "$max_lines" -le 40 ] && ok "stop-gate: stderr ${max_lines}줄 (40줄 이내)" || ng "stop-gate: stderr 40줄 이내" "${max_lines}줄"
grep -q "품질 게이트 실패 (1/3)" <<<"$FIRST_ERR" && grep -q "FAIL     관련 테스트" <<<"$FIRST_ERR" \
  && ok "stop-gate: 1회차 메시지에 횟수와 실패한 검사 포함" || ng "stop-gate: 1회차 메시지" "$FIRST_ERR"
grep -q "사용자에게 실패 내용을 반드시 보고할 것" <<<"$LAST_ERR" \
  && grep -q systemMessage "$WORK/stop_stdout_4" && [ ! -f "$SB/.claude/state/retries" ] \
  && [ -f "$SB/.claude/state/dirty" ] \
  && ok "stop-gate: 4회차 보고 지시 + systemMessage, 카운터 삭제, dirty 유지" \
  || ng "stop-gate: 4회차" "$LAST_ERR"
(cd "$SB" && git checkout -q -- src/rag_service/retrieval/fusion.py)

# 게이트 자체 오류(종료 코드 3) → fail-open
: >"$SB/.claude/state/dirty"
rc=0
out=$(printf '{}' | PATH="$(path_without uv | tr ':' '\n' | grep -v -i python | paste -sd:)" \
  CLAUDE_PROJECT_DIR="$ROOT_ENV" bash "$STOP" 2>&1) || rc=$?
[ "$rc" -eq 0 ] && grep -q "자체 오류" <<<"$out" && ok "stop-gate: 게이트 자체 오류 → exit 0 (fail-open)" \
  || ng "stop-gate: 게이트 자체 오류 → fail-open" "rc=$rc $out"
rm -f "$SB/.claude/state/dirty" "$SB/.claude/state/retries"

# --fast 소요 시간
s=$(date +%s%N)
(cd "$SB" && CLAUDE_PROJECT_DIR="$ROOT_ENV" bash .claude/scripts/quality_gate.sh --fast >/dev/null 2>&1) || true
FAST_MS=$(( ($(date +%s%N) - s) / 1000000 ))

echo "INFO  guard 1회 평균: ${GUARD_MS}ms (경로 2개 확인하는 sed -i 명령, timeout 10초)"
echo "INFO  quality_gate --fast: ${FAST_MS}ms (stop-gate timeout 180초)"
echo "결과: 통과 $PASS, 실패 $FAIL"
[ "$FAIL" -eq 0 ]
