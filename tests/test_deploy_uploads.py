"""올린 문서의 배포 설정: 앱만 업로드 볼륨을 쓰고, 이미지가 앱 사용자 소유의 폴더를 만든다."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_only_the_app_mounts_the_upload_volume_at_upload_dir() -> None:
    compose: dict[str, Any] = yaml.safe_load(
        (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    app = services["app"]

    assert "uploads:/data/uploads" in app["volumes"]
    assert app["environment"]["UPLOAD_DIR"] == "/data/uploads"
    assert app["environment"]["UPLOAD_MAX_MB"] == "${UPLOAD_MAX_MB:-30}"
    others = [name for name, s in services.items() if name != "app" and "uploads" in str(s)]
    assert others == []
    assert "uploads" in compose["volumes"]


def test_image_creates_the_upload_folder_for_the_app_user() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    # 새 이름 있는 볼륨은 이미지의 폴더 소유자를 물려받는다 (앱은 root가 아니다)
    assert "mkdir -p /models /data/uploads" in dockerfile
    assert "chown rag /models /data/uploads" in dockerfile
