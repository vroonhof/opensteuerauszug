from tests.utils import samples as sample_utils


def test_get_sample_dirs_finds_nested_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(sample_utils, "REPO_ROOT", tmp_path)

    sample_dir = tmp_path / "tests" / "samples" / "import" / "degiro" / "france"
    sample_dir.mkdir(parents=True)
    (sample_dir / "Account.csv").write_text("dummy")
    (sample_dir / "Portfolio.csv").write_text("dummy")

    assert sample_utils.get_sample_dirs("import/degiro", extensions=[".csv"]) == [str(sample_dir)]


def test_get_sample_dirs_ignores_archived_and_hidden_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(sample_utils, "REPO_ROOT", tmp_path)

    base = tmp_path / "tests" / "samples" / "import" / "schwab"
    valid_dir = base / "2024"
    valid_dir.mkdir(parents=True)
    (valid_dir / "statement.pdf").write_text("dummy")

    old_dir = valid_dir / "old"
    old_dir.mkdir()
    (old_dir / "archive.json").write_text("dummy")

    hidden_dir = valid_dir / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "hidden.json").write_text("dummy")

    assert sample_utils.get_sample_dirs("import/schwab") == [str(valid_dir)]
