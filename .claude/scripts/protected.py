#!/usr/bin/env python3
"""보호 경로 manifest를 계산하고 기준(protected.sha)과 비교한다.

quality_gate.sh, approve.sh, guard.sh, CI가 모두 이 파일의 규칙을 공유한다.
표준 라이브러리만 사용하며, 반드시 시스템 Python으로 `-I -S`를 붙여 실행한다
(venv의 .pth나 sitecustomize 같은 시작 코드가 이 검사를 조작하지 못하게). _common.sh 참고.

명령:
  check            현재 상태를 .claude/state/protected.sha와 비교 (0 통과, 1 위반, 2 기준 없음)
  check --ci       기준으로 .claude/protected.sha.lock을 사용 (CI용, 해시는 직접 다시 계산)
  changed          기준 대비 바뀐 실제 파일 경로를 한 줄씩 출력 (approve.sh가 git add에 사용)
  write            현재 manifest를 기준으로 저장 (state와 lock 둘 다). 사용자 전용
  venv-check       .venv의 시작 코드(*.pth, sitecustomize, usercustomize)를 기준과 비교
  venv-write       .venv 시작 코드 기준 저장
                   (state 전용: CI는 venv를 새로 만들므로 lock에 넣지 않음)
  hooks-check      훅을 끄는 설정이 어느 단계에든 있으면 exit 1
                   (managed 파일, 정책 레지스트리, 사용자, 프로젝트, 현재 환경 변수)
  is-protected P   Claude가 경로 P를 Edit/Write하면 안 되면 exit 0, 괜찮으면 exit 1 (guard.sh용)
  list             현재 manifest 출력
종료 코드 3: 잘못된 실행 방법(-I -S 없음, Python 3.11 미만)

왜 해시 비교인가: Bash 명령을 정규식으로 막아도 sed, echo, python으로 쉽게 우회된다.
어떤 방법으로 바꿨든 결과(파일 내용)에서 잡아내는 것이 최종 방어다.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_REL = ".claude/state"
LOCK_REL = ".claude/protected.sha.lock"
STATE_SHA = ROOT / STATE_REL / "protected.sha"
VENV_SHA = ROOT / STATE_REL / "venv_startup.sha"
LOCK = ROOT / LOCK_REL

# 경로 비교는 소문자로 한다. Windows는 대소문자를 구분하지 않아 CONFTEST.py도 conftest.py로
# 동작하기 때문이다. manifest 키는 원래 경로를 유지한다.
# 아래의 모든 경로/패턴 상수는 소문자여야 하며 tests/test_protected.py가 이를 검사한다.

# (패턴, 새 파일 추가 허용 여부). 여러 규칙에 걸리면 가장 엄격한 쪽을 따른다.
RULES: list[tuple[str, bool]] = [
    ("tests/*", True),  # 기존 테스트 수정/삭제는 금지, 새 테스트 추가는 허용
    ("conftest.py", False),
    ("*/conftest.py", False),
    ("pytest.ini", False),
    ("*/pytest.ini", False),
    ("setup.cfg", False),  # pytest/mypy/coverage/flake8 설정이 모두 들어갈 수 있어 파일 전체 보호
    ("tox.ini", False),
    # 검사 도구 설정 파일 (pyproject.toml 안의 설정은 TOML_SECTIONS에서 섹션 단위로 보호)
    ("ruff.toml", False),
    (".ruff.toml", False),
    ("*/ruff.toml", False),
    ("*/.ruff.toml", False),
    ("mypy.ini", False),
    (".mypy.ini", False),
    (".coveragerc", False),
    # Python 시작 코드: 인터프리터가 뜰 때 자동 실행되어 검사 도구를 조작할 수 있다
    ("sitecustomize.py", False),
    ("*/sitecustomize.py", False),
    ("usercustomize.py", False),
    ("*/usercustomize.py", False),
    ("*.pth", False),
    # eval: 정답 데이터, baseline, 채점 코드, 임베딩 캐시
    ("eval/golden*.jsonl", False),
    ("eval/baseline.json", False),
    ("eval/*.py", False),
    # TODO(eval 구현 시): 캐시가 커지면 매번 전체를 해시하느라 게이트가 느려져 stop-gate timeout에
    # 걸릴 수 있다. "크기 + 수정 시각이 같으면 이전 해시 재사용" 방식을 검토할 것.
    ("eval/cache/*", False),
    # .gitignore: 숨긴 폴더 안의 테스트나 conftest도 pytest는 수집하므로 무시 규칙 자체를 보호한다
    (".gitignore", False),
    ("*/.gitignore", False),
    # 하네스
    (".claude/hooks/*", False),
    (".claude/scripts/*", False),
    (".claude/settings.json", False),
    # .claude/settings.local.json은 해시로 보호하지 않는다. "다시 묻지 않기"를 고르면 Claude Code가
    # 권한 규칙을 저장하는 파일이기 때문이다.
    # 대신 hooks-check가 내용(훅을 끄거나 덮어쓰는 설정)을 검사한다.
    (".claude/skills/find-skills/*", False),  # 외부 스킬
    ("skills-lock.json", False),
    (".github/workflows/*", False),
    # uv.lock은 보호하지 않는다. 대신 게이트가 `uv lock --check`로 pyproject와 일치하는지 검사한다
]

# 파일 전체가 아니라 일부 섹션만 보호하는 TOML 파일
TOML_SECTIONS: list[tuple[str, str]] = [
    ("pyproject.toml", "tool.pytest"),
    ("pyproject.toml", "tool.coverage"),  # omit 등으로 커버리지를 부풀리지 못하게
    ("pyproject.toml", "tool.ruff"),
    ("pyproject.toml", "tool.mypy"),
    ("pyproject.toml", "project.entry-points"),  # pytest11 등 플러그인 자동 등록
    ("pyproject.toml", "build-system"),  # 설치할 때 실행되는 빌드 백엔드
]

# .gitignore에 숨겨도 찾아내기 위해 파일시스템을 직접 훑는 위치
WALK_DIRS = ["tests", "eval", ".claude/hooks", ".claude/scripts", ".claude/skills", ".github"]
WALK_ANYWHERE = {
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "ruff.toml",
    ".ruff.toml",
    "mypy.ini",
    ".mypy.ini",
    ".coveragerc",
    ".gitignore",
    "sitecustomize.py",
    "usercustomize.py",
}
WALK_ANYWHERE_SUFFIXES = (".pth",)
# .gitignore로 숨겨질 수 있는 개별 파일 (해시 보호 대상)
EXPLICIT_FILES = [".claude/settings.json"]
# hooks-check가 내용을 검사하는 프로젝트 설정 파일
PROJECT_SETTINGS = [".claude/settings.json", ".claude/settings.local.json"]
LOCAL_SETTINGS_REL = ".claude/settings.local.json"

# 이름으로 건너뛰는 폴더: pytest가 위치와 상관없이 수집하지 않는 폴더만 둔다
# (점으로 시작하는 폴더, node_modules, __pycache__, dist, build: 실제 pytest로 확인함).
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
}
# 정확한 경로로 건너뛰는 폴더: 하네스 런타임 상태, 빌드 결과물, 데이터와 벡터 DB.
# tests/data/ 처럼 pytest가 수집하는 위치는 여기에 넣지 않는다.
SKIP_DIR_PATHS = {STATE_REL, "dist", "build", "data"}
SKIP_SUFFIXES = (".pyc", ".pyo")

# .venv 시작 코드 (venv-check)
VENV_REL = ".venv"
VENV_STARTUP_NAMES = {"sitecustomize.py", "usercustomize.py"}

# 훅을 끄는 설정 (hooks-check)
HOOK_DISABLING_ENV = ("CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_SAFE_MODE")

APPROVAL_HINT = (
    "보호 경로는 직접 고치지 마세요.\n"
    "정당한 변경이 필요하면 이유를 설명하고 사용자 승인을 받으세요.\n"
    "(사용자 절차: ! bash .claude/scripts/unlock.sh → 수정 → "
    "! bash .claude/scripts/approve.sh 로 확인 → --yes 로 승인)"
)


# ---------------------------------------------------------------- 경로 규칙


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _rules_for(path: str) -> list[bool]:
    low = path.lower()
    return [allow for pat, allow in RULES if fnmatch.fnmatchcase(low, pat)]


def _new_allowed(path: str) -> bool:
    rules = _rules_for(path)
    return bool(rules) and all(rules)


def _norm(p: Path) -> str:
    return os.path.normcase(os.path.abspath(p)).replace("\\", "/").lower()


def _to_rel(raw: str) -> str | None:
    """절대/상대 경로를 프로젝트 기준 상대 경로(posix)로 바꾼다. 프로젝트 밖이면 None.

    프로젝트 안인지는 대소문자를 무시하고 판단하고, 돌려주는 경로는 원래 대소문자를 유지한다
    (대소문자를 구분하는 파일시스템에서 존재 여부를 올바르게 확인하기 위해).
    """
    p = Path(raw.replace("\\", "/"))
    if not p.is_absolute():
        p = ROOT / p
    full = os.path.abspath(p).replace("\\", "/")
    root = os.path.abspath(ROOT).replace("\\", "/")
    if full.lower() == root.lower():
        return ""
    return full[len(root) + 1 :] if full.lower().startswith(root.lower() + "/") else None


# ---------------------------------------------------------------- Claude Code 설정 파일


def _config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _managed_dirs() -> list[Path]:
    if os.name == "nt":
        return [Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "ClaudeCode"]
    if sys.platform == "darwin":
        return [Path("/Library/Application Support/ClaudeCode")]
    return [Path("/etc/claude-code")]


def _outside_settings() -> list[tuple[str, Path]]:
    """프로젝트 밖의 설정 파일: managed와 사용자 (Claude가 수정하면 안 됨)."""
    sources: list[tuple[str, Path]] = []
    for d in _managed_dirs():
        sources.append(("managed", d / "managed-settings.json"))
        drop_in = d / "managed-settings.d"
        if drop_in.is_dir():
            sources += [("managed", f) for f in sorted(drop_in.glob("*.json"))]
    # CLAUDE_CONFIG_DIR가 있어도 기본 위치(~/.claude)를 함께 본다
    for cfg in dict.fromkeys([_config_dir(), Path.home() / ".claude"]):
        sources += [("user", cfg / "settings.json"), ("user", cfg / "settings.local.json")]
    return sources


def settings_sources() -> list[tuple[str, Path]]:
    """훅 설정이 들어갈 수 있는 파일 (단계, 경로). 레지스트리는 _registry_settings()."""
    return _outside_settings() + [("project", ROOT / f) for f in PROJECT_SETTINGS]


def _is_settings_file(raw: str) -> bool:
    """managed/사용자 설정 파일인가 (프로젝트 설정은 RULES와 hooks-check가 따로 다룬다)."""
    p = Path(raw.replace("\\", "/"))
    target = _norm(p if p.is_absolute() else ROOT / p)
    if any(_norm(path) == target for _, path in _outside_settings()):
        return True
    # managed 폴더 안의 파일은 새로 만드는 것도 금지
    return any(target.startswith(_norm(d) + "/") for d in _managed_dirs())


def write_forbidden(raw: str) -> bool:
    """Claude가 이 경로를 Edit/Write하면 안 되는지 판단한다 (guard.sh용)."""
    if _is_settings_file(raw):
        return True  # 사용자/managed 설정: 훅을 끄는 데 쓰일 수 있다
    rel = _to_rel(raw)
    if rel is None:
        return False
    low = rel.lower()
    if low == LOCK_REL or low.startswith(STATE_REL + "/"):
        return True  # 기준 파일, unlock 만료 시각, 재시도 카운터는 훅과 사용자 스크립트만 쓴다
    if low.startswith(VENV_REL + "/") and _is_startup_file(low):
        return True
    rules = _rules_for(rel)
    if not rules:
        return False
    exists = (ROOT / rel).exists()
    return exists or not all(rules)  # 기존 파일 수정은 금지, 새 파일은 허용 규칙일 때만 가능


# ---------------------------------------------------------------- manifest


def _skip_dir(dirpath: str, name: str) -> bool:
    return name.lower() in SKIP_DIR_NAMES or _rel(Path(dirpath) / name).lower() in SKIP_DIR_PATHS


def _walk_target(name: str) -> bool:
    low = name.lower()
    return low in WALK_ANYWHERE or low.endswith(WALK_ANYWHERE_SUFFIXES)


def _candidate_files() -> set[str]:
    files: set[str] = set()
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        files.update(f for f in out.split("\0") if f)
    except (OSError, subprocess.CalledProcessError):
        pass  # git이 없어도 아래 파일시스템 탐색으로 계속한다

    def walk(base: Path, only_targets: bool) -> None:
        if not base.is_dir():
            return
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not _skip_dir(dirpath, d)]
            for name in filenames:
                if not only_targets or _walk_target(name):
                    files.add(_rel(Path(dirpath) / name))

    for d in WALK_DIRS:
        walk(ROOT / d, only_targets=False)
    walk(ROOT, only_targets=True)
    files.update(f for f in EXPLICIT_FILES if (ROOT / f).is_file())
    # git ls-files 결과에도 같은 제외 규칙을 적용한다 (탐색과 목록이 서로 다르게 판단하지 않도록)
    return {f for f in files if not _skipped_file(f) and (ROOT / f).is_file()}


def _skipped_file(rel: str) -> bool:
    low = rel.lower()
    if low.endswith(SKIP_SUFFIXES) or any(low.startswith(p + "/") for p in SKIP_DIR_PATHS):
        return True
    return any(part in SKIP_DIR_NAMES for part in low.split("/")[:-1])


def _sha_file(path: Path) -> str:
    # 줄바꿈 차이(CRLF/LF)로 오탐이 나지 않도록 정규화해서 해시한다
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _toml_section(file: str, dotted: str) -> object:
    import tomllib  # 3.11+ 표준 라이브러리 (실행 전 버전 확인함)

    path = ROOT / file
    if not path.is_file():
        return None
    node: object = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def compute() -> dict[str, str]:
    manifest = {f: _sha_file(ROOT / f) for f in _candidate_files() if _rules_for(f)}
    for file, section in TOML_SECTIONS:
        blob = json.dumps(_toml_section(file, section), sort_keys=True, ensure_ascii=False)
        manifest[f"{file}#{section}"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return manifest


def _serialize(manifest: dict[str, str]) -> str:
    return "".join(f"{h}  {p}\n" for p, h in sorted(manifest.items()))


def _parse(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if line.strip():
            h, p = line.split("  ", 1)
            result[p] = h
    return result


def diff(
    base: dict[str, str], cur: dict[str, str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    changed = sorted(p for p in base if p in cur and base[p] != cur[p])
    deleted = sorted(p for p in base if p not in cur and "#" not in p)
    added = sorted(p for p in cur if p not in base)
    banned_new = [p for p in added if "#" in p or not _new_allowed(p)]
    allowed_new = [p for p in added if p not in banned_new]
    return changed, deleted, banned_new, allowed_new


def _git_ok(*args: str) -> bool:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True).returncode == 0
    except OSError:
        return False


def _lock_vs_head() -> str | None:
    """lock 파일이 HEAD와 다르면 경고 문구를 돌려준다."""
    if not _git_ok("ls-files", "--error-unmatch", LOCK_REL):
        return "lock 파일이 아직 커밋되지 않았습니다"
    if not _git_ok("diff", "--quiet", "HEAD", "--", LOCK_REL):
        return "lock 파일이 HEAD와 다릅니다 (커밋되지 않은 기준 변경)"
    return None


def _restore_state_from_lock() -> None:
    """state 기준이 없고 lock이 HEAD와 같으면(사용자가 커밋한 기준) lock을 state로 복사한다."""
    if STATE_SHA.is_file() or not LOCK.is_file() or _lock_vs_head() is not None:
        return
    STATE_SHA.parent.mkdir(parents=True, exist_ok=True)
    STATE_SHA.write_text(LOCK.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    # stdout은 changed 명령의 경로 목록으로 쓰이므로 알림은 stderr로 보낸다
    print("알림: 보호 기준이 없어 HEAD에 커밋된 lock 파일에서 복원했습니다", file=sys.stderr)


# ---------------------------------------------------------------- 명령


def cmd_check(ci: bool) -> int:
    if not ci:
        _restore_state_from_lock()
    source = LOCK if ci else STATE_SHA
    if not source.is_file():
        print(f"보호 기준 없음: {_rel(source)}")
        print("사용자가 ! bash .claude/scripts/approve.sh --yes 로 기준을 만들어야 합니다.")
        return 2

    base_text = source.read_text(encoding="utf-8")
    problems: list[str] = []

    if not ci:
        if not LOCK.is_file() or LOCK.read_text(encoding="utf-8") != base_text:
            problems.append(f"기준 불일치: {_rel(STATE_SHA)} 와 {LOCK_REL} 가 다릅니다")
        warn = _lock_vs_head()
        if warn:
            print(f"!!! 경고: 보호 기준 파일 변경됨 - {warn}")

    changed, deleted, banned_new, allowed_new = diff(_parse(base_text), compute())
    problems += [f"수정됨: {p}" for p in changed]
    problems += [f"삭제됨: {p}" for p in deleted]
    problems += [f"추가 금지: {p}" for p in banned_new]

    if allowed_new:
        print(f"새 테스트 파일 {len(allowed_new)}개 (approve.sh --yes 전까지는 보호되지 않음)")
    if problems:
        print(f"보호 경로 변경 {len(problems)}건:")
        for line in problems[:20]:
            print(f"  {line}")
        if len(problems) > 20:
            print(f"  ... 외 {len(problems) - 20}건")
        print(APPROVAL_HINT)
        return 1
    print("보호 경로 무결성 통과")
    return 0


def cmd_changed() -> int:
    _restore_state_from_lock()
    base = _parse(STATE_SHA.read_text(encoding="utf-8")) if STATE_SHA.is_file() else {}
    changed, deleted, banned_new, allowed_new = diff(base, compute())
    paths = {p.split("#", 1)[0] for p in changed + deleted + banned_new + allowed_new}
    for p in sorted(paths):
        print(p)
    return 0


def cmd_write() -> int:
    text = _serialize(compute())
    STATE_SHA.parent.mkdir(parents=True, exist_ok=True)
    STATE_SHA.write_text(text, encoding="utf-8", newline="\n")
    LOCK.write_text(text, encoding="utf-8", newline="\n")
    print(f"보호 기준 저장: 항목 {len(text.splitlines())}개")
    return 0


def _is_startup_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1].lower()
    return name in VENV_STARTUP_NAMES or name.endswith(".pth")


def _pth_import_lines(path: Path) -> list[str]:
    """.pth에서 실제로 실행되는 줄만 고른다.

    site.py와 같은 규칙: "import " 또는 "import\\t"로 시작하는 줄만 실행된다.

    경로만 적힌 줄은 실행되지 않으므로 비교하지 않는다.
    """
    text = path.read_bytes().decode("utf-8", errors="replace")
    return [line.rstrip() for line in text.splitlines() if line.startswith(("import ", "import\t"))]


def compute_venv() -> dict[str, str]:
    """.venv 시작 코드: sitecustomize/usercustomize는 파일 전체, .pth는 import 줄만 해시한다."""
    venv = ROOT / VENV_REL
    result: dict[str, str] = {}
    if not venv.is_dir():
        return result
    for dirpath, dirnames, filenames in os.walk(venv):
        dirnames[:] = [d for d in dirnames if d.lower() != "__pycache__"]
        for name in filenames:
            rel = _rel(Path(dirpath) / name)
            if not _is_startup_file(rel):
                continue
            if name.lower().endswith(".pth"):
                lines = _pth_import_lines(ROOT / rel)
                if lines:  # import 줄이 없는 .pth는 경로만 추가하므로 비교 대상이 아니다
                    blob = "\n".join(lines).encode("utf-8")
                    result[rel] = hashlib.sha256(blob).hexdigest()
            else:
                result[rel] = _sha_file(ROOT / rel)
    return result


def cmd_venv_check() -> int:
    current = compute_venv()
    if not VENV_SHA.is_file():
        if not STATE_SHA.is_file():
            print("venv 시작 코드 기준 없음 (보호 기준도 아직 없음)")
            return 10
        print(
            f"venv 시작 코드 기준 없음: {_rel(VENV_SHA)} - ! bash .claude/scripts/approve.sh --yes"
        )
        return 1
    base = _parse(VENV_SHA.read_text(encoding="utf-8"))
    problems = [f"수정됨: {p}" for p in sorted(base) if p in current and base[p] != current[p]]
    problems += [f"추가됨: {p}" for p in sorted(current) if p not in base]
    problems += [f"삭제됨: {p}" for p in sorted(base) if p not in current]
    if problems:
        print(
            ".venv 시작 코드(.pth의 import 줄, sitecustomize, usercustomize) "
            f"변경 {len(problems)}건:"
        )
        for line in problems[:10]:
            print(f"  {line}")
        print(
            "의존성 변경(uv sync)으로 생긴 정상 변경이면 사용자가 approve.sh --yes 로 승인합니다."
        )
        return 1
    print(f"venv 시작 코드 변경 없음 ({len(current)}개)")
    return 0


def cmd_venv_write() -> int:
    text = _serialize(compute_venv())
    VENV_SHA.parent.mkdir(parents=True, exist_ok=True)
    VENV_SHA.write_text(text, encoding="utf-8", newline="\n")
    print(f"venv 시작 코드 기준 저장: {len(text.splitlines())}개")
    return 0


def _registry_settings() -> list[tuple[str, str]]:
    """Windows 정책 레지스트리의 Settings 값 (HKLM은 관리자 전용, HKCU는 사용자가 쓸 수 있음)."""
    if os.name != "nt":
        return []
    import winreg

    found: list[tuple[str, str]] = []
    for hive, label in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Policies\ClaudeCode") as key:
                value, _ = winreg.QueryValueEx(key, "Settings")
                found.append((f"레지스트리 {label}", str(value)))
        except OSError:
            continue
    return found


def hook_problems(settings: object, *, local: bool = False) -> list[str]:
    """설정 하나(dict)에서 훅을 끄거나 우리 훅을 막는 항목을 찾는다.

    local=True(.claude/settings.local.json): 해시로 보호하지 않는 대신, 프로젝트 훅을
    덮어쓰거나 끌 수 있는 "hooks" 키가 있으면 내용과 관계없이 문제로 본다.
    """
    if not isinstance(settings, dict):
        return ["설정 형식이 객체가 아님"]
    found: list[str] = []
    if local and "hooks" in settings:
        found.append(
            '"hooks" 키 있음 (프로젝트 훅을 덮어쓰거나 끌 수 있음. 훅은 settings.json에만)'
        )
    if settings.get("disableAllHooks") is True:
        found.append("disableAllHooks: true")
    if settings.get("allowManagedHooksOnly") is True:
        found.append("allowManagedHooksOnly: true (프로젝트 훅이 막힘)")
    strict = settings.get("strictPluginOnlyCustomization")
    if strict is True or (isinstance(strict, list) and "hooks" in strict):
        found.append("strictPluginOnlyCustomization에 hooks 포함 (프로젝트 훅이 막힘)")
    env = settings.get("env")
    if isinstance(env, dict):
        for name in HOOK_DISABLING_ENV:
            if str(env.get(name, "")).strip().lower() not in ("", "0", "false"):
                found.append(f"env.{name} 설정됨 (훅을 불러오지 않음)")
    return found


def cmd_hooks_check() -> int:
    problems: list[str] = []
    documents: list[tuple[str, str, bool]] = []
    local_path = _norm(ROOT / LOCAL_SETTINGS_REL)
    for level, path in settings_sources():
        if path.is_file():
            is_local = _norm(path) == local_path
            documents.append((f"{level} {path}", path.read_text(encoding="utf-8-sig"), is_local))
    documents += [(label, text, False) for label, text in _registry_settings()]
    for label, text, is_local in documents:
        try:
            settings = json.loads(text)
        except ValueError:
            problems.append(f"{label}: JSON 파싱 실패 (내용을 확인할 수 없음)")
            continue
        problems += [f"{label}: {p}" for p in hook_problems(settings, local=is_local)]
    for name in HOOK_DISABLING_ENV:
        if os.environ.get(name, "").strip().lower() not in ("", "0", "false"):
            problems.append(f"현재 환경 변수 {name} 설정됨")
    if problems:
        print(f"훅을 끄는 설정 {len(problems)}건:")
        for line in problems[:10]:
            print(f"  {line}")
        print("이 설정이 있으면 guard/stop-gate 훅이 동작하지 않습니다. 사용자에게 보고하세요.")
        return 1
    print(f"훅을 끄는 설정 없음 (확인한 설정 {len(documents)}개)")
    return 0


def _require_isolated() -> str | None:
    # 시스템 Python은 프로젝트(3.12)와 버전이 다를 수 있다. 필요한 것은 3.11의 tomllib이다.
    if importlib.util.find_spec("tomllib") is None:
        return f"Python 3.11 이상이 필요합니다 (현재 {sys.version.split()[0]})"
    if not (sys.flags.isolated and sys.flags.no_site):
        return "시스템 Python에 -I -S를 붙여 실행해야 합니다 (.claude/scripts/_common.sh 참고)"
    return None


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔/파이프에서 한글이 깨지지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    error = _require_isolated()
    if error:
        print(f"protected.py 실행 거부: {error}", file=sys.stderr)
        return 3
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    simple = {
        "changed": cmd_changed,
        "write": cmd_write,
        "venv-check": cmd_venv_check,
        "venv-write": cmd_venv_write,
        "hooks-check": cmd_hooks_check,
    }
    if cmd == "check":
        return cmd_check(ci="--ci" in args)
    if cmd in simple:
        return simple[cmd]()
    if cmd == "is-protected" and len(args) == 1:
        return 0 if write_forbidden(args[0]) else 1
    if cmd == "list":
        sys.stdout.write(_serialize(compute()))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
