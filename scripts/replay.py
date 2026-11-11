"""감사 기록 재현. 사용법: uv run python scripts/replay.py <audit_id> [--question ...] [--call]

내용은 rag_service.audit.replay에 있다 (테스트와 커버리지 대상).
"""

import sys

from rag_service.audit.replay import main

if __name__ == "__main__":
    sys.exit(main())
