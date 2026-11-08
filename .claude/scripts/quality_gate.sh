#!/usr/bin/env bash
# 품질 게이트.
#   --fast : 1~2분 안에 끝나는 검사. 보호 경로 무결성 → 훅 설정 → venv 시작 코드 → lock 일치
#            → format 체크 → 타입체크 → lint → 억제 주석 증가 → 관련 테스트
#   --full : fast 검사 + 전체 테스트/커버리지 + eval + baseline 비교
#   --full --no-compare : 지표만 모으고 baseline 비교는 생략 (make_baseline.sh 전용)
# 종료 코드: 0 통과, 1 실패, 3 게이트 자체 오류 (stop-gate는 3을 받으면 통과시킨다: fail-open)
# 출력: 검사별 결과 + 실패한 검사의 핵심 에러 30줄 이내. 전체 로그는 .claude/state/gate.log
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8  # Windows에서 한글 출력이 cp949로 깨지지 않게
# pytest 플러그인 자동 로딩 금지: 설치된 패키지의 entry point가 테스트 결과를 조작하지 못하게.
# 필요한 플러그인은 -p로 명시한다 (--full의 pytest_cov).
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
set -uo pipefail

MODE="${1:-}"
NO_COMPARE=0
[ "${2:-}" = "--no-compare" ] && NO_COMPARE=1
case "$MODE" in --fast|--full) ;; *) echo "사용법: $0 --fast | --full [--no-compare]" >&2; exit 3 ;; esac

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT" || exit 3
STATE=".claude/state"
mkdir -p "$STATE" || exit 3
LOG="$STATE/gate.log"
{ echo "# quality_gate $MODE $(date '+%F %T')"; } >"$LOG" || exit 3

if command -v uv >/dev/null 2>&1; then UV=(uv)
elif python -m uv --version >/dev/null 2>&1; then UV=(python -m uv)
else echo "게이트 오류: uv를 찾을 수 없음" >&2; exit 3; fi
RUN=("${UV[@]}" run --frozen --quiet)
# protected.py와 metrics.py는 venv가 아닌 시스템 Python에 -I -S를 붙여 실행한다 (_common.sh)
# shellcheck source=.claude/scripts/_common.sh
. .claude/scripts/_common.sh || exit 3
find_sys_python || { echo "게이트 오류: 시스템 Python 3.11+를 찾을 수 없음" >&2; exit 3; }
PROTECTED=("${SYSPY[@]}" .claude/scripts/protected.py)
METRICS=("${SYSPY[@]}" .claude/scripts/metrics.py)
TEST_TIMEOUT="${GATE_TEST_TIMEOUT:-90}"

RESULTS=()
WARNINGS=""
EXCERPT=""
FAILS=0

# check 이름 제한시간(초) 명령... : 통과 코드 0 (pytest의 5 = 수집된 테스트 없음도 통과)
# 종료 코드 10은 SKIPPED로 표시한다 (출력 첫 줄이 사유)
check() {
  local name="$1" limit="$2"; shift 2
  local out rc
  echo "===== $name: $*" >>"$LOG"
  out=$(timeout "$limit" "$@" 2>&1); rc=$?
  printf '%s\n' "$out" >>"$LOG"
  WARNINGS+=$(printf '%s\n' "$out" | grep -a '^!!!' || true)
  if [ "$rc" -eq 0 ] || { [ "$rc" -eq 5 ] && [[ "$name" == *테스트* ]]; }; then
    RESULTS+=("PASS     $name")
    return 0
  fi
  if [ "$rc" -eq 10 ]; then
    RESULTS+=("SKIPPED  $name ($(printf '%s\n' "$out" | head -1))")
    return 0
  fi
  [ "$rc" -eq 124 ] && out="시간 초과 (${limit}초)"$'\n'"$out"
  RESULTS+=("FAIL     $name")
  FAILS=$((FAILS + 1))
  local body key
  body=$(printf '%s\n' "$out" | grep -av '^!!!' | grep -av '^[[:space:]]*$')
  # 핵심 줄(pytest의 FAILED/ERROR/E, mypy·ruff의 error)을 먼저 보여주고, 없으면 앞부분을 보여준다
  key=$(printf '%s\n' "$body" | grep -aE '^(FAILED|ERROR|E  |.*error:|.*Error)' | head -12)
  [ -z "$key" ] && key=$(printf '%s\n' "$body" | head -12)
  [ "$name" = "baseline 비교" ] && return 1 # 비교 결과는 요약에 이미 들여쓰기로 나온다
  EXCERPT+="--- $name ---"$'\n'"$key"$'\n'
  return 1
}

skip() {
  RESULTS+=("SKIPPED  $1 ($2)")
  echo "===== $1: SKIPPED ($2)" >>"$LOG"
}

# 변경된 파일과 관련된 테스트 목록. "ALL"이면 전체 실행
related_tests() {
  local changed f mod base
  if ! git rev-parse --verify -q HEAD >/dev/null 2>&1; then echo ALL; return; fi
  changed=$( { git diff --name-only HEAD; git ls-files --others --exclude-standard; } 2>/dev/null | sort -u)
  [ -z "$changed" ] && return
  while IFS= read -r f; do
    case "$f" in
      tests/fixtures/*|pyproject.toml|uv.lock|*conftest.py) echo ALL; return ;;
      tests/*test_*.py) [ -f "$f" ] && echo "$f" ;;
      src/rag_service/*.py)
        mod="${f#src/rag_service/}"; base="$(basename "$mod" .py)"
        for t in "tests/$(dirname "$mod")/test_${base}.py" "tests/test_${base}.py"; do
          t="${t//\/.\//\/}"; [ -f "$t" ] && echo "$t"
        done ;;
    esac
  done <<<"$changed" | sort -u
}

# ---------- 1. 보호 경로 무결성 (항상 첫 번째) ----------
check "보호 경로 무결성" 60 "${PROTECTED[@]}" check

# ---------- 2. 훅을 끄는 설정 / venv 시작 코드 ----------
check "훅 설정" 30 "${PROTECTED[@]}" hooks-check
check "venv 시작 코드" 60 "${PROTECTED[@]}" venv-check

# ---------- 3. lock 파일 일치 (uv.lock은 보호 경로가 아닌 대신 pyproject와 일치해야 한다) ----------
check "lock 일치" 60 "${UV[@]}" lock --check --quiet

# ---------- 4~6. 정적 검사 ----------
check "format 체크" 60 "${RUN[@]}" ruff format --check .
check "타입체크" 120 "${RUN[@]}" mypy
check "lint" 60 "${RUN[@]}" ruff check .

# ---------- 7. 억제 주석 증가 (type: ignore / noqa / pragma: no cover) ----------
base_arg=()
[ -f eval/baseline.json ] && base_arg=(--baseline eval/baseline.json)
check "억제 주석" 60 "${METRICS[@]}" suppressions "${base_arg[@]}"

# ---------- 8. 테스트 ----------
if [ "$MODE" = "--fast" ]; then
  tests=$(related_tests)
  if [ -z "$tests" ]; then
    skip "관련 테스트" "변경된 코드와 연결된 테스트 없음"
  elif printf '%s\n' "$tests" | grep -qx ALL; then
    check "관련 테스트(전체)" "$TEST_TIMEOUT" "${RUN[@]}" pytest -q -p no:cacheprovider
  else
    # shellcheck disable=SC2086
    check "관련 테스트" "$TEST_TIMEOUT" "${RUN[@]}" pytest -q -p no:cacheprovider $tests
  fi
else
  PYLOG="$STATE/pytest_full.log"
  rm -f "$STATE/coverage.json" "$STATE/eval.json"
  check "전체 테스트+커버리지" 600 bash -c '"$@" >"'"$PYLOG"'" 2>&1; rc=$?; tail -40 "'"$PYLOG"'"; exit $rc' _ \
    "${RUN[@]}" pytest -q -rs -p no:cacheprovider -p pytest_cov --cov --cov-report=json:"$STATE/coverage.json"

  if [ -f eval/run_eval.py ]; then
    check "eval" 900 "${RUN[@]}" python eval/run_eval.py --json "$STATE/eval.json"
  else
    skip "eval" "eval/run_eval.py 없음"
  fi

  eval_arg=()
  [ -f "$STATE/eval.json" ] && eval_arg=(--eval "$STATE/eval.json")
  "${METRICS[@]}" collect --pytest-log "$PYLOG" \
    --coverage "$STATE/coverage.json" "${eval_arg[@]}" --out "$STATE/metrics.json" >>"$LOG" 2>&1 \
    || { echo "게이트 오류: 지표 수집 실패 (gate.log 참고)" >&2; exit 3; }

  if [ "$NO_COMPARE" -eq 1 ]; then
    skip "baseline 비교" "--no-compare"
  else
    base_arg=()
    [ -f eval/baseline.json ] && base_arg=(--baseline eval/baseline.json)
    check "baseline 비교" 60 "${METRICS[@]}" compare \
      --metrics "$STATE/metrics.json" "${base_arg[@]}"
    cmp_out=$(sed -n '/===== baseline 비교/,$p' "$LOG" | grep -aE '^(PASS|FAIL|SKIPPED|  )' || true)
  fi
fi

# ---------- 출력 (30줄 이내) ----------
# 요약을 gate.log 끝에도 붙여서, stop-gate가 "gate.log 마지막 30줄"을 보여주면 이 요약이 나오게 한다.
SUMMARY=$(
  [ -n "$WARNINGS" ] && printf '%s\n' "$WARNINGS"
  echo "품질 게이트 $MODE: $([ "$FAILS" -eq 0 ] && echo 통과 || echo "실패 ${FAILS}건")"
  printf '  %s\n' "${RESULTS[@]}"
  [ -n "${cmp_out:-}" ] && printf '%s\n' "$cmp_out" | sed 's/^/    /'
  [ -n "$EXCERPT" ] && printf '%s' "$EXCERPT"
)
SUMMARY=$(printf '%s\n' "$SUMMARY" | head -29)$'\n'"(전체 로그: $LOG)"
printf '\n===== 요약\n%s\n' "$SUMMARY" >>"$LOG"
printf '%s\n' "$SUMMARY"

[ "$FAILS" -eq 0 ] && exit 0 || exit 1
