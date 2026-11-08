"""공용 fixture 모음. conftest.py 대신 테스트 파일에서 명시적으로 import해서 쓴다."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from rag_service.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
