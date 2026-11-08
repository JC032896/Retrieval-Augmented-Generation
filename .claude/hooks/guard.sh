#!/usr/bin/env bash
# PreToolUse guard: 위험한 동작을 실행 전에 막는다 (fail-closed).
#
# - 이 스크립트에서 오류가 나면 차단한다: trap ERR → exit 2, settings.json의 "onFailure": "block".
# - 종료 코드는 0(허용)과 2(차단, stderr가 Claude에게 전달됨)만 쓴다. 1 같은 다른 코드는 차단되지 않는다.
# - 정규식 차단은 1차 방어일 뿐이다. python -c, 스크립트 파일, 따옴표 속 명령 등으로 우회할 수 있다.
#   최종 방어는 quality_gate.sh의 "보호 경로 무결성" 검사(어떻게 바꿨든 파일 내용 해시로 잡는다)와
#   CI의 해시 재계산이다.
# - 보호 경로 판단은 protected.py is-protected 한 곳에서 한다 (게이트, approve, CI와 같은 규칙).
trap 'echo "guard 내부 오류로 차단" >&2; exit 2' ERR
set -Eeuo pipefail

block() {
  echo "guard 차단: $*" >&2
  exit 2
}

command -v jq >/dev/null 2>&1 || block "jq를 찾을 수 없음"
INPUT=$(cat)
TOOL=$(jq -er '.tool_name' <<<"$INPUT" 2>/dev/null) || block "입력 JSON을 해석할 수 없음"

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT" 2>/dev/null || block "프로젝트 폴더로 이동할 수 없음: $ROOT"
ROOT=$(pwd)
# shellcheck source=../scripts/_common.sh
. .claude/scripts/_common.sh || block "_common.sh를 불러올 수 없음"
find_sys_python || block "시스템 Python 3.11+를 찾을 수 없음"

APPROVAL="직접 고치지 말고 이유를 설명해 사용자 승인을 받으세요 (사용자: unlock.sh → 수정 → approve.sh)"

# ---------------------------------------------------------------- 경로 판단

# POSIX 경로(/c/..., ~)를 Python이 이해하는 경로로 바꾼다
native_path() {
  local p="$1"
  if [[ "$p" == "~" || "$p" == "~/"* ]]; then p="$HOME${p:1}"; fi
  if [[ "$p" == /* ]] && command -v cygpath >/dev/null 2>&1; then p=$(cygpath -w "$p"); fi
  printf '%s' "$p"
}

# 0: 쓰기 금지, 1: 괜찮음. 판단 자체가 실패하면 차단한다.
is_forbidden() {
  local rc=0
  "${SYSPY[@]}" .claude/scripts/protected.py is-protected "$(native_path "$1")" >/dev/null 2>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then return 0; fi
  if [ "$rc" -eq 1 ]; then return 1; fi
  block "보호 경로를 판단할 수 없음: $1"
}

# unlock으로도 풀 수 없는 경로: 프로젝트 밖(사용자/managed 설정), 하네스 상태, lock, venv 시작 코드
always_locked() {
  local p low root
  p=$(native_path "$1")
  if command -v cygpath >/dev/null 2>&1; then p=$(cygpath -u "$p"); fi
  if [[ "$p" != /* ]]; then p="$ROOT/$p"; fi
  low=${p,,}
  root=${ROOT,,}
  if [[ "$low" != "$root"/* ]]; then return 0; fi
  low=${low#"$root"/}
  if [[ "$low" == .claude/state/* || "$low" == .claude/protected.sha.lock || "$low" == .venv/* ]]; then
    return 0
  fi
  return 1
}

unlocked() {
  local f=.claude/state/unlock expires
  if [ ! -f "$f" ]; then return 1; fi
  expires=$(tr -dc '0-9' <"$f")
  if [ -n "$expires" ] && [ "$expires" -gt "$(date +%s)" ]; then return 0; fi
  return 1
}

check_write() {
  local path="$1"
  if ! is_forbidden "$path"; then return 0; fi
  if ! always_locked "$path" && unlocked; then return 0; fi
  block "보호 경로 수정: $path. $APPROVAL"
}

is_secret() {
  local base
  base=$(basename "${1//\\//}")
  base=${base,,}
  case "$base" in
    .env.example) return 1 ;;
    .env | .env.* | *.pem | *.key | id_rsa* | id_ed25519*) return 0 ;;
  esac
  return 1
}

# ---------------------------------------------------------------- 파일 도구

case "$TOOL" in
  Edit | Write | NotebookEdit)
    path=$(jq -r '.tool_input.file_path // .tool_input.notebook_path // ""' <<<"$INPUT")
    if [ -z "$path" ]; then block "$TOOL 입력에 경로가 없음"; fi
    check_write "$path"
    exit 0
    ;;
  Read)
    path=$(jq -r '.tool_input.file_path // ""' <<<"$INPUT")
    if is_secret "$path"; then block "비밀 파일 읽기: $path"; fi
    exit 0
    ;;
  Bash | PowerShell) ;;
  *) exit 0 ;;
esac

# ---------------------------------------------------------------- 셸 명령 (1차 방어)

CMD=$(jq -r '.tool_input.command // ""' <<<"$INPUT")
LC=${CMD,,}
# 따옴표 안의 글자를 지운 버전: grep "rm" 같은 문자열 인자를 명령으로 오인하지 않기 위해
NOQ=$(sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g" <<<"$LC")
SEP='(^|[;&|(`[:space:]])'
END='([;&|)`[:space:]]|$)'

# 사용자 전용 스크립트 (bash, sh -c, source, ./ 경유 모두: 이름이 보이면 차단)
if [[ "$LC" =~ (unlock|approve|make_baseline)\.sh ]]; then
  block "사용자 전용 스크립트(${BASH_REMATCH[0]})는 Claude가 실행할 수 없음"
fi

# git add / commit (2차 방어: 커밋은 사용자만 한다)
if [[ "$NOQ" =~ ${SEP}git([[:space:]]+(-c|-C)[[:space:]]+[^[:space:]]+|[[:space:]]+--?[a-z][a-z-]*(=[^[:space:]]*)?)*[[:space:]]+(add|commit)${END} ]]; then
  block "git add/commit은 사용자만 실행함"
fi

# 파괴적 명령
destructive=(
  "${SEP}git[^;&|]*[[:space:]]push[^;&|]*([[:space:]](-f|--force|--force-with-lease)([[:space:]=]|$)|[[:space:]]\+)"
  "${SEP}git[^;&|]*[[:space:]]reset[^;&|]*[[:space:]]--hard"
  "${SEP}git[^;&|]*[[:space:]]clean([[:space:]]+-[^[:space:]]*)*[[:space:]]+(-[a-z]*f|--force)"
  "${SEP}remove-item[^;|]*[[:space:]]-r(ecurse)?"
  "${SEP}(rd|rmdir|del|erase)[[:space:]][^;&|]*/s"
)
for pattern in "${destructive[@]}"; do
  if [[ "$LC" =~ $pattern ]]; then block "파괴적 명령: ${BASH_REMATCH[0]# }"; fi
done

# rm: -r과 -f가 함께 있으면 차단 (-rf, -fr, -r -f, --recursive --force)
while IFS= read -r segment; do
  read -ra words <<<"$segment" || true
  i=0
  while [ "$i" -lt "${#words[@]}" ] && [[ "${words[$i]}" =~ ^(sudo|command|env|nohup|time)$ ]]; do
    i=$((i + 1))
  done
  if [ "$i" -ge "${#words[@]}" ] || [ "${words[$i]}" != "rm" ]; then continue; fi
  has_r=0
  has_f=0
  for word in "${words[@]:$((i + 1))}"; do
    case "$word" in
      --recursive) has_r=1 ;;
      --force) has_f=1 ;;
      --*) ;;
      -*)
        if [[ "$word" == *r* ]]; then has_r=1; fi
        if [[ "$word" == *f* ]]; then has_f=1; fi
        ;;
    esac
  done
  if [ "$has_r" -eq 1 ] && [ "$has_f" -eq 1 ]; then block "파괴적 명령: rm -rf"; fi
done < <(sed -E 's/(&&|\|\||[;&|])/\n/g' <<<"$LC")

# Claude Code 정책 레지스트리 (HKCU는 일반 사용자 권한으로 쓸 수 있어 훅을 끌 수 있다)
if [[ "$LC" =~ policies[\\/]+claudecode ]]; then
  block "Claude Code 정책 레지스트리(Policies\\ClaudeCode) 변경"
fi

# 명령에 등장하는 경로 후보 (따옴표, 옵션 접두사 제거)
mapfile -t tokens < <(sed -E "s/[\"'\`]//g; s/[;&|<>()]/ /g" <<<"$CMD" | tr -s '[:space:]' '\n' \
  | sed -E 's/^--?[a-zA-Z-]+=//' | grep -E '[/\\.~]' | grep -vE '^-' | head -30 || true)

# 비밀 파일
for token in "${tokens[@]}"; do
  if is_secret "$token"; then block "비밀 파일 접근: $token"; fi
done

# 리다이렉트 대상
rest="$CMD"
while [[ "$rest" =~ [0-9]*\>\>?[[:space:]]*([^[:space:]\;\&\|\<\>]+)(.*) ]]; do
  target="${BASH_REMATCH[1]//[\"\']/}"
  rest="${BASH_REMATCH[2]}"
  if [[ "$target" == "&"* || "$target" == /dev/* || "${target,,}" == nul ]]; then continue; fi
  check_write "$target"
done

# 쓰기 명령이 있으면 경로 후보를 모두 확인
WRITE_VERBS="${SEP}(rm|mv|cp|tee|truncate|ln|chmod|install|dd|unlink|shred|set-content|add-content|out-file|remove-item|move-item|copy-item|new-item|rename-item|clear-content|del|erase|move|copy|ren)${END}"
IN_PLACE="${SEP}(sed|perl)[[:space:]][^;&|]*-[a-z]*i"
if [[ "$NOQ" =~ $WRITE_VERBS || "$NOQ" =~ $IN_PLACE ]]; then
  for token in "${tokens[@]}"; do
    check_write "$token"
  done
fi

exit 0
