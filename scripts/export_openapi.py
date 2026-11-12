"""관리 화면이 쓰는 API 명세를 web/admin/src/api/openapi.json으로 내보낸다.

API를 바꾸면 다시 돌리고, 화면의 타입을 새로 만든다 (cd web/admin && npm run gen:api).
tests/test_openapi_snapshot.py가 사본과 실제 API가 어긋나면 알려 준다.

    uv run python scripts/export_openapi.py
"""

from pathlib import Path

from rag_service.openapi_snapshot import SNAPSHOT, render

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target = ROOT / SNAPSHOT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render().encode("utf-8"))
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
