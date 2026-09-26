"""Directory additions preserve the requested mode at every depth."""
import hashlib
import os
import subprocess

import pytest

from lfc.cli import lfc_add
from lfc.lfcrepo import LFCRepo
from lfc.lfcerror import LFCValueError


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run([
        "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "--allow-empty", "-qm", "Initial test commit"
    ], check=True)
    repo = LFCRepo()
    repo.lfc_init()
    return repo


@pytest.mark.parametrize("mode", [1, 2, 3])
@pytest.mark.parametrize("selection", ["directory", "glob", "files"])
@pytest.mark.parametrize("interface", ["api", "cli"])
def test_add_preserves_mode_and_cached_contents(
        repository, tmp_path, mode, selection, interface):
    names = ["data/first.bin", "data/nested/second.bin",
             "data/nested/deep/third.bin"]
    contents = {}
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        contents[name] = b"\x00\xff" + name.encode("ascii")
        path.write_bytes(contents[name])

    patterns = {"directory": ["data"], "glob": ["data/*"], "files": names}
    if interface == "api":
        repository.lfc_add(*patterns[selection], mode=mode)
    else:
        lfc_add(argv=["lfc-add", "--mode", str(mode)] + patterns[selection])

    staged = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], text=True).splitlines()
    for name in names:
        path = tmp_path / name
        metadata = repository.read_lfc_file(name)
        digest = hashlib.sha256(contents[name]).hexdigest()
        cache = tmp_path / ".lfc" / "cache" / digest[:2] / digest[2:]
        assert metadata["mode"] == mode
        assert metadata["sha256"] == digest
        assert metadata["size"] == len(contents[name])
        assert path.read_bytes() == contents[name]
        assert cache.read_bytes() == contents[name]
        assert path.is_symlink() == (mode == 3)
        if mode == 3:
            assert path.resolve() == cache
            assert cache.stat().st_mode & 0o222 == 0
        assert name + ".lfc" in staged
        assert name not in staged
    assert set(repository.genr8_lfc_glob(mode=mode)) == {
        name + ".lfc" for name in names}


def test_default_directory_mode_remains_one(repository, tmp_path):
    path = tmp_path / "data" / "nested" / "file.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"default-mode")
    repository.lfc_add("data")
    assert repository.read_lfc_mode(str(path)) == 1
    assert not path.is_symlink()


def test_empty_directory_remains_empty(repository, tmp_path):
    path = tmp_path / "empty"
    path.mkdir()
    repository.lfc_add("empty", mode=2)
    assert list(path.iterdir()) == []


def test_invalid_directory_mode_is_rejected_before_changes(repository, tmp_path):
    path = tmp_path / "data" / "file.bin"
    path.parent.mkdir()
    path.write_bytes(b"unchanged")
    with pytest.raises(LFCValueError):
        repository.lfc_add("data", mode=4)
    assert path.read_bytes() == b"unchanged"
    assert not (tmp_path / "data" / "file.bin.lfc").exists()
