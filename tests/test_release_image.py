"""미리 만든 이미지 배포 규칙.

compose가 받는 기본 이미지는 release가 올리는 이미지와 같은 이름이고, 태그는 코드 버전이다.
release는 버전 태그에서만 돌고, 품질 게이트를 통과한 뒤에만 올리며,
쓰기 권한은 올리는 작업에만 준다.
"""

import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _yaml(path: Path) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1에서 on은 True로 읽힌다
    triggers: dict[str, Any] = workflow[True]
    return triggers


def test_compose_pulls_the_released_image_of_this_code_version() -> None:
    compose = _yaml(ROOT / "deploy" / "compose.yaml")
    release = _yaml(WORKFLOWS / "release.yml")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]

    app_image = compose["x-app-image"]
    assert app_image["image"] == f"${{APP_IMAGE:-{release['env']['IMAGE']}:{version}}}"
    # 없을 때만 받고, 받을 수 없으면 Dockerfile로 만든다
    assert app_image["pull_policy"] == "missing"
    assert app_image["build"]["dockerfile"] == "Dockerfile"


def test_release_runs_on_version_tags_after_the_quality_gate() -> None:
    release = _yaml(WORKFLOWS / "release.yml")
    quality = _yaml(WORKFLOWS / "quality.yml")

    assert _triggers(release) == {"push": {"tags": ["v*.*.*"]}}
    assert "workflow_call" in _triggers(quality)
    jobs = release["jobs"]
    assert jobs["quality"]["uses"] == "./.github/workflows/quality.yml"
    assert jobs["image"]["needs"] == "quality"


def test_only_the_image_job_can_write_packages() -> None:
    release = _yaml(WORKFLOWS / "release.yml")

    assert release["permissions"] == {"contents": "read"}
    assert release["jobs"]["image"]["permissions"] == {"contents": "read", "packages": "write"}
    assert "permissions" not in release["jobs"]["quality"]


def test_release_checks_the_tag_and_the_image_before_pushing() -> None:
    steps = _yaml(WORKFLOWS / "release.yml")["jobs"]["image"]["steps"]
    names = [step.get("name", step.get("uses", "")) for step in steps]
    pushes = [i for i, step in enumerate(steps) if step.get("with", {}).get("push") is True]

    assert names.index("태그와 pyproject.toml 버전 일치 확인") < names.index("이미지 실행 점검")
    assert pushes == [len(steps) - 1]
    assert names.index("이미지 실행 점검") < pushes[0]
    smoke = steps[names.index("이미지 실행 점검")]["run"]
    assert 'test "$(id -u)" = 10001' in smoke
