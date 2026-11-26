"""資料版本：更新時自動快照、升級資料庫，以及還原。"""

import json
import sqlite3

import pytest

from harness import cli
from harness import scaffold
from harness.web import accounts as accounts_lib
from harness.web import datastore


@pytest.fixture
def root(tmp_path):
    """一個剛建立、還沒啟動過網頁版的助手專案。"""
    path = tmp_path / "assistant"
    scaffold.create_assistant(path, sandbox=False)
    return path


def _usernames(root):
    store = accounts_lib.AccountStore.for_project(root)
    return [user.username for user in store.list_users()]


def _add_user(root, name):
    accounts_lib.AccountStore.for_project(root).create_user(
        name, name, "member"
    )


class TestPrepare:
    def test_fresh_project_has_nothing_to_back_up(self, root):
        report = datastore.prepare(root, version="v1")
        assert report.snapshot is None
        # 新建的資料庫已經是最新的樣子，不必執行升級步驟。
        assert report.applied == ()
        assert datastore.schema_version(root) == datastore.SCHEMA_VERSION
        assert datastore.list_snapshots(root) == []

    def test_same_version_does_nothing(self, root):
        datastore.prepare(root, version="v1")
        report = datastore.prepare(root, version="v1")
        assert report.snapshot is None
        assert report.applied == ()
        assert report.messages() == []

    def test_existing_data_without_version_is_snapshotted_first(self, root):
        # 這個功能之前就有的資料庫：沒有版本號也沒有版本紀錄。
        _add_user(root, "alice")
        report = datastore.prepare(root, version="v1")
        assert report.snapshot is not None
        assert report.snapshot.schema_version == 0
        assert [step.version for step in report.applied] == [1]
        saved = report.snapshot.path / "db" / "harness.db"
        db = sqlite3.connect(saved)
        names = [row[0] for row in db.execute("SELECT username FROM users")]
        db.close()
        assert names == ["alice"]
        files = json.loads((report.snapshot.path / "manifest.json").read_text())
        assert "harness.yaml" in files["files"]
        assert "agents/main.md" in files["files"]

    def test_new_app_version_takes_a_snapshot(self, root):
        datastore.prepare(root, version="v1")
        report = datastore.prepare(root, version="v2")
        assert report.snapshot is not None
        assert "v1 → v2" in report.snapshot.reason
        assert report.applied == ()
        assert report.previous_app == "v1"
        assert any("已自動備份" in line for line in report.messages())

    def test_keeps_only_recent_automatic_snapshots(self, root):
        datastore.prepare(root, version="v0")
        manual = datastore.create_snapshot(root)
        for number in range(1, 6):
            datastore.prepare(root, version=f"v{number}", keep=2)
        snapshots = datastore.list_snapshots(root)
        automatic = [item for item in snapshots if item.automatic]
        assert len(automatic) == 2
        assert manual.name in [item.name for item in snapshots]

    def test_runs_new_migrations_in_order(self, root, monkeypatch):
        datastore.prepare(root, version="v1")
        _add_user(root, "alice")

        def add_column(db):
            datastore.add_column(db, "users", "nickname", "TEXT")
            db.execute("UPDATE users SET nickname = username || '!'")

        steps = (
            *datastore.MIGRATIONS,
            datastore.Migration(2, "加上暱稱", add_column),
        )
        monkeypatch.setattr(datastore, "MIGRATIONS", steps)
        monkeypatch.setattr(datastore, "SCHEMA_VERSION", 2)
        report = datastore.prepare(root, version="v1")
        # 程式版本沒變，但有新的升級步驟：一樣先快照。
        assert report.snapshot is not None
        assert [step.version for step in report.applied] == [2]
        assert datastore.schema_version(root) == 2
        db = sqlite3.connect(root / accounts_lib.DB_FILE)
        assert db.execute("SELECT nickname FROM users").fetchone() == (
            "alice!",
        )
        db.close()

    def test_fresh_database_skips_migrations(self, root, monkeypatch):
        def must_not_run(db):
            raise AssertionError("新建的資料庫不該執行升級步驟")

        steps = (
            *datastore.MIGRATIONS,
            datastore.Migration(2, "x", must_not_run),
        )
        monkeypatch.setattr(datastore, "MIGRATIONS", steps)
        monkeypatch.setattr(datastore, "SCHEMA_VERSION", 2)
        datastore.prepare(root, version="v1")
        assert datastore.schema_version(root) == 2

    def test_add_column_is_idempotent(self, root):
        datastore.prepare(root, version="v1")
        db = sqlite3.connect(root / accounts_lib.DB_FILE)
        datastore.add_column(db, "users", "nickname", "TEXT")
        datastore.add_column(db, "users", "nickname", "TEXT")
        columns = [row[1] for row in db.execute("PRAGMA table_info(users)")]
        db.close()
        assert columns.count("nickname") == 1

    def test_failed_migration_leaves_data_untouched(self, root, monkeypatch):
        datastore.prepare(root, version="v1")

        def broken(db):
            db.execute("ALTER TABLE users ADD COLUMN extra TEXT")
            raise RuntimeError("壞掉了")

        steps = (*datastore.MIGRATIONS, datastore.Migration(2, "壞的", broken))
        monkeypatch.setattr(datastore, "MIGRATIONS", steps)
        monkeypatch.setattr(datastore, "SCHEMA_VERSION", 2)
        with pytest.raises(RuntimeError, match="壞掉了"):
            datastore.prepare(root, version="v2")
        assert datastore.schema_version(root) == 1
        db = sqlite3.connect(root / accounts_lib.DB_FILE)
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        db.close()
        assert "extra" not in columns

    def test_refuses_data_from_a_newer_version(self, root):
        datastore.prepare(root, version="v1")
        db = sqlite3.connect(root / accounts_lib.DB_FILE)
        db.execute(f"PRAGMA user_version = {datastore.SCHEMA_VERSION + 1}")
        db.close()
        with pytest.raises(datastore.DataError, match="較新的程式"):
            datastore.prepare(root, version="v0")


class TestRestore:
    def test_restores_database_and_config(self, root):
        datastore.prepare(root, version="v1")
        _add_user(root, "alice")
        snapshot = datastore.create_snapshot(root)
        _add_user(root, "bob")
        (root / "harness.yaml").write_text("broken: [", "utf-8")
        before = datastore.restore(root, snapshot.name)
        assert _usernames(root) == ["alice"]
        assert "broken" not in (root / "harness.yaml").read_text("utf-8")
        # 還原前的狀態也留了一份，可以再換回來。
        datastore.restore(root, before.name)
        assert _usernames(root) == ["alice", "bob"]

    def test_unknown_snapshot(self, root):
        with pytest.raises(datastore.DataError, match="找不到快照"):
            datastore.restore(root, "20260101-000000-auto")
        with pytest.raises(datastore.DataError, match="名稱不對"):
            datastore.restore(root, "../../etc")

    def test_secrets_are_kept_private(self, root):
        datastore.prepare(root, version="v1")
        (root / ".harness" / "secrets").mkdir()
        (root / ".harness" / "secrets" / "web-password").write_text("x")
        snapshot = datastore.create_snapshot(root)
        assert (snapshot.path / "files/.harness/secrets/web-password").exists()
        mode = (root / datastore.BACKUP_DIR).stat().st_mode & 0o777
        assert mode == 0o700

    def test_snapshot_skips_conversations(self, root):
        datastore.prepare(root, version="v1")
        sessions = root / ".harness" / "users" / "u1" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "a.jsonl").write_text("{}\n")
        (sessions / "a.meta.json").write_text("{}")
        (root / ".harness" / "users" / "u1" / "memory.json").write_text("{}")
        snapshot = datastore.create_snapshot(root)
        manifest = json.loads((snapshot.path / "manifest.json").read_text())
        assert ".harness/users/u1/memory.json" in manifest["files"]
        assert not any("sessions" in name for name in manifest["files"])


class TestCommand:
    def test_status_backup_restore(self, root, capsys):
        assert cli.main(["data", "-p", str(root)]) == 0
        assert "還沒有任何快照" in capsys.readouterr().out
        _add_user(root, "alice")
        assert cli.main(["data", "backup", "-p", str(root)]) == 0
        assert "已備份" in capsys.readouterr().out
        name = datastore.list_snapshots(root)[0].name
        _add_user(root, "bob")
        assert cli.main(["data", "restore", name, "-p", str(root)]) == 0
        assert "已還原" in capsys.readouterr().out
        assert _usernames(root) == ["alice"]
        assert cli.main(["data", "list", "-p", str(root)]) == 0
        assert name in capsys.readouterr().out

    def test_missing_project(self, tmp_path, capsys):
        assert cli.main(["data", "-p", str(tmp_path)]) == 1
        assert "harness.yaml" in capsys.readouterr().err

    def test_restore_unknown(self, root, capsys):
        assert (
            cli.main(
                ["data", "restore", "20260101-000000-auto", "-p", str(root)]
            )
            == 1
        )
        assert "找不到快照" in capsys.readouterr().err


class TestWebStartup:
    @pytest.fixture
    def serve(self, monkeypatch):
        async def fake_serve(*args, **kwargs):
            return None

        monkeypatch.setattr("harness.web.serve", fake_serve)
        monkeypatch.delenv("HARNESS_WEB_PASSWORD", raising=False)

    def test_upgrade_snapshots_before_starting(
        self, root, serve, monkeypatch, capsys
    ):
        monkeypatch.setattr(datastore, "app_version", lambda: "v1")
        assert cli.main(["web", "-p", str(root), "--host", "0.0.0.0"]) == 0
        assert "已自動備份" not in capsys.readouterr().out
        monkeypatch.setattr(datastore, "app_version", lambda: "v2")
        assert cli.main(["web", "-p", str(root), "--host", "0.0.0.0"]) == 0
        assert "已自動備份資料庫與設定" in capsys.readouterr().out
        assert len(datastore.list_snapshots(root)) == 1

    def test_refuses_to_start_on_newer_data(self, root, serve, capsys):
        datastore.prepare(root, version="v1")
        db = sqlite3.connect(root / accounts_lib.DB_FILE)
        db.execute(f"PRAGMA user_version = {datastore.SCHEMA_VERSION + 1}")
        db.close()
        assert cli.main(["web", "-p", str(root), "--host", "0.0.0.0"]) == 1
        assert "pyharness data restore" in capsys.readouterr().err
