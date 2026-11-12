"""관리 화면이 쓰는 API 명세 사본 (web/admin/src/api/openapi.json).

화면의 타입(schema.d.ts)은 이 사본에서 만든다. API를 바꾸면 scripts/export_openapi.py로 다시
쓰고 화면에서 npm run gen:api를 돌린다. 사본이 실제 API와 다르면 테스트가 알려 준다.
"""

import json
from pathlib import Path

SNAPSHOT = Path("web") / "admin" / "src" / "api" / "openapi.json"


def render() -> str:
    from rag_service.main import app  # 앱을 import하면 라우터가 모두 등록된다

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
