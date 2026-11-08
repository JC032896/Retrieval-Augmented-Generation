"""protected.py 단위 테스트. 표준 라이브러리 unittest만 사용한다.

실행: uv run --frozen python .claude/scripts/tests/test_protected.py
실제 저장소는 건드리지 않는다: 임시 폴더에 protected.py를 복사한 작은 프로젝트를 만들어 실행한다.
protected.py는 실제와 같이 시스템(base) Python에 -I -S를 붙여 실행한다.
사용자 설정은 CLAUDE_CONFIG_DIR로 임시 폴더를 가리켜 실제 ~/.claude를 읽거나 쓰지 않는다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "protected.py"
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("protected_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConstantsAreLowercase(unittest.TestCase):
    """경로는 소문자로 바꿔 규칙과 비교하므로 모든 패턴이 소문자여야 한다."""

    def test_all_path_patterns_are_lowercase(self) -> None:
        m = _load_module()
        values: list[tuple[str, str]] = []
        values += [("RULES", pat) for pat, _ in m.RULES]
        values += [("TOML_SECTIONS", f"{f}#{s}") for f, s in m.TOML_SECTIONS]
        values += [("WALK_DIRS", d) for d in m.WALK_DIRS]
        values += [("WALK_ANYWHERE", n) for n in m.WALK_ANYWHERE]
        values += [("WALK_ANYWHERE_SUFFIXES", n) for n in m.WALK_ANYWHERE_SUFFIXES]
        values += [("EXPLICIT_FILES", n) for n in m.EXPLICIT_FILES]
        values += [("PROJECT_SETTINGS", n) for n in m.PROJECT_SETTINGS]
        values += [("LOCAL_SETTINGS_REL", m.LOCAL_SETTINGS_REL)]
        values += [("SKIP_DIR_NAMES", n) for n in m.SKIP_DIR_NAMES]
        values += [("SKIP_DIR_PATHS", p) for p in m.SKIP_DIR_PATHS]
        values += [("VENV_STARTUP_NAMES", n) for n in m.VENV_STARTUP_NAMES]
        values += [("STATE_REL", m.STATE_REL), ("LOCK_REL", m.LOCK_REL), ("VENV_REL", m.VENV_REL)]
        not_lower = [f"{name}: {v}" for name, v in values if v != v.lower()]
        self.assertEqual(not_lower, [], "소문자가 아닌 경로 패턴")
        self.assertGreater(len(values), 30)


class HookProblemsUnit(unittest.TestCase):
    def test_detects_each_disabling_setting(self) -> None:
        m = _load_module()
        self.assertTrue(m.hook_problems({"disableAllHooks": True}))
        self.assertTrue(m.hook_problems({"allowManagedHooksOnly": True}))
        self.assertTrue(m.hook_problems({"strictPluginOnlyCustomization": ["hooks"]}))
        self.assertTrue(m.hook_problems({"strictPluginOnlyCustomization": True}))
        self.assertTrue(m.hook_problems({"env": {"CLAUDE_CODE_SIMPLE": "1"}}))
        self.assertTrue(m.hook_problems({"env": {"CLAUDE_CODE_SAFE_MODE": "true"}}))

    def test_clean_settings(self) -> None:
        m = _load_module()
        self.assertEqual(m.hook_problems({"disableAllHooks": False, "env": {"X": "1"}}), [])
        self.assertEqual(m.hook_problems({"env": {"CLAUDE_CODE_SIMPLE": "0"}}), [])

    def test_hooks_key_only_flagged_in_local_settings(self) -> None:
        m = _load_module()
        hooks = {"hooks": {"PreToolUse": []}}
        self.assertTrue(m.hook_problems(hooks, local=True))
        self.assertTrue(m.hook_problems({"hooks": {}}, local=True))
        self.assertEqual(m.hook_problems(hooks, local=False), [])

    def test_local_permissions_only_is_clean(self) -> None:
        m = _load_module()
        local = {"permissions": {"allow": ["Bash(uv run pytest:*)"]}}
        self.assertEqual(m.hook_problems(local, local=True), [])


class ProjectFixture(unittest.TestCase):
    """임시 프로젝트: .claude/scripts/protected.py + tests/ + .gitignore, git 저장소."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.config_dir = Path(tempfile.mkdtemp())  # 가짜 ~/.claude
        (self.root / ".claude" / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPT, self.root / ".claude" / "scripts" / "protected.py")
        self.write("tests/test_main.py", "def test_a() -> None:\n    assert True\n")
        self.write("tests/state/test_state.py", "def test_s() -> None:\n    assert True\n")
        self.write(".gitignore", ".claude/state/\n.claude/settings.local.json\n.venv/\n")
        self.write("pyproject.toml", '[project]\nname = "x"\n\n[build-system]\nrequires = ["a"]\n')
        self.git("init", "-q")
        self.git("add", "-A")
        self.commit("init")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.config_dir, ignore_errors=True)

    def write(self, rel: str, text: str, base: Path | None = None) -> None:
        path = (base or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def commit(self, message: str) -> None:
        self.git(
            "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", message
        )

    def run_protected(
        self, *args: str, isolated: bool = True, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONUTF8": "1", "CLAUDE_CONFIG_DIR": str(self.config_dir)}
        for name in ("CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_SAFE_MODE"):
            env.pop(name, None)
        env.update(extra_env or {})
        flags = ["-I", "-S"] if isolated else []
        return subprocess.run(
            [BASE_PYTHON, *flags, str(self.root / ".claude" / "scripts" / "protected.py"), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def listed(self) -> set[str]:
        out = self.run_protected("list").stdout
        return {line.split("  ", 1)[1] for line in out.splitlines() if line.strip()}

    def assert_check_fails_with(self, text: str) -> None:
        result = self.run_protected("check")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(text, result.stdout)


class Invocation(ProjectFixture):
    def test_refuses_without_isolation_flags(self) -> None:
        result = self.run_protected("list", isolated=False)
        self.assertEqual(result.returncode, 3)
        self.assertIn("-I -S", result.stderr)


class StateNamedFolders(ProjectFixture):
    def test_tests_state_folder_is_in_manifest(self) -> None:
        self.assertIn("tests/state/test_state.py", self.listed())

    def test_tests_state_folder_change_is_detected(self) -> None:
        self.run_protected("write")
        self.write("tests/state/test_state.py", "def test_s() -> None:\n    assert False\n")
        self.assert_check_fails_with("수정됨: tests/state/test_state.py")

    def test_tests_state_folder_hidden_by_gitignore_is_still_listed(self) -> None:
        # 커밋된 파일은 git ls-files가 찾아주므로, 폴더 탐색을 검증하려면
        # "커밋되지 않았고 .gitignore로 숨겨진" 파일이어야 한다
        self.write(".gitignore", ".claude/state/\ntests/state/\n")
        self.write("tests/state/test_hidden.py", "def test_h() -> None:\n    pass\n")
        self.assertIn("tests/state/test_hidden.py", self.listed())

    def test_untracked_hidden_conftest_in_state_folder_is_banned(self) -> None:
        self.run_protected("write")
        self.write(".git/info/exclude", "tests/state/\n")  # .gitignore를 건드리지 않고 숨기기
        self.write("tests/state/conftest.py", "collect_ignore_glob = ['*']\n")
        self.assert_check_fails_with("추가 금지: tests/state/conftest.py")

    def test_claude_state_is_excluded(self) -> None:
        self.write(".claude/state/gate.log", "log")
        self.write(".claude/state/conftest.py", "")
        listed = self.listed()
        self.assertFalse([p for p in listed if p.startswith(".claude/state/")], listed)


class SkippedFolders(ProjectFixture):
    """pytest가 수집하지 않는 폴더만 건너뛴다 (실제 pytest로 확인한 동작)."""

    def test_pycache_dist_build_data_at_root_are_skipped(self) -> None:
        for rel in (
            "tests/__pycache__/test_x.py",
            "tests/__pycache__/conftest.py",
            "dist/conftest.py",
            "build/conftest.py",
            "data/conftest.py",
        ):
            self.write(rel, "")
        listed = self.listed()
        self.assertFalse([p for p in listed if "__pycache__" in p], listed)
        for prefix in ("dist/", "build/", "data/"):
            self.assertFalse([p for p in listed if p.startswith(prefix)], listed)

    def test_tests_data_folder_is_not_skipped(self) -> None:
        # pytest는 tests/data/ 안의 테스트를 수집하므로 건너뛰면 안 된다
        self.write("tests/data/test_in_data.py", "def test_d() -> None:\n    pass\n")
        self.assertIn("tests/data/test_in_data.py", self.listed())


class CaseInsensitiveRules(ProjectFixture):
    def test_uppercase_conftest_is_banned(self) -> None:
        self.run_protected("write")
        self.write("CONFTEST.py", "")
        self.assert_check_fails_with("추가 금지: CONFTEST.py")

    def test_uppercase_conftest_in_tests_is_banned(self) -> None:
        self.run_protected("write")
        self.write("tests/ConfTest.py", "")
        self.assert_check_fails_with("추가 금지: tests/ConfTest.py")


class StartupCode(ProjectFixture):
    def test_sitecustomize_usercustomize_and_pth_are_banned(self) -> None:
        self.run_protected("write")
        self.write("src/sitecustomize.py", "")
        self.write("usercustomize.py", "")
        self.write("src/evil.pth", "import os\n")
        result = self.run_protected("check")
        self.assertEqual(result.returncode, 1)
        for rel in ("src/sitecustomize.py", "usercustomize.py", "src/evil.pth"):
            self.assertIn(f"추가 금지: {rel}", result.stdout)

    def test_entry_points_section_is_protected(self) -> None:
        self.run_protected("write")
        self.write(
            "pyproject.toml",
            '[project]\nname = "x"\n\n[project.entry-points.pytest11]\nevil = "evil"\n\n'
            '[build-system]\nrequires = ["a"]\n',
        )
        self.assert_check_fails_with("pyproject.toml#project.entry-points")

    def test_build_system_section_is_protected(self) -> None:
        self.run_protected("write")
        self.write("pyproject.toml", '[project]\nname = "x"\n\n[build-system]\nrequires = ["b"]\n')
        self.assert_check_fails_with("수정됨: pyproject.toml#build-system")


class VenvStartupCode(ProjectFixture):
    def setUp(self) -> None:
        super().setUp()
        self.site = ".venv/Lib/site-packages"
        self.write(f"{self.site}/_virtualenv.pth", "import _virtualenv\n")
        self.write(f"{self.site}/mixed.pth", "/some/path\nimport mixed_hook\n")
        self.run_protected("write")
        self.run_protected("venv-write")

    def test_unchanged_venv_passes(self) -> None:
        self.assertEqual(self.run_protected("venv-check").returncode, 0)

    def test_new_path_only_pth_is_ignored(self) -> None:
        # 경로만 적힌 .pth는 코드를 실행하지 않으므로 비교 대상이 아니다
        self.write(f"{self.site}/_rag_service.pth", "C:/project/src\n")
        result = self.run_protected("venv-check")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_non_import_line_change_is_ignored(self) -> None:
        self.write(f"{self.site}/mixed.pth", "/other/path\nimport mixed_hook\n")
        result = self.run_protected("venv-check")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_import_line_change_fails(self) -> None:
        self.write(f"{self.site}/mixed.pth", "/some/path\nimport mixed_hook; import os\n")
        result = self.run_protected("venv-check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("수정됨: .venv/Lib/site-packages/mixed.pth", result.stdout)

    def test_import_line_added_to_path_only_pth_fails(self) -> None:
        self.write(f"{self.site}/_rag_service.pth", "C:/project/src\n")
        self.run_protected("venv-write")
        self.write(f"{self.site}/_rag_service.pth", "C:/project/src\nimport os\n")
        result = self.run_protected("venv-check")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("추가됨: .venv/Lib/site-packages/_rag_service.pth", result.stdout)

    def test_new_pth_in_venv_fails(self) -> None:
        self.write(f"{self.site}/evil.pth", "import os; os.system('x')\n")
        result = self.run_protected("venv-check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("추가됨: .venv/Lib/site-packages/evil.pth", result.stdout)

    def test_sitecustomize_in_venv_fails(self) -> None:
        self.write(f"{self.site}/sitecustomize.py", "")
        self.assertEqual(self.run_protected("venv-check").returncode, 1)

    def test_missing_venv_baseline_fails_when_protected_baseline_exists(self) -> None:
        (self.root / ".claude/state/venv_startup.sha").unlink()
        self.assertEqual(self.run_protected("venv-check").returncode, 1)


class SettingsLocal(ProjectFixture):
    """settings.local.json은 해시 보호 대상이 아니다 (hooks-check가 내용만 검사)."""

    def test_settings_local_json_is_not_in_manifest(self) -> None:
        self.run_protected("write")
        self.write(".claude/settings.local.json", '{"permissions": {"allow": ["Bash(ls)"]}}')
        self.assertNotIn(".claude/settings.local.json", self.listed())
        result = self.run_protected("check")
        self.assertEqual(result.returncode, 0, result.stdout)


class RestoreStateFromLock(ProjectFixture):
    def setUp(self) -> None:
        super().setUp()
        self.run_protected("write")
        self.git("add", ".claude/protected.sha.lock")
        self.commit("lock")
        (self.root / ".claude/state/protected.sha").unlink()

    def test_restores_when_lock_matches_head(self) -> None:
        result = self.run_protected("check")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("복원", result.stderr)  # stdout은 경로 목록 등으로 쓰이므로 알림은 stderr
        self.assertTrue((self.root / ".claude/state/protected.sha").is_file())

    def test_does_not_restore_when_lock_differs_from_head(self) -> None:
        lock = self.root / ".claude/protected.sha.lock"
        lock.write_text(lock.read_text(encoding="utf-8") + "0  fake\n", encoding="utf-8")
        result = self.run_protected("check")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertFalse((self.root / ".claude/state/protected.sha").exists())


class HooksCheck(ProjectFixture):
    def hooks_check(
        self, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.run_protected("hooks-check", extra_env=extra_env)

    def test_clean_passes(self) -> None:
        result = self.hooks_check()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_user_settings_disable_all_hooks(self) -> None:
        self.write("settings.json", json.dumps({"disableAllHooks": True}), base=self.config_dir)
        self.assertEqual(self.hooks_check().returncode, 1)

    def test_project_settings_disable_all_hooks(self) -> None:
        self.write(".claude/settings.json", json.dumps({"disableAllHooks": True}))
        self.assertEqual(self.hooks_check().returncode, 1)

    def test_local_settings_env_simple_mode(self) -> None:
        self.write(".claude/settings.local.json", json.dumps({"env": {"CLAUDE_CODE_SIMPLE": "1"}}))
        self.assertEqual(self.hooks_check().returncode, 1)

    def test_local_settings_hooks_key_fails(self) -> None:
        self.write(".claude/settings.local.json", json.dumps({"hooks": {"Stop": []}}))
        result = self.hooks_check()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('"hooks" 키', result.stdout)

    def test_local_settings_permissions_only_passes(self) -> None:
        local = {"permissions": {"allow": ["Bash(uv run pytest:*)"]}}
        self.write(".claude/settings.local.json", json.dumps(local))
        result = self.hooks_check()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_invalid_json_fails(self) -> None:
        self.write(".claude/settings.json", "{ not json")
        self.assertEqual(self.hooks_check().returncode, 1)

    def test_process_env_safe_mode(self) -> None:
        self.assertEqual(self.hooks_check({"CLAUDE_CODE_SAFE_MODE": "1"}).returncode, 1)


class WriteForbidden(ProjectFixture):
    def forbidden(self, path: str | Path) -> bool:
        target = path if isinstance(path, Path) else self.root / path
        return self.run_protected("is-protected", str(target)).returncode == 0

    def test_existing_test_file(self) -> None:
        self.assertTrue(self.forbidden("tests/state/test_state.py"))

    def test_new_test_file(self) -> None:
        self.assertFalse(self.forbidden("tests/state/test_brand_new.py"))

    def test_new_conftest_in_tests(self) -> None:
        self.assertTrue(self.forbidden("tests/conftest.py"))

    def test_gitignore(self) -> None:
        self.assertTrue(self.forbidden(".gitignore"))

    def test_harness_state_and_lock(self) -> None:
        self.assertTrue(self.forbidden(".claude/state/retries"))
        self.assertTrue(self.forbidden(".claude/protected.sha.lock"))

    def test_project_local_settings_is_not_write_forbidden(self) -> None:
        # 해시 보호 대상이 아니므로 guard도 막지 않는다 (게이트의 hooks-check가 내용을 검사)
        self.assertFalse(self.forbidden(".claude/settings.local.json"))

    def test_user_settings_files(self) -> None:
        self.assertTrue(self.forbidden(self.config_dir / "settings.json"))
        self.assertTrue(self.forbidden(self.config_dir / "settings.local.json"))

    def test_managed_settings_folder(self) -> None:
        m = _load_module()
        managed = m._managed_dirs()[0]
        self.assertTrue(self.forbidden(managed / "managed-settings.json"))
        self.assertTrue(self.forbidden(managed / "managed-settings.d" / "x.json"))

    def test_venv_startup_files(self) -> None:
        self.assertTrue(self.forbidden(".venv/Lib/site-packages/evil.pth"))
        self.assertTrue(self.forbidden(".venv/Lib/site-packages/sitecustomize.py"))
        self.assertFalse(self.forbidden(".venv/Lib/site-packages/pkg/module.py"))

    def test_source_file(self) -> None:
        self.assertFalse(self.forbidden("src/app.py"))

    def test_outside_project(self) -> None:
        self.assertFalse(self.forbidden(Path(tempfile.gettempdir()) / "somewhere_else.py"))

    @unittest.skipUnless(os.name == "nt", "대소문자를 구분하지 않는 Windows 파일시스템에서만")
    def test_uppercase_path_on_windows(self) -> None:
        self.assertTrue(self.forbidden("TESTS/STATE/TEST_STATE.PY"))
        self.assertTrue(self.forbidden(".GITIGNORE"))
        self.assertTrue(self.forbidden("CONFTEST.PY"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
