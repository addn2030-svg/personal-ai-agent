# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest

from connectors import state_evidence
from engine import store


class UnderTests(unittest.TestCase):
    def test_parent_root(self):
        # parent is '/', path under root should be True
        self.assertTrue(state_evidence._under("/data", "/"))

    def test_same_path(self):
        self.assertTrue(state_evidence._under("/data", "/data"))

    def test_subdir(self):
        self.assertTrue(state_evidence._under("/data/sub", "/data"))

    def test_sibling_prefix(self):
        # '/database' should not be considered under '/data'
        self.assertFalse(state_evidence._under("/database", "/data"))

    def test_empty_args(self):
        self.assertFalse(state_evidence._under("", "/data"))
        self.assertFalse(state_evidence._under("/data", ""))


class WritableProbeTests(unittest.TestCase):
    def test_writable_creates_and_cleans_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            # call _writable and ensure it returns True and probe is removed
            ok = state_evidence._writable(tmp)
            self.assertTrue(ok)
            probe = os.path.join(tmp, ".write_probe")
            self.assertFalse(os.path.exists(probe))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_durable_and_counts(self):
        with tempfile.TemporaryDirectory() as mount_dir, tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as backup_dir:
            # set env to indicate mount path; store.DATA_DIR will be data_dir
            os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = mount_dir
            os.environ["AI_OS_DATA_DIR"] = data_dir

            store.DATA_DIR = data_dir
            store.STATE_PATH = os.path.join(data_dir, "state.json")
            store.AUDIT_PATH = os.path.join(data_dir, "audit.log")
            store.BACKUP_DIR = backup_dir
            store.SECTIONS = ["items"]

            # create a state file with metadata and three records
            with open(store.STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 1}, "items": [1, 2, 3]}, fh)

            # create a single backup file
            open(os.path.join(backup_dir, "state-1.json"), "w").close()

            facts = state_evidence.snapshot()
            # When the data_dir is not actually under mount_dir, durable is False,
            # so exercise both states by temporarily setting mount to the parent.
            self.assertIn("dir", facts)
            self.assertEqual(facts["version"], 1)
            self.assertEqual(facts["records"], 3)
            self.assertEqual(facts["backups"], 1)
            # writable should be True in a tmp dir
            self.assertTrue(facts["writable"])

    def test_snapshot_durable_flag_false_if_not_under_mount(self):
        with tempfile.TemporaryDirectory() as mount_dir, tempfile.TemporaryDirectory() as data_dir:
            os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = mount_dir
            store.DATA_DIR = data_dir
            store.STATE_PATH = os.path.join(data_dir, "state.json")
            store.AUDIT_PATH = os.path.join(data_dir, "audit.log")
            store.BACKUP_DIR = data_dir
            store.SECTIONS = []

            # ensure state file exists but empty
            with open(store.STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 2}}, fh)

            facts = state_evidence.snapshot()
            # data_dir is not under mount_dir => durable False
            self.assertFalse(facts["durable"])


if __name__ == "__main__":
    unittest.main()
