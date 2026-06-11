import os

from epub_dual_language.cli import load_environment


def test_load_environment_reads_dotenv_from_calling_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    tmp_path.joinpath(".env").write_text("OPENROUTER_API_KEY=from-dotenv\n", encoding="utf-8")

    load_environment()

    assert tmp_path.joinpath(".env").exists()
    assert os.environ["OPENROUTER_API_KEY"] == "from-dotenv"


def test_load_environment_keeps_existing_environment_value(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-shell")
    tmp_path.joinpath(".env").write_text("OPENROUTER_API_KEY=from-dotenv\n", encoding="utf-8")

    load_environment()

    assert os.environ["OPENROUTER_API_KEY"] == "from-shell"
