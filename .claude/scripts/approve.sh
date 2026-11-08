#!/usr/bin/env bash
# [사용자 전용] 보호 경로의 현재 상태를 새 기준으로 승인한다.
#
# 사용:
#   ! bash .claude/scripts/approve.sh          dry-run: 바뀐 보호 경로와 diff --stat만 출력 (아무것도 쓰지 않음)
#   ! bash .claude/scripts/approve.sh --yes    기준 갱신 + 바뀐 보호 파일과 lock만 골라서 커밋
# 옵션:
#   --allow-harness-change  하네스 파일(.claude/scripts, .claude/hooks, .claude/settings.json)이
#                           HEAD와 달라도 진행 (하네스 자체를 승인할 때만)
#   --no-commit             --yes와 함께: 커밋 없이 기준만 갱신
#
# 안전장치:
#   1) 하네스 파일이 HEAD와 다르면(추적되지 않은 새 파일 포함) 중단. HEAD가 없으면 경고만 출력
#   2) 변경 목록(changed) 계산이 실패하면 아무것도 쓰기 전에 중단
#   3) 커밋할 때 git user.email이 noreply 주소가 아니면 아무것도 쓰기 전에 중단
#   4) 기준 저장, git add, git commit 중 하나라도 실패하면 protected.sha, lock, venv 기준을
#      이전 내용으로 되돌리고 staging을 취소
#   protected.py는 venv가 아닌 시스템 Python에 -I -S를 붙여 실행한다 (_common.sh)
# Claude가 이 스크립트를 실행하는 것은 guard.sh가 차단한다.
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 # Windows에서 한글 출력이 cp949로 깨지지 않게
set -euo pipefail

YES=0
ALLOW_HARNESS=0
NO_COMMIT=0
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    --allow-harness-change) ALLOW_HARNESS=1 ;;
    --no-commit) NO_COMMIT=1 ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT"
die() { echo "중단: $*" >&2; exit 1; }

# shellcheck source=.claude/scripts/_common.sh
. .claude/scripts/_common.sh
find_sys_python || die "시스템 Python 3.11 이상을 찾을 수 없습니다."
PY=("${SYSPY[@]}")
P=.claude/scripts/protected.py
STATE_SHA=.claude/state/protected.sha
VENV_SHA=.claude/state/venv_startup.sha
LOCK=.claude/protected.sha.lock
# .claude/settings.local.json은 승인 대상이 아니다 (게이트의 훅 설정 검사가 내용만 확인한다)
HARNESS=(.claude/scripts .claude/hooks .claude/settings.json)

# ---------- 1) 하네스 파일이 HEAD와 같은지 ----------
if git rev-parse --verify -q HEAD >/dev/null; then
  # git diff는 추적되지 않은 새 파일을 보지 못하므로 ls-files --others로 함께 확인한다
  harness_diff=$( {
    git diff --name-only HEAD -- "${HARNESS[@]}"
    git ls-files --others --exclude-standard -- "${HARNESS[@]}"
  } | sort -u)
  if [ -n "$harness_diff" ]; then
    if [ "$ALLOW_HARNESS" -eq 1 ]; then
      echo "경고: 하네스 파일이 HEAD와 다르지만 --allow-harness-change로 진행합니다:"
    else
      echo "중단: 하네스 파일이 HEAD와 다릅니다. 검토 후 의도한 변경이면 --allow-harness-change를 붙이세요:" >&2
    fi
    printf '%s\n' "$harness_diff" | head -20 | sed 's/^/  /' >&2
    [ "$ALLOW_HARNESS" -eq 1 ] || exit 1
  fi
else
  echo "경고: HEAD가 없습니다(최초 커밋 전). 하네스 파일 확인을 건너뜁니다."
fi

# ---------- 2) 바뀐 보호 경로 계산 (실패하면 아무것도 쓰지 않고 중단) ----------
if ! changed_out=$("${PY[@]}" "$P" changed); then
  die "보호 경로 변경 목록 계산에 실패했습니다. 아무것도 쓰지 않았습니다."
fi
paths=()
while IFS= read -r line; do
  [ -n "$line" ] && paths+=("$line")
done < <(printf '%s\n' "$changed_out" | tr -d '\r') # Windows Python의 CRLF 제거

if [ -f "$STATE_SHA" ]; then
  echo "== 기준 대비 바뀐 보호 경로: ${#paths[@]}개"
else
  echo "== 기준 없음(최초 승인): 보호 경로 전체 ${#paths[@]}개가 대상입니다"
fi
for p in "${paths[@]}"; do
  if git ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then echo "  $p"; else echo "  $p  (추적 안 됨)"; fi
done
if [ "${#paths[@]}" -gt 0 ] && git rev-parse --verify -q HEAD >/dev/null; then
  stat=$(git diff --stat HEAD -- "${paths[@]}")
  [ -n "$stat" ] && { echo "== diff --stat (HEAD 대비)"; printf '%s\n' "$stat"; }
fi
for p in "${paths[@]}"; do
  if [ "$p" = "pyproject.toml" ]; then
    echo "알림: pyproject.toml은 일부 섹션만 보호하지만 커밋은 파일 전체가 됩니다 (의존성 등 다른 변경 포함)."
  fi
done
echo "== .venv 시작 코드 (.pth의 import 줄, sitecustomize, usercustomize)"
"${PY[@]}" "$P" venv-check | sed 's/^/  /' || true

if [ "$YES" -ne 1 ]; then
  echo "dry-run: 아무것도 쓰지 않았습니다. 승인하려면 --yes를 붙이세요."
  exit 0
fi

# ---------- 3) 커밋 작성자 확인 (쓰기 전에) ----------
if [ "$NO_COMMIT" -eq 0 ]; then
  email=$(git config user.email || true)
  shopt -s nocasematch
  if [[ "$email" != *noreply* ]]; then
    die "git user.email($email)이 noreply 주소가 아닙니다. (예: ID+이름@users.noreply.github.com) 아무것도 쓰지 않았습니다."
  fi
  shopt -u nocasematch
fi

# ---------- 4) 기준 저장 + 커밋 (실패하면 되돌림) ----------
backup=$(mktemp -d)
for f in "$STATE_SHA" "$LOCK" "$VENV_SHA"; do
  [ -f "$f" ] && cp "$f" "$backup/$(basename "$f")"
done
targets=("$LOCK" "${paths[@]}")

restore() {
  local f b
  for f in "$STATE_SHA" "$LOCK" "$VENV_SHA"; do
    b="$backup/$(basename "$f")"
    if [ -f "$b" ]; then cp "$b" "$f"; else rm -f "$f"; fi
  done
  git reset -q -- "${targets[@]}" >/dev/null 2>&1 || true
  rm -rf "$backup"
  echo "protected.sha, lock, venv 기준을 이전 내용으로 되돌리고 staging을 취소했습니다." >&2
}

"${PY[@]}" "$P" write || { restore; die "기준 저장에 실패했습니다."; }
"${PY[@]}" "$P" venv-write || { restore; die "venv 시작 코드 기준 저장에 실패했습니다."; }

if [ "$NO_COMMIT" -eq 1 ]; then
  rm -f .claude/state/unlock
  rm -rf "$backup"
  echo "커밋 생략(--no-commit). lock 파일을 커밋하기 전까지 게이트가 경고를 출력합니다."
  exit 0
fi

git add -A -- "${targets[@]}" || { restore; die "git add에 실패했습니다."; }
if git diff --cached --quiet -- "${targets[@]}"; then
  echo "커밋할 변경 없음"
else
  git commit -q -m "보호 경로 승인 (${#paths[@]}개 경로)" -- "${targets[@]}" \
    || { restore; die "git commit에 실패했습니다."; }
  echo "커밋 완료: $(git log -1 --format='%h %s')"
fi
rm -f .claude/state/unlock
rm -rf "$backup"
echo "승인 완료. unlock 해제됨"
