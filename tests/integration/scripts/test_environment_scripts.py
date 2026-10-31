import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]


def test_setup_selects_locked_optional_dependencies_from_a_checkout_path_with_spaces(
    tmp_path: Path,
):
    repository = tmp_path / "review checkout"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(
        REPOSITORY / "scripts" / "setup_environment.sh",
        scripts / "setup_environment.sh",
    )
    (repository / "pyproject.toml").write_text("[project]\nname = 'sample'\n")
    (repository / "uv.lock").write_text("version = 1\n")

    commands = tmp_path / "commands"
    commands.mkdir()
    command_log = tmp_path / "uv-arguments.txt"
    uv = commands / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$UV_COMMAND_LOG"\nexit 0\n')
    uv.chmod(0o755)
    environment = os.environ | {
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
        "UV_COMMAND_LOG": str(command_log),
    }

    result = subprocess.run(
        [
            "bash",
            str(scripts / "setup_environment.sh"),
            "--provider",
            "anthropic",
            "--provider",
            "google",
            "--provider",
            "openai",
            "--provider",
            "openrouter",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert command_log.read_text().splitlines() == [
        "--version",
        "sync",
        "--locked",
        "--no-default-groups",
        "--project",
        str(repository),
        "--python",
        "3.14",
        "--group",
        "provider-anthropic",
        "--group",
        "provider-google",
        "--group",
        "provider-openai",
        "--group",
        "provider-openrouter",
    ]


def test_verification_checks_the_lock_and_imports_base_modules_without_credentials(
    tmp_path: Path,
):
    repository = tmp_path / "review checkout"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(
        REPOSITORY / "scripts" / "verify_environment.sh",
        scripts / "verify_environment.sh",
    )
    (repository / "pyproject.toml").write_text("[project]\nname = 'sample'\n")
    (repository / "uv.lock").write_text("version = 1\n")

    commands = tmp_path / "commands"
    commands.mkdir()
    command_log = tmp_path / "uv-arguments.txt"
    uv = commands / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$UV_COMMAND_LOG"\nexit 0\n')
    uv.chmod(0o755)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
        }
    } | {
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
        "UV_COMMAND_LOG": str(command_log),
    }

    result = subprocess.run(
        ["bash", str(scripts / "verify_environment.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands_run = command_log.read_text().splitlines()
    assert "--check" in commands_run
    assert "--no-sync" in commands_run
    assert any("factory_simulator.api.main" in item for item in commands_run)
    assert (
        not {
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
        }
        & environment.keys()
    )


def test_verification_reports_a_stale_lock_without_syncing(tmp_path: Path):
    repository = tmp_path / "checkout"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(
        REPOSITORY / "scripts" / "verify_environment.sh",
        scripts / "verify_environment.sh",
    )
    (repository / "pyproject.toml").write_text("[project]\nname = 'sample'\n")
    (repository / "uv.lock").write_text("version = 1\n")

    commands = tmp_path / "commands"
    commands.mkdir()
    uv = commands / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "lock" ]; then\n'
        '  printf "%s\\n" "stale lock" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    uv.chmod(0o755)
    environment = os.environ | {"PATH": f"{commands}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(
        ["bash", str(scripts / "verify_environment.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "uv.lock does not match" in result.stderr
    assert "update and commit the lock intentionally" in result.stderr


def test_setup_without_uv_fails_and_asks_to_install_uv(tmp_path: Path):
    repository = tmp_path / "checkout"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(
        REPOSITORY / "scripts" / "setup_environment.sh",
        scripts / "setup_environment.sh",
    )
    environment = os.environ | {"PATH": "/bin:/usr/bin"}

    result = subprocess.run(
        ["bash", str(scripts / "setup_environment.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "install uv" in result.stderr


def test_every_shell_script_parses_with_bash():
    for script in sorted((REPOSITORY / "scripts").glob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_server_command_uses_the_checkout_database_and_preserves_explicit_url(
    tmp_path: Path,
):
    repository = tmp_path / "review checkout"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(REPOSITORY / "scripts" / "start_server.sh", scripts / "start_server.sh")

    commands = tmp_path / "commands"
    commands.mkdir()
    command_log = tmp_path / "server-arguments.txt"
    uv = commands / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$FACTORY_SIMULATOR_DATABASE_URL" "$@" > "$UV_COMMAND_LOG"\n'
        "exit 0\n"
    )
    uv.chmod(0o755)
    database_url = "duckdb:///private/reviewer.duckdb"
    environment = os.environ | {
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
        "UV_COMMAND_LOG": str(command_log),
        "FACTORY_SIMULATOR_DATABASE_URL": database_url,
    }

    result = subprocess.run(
        ["bash", str(scripts / "start_server.sh"), "--port", "8123"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert command_log.read_text().splitlines() == [
        database_url,
        "run",
        "--locked",
        "--no-sync",
        "--project",
        str(repository),
        "uvicorn",
        "factory_simulator.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--port",
        "8123",
    ]


@pytest.mark.slow
def test_smoke_uses_a_private_server_and_removes_its_temporary_database():
    records = REPOSITORY / "data" / "records"
    before = set(records.glob("smoke.*"))

    result = subprocess.run(
        ["bash", str(REPOSITORY / "scripts" / "check_server.sh")],
        cwd=Path.cwd().parent,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Smoke request passed" in result.stdout
    assert set(records.glob("smoke.*")) == before


@pytest.mark.slow
def test_clean_checkout_setup_verification_and_smoke_work_from_another_directory(
    tmp_path: Path,
):
    repository = tmp_path / "clean reviewer checkout"
    shutil.copytree(
        REPOSITORY,
        repository,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".pytest_cache",
            ".ruff_cache",
            ".hypothesis",
            "__pycache__",
            "site",
            "data",
        ),
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
        }
    } | {
        "PATH": os.environ["PATH"],
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "review environment"),
    }

    for script in ("setup_environment.sh", "verify_environment.sh", "check_server.sh"):
        result = subprocess.run(
            ["bash", str(repository / "scripts" / script)],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert result.returncode == 0, f"{script}: {result.stdout}\n{result.stderr}"
