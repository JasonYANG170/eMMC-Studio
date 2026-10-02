import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
from check_ready import check_jobs


class DeploymentChecks(unittest.TestCase):
    def test_busy_jobs_refuse_upgrade_without_modifying_history(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "jobs.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "CREATE TABLE jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
                )
                for state in ("queued", "running"):
                    connection.execute("DELETE FROM jobs")
                    connection.execute(
                        "INSERT INTO jobs VALUES (?,?)",
                        ("test", json.dumps({"state": state})),
                    )
                    connection.commit()
                    with self.assertRaises(RuntimeError):
                        check_jobs(database, True)
                    self.assertEqual(
                        json.loads(
                            connection.execute("SELECT data FROM jobs").fetchone()[0]
                        )["state"],
                        state,
                    )

    def test_terminal_and_stopped_worker_do_not_block(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "jobs.sqlite"
            check_jobs(database, True)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "CREATE TABLE jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
                )
                for state in ("completed", "cancelled", "failed", "interrupted"):
                    connection.execute(
                        "INSERT INTO jobs VALUES (?,?)",
                        (state, json.dumps({"state": state})),
                    )
            check_jobs(database, True)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "INSERT INTO jobs VALUES (?,?)",
                    ("stale", json.dumps({"state": "running"})),
                )
            check_jobs(database, False)

    def test_unreadable_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "jobs.sqlite"
            database.write_bytes(b"invalid sqlite")
            with self.assertRaises(sqlite3.DatabaseError):
                check_jobs(database, True)


if __name__ == "__main__":
    unittest.main()
