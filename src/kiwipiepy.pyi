# kiwipiepy 타입 스텁.
# kiwipiepy(0.24)는 코드에 타입 주석이 있지만 py.typed 표시 파일이 없어서 mypy가 읽지 않는다.
# 이 프로젝트가 쓰는 API만 kiwipiepy/_wrap.py의 주석과 같게 선언한다.
# mypy_path(src)에 있어서 mypy가 찾고, 실행할 때는 .pyi라서 import되지 않는다.

class Token:
    form: str
    tag: str
    start: int
    len: int

class Kiwi:
    def __init__(self) -> None: ...
    def tokenize(self, text: str) -> list[Token]: ...
