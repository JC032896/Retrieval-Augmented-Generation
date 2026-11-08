#!/usr/bin/env python3
"""--full 모드의 점수형 지표를 모으고 baseline과 비교한다. 표준 라이브러리만 사용한다.

명령:
  collect --pytest-log F --coverage F [--eval F] --out F
  compare --metrics F --baseline F
  suppressions [--baseline F]   억제 주석 개수 비교 (0 통과, 1 증가, 10 baseline 없음)
  baseline --metrics F [--eval-repeat F] --out F     (make_baseline.sh 전용)

eval 결과 JSON 규약 (eval/run_eval.py가 출력):
  {"n_questions": int, "recall_at_5": float, "mrr": float, "acl_leaks": int,
   "golden_sha": str, "embedding_cache": bool, "index": "flat" | ...}

규칙:
  - 커버리지: baseline - 0.5%p 이상
  - skip/deselect/xfail 개수: baseline 이하
  - 권한 유출(acl_leaks): baseline과 상관없이 반드시 0
  - Recall@5, MRR: 결정성이 확인된 경우(임베딩 캐시 + flat 검색 + 2회 연속 동일) 허용 오차 0,
    아니면 질문 1개 분량(1 / n_questions)
  - golden set이 바뀌면(golden_sha 불일치) 실패. baseline 재생성은 사용자 승인 필요
  - "type: ignore", "noqa", "pragma: no cover" 개수: 종류별로 baseline 이하 (--fast에서도 검사)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

COVERAGE_TOLERANCE = 0.5
SUMMARY_RE = re.compile(
    r"(\d+) (passed|failed|skipped|deselected|xfailed|xpassed|errors?|warnings?)"
)
REGEN_HINT = "baseline 재생성은 사용자 승인 필요: ! bash .claude/scripts/make_baseline.sh"
EXIT_SKIPPED = 10  # quality_gate.sh가 SKIPPED로 표시하는 종료 코드

ROOT = Path(__file__).resolve().parents[2]
# 검사를 끄는 주석. 개수가 baseline보다 늘면 실패한다.
SUPPRESSION_PATTERNS = {
    "type: ignore": re.compile(r"#\s*type:\s*ignore", re.IGNORECASE),
    "noqa": re.compile(r"#\s*noqa\b", re.IGNORECASE),
    "pragma: no cover": re.compile(r"#\s*pragma:\s*no\s*cover", re.IGNORECASE),
}
# 하네스 자신(.claude)은 이 패턴 문자열을 담고 있고 보호 경로이므로 세지 않는다
SUPPRESSION_SKIP_DIRS = {
    ".git",
    ".venv",
    ".claude",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}


def count_suppressions(root: Path = ROOT) -> dict[str, int]:
    counts = dict.fromkeys(SUPPRESSION_PATTERNS, 0)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SUPPRESSION_SKIP_DIRS]
        for name in filenames:
            if not name.endswith((".py", ".pyi")):
                continue
            text = (Path(dirpath) / name).read_text(encoding="utf-8", errors="replace")
            for key, pattern in SUPPRESSION_PATTERNS.items():
                counts[key] += len(pattern.findall(text))
    return counts


def _arg(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def _load(path: str | None) -> Any:
    if not path or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_pytest_summary(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in reversed(text.splitlines()):
        found = SUMMARY_RE.findall(line)
        if found and (" in " in line or "no tests ran" in line):
            for n, kind in found:
                counts[kind.rstrip("s") if kind.startswith(("error", "warning")) else kind] = int(n)
            break
    return counts


def cmd_collect(args: list[str]) -> int:
    log = Path(_arg(args, "--pytest-log") or "").read_text(encoding="utf-8", errors="replace")
    counts = parse_pytest_summary(log)
    cov = _load(_arg(args, "--coverage"))
    metrics = {
        "coverage": round(cov["totals"]["percent_covered"], 2) if cov else None,
        "skipped": counts.get("skipped", 0)
        + counts.get("deselected", 0)
        + counts.get("xfailed", 0),
        "pytest_counts": counts,
        "suppressions": count_suppressions(),
        "eval": _load(_arg(args, "--eval")),
    }
    Path(_arg(args, "--out") or "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def _eval_tolerance(base: dict[str, Any]) -> float:
    if base.get("deterministic_verified"):
        return 0.0
    n = (base.get("eval") or {}).get("n_questions") or 1
    return 1.0 / n


def compare(metrics: dict[str, Any], base: dict[str, Any] | None) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True

    def fail(msg: str) -> None:
        nonlocal ok
        ok = False
        lines.append(f"FAIL     {msg}")

    ev = metrics.get("eval")
    if ev is not None:  # 권한 유출은 baseline 없이도 항상 강제
        if ev.get("acl_leaks", 1) != 0:
            fail(f"권한 유출 {ev.get('acl_leaks')}건 (반드시 0)")
        else:
            lines.append("PASS     권한 유출 0건")
    else:
        lines.append("SKIPPED  eval 결과 없음 (eval/run_eval.py 미구현) - 권한 유출 검사 생략")

    if base is None:
        lines.append("SKIPPED  baseline 없음 - 커버리지/skip 개수/eval 점수 비교 생략")
        lines.append(f"         ({REGEN_HINT})")
        return lines, ok

    cov, bcov = metrics.get("coverage"), base.get("coverage")
    if cov is None or bcov is None:
        lines.append("SKIPPED  커버리지 비교 (값 없음)")
    elif cov < bcov - COVERAGE_TOLERANCE:
        fail(f"커버리지 {cov}% < baseline {bcov}% - {COVERAGE_TOLERANCE}%p")
    else:
        lines.append(f"PASS     커버리지 {cov}% (baseline {bcov}%)")

    sk, bsk = metrics.get("skipped", 0), base.get("skipped", 0)
    if sk > bsk:
        fail(f"skip/deselect/xfail {sk}개 > baseline {bsk}개 (테스트를 건너뛰어 통과시키지 말 것)")
    else:
        lines.append(f"PASS     skip/deselect/xfail {sk}개 (baseline {bsk}개)")

    bev = base.get("eval")
    if ev is None or bev is None:
        lines.append("SKIPPED  eval 점수 비교 (eval 또는 baseline의 eval 값 없음)")
        return lines, ok
    if ev.get("golden_sha") != bev.get("golden_sha"):
        fail(f"golden set 변경됨 - 기존 baseline으로 비교 불가. {REGEN_HINT}")
        return lines, ok
    tol = _eval_tolerance(base)
    for key, label in (("recall_at_5", "Recall@5"), ("mrr", "MRR")):
        cur, ref = ev.get(key), bev.get(key)
        if cur is None or ref is None:
            fail(f"{label} 값 없음")
        elif cur < ref - tol - 1e-12:
            fail(f"{label} {cur:.4f} < baseline {ref:.4f} - 허용 {tol:.4f}")
        else:
            lines.append(f"PASS     {label} {cur:.4f} (baseline {ref:.4f}, 허용 {tol:.4f})")
    return lines, ok


def cmd_compare(args: list[str]) -> int:
    metrics = _load(_arg(args, "--metrics"))
    if metrics is None:
        print("metrics 파일 없음")
        return 1
    lines, ok = compare(metrics, _load(_arg(args, "--baseline")))
    print("\n".join(lines))
    return 0 if ok else 1


def _stable(ev: dict[str, Any] | None) -> Any:
    return None if ev is None else {k: v for k, v in ev.items() if not k.endswith("_seconds")}


def cmd_baseline(args: list[str]) -> int:
    metrics = _load(_arg(args, "--metrics"))
    if metrics is None:
        print("metrics 파일 없음 - 먼저 quality_gate.sh --full --no-compare 실행")
        return 1
    ev, ev2 = metrics.get("eval"), _load(_arg(args, "--eval-repeat"))
    deterministic = bool(
        ev
        and ev2
        and _stable(ev) == _stable(ev2)
        and ev.get("embedding_cache") is True
        and ev.get("index") == "flat"
    )
    baseline = {
        "coverage": metrics.get("coverage"),
        "skipped": metrics.get("skipped", 0),
        "suppressions": metrics.get("suppressions") or count_suppressions(),
        "eval": ev,
        "deterministic_verified": deterministic,
    }
    Path(_arg(args, "--out") or "baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tol = "0" if deterministic else ("질문 1개 분량" if ev else "해당 없음(eval 없음)")
    print(
        f"baseline 저장: 커버리지 {baseline['coverage']}%, skip {baseline['skipped']}개, "
        f"eval 허용 오차 {tol}"
    )
    return 0


def cmd_suppressions(args: list[str]) -> int:
    current = count_suppressions()
    summary = ", ".join(f"{k} {v}" for k, v in current.items())
    base = _load(_arg(args, "--baseline"))
    if not base or not isinstance(base.get("suppressions"), dict):
        print(f"baseline 없음 - 현재 {summary}")
        return EXIT_SKIPPED
    increased = [
        f"{k} {v}개 > baseline {base['suppressions'].get(k, 0)}개"
        for k, v in current.items()
        if v > base["suppressions"].get(k, 0)
    ]
    if increased:
        print("검사를 끄는 주석이 늘었습니다: " + "; ".join(increased))
        print("주석으로 덮지 말고 원인을 고치세요.")
        print("꼭 필요하면 이유를 설명하고 사용자 승인을 받으세요.")
        print(f"({REGEN_HINT})")
        return 1
    print(f"억제 주석 증가 없음 ({summary})")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔/파이프에서 한글이 깨지지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    cmds = {
        "collect": cmd_collect,
        "compare": cmd_compare,
        "baseline": cmd_baseline,
        "suppressions": cmd_suppressions,
    }
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
