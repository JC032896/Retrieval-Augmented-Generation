#!/usr/bin/env bash
# quality_gate.sh 회귀 테스트 (훅 설정, venv 시작 코드, 대소문자, pytest 플러그인 자동 로딩).
# 실제 저장소는 건드리지 않는다: 임시 폴더에 복제본을 만들고 그 안에서만 실행한다.
# 사용: bash .claude/scripts/tests/test_gate.sh     (종료 코드: 0 전부 통과, 1 실패 있음)
set -uo pipefail
unset CLAUDE_PROJECT_DIR CLAUDE_CODE_SIMPLE CLAUDE_CODE_SAFE_MODE
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 UV_PYTHON_DOWNLOADS=never

SRC=$(cd "$(dirname "$0")/../../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export CLAUDE_CONFIG_DIR="$WORK/claude-config" # 실제 ~/.claude 대신 빈 설정 폴더
mkdir -p "$CLAUDE_CONFIG_DIR"
PASS=0
FAIL=0
ok() { echo "PASS  $1"; PASS=$((PASS + 1)); }
ng() { echo "FAIL  $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | head -10 | sed 's/^/      /'; FAIL=$((FAIL + 1)); }

SB="$WORK/sb"
git clone -q "$SRC" "$SB"
rm -rf "$SB/.claude/scripts"
cp -r "$SRC/.claude/scripts" "$SB/.claude/"
cp "$SRC/pyproject.toml" "$SB/"
(
  cd "$SB" || exit 1
  git config user.name "Test"
  git config user.email "test@users.noreply.github.com"
  git add -A
  git commit -qm "sandbox setup"
  uv sync --frozen --quiet >/dev/null 2>&1
  bash .claude/scripts/approve.sh --yes >/dev/null 2>&1
) || { echo "샌드박스 준비 실패"; exit 1; }
SITE=$(cd "$SB" && find .venv -type d -name site-packages | head -1)

gate() { (cd "$SB" && bash .claude/scripts/quality_gate.sh --fast 2>&1); }
reset() { (cd "$SB" && git checkout -q -- . && git clean -qfd -e .claude/state -e .venv); }

# 0. 기준 상태는 통과
out=$(gate); rc=$?
[ "$rc" -eq 0 ] && ok "기준 상태: --fast 통과" || ng "기준 상태: --fast 통과" "$out"

# 1. 훅을 끄는 설정
echo '{"disableAllHooks": true}' >"$CLAUDE_CONFIG_DIR/settings.json"
out=$(gate); rc=$?
if [ "$rc" -eq 1 ] && grep -q "FAIL     훅 설정" <<<"$out" && grep -q "disableAllHooks" <<<"$out"; then
  ok "사용자 설정의 disableAllHooks → 게이트 실패"
else
  ng "사용자 설정의 disableAllHooks → 게이트 실패" "$out"
fi
rm -f "$CLAUDE_CONFIG_DIR/settings.json"

for content in '{"env": {"CLAUDE_CODE_SIMPLE": "1"}}' '{"hooks": {"Stop": []}}'; do
  echo "$content" >"$SB/.claude/settings.local.json"
  out=$(gate); rc=$?
  if [ "$rc" -eq 1 ] && grep -q "FAIL     훅 설정" <<<"$out" && grep -q "PASS     보호 경로 무결성" <<<"$out"; then
    ok "settings.local.json $content → 훅 설정 실패 (무결성은 해시 대상이 아니라 통과)"
  else
    ng "settings.local.json $content → 훅 설정 실패" "$out"
  fi
done
echo '{"permissions": {"allow": ["Bash(ls)"]}}' >"$SB/.claude/settings.local.json"
out=$(gate); rc=$?
[ "$rc" -eq 0 ] && ok "settings.local.json(권한 규칙만) → 게이트 통과" \
  || ng "settings.local.json(권한 규칙만) → 게이트 통과" "$out"
rm -f "$SB/.claude/settings.local.json"

# 2. venv 시작 코드
echo "import os" >"$SB/$SITE/zz_evil.pth"
out=$(gate); rc=$?
if [ "$rc" -eq 1 ] && grep -q "FAIL     venv 시작 코드" <<<"$out"; then
  ok "venv에 .pth 추가 → 게이트 실패"
else
  ng "venv에 .pth 추가 → 게이트 실패" "$out"
fi
rm -f "$SB/$SITE/zz_evil.pth"
echo "/some/extra/path" >"$SB/$SITE/zz_paths.pth"
out=$(gate); rc=$?
[ "$rc" -eq 0 ] && ok "venv에 경로만 있는 .pth 추가 → 통과 (import 줄만 비교)" \
  || ng "venv에 경로만 있는 .pth 추가 → 통과" "$out"
rm -f "$SB/$SITE/zz_paths.pth"

# 3. 대소문자
echo "" >"$SB/CONFTEST.py"
out=$(gate); rc=$?
if [ "$rc" -eq 1 ] && grep -q "추가 금지: CONFTEST.py" <<<"$out"; then
  ok "CONFTEST.py 추가 → 무결성 실패"
else
  ng "CONFTEST.py 추가 → 무결성 실패" "$out"
fi
reset

# 4. pytest 플러그인 자동 로딩 차단
# entry point(pytest11)로 등록되는 플러그인: 모든 테스트 결과를 "통과"로 바꾼다.
# .pth가 아니므로 venv 시작 코드 검사로는 잡히지 않는다 → 자동 로딩 차단이 방어선이다.
cat >"$SB/$SITE/evilplug.py" <<'EOF'
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    outcome.get_result().outcome = "passed"
EOF
mkdir -p "$SB/$SITE/evilplug-1.0.dist-info"
printf 'Metadata-Version: 2.1\nName: evilplug\nVersion: 1.0\n' >"$SB/$SITE/evilplug-1.0.dist-info/METADATA"
printf '[pytest11]\nevil = evilplug\n' >"$SB/$SITE/evilplug-1.0.dist-info/entry_points.txt"
sed -i 's|1.0 / (k + rank)|1.0 / (k + rank + 1)|' "$SB/src/rag_service/retrieval/fusion.py" # 테스트를 깨뜨림
control=$(cd "$SB" && env -u PYTEST_DISABLE_PLUGIN_AUTOLOAD uv run --frozen -q pytest -q -p no:cacheprovider \
  tests/retrieval/test_fusion.py 2>&1 | tail -1)
out=$(gate); rc=$?
if grep -q "passed" <<<"$control" && ! grep -q "failed" <<<"$control" \
  && [ "$rc" -eq 1 ] && grep -q "FAIL     관련 테스트" <<<"$out"; then
  ok "악성 pytest 플러그인이 있어도 게이트는 테스트 실패를 잡음 (대조군: 자동 로딩 시 '$control')"
else
  ng "pytest 플러그인 자동 로딩 차단" "대조군: $control"$'\n'"$out"
fi
rm -rf "$SB/$SITE/evilplug.py" "$SB/$SITE/evilplug-1.0.dist-info"
reset

# 5. 소요 시간
s=$(date +%s%N)
gate >/dev/null
ms=$(( ($(date +%s%N) - s) / 1000000 ))
echo "INFO  --fast 소요 시간(변경 없음): ${ms}ms"
echo "x = 1" >>"$SB/src/rag_service/retrieval/fusion.py"
s=$(date +%s%N)
gate >/dev/null
ms=$(( ($(date +%s%N) - s) / 1000000 ))
echo "INFO  --fast 소요 시간(src 1개 변경): ${ms}ms"
reset

echo
echo "결과: 통과 $PASS, 실패 $FAIL"
[ "$FAIL" -eq 0 ]
