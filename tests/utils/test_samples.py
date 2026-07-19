from tests.utils import samples as sample_utils


def test_get_sample_dirs_finds_nested_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(sample_utils, "REPO_ROOT", tmp_path)

    sample_dir = tmp_path / "tests" / "samples" / "import" / "degiro" / "france"
    sample_dir.mkdir(parents=True)
    (sample_dir / "Account.csv").write_text("dummy")
    (sample_dir / "Portfolio.csv").write_text("dummy")

    assert sample_utils.get_sample_dirs("import/degiro", extensions=[".csv"]) == [str(sample_dir)]
