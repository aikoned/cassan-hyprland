#!/usr/bin/env python3
"""Isolated tests for Cassan's transactional configuration deployment."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIRECTORY))

import cassan  # noqa: E402


class CassanDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        self.home = self.base / "home"
        self.config = self.base / "xdg-config"
        self.state = self.base / "xdg-state" / "cassan"
        self.repo.mkdir()
        self.home.mkdir()
        self.roots = cassan.Roots(
            home=self.home,
            xdg_config=self.config,
            home_config=self.home / ".config",
            state=self.state,
        )
        self.deployments = (
            cassan.Deployment("source/alpha", "xdg_config", "demo/alpha"),
            cassan.Deployment("source/wallpaper", "home_config", "cassan/wallpaper"),
        )
        self.write_source("source/alpha", b"alpha-v1\n")
        self.write_source("source/wallpaper", b"wallpaper-v1")

    def write_source(self, relative: str, content: bytes) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def deployer(self, deployments=None) -> cassan.Deployer:
        selected = self.deployments if deployments is None else deployments
        return cassan.Deployer(
            repo=self.repo,
            roots=self.roots,
            deployments=selected,
            validate_repository=False,
            euid=1000,
        )

    def deployer_with_other_config(self, deployments=None) -> cassan.Deployer:
        selected = self.deployments if deployments is None else deployments
        changed_roots = cassan.Roots(
            home=self.home,
            xdg_config=self.base / "other-xdg-config",
            home_config=self.home / ".config",
            state=self.state,
        )
        return cassan.Deployer(
            repo=self.repo,
            roots=changed_roots,
            deployments=selected,
            validate_repository=False,
            euid=1000,
        )

    def backup_ids(self) -> list:
        directory = self.state / "backups"
        return sorted(path.name for path in directory.iterdir()) if directory.exists() else []

    def test_runtime_manifest_is_explicit_and_excludes_non_runtime_files(self) -> None:
        expected = [
            (
                "assets/nighthowler/wallpaper.jpg",
                "home_config",
                "cassan/assets/nighthowler/wallpaper.jpg",
            ),
            ("hypr/theme.lua", "xdg_config", "hypr/theme.lua"),
            ("kitty/theme.conf", "xdg_config", "kitty/theme.conf"),
            ("waybar/theme.css", "xdg_config", "waybar/theme.css"),
            ("wofi/theme.css", "xdg_config", "wofi/theme.css"),
            ("swaync/theme.css", "xdg_config", "swaync/theme.css"),
            ("yazi/theme.toml", "xdg_config", "yazi/theme.toml"),
            (
                "cava/themes/nighthowler",
                "xdg_config",
                "cava/themes/nighthowler",
            ),
            ("hypr/hyprpaper.conf", "xdg_config", "hypr/hyprpaper.conf"),
            ("hypr/hyprlock.conf", "xdg_config", "hypr/hyprlock.conf"),
            ("hypr/environment.lua", "xdg_config", "hypr/environment.lua"),
            ("hypr/monitor.lua", "xdg_config", "hypr/monitor.lua"),
            ("hypr/looknfeel.lua", "xdg_config", "hypr/looknfeel.lua"),
            ("hypr/input.lua", "xdg_config", "hypr/input.lua"),
            ("hypr/animation.lua", "xdg_config", "hypr/animation.lua"),
            ("hypr/rules.lua", "xdg_config", "hypr/rules.lua"),
            ("hypr/startup.lua", "xdg_config", "hypr/startup.lua"),
            ("hypr/bind.lua", "xdg_config", "hypr/bind.lua"),
            ("hypr/hypridle.conf", "xdg_config", "hypr/hypridle.conf"),
            ("kitty/kitty.conf", "xdg_config", "kitty/kitty.conf"),
            ("waybar/style.css", "xdg_config", "waybar/style.css"),
            ("waybar/config.jsonc", "xdg_config", "waybar/config.jsonc"),
            ("wofi/style.css", "xdg_config", "wofi/style.css"),
            ("wofi/config", "xdg_config", "wofi/config"),
            ("swaync/style.css", "xdg_config", "swaync/style.css"),
            ("swaync/config.json", "xdg_config", "swaync/config.json"),
            ("yazi/yazi.toml", "xdg_config", "yazi/yazi.toml"),
            ("cava/config", "xdg_config", "cava/config"),
            (
                "fastfetch/config.jsonc",
                "xdg_config",
                "fastfetch/config.jsonc",
            ),
            ("hypr/hyprland.lua", "xdg_config", "hypr/hyprland.lua"),
        ]
        actual = [
            (item.source, item.root, item.relative) for item in cassan.DEPLOYMENTS
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(len(cassan.DEPLOYMENTS), 30)
        self.assertEqual(
            [item.component for item in cassan.DEPLOYMENTS],
            [
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "cava",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "cava",
                "fastfetch",
                "core",
            ],
        )

    def test_default_deployer_always_manages_all_runtime_files(self) -> None:
        deployer = cassan.Deployer(
            repo=cassan.REPO_DIR,
            roots=self.roots,
            validate_repository=False,
            euid=1000,
        )
        self.assertEqual(deployer.deployments, cassan.DEPLOYMENTS)

    def test_transaction_preserves_declared_dependency_order(self) -> None:
        ordered = (self.deployments[1], self.deployments[0])
        deployer = self.deployer(ordered)
        plan = deployer.plan()
        self.assertEqual([item.key for item in plan.items], [item.key for item in ordered])
        backup_id = deployer.apply(plan)
        transaction = json.loads(
            (self.state / "backups" / backup_id / "transaction.json").read_text()
        )
        actual = [
            "%s:%s" % (item["root"], item["relative"])
            for item in transaction["operations"]
        ]
        self.assertEqual(actual, [item.key for item in ordered])

    def test_source_parent_symlink_escape_is_rejected(self) -> None:
        outside = self.base / "outside-source"
        outside.mkdir()
        (outside / "payload").write_bytes(b"outside")
        os.symlink(str(outside), str(self.repo / "linked"))
        deployment = cassan.Deployment(
            "linked/payload", "xdg_config", "demo/payload"
        )
        with self.assertRaises(cassan.PreflightError):
            self.deployer((deployment,)).plan()

    def test_plan_is_read_only_apply_is_idempotent(self) -> None:
        deployer = self.deployer()
        plan = deployer.plan()
        self.assertEqual([item.action for item in plan.items], ["create", "create"])
        self.assertFalse(self.config.exists())
        self.assertFalse(self.state.exists())

        first_backup = deployer.apply(plan)
        self.assertIsNotNone(first_backup)
        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v1\n")
        self.assertEqual(
            (self.home / ".config/cassan/wallpaper").read_bytes(), b"wallpaper-v1"
        )
        self.assertEqual(
            os.stat(str(self.config / "demo/alpha")).st_mode & 0o777, 0o644
        )
        backups_after_first = self.backup_ids()

        second_plan = deployer.plan()
        self.assertTrue(all(item.action == "unchanged" for item in second_plan.items))
        self.assertIsNone(deployer.apply(second_plan))
        self.assertEqual(self.backup_ids(), backups_after_first)

    def test_first_install_fsyncs_each_created_directory_parent_immediately(self) -> None:
        deployer = self.deployer()
        real_mkdir = cassan.os.mkdir
        real_fsync_directory = cassan.fsync_directory
        events = []

        def tracked_mkdir(path, mode=0o777, *args, **kwargs):
            events.append(("mkdir", Path(path)))
            return real_mkdir(path, mode, *args, **kwargs)

        def tracked_fsync(path):
            events.append(("fsync", Path(path)))
            return real_fsync_directory(path)

        with mock.patch.object(cassan.os, "mkdir", side_effect=tracked_mkdir), mock.patch.object(
            cassan, "fsync_directory", side_effect=tracked_fsync
        ):
            backup_id = deployer.apply(deployer.plan())

        mkdir_events = [event for event in events if event[0] == "mkdir"]
        self.assertTrue(mkdir_events)
        for index, event in enumerate(events):
            if event[0] != "mkdir":
                continue
            self.assertLess(index + 1, len(events))
            self.assertEqual(events[index + 1], ("fsync", event[1].parent))

        created = {event[1] for event in mkdir_events}
        self.assertTrue(
            {
                self.state.parent,
                self.state,
                self.state / "backups",
                self.config,
                self.config / "demo",
                self.home / ".config",
                self.home / ".config/cassan",
                self.state / "backups" / backup_id,
            }.issubset(created)
        )

    def test_directory_fsync_failure_is_not_silenced_on_linux(self) -> None:
        unsupported = OSError(cassan.errno.EINVAL, "directory fsync unsupported")
        with mock.patch.object(cassan.sys, "platform", "linux"), mock.patch.object(
            cassan.os, "open", side_effect=unsupported
        ):
            with self.assertRaises(OSError):
                cassan.fsync_directory(self.base)
        with mock.patch.object(cassan.sys, "platform", "darwin"), mock.patch.object(
            cassan.os, "open", side_effect=unsupported
        ):
            cassan.fsync_directory(self.base)

    def test_atomic_write_sets_mode_before_file_fsync(self) -> None:
        destination = self.base / "atomic-mode-test"
        events = []
        real_fchmod = cassan.os.fchmod
        real_fsync = cassan.os.fsync

        def tracked_fchmod(descriptor, mode):
            events.append(("fchmod", descriptor, mode))
            return real_fchmod(descriptor, mode)

        def tracked_fsync(descriptor):
            events.append(("fsync", descriptor))
            return real_fsync(descriptor)

        with mock.patch.object(
            cassan.os, "fchmod", side_effect=tracked_fchmod
        ), mock.patch.object(cassan.os, "fsync", side_effect=tracked_fsync):
            cassan.atomic_write_bytes(destination, b"durable-mode", 0o640)

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0][0], "fchmod")
        self.assertEqual(events[0][2], 0o640)
        self.assertEqual(events[1], ("fsync", events[0][1]))
        self.assertEqual(destination.read_bytes(), b"durable-mode")
        self.assertEqual(destination.stat().st_mode & 0o777, 0o640)

    def test_apply_rechecks_unchanged_sources_after_taking_lock(self) -> None:
        deployer = self.deployer()
        deployer.apply(deployer.plan())
        self.write_source("source/alpha", b"alpha-v2\n")
        reviewed = deployer.plan()
        self.assertEqual(
            [item.action for item in reviewed.items], ["update", "unchanged"]
        )
        real_verify = deployer._verify_plan_snapshot
        verification_count = {"value": 0}

        def mutate_after_first_verification(plan):
            real_verify(plan)
            verification_count["value"] += 1
            if verification_count["value"] == 1:
                self.write_source("source/wallpaper", b"wallpaper-v2")

        with mock.patch.object(
            deployer,
            "_verify_plan_snapshot",
            side_effect=mutate_after_first_verification,
        ):
            with self.assertRaisesRegex(cassan.TransactionError, "source changed"):
                deployer.apply(reviewed)

        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v1\n")
        self.assertEqual(
            (self.home / ".config/cassan/wallpaper").read_bytes(), b"wallpaper-v1"
        )

    def test_apply_detects_unchanged_destination_race_before_commit(self) -> None:
        deployer = self.deployer()
        deployer.apply(deployer.plan())
        original_state = deployer.state_file.read_bytes()
        self.write_source("source/alpha", b"alpha-v2\n")
        reviewed = deployer.plan()
        wallpaper = self.home / ".config/cassan/wallpaper"
        real_atomic_copy = cassan.atomic_copy
        changed = {"value": False}

        def change_unchanged_destination(source, destination, mode):
            result = real_atomic_copy(source, destination, mode)
            if destination.parent.name == "staged" and not changed["value"]:
                changed["value"] = True
                wallpaper.write_bytes(b"external-change")
            return result

        with mock.patch.object(
            cassan, "atomic_copy", side_effect=change_unchanged_destination
        ):
            with self.assertRaisesRegex(
                cassan.TransactionError, "destination changed before transaction commit"
            ):
                deployer.apply(reviewed)

        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v1\n")
        self.assertEqual(wallpaper.read_bytes(), b"external-change")
        self.assertEqual(deployer.state_file.read_bytes(), original_state)

    def test_apply_rejects_manifest_change_after_review(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer.apply(deployer.plan())
        self.write_source("source/alpha", b"alpha-v2\n")
        reviewed = deployer.plan()
        state = deployer.load_state()
        state["installed_at"] = "externally-modified"
        cassan.atomic_write_json(deployer.state_file, state)
        with self.assertRaisesRegex(cassan.TransactionError, "changed after review"):
            deployer.apply(reviewed)
        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v1\n")

    def test_apply_binds_manifest_mode_as_well_as_content(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer.apply(deployer.plan())
        self.write_source("source/alpha", b"alpha-v2\n")
        reviewed = deployer.plan()
        os.chmod(str(deployer.state_file), 0o644)
        with self.assertRaisesRegex(cassan.TransactionError, "changed after review"):
            deployer.apply(reviewed)
        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v1\n")

    def test_unmanaged_conflict_requires_replace_and_restore_is_reversible(self) -> None:
        destination = self.config / "demo/alpha"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"user-data\n")
        deployer = self.deployer((self.deployments[0],))

        conflict_plan = deployer.plan()
        self.assertEqual(conflict_plan.items[0].action, "conflict")
        with self.assertRaises(cassan.ConflictError):
            deployer.apply(conflict_plan)
        self.assertEqual(destination.read_bytes(), b"user-data\n")

        replace_plan = deployer.plan(replace=True)
        self.assertEqual(replace_plan.items[0].action, "replace")
        applied_backup = deployer.apply(replace_plan)
        self.assertEqual(destination.read_bytes(), b"alpha-v1\n")

        restore_plan, previous_state = deployer.plan_restore(applied_backup)
        self.assertEqual(destination.read_bytes(), b"alpha-v1\n")
        pre_restore_backup = deployer.restore(
            applied_backup, restore_plan, previous_state
        )
        self.assertIsNotNone(pre_restore_backup)
        self.assertEqual(destination.read_bytes(), b"user-data\n")

        reverse_plan, reverse_state = deployer.plan_restore(pre_restore_backup)
        deployer.restore(pre_restore_backup, reverse_plan, reverse_state)
        self.assertEqual(destination.read_bytes(), b"alpha-v1\n")

    def test_modified_managed_file_conflicts_and_replace_backs_it_up(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer.apply(deployer.plan())
        destination = self.config / "demo/alpha"
        destination.write_bytes(b"local-edit\n")
        self.write_source("source/alpha", b"alpha-v2\n")

        plan = deployer.plan()
        self.assertEqual(plan.items[0].action, "conflict")
        forced = deployer.plan(replace=True)
        backup_id = deployer.apply(forced)
        self.assertEqual(destination.read_bytes(), b"alpha-v2\n")

        transaction = json.loads(
            (self.state / "backups" / backup_id / "transaction.json").read_text()
        )
        backup_name = transaction["operations"][0]["before"]["backup"]
        self.assertEqual(
            (self.state / "backups" / backup_id / "files" / backup_name).read_bytes(),
            b"local-edit\n",
        )

    def test_stale_managed_file_is_removed_only_when_unmodified(self) -> None:
        deployer = self.deployer()
        deployer.apply(deployer.plan())
        reduced = self.deployer((self.deployments[0],))
        stale = self.home / ".config/cassan/wallpaper"
        plan = reduced.plan()
        actions = {item.relative: item.action for item in plan.items}
        self.assertEqual(actions["cassan/wallpaper"], "remove")
        reduced.apply(plan)
        self.assertFalse(stale.exists())

        # Reinstall and prove a user edit changes removal into a conflict.
        deployer.apply(deployer.plan())
        stale.write_bytes(b"local-wallpaper")
        conflict = reduced.plan()
        actions = {item.relative: item.action for item in conflict.items}
        self.assertEqual(actions["cassan/wallpaper"], "conflict")

    def test_symlinked_component_parent_is_rejected(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        self.config.mkdir()
        os.symlink(str(outside), str(self.config / "demo"))
        deployer = self.deployer((self.deployments[0],))
        with self.assertRaises(cassan.ConflictError):
            deployer.plan()
        self.assertEqual(list(outside.iterdir()), [])

    def test_injected_mid_transaction_failure_rolls_back(self) -> None:
        deployer = self.deployer()
        plan = deployer.plan()
        real_atomic_copy = cassan.atomic_copy
        destinations = {
            str(self.config / "demo/alpha"),
            str(self.home / ".config/cassan/wallpaper"),
        }
        writes = {"count": 0}

        def fail_second_destination(source, destination, mode):
            if str(destination) in destinations:
                writes["count"] += 1
                if writes["count"] == 2:
                    raise OSError("injected write failure")
            return real_atomic_copy(source, destination, mode)

        with mock.patch.object(cassan, "atomic_copy", side_effect=fail_second_destination):
            with self.assertRaises(cassan.TransactionError):
                deployer.apply(plan)

        self.assertFalse((self.config / "demo/alpha").exists())
        self.assertFalse((self.home / ".config/cassan/wallpaper").exists())
        self.assertFalse((self.state / "manifest.json").exists())
        metadata_files = list((self.state / "backups").glob("*/transaction.json"))
        self.assertEqual(len(metadata_files), 1)
        metadata = json.loads(metadata_files[0].read_text())
        self.assertEqual(metadata["status"], "rolled-back")

    def test_manifest_third_state_is_preserved_and_marks_rollback_failed(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        reviewed = deployer.plan()
        real_atomic_write_json = cassan.atomic_write_json
        injected = {"value": False}

        def fail_after_manifest_commit(path, value, mode=0o600):
            if (
                path.name == "transaction.json"
                and value.get("status") == "completed"
                and not injected["value"]
            ):
                injected["value"] = True
                third_state = json.loads(deployer.state_file.read_text())
                third_state["installed_at"] = "concurrent-third-state"
                real_atomic_write_json(deployer.state_file, third_state)
                raise OSError("injected journal completion failure")
            return real_atomic_write_json(path, value, mode)

        with mock.patch.object(
            cassan, "atomic_write_json", side_effect=fail_after_manifest_commit
        ):
            with self.assertRaisesRegex(
                cassan.TransactionError, "rollback also failed"
            ):
                deployer.apply(reviewed)

        self.assertTrue(injected["value"])
        self.assertFalse((self.config / "demo/alpha").exists())
        preserved = deployer.load_state()
        self.assertEqual(preserved["installed_at"], "concurrent-third-state")
        backup_id = self.backup_ids()[0]
        transaction = json.loads(
            (
                self.state / "backups" / backup_id / "transaction.json"
            ).read_text()
        )
        self.assertEqual(transaction["status"], "rollback-failed")
        self.assertTrue(
            any("exact transaction result" in item for item in transaction["rollback_errors"])
        )
        self.assertTrue(deployer.active_transaction_path.is_file())

    def test_preparation_failure_is_wrapped_and_partial_backup_is_removed(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        plan = deployer.plan()
        real_atomic_copy = cassan.atomic_copy

        def fail_staging(source, destination, mode):
            if destination.parent.name == "staged":
                raise OSError("injected preparation failure")
            return real_atomic_copy(source, destination, mode)

        with mock.patch.object(cassan, "atomic_copy", side_effect=fail_staging):
            with self.assertRaisesRegex(
                cassan.TransactionError, "transaction preparation failed"
            ):
                deployer.apply(plan)

        self.assertFalse((self.config / "demo/alpha").exists())
        self.assertFalse((self.state / "manifest.json").exists())
        self.assertEqual(self.backup_ids(), [])

    def test_adopt_and_state_only_restore_are_reversible(self) -> None:
        destination = self.config / "demo/alpha"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"alpha-v1\n")
        deployer = self.deployer((self.deployments[0],))

        adopt_plan = deployer.plan()
        self.assertEqual(adopt_plan.items[0].action, "adopt")
        adopt_backup = deployer.apply(adopt_plan)
        self.assertIsNotNone(adopt_backup)
        self.assertEqual(destination.read_bytes(), b"alpha-v1\n")
        self.assertEqual(len(deployer.load_state()["files"]), 1)

        restore_plan, previous_state = deployer.plan_restore(adopt_backup)
        self.assertTrue(restore_plan.state_change)
        self.assertEqual(restore_plan.items[0].action, "reconcile")
        reverse_backup = deployer.restore(adopt_backup, restore_plan, previous_state)
        self.assertEqual(destination.read_bytes(), b"alpha-v1\n")
        self.assertEqual(deployer.load_state()["files"], [])

        reverse_plan, installed_state = deployer.plan_restore(reverse_backup)
        deployer.restore(reverse_backup, reverse_plan, installed_state)
        self.assertEqual(destination.read_bytes(), b"alpha-v1\n")
        self.assertEqual(len(deployer.load_state()["files"]), 1)

    def test_stale_state_snapshot_reports_drift_and_reconciles_transactionally(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer.apply(deployer.plan())
        state = deployer.load_state()
        state["files"][0]["sha256"] = "0" * 64
        cassan.atomic_write_json(deployer.state_file, state)

        plan = deployer.plan()
        self.assertTrue(plan.drift)
        self.assertEqual(plan.items[0].action, "reconcile")
        destination = self.config / "demo/alpha"
        before = destination.stat().st_mtime_ns
        backup_id = deployer.apply(plan)
        self.assertEqual(destination.stat().st_mtime_ns, before)
        transaction = json.loads(
            (self.state / "backups" / backup_id / "transaction.json").read_text()
        )
        self.assertTrue(transaction["operations"][0]["state_only"])
        self.assertEqual(deployer.plan().items[0].action, "unchanged")

    def test_older_backup_is_refused_even_with_replace(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        older = deployer.apply(deployer.plan())
        self.write_source("source/alpha", b"alpha-v2\n")
        newer = deployer.apply(deployer.plan())
        self.assertNotEqual(older, newer)
        with self.assertRaises(cassan.ConflictError):
            deployer.plan_restore(older, replace=True)

    def test_restore_rechecks_lineage_after_taking_lock(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        first = deployer.apply(deployer.plan())
        reviewed, reviewed_state = deployer.plan_restore(first)
        self.write_source("source/alpha", b"alpha-v2\n")
        second = deployer.apply(deployer.plan())
        self.assertNotEqual(first, second)
        with self.assertRaises(cassan.ConflictError):
            deployer.restore(first, reviewed, reviewed_state)
        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v2\n")

    def test_state_and_restore_refuse_changed_config_root(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        backup_id = deployer.apply(deployer.plan())
        changed = self.deployer_with_other_config((self.deployments[0],))
        with self.assertRaisesRegex(cassan.PreflightError, "different deployment roots"):
            changed.plan()
        with self.assertRaisesRegex(cassan.PreflightError, "different deployment roots"):
            changed.plan_restore(backup_id)
        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v1\n")
        self.assertFalse((self.base / "other-xdg-config/demo/alpha").exists())

    def test_restore_binds_stored_manifest_snapshot(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer.apply(deployer.plan())
        self.write_source("source/alpha", b"alpha-v2\n")
        second = deployer.apply(deployer.plan())
        reviewed, reviewed_state = deployer.plan_restore(second)
        prior_manifest = self.state / "backups" / second / "manifest.before.json"
        stored = json.loads(prior_manifest.read_text())
        stored["installed_at"] = "modified-backup"
        cassan.atomic_write_json(prior_manifest, stored)
        with self.assertRaisesRegex(cassan.PreflightError, "failed verification"):
            deployer.restore(second, reviewed, reviewed_state)
        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v2\n")

    def test_corrupt_had_manifest_metadata_is_rejected(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        backup_id = deployer.apply(deployer.plan())
        transaction_path = self.state / "backups" / backup_id / "transaction.json"
        transaction = json.loads(transaction_path.read_text())
        self.assertFalse(transaction["had_manifest"])
        transaction["had_manifest"] = True
        transaction_path.write_text(json.dumps(transaction), encoding="utf-8")
        with self.assertRaisesRegex(cassan.PreflightError, "had_manifest"):
            deployer.plan_restore(backup_id)

    def test_missing_stored_file_makes_backup_unrestorable(self) -> None:
        destination = self.config / "demo/alpha"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"existing")
        deployer = self.deployer((self.deployments[0],))
        backup_id = deployer.apply(deployer.plan(replace=True))
        transaction_path = self.state / "backups" / backup_id / "transaction.json"
        transaction = json.loads(transaction_path.read_text())
        backup_name = transaction["operations"][0]["before"]["backup"]
        (self.state / "backups" / backup_id / "files" / backup_name).unlink()
        with self.assertRaisesRegex(cassan.PreflightError, "failed verification"):
            deployer.plan_restore(backup_id)

    def test_invalid_backup_identifier_is_rejected(self) -> None:
        with self.assertRaises(cassan.PreflightError):
            self.deployer().plan_restore("../../outside")

    def test_package_manifest_parser_rejects_invalid_and_duplicate_tokens(self) -> None:
        packages = self.repo / "packages/official.txt"
        packages.parent.mkdir()
        packages.write_text("# core\nhyprland\n\nwaybar\n", encoding="utf-8")
        self.assertEqual(cassan.load_official_packages(self.repo), ["hyprland", "waybar"])

        packages.write_text("hyprland\nhyprland\n", encoding="utf-8")
        with self.assertRaises(cassan.PreflightError):
            cassan.load_official_packages(self.repo)

        packages.write_text("hyprland --needed\n", encoding="utf-8")
        with self.assertRaises(cassan.PreflightError):
            cassan.load_official_packages(self.repo)

    def test_package_selection_keeps_configs_stable_and_accessories_opt_in(self) -> None:
        non_blocking = [
            "btop",
            "fastfetch",
            "lua",
            "file",
            "wl-clipboard",
            "blueman",
            "noto-fonts",
            "zsh",
        ]
        manifest = non_blocking + sorted(cassan.CORE_PACKAGE_NAMES) + [
            "cava",
            "zathura",
        ]
        core = cassan.select_packages(manifest, ())
        self.assertEqual(core, sorted(cassan.CORE_PACKAGE_NAMES))
        self.assertNotIn("cava", core)
        self.assertNotIn("fastfetch", core)
        self.assertNotIn("btop", core)
        for package in ("lua", "file", "wl-clipboard", "blueman", "noto-fonts", "zsh"):
            self.assertNotIn(package, core)
        selected = cassan.select_packages(manifest, ("cava", "fastfetch"))
        self.assertEqual(
            selected,
            [
                package
                for package in manifest
                if package in cassan.CORE_PACKAGE_NAMES
                or package in ("cava", "fastfetch")
            ],
        )
        # The manifest order is authoritative, so Fastfetch remains first.
        self.assertEqual(selected[0], "fastfetch")
        with self.assertRaises(cassan.PreflightError):
            cassan.select_packages(manifest, ("future-tools",))

    def test_package_inspection_uses_fixed_pacman_and_reports_missing(self) -> None:
        completed = mock.Mock(returncode=127, stdout="waybar\nkitty\n", stderr="")
        with mock.patch.object(cassan, "is_arch_linux", return_value=True), mock.patch.object(
            cassan,
            "verified_system_executable",
            return_value=str(cassan.PACMAN_PATH),
        ) as verify, mock.patch.object(
            cassan.subprocess, "run", return_value=completed
        ) as run:
            missing = cassan.inspect_packages(["hyprland", "waybar", "kitty"])
        self.assertEqual(missing, ["waybar", "kitty"])
        verify.assert_called_once_with(cassan.PACMAN_PATH, "pacman")
        run.assert_called_once_with(
            ["/usr/bin/pacman", "-T", "hyprland", "waybar", "kitty"],
            stdout=cassan.subprocess.PIPE,
            stderr=cassan.subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_package_install_uses_fixed_absolute_argv(self) -> None:
        completed = mock.Mock(returncode=0)

        def verified(path, _label):
            return str(path)

        with mock.patch.object(cassan, "is_arch_linux", return_value=True), mock.patch.object(
            cassan, "verified_system_executable", side_effect=verified
        ) as verify, mock.patch.object(
            cassan.subprocess, "run", return_value=completed
        ) as run:
            cassan.install_packages(["hyprland", "waybar"], euid=1000)
        self.assertEqual(
            verify.call_args_list,
            [
                mock.call(cassan.PACMAN_PATH, "pacman"),
                mock.call(cassan.SUDO_PATH, "sudo"),
            ],
        )
        run.assert_called_once_with(
            [
                "/usr/bin/sudo",
                "/usr/bin/pacman",
                "-Syu",
                "--needed",
                "--",
                "hyprland",
                "waybar",
            ],
            check=False,
        )

    def test_package_arch_root_and_failure_gates(self) -> None:
        with mock.patch.object(cassan, "is_arch_linux", return_value=False), mock.patch.object(
            cassan, "verified_system_executable"
        ) as verify:
            with self.assertRaises(cassan.PreflightError):
                cassan.inspect_packages(["hyprland"])
            verify.assert_not_called()

        with self.assertRaises(cassan.PreflightError):
            cassan.install_packages(["hyprland"], euid=0)

        inspection_failure = mock.Mock(returncode=1, stdout="", stderr="failure")
        installation_failure = mock.Mock(returncode=9)
        with mock.patch.object(cassan, "is_arch_linux", return_value=True), mock.patch.object(
            cassan,
            "verified_system_executable",
            side_effect=lambda path, _label: str(path),
        ), mock.patch.object(
            cassan.subprocess, "run", return_value=inspection_failure
        ):
            with self.assertRaises(cassan.PackageError) as inspected:
                cassan.inspect_packages(["hyprland"])
            self.assertEqual(inspected.exception.exit_code, 5)

        with mock.patch.object(cassan, "is_arch_linux", return_value=True), mock.patch.object(
            cassan,
            "verified_system_executable",
            side_effect=lambda path, _label: str(path),
        ), mock.patch.object(
            cassan.subprocess, "run", return_value=installation_failure
        ):
            with self.assertRaises(cassan.PackageError) as installed:
                cassan.install_packages(["hyprland"], euid=1000)
            self.assertEqual(installed.exception.exit_code, 5)

    def test_relative_xdg_root_is_rejected(self) -> None:
        environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": "relative/config",
            "XDG_STATE_HOME": str(self.base / "state"),
        }
        with self.assertRaises(cassan.PreflightError):
            cassan.Roots.from_environ(environment)

    def test_symlinked_state_directory_is_rejected(self) -> None:
        outside = self.base / "outside-state"
        outside.mkdir()
        self.state.parent.mkdir(parents=True)
        os.symlink(str(outside), str(self.state))
        deployer = self.deployer((self.deployments[0],))
        with self.assertRaises(cassan.PreflightError):
            deployer.apply(deployer.plan())
        self.assertEqual(list(outside.iterdir()), [])

    def test_noop_apply_still_takes_persistent_transaction_lock(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer.apply(deployer.plan())
        reviewed = deployer.plan()
        with mock.patch.object(
            deployer,
            "_acquire_transaction_lock",
            wraps=deployer._acquire_transaction_lock,
        ) as acquire:
            self.assertIsNone(deployer.apply(reviewed))
        acquire.assert_called_once()
        self.assertTrue(deployer.lock_path.is_file())
        self.assertFalse(deployer.active_transaction_path.exists())

    def test_noop_restore_rechecks_lineage_under_lock(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        applied = deployer.apply(deployer.plan())
        restore_plan, restore_state = deployer.plan_restore(applied)
        deployer.restore(applied, restore_plan, restore_state)
        reviewed, reviewed_state = deployer.plan_restore(applied)
        self.assertFalse(reviewed.state_change)
        with mock.patch.object(
            deployer,
            "_acquire_transaction_lock",
            wraps=deployer._acquire_transaction_lock,
        ) as acquire:
            self.assertIsNone(deployer.restore(applied, reviewed, reviewed_state))
        acquire.assert_called_once()

    def test_prepared_partial_transaction_is_recovered_from_stale_lock(self) -> None:
        destination = self.config / "demo/alpha"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"user-data\n")
        deployer = self.deployer((self.deployments[0],))
        operation_id = deployer.apply(deployer.plan(replace=True))
        transaction_path = (
            self.state / "backups" / operation_id / "transaction.json"
        )
        transaction = json.loads(transaction_path.read_text())
        transaction["status"] = "prepared"
        cassan.atomic_write_json(transaction_path, transaction)
        cassan.atomic_write_json(
            deployer.active_transaction_path,
            {
                "schema": cassan.SCHEMA,
                "status": "active",
                "roots": deployer.root_identity(),
                "operation_id": operation_id,
                "pid": 2147483647,
                "uid": deployer.euid,
                "process_identity": "stale-process",
                "created_at": cassan.utc_now(),
            },
        )

        recovery = deployer.plan_recovery()
        self.assertEqual(recovery.recovery_status, "prepared")
        self.assertEqual(recovery.items[0].action, "update")
        self.assertTrue(recovery.state_change)
        deployer.recover(recovery)

        self.assertEqual(destination.read_bytes(), b"user-data\n")
        self.assertFalse(deployer.state_file.exists())
        recovered = json.loads(transaction_path.read_text())
        self.assertEqual(recovered["status"], "recovered-rolled-back")
        self.assertTrue(deployer.lock_path.is_file())
        self.assertFalse(deployer.active_transaction_path.exists())

    def test_recovery_rejects_edited_manifest_with_same_transaction_id(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        operation_id = deployer.apply(deployer.plan())
        transaction_path = (
            self.state / "backups" / operation_id / "transaction.json"
        )
        transaction = json.loads(transaction_path.read_text())
        transaction["status"] = "prepared"
        cassan.atomic_write_json(transaction_path, transaction)
        edited_state = deployer.load_state()
        self.assertEqual(edited_state["transaction_id"], operation_id)
        edited_state["installed_at"] = "third-party-edit-with-same-id"
        cassan.atomic_write_json(deployer.state_file, edited_state)
        cassan.atomic_write_json(
            deployer.active_transaction_path,
            {
                "schema": cassan.SCHEMA,
                "status": "active",
                "roots": deployer.root_identity(),
                "operation_id": operation_id,
                "pid": 2147483647,
                "uid": deployer.euid,
                "process_identity": None,
                "created_at": cassan.utc_now(),
            },
        )
        with self.assertRaisesRegex(cassan.ConflictError, "exact interrupted result"):
            deployer.plan_recovery()

    def test_recovery_refuses_changed_config_root_without_clearing_marker(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        operation_id = deployer.apply(deployer.plan())
        transaction_path = (
            self.state / "backups" / operation_id / "transaction.json"
        )
        transaction = json.loads(transaction_path.read_text())
        transaction["status"] = "prepared"
        cassan.atomic_write_json(transaction_path, transaction)
        cassan.atomic_write_json(
            deployer.active_transaction_path,
            {
                "schema": cassan.SCHEMA,
                "status": "active",
                "roots": deployer.root_identity(),
                "operation_id": operation_id,
                "pid": 2147483647,
                "uid": deployer.euid,
                "process_identity": None,
                "created_at": cassan.utc_now(),
            },
        )
        changed = self.deployer_with_other_config((self.deployments[0],))
        with self.assertRaisesRegex(cassan.PreflightError, "different deployment roots"):
            changed.plan_recovery()
        self.assertTrue(deployer.active_transaction_path.is_file())
        self.assertEqual((self.config / "demo/alpha").read_bytes(), b"alpha-v1\n")
        self.assertFalse((self.base / "other-xdg-config/demo/alpha").exists())

    def test_recovery_refuses_a_lock_held_by_an_active_process(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer._ensure_private_state_directories()
        operation_id = cassan.new_backup_id()
        cassan.atomic_write_json(
            deployer.active_transaction_path,
            {
                "schema": cassan.SCHEMA,
                "status": "active",
                "roots": deployer.root_identity(),
                "operation_id": operation_id,
                "pid": os.getpid(),
                "uid": deployer.euid,
                "process_identity": cassan.process_identity(os.getpid()),
                "created_at": cassan.utc_now(),
            },
        )
        descriptor = deployer._open_lock_file(create=True)
        cassan.fcntl.flock(descriptor, cassan.fcntl.LOCK_EX | cassan.fcntl.LOCK_NB)
        try:
            with self.assertRaisesRegex(cassan.TransactionError, "active"):
                deployer.plan_recovery()
        finally:
            cassan.fcntl.flock(descriptor, cassan.fcntl.LOCK_UN)
            os.close(descriptor)

    def test_recovery_refuses_foreign_lock_metadata(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer._ensure_private_state_directories()
        descriptor = deployer._open_lock_file(create=True)
        os.close(descriptor)
        cassan.atomic_write_json(
            deployer.active_transaction_path,
            {
                "schema": cassan.SCHEMA,
                "status": "active",
                "roots": deployer.root_identity(),
                "operation_id": cassan.new_backup_id(),
                "pid": 2147483647,
                "uid": deployer.euid + 1,
                "process_identity": None,
                "created_at": cassan.utc_now(),
            },
        )
        with self.assertRaisesRegex(cassan.TransactionError, "different effective user"):
            deployer.plan_recovery()

    def test_recovery_cleans_only_known_incomplete_transaction_directory(self) -> None:
        deployer = self.deployer((self.deployments[0],))
        deployer._ensure_private_state_directories()
        descriptor = deployer._open_lock_file(create=True)
        os.close(descriptor)
        operation_id = cassan.new_backup_id()
        incomplete = self.state / "backups" / operation_id
        incomplete.mkdir(mode=0o700)
        (incomplete / "partial").write_bytes(b"setup-only")
        cassan.atomic_write_json(
            deployer.active_transaction_path,
            {
                "schema": cassan.SCHEMA,
                "status": "active",
                "roots": deployer.root_identity(),
                "operation_id": operation_id,
                "pid": 2147483647,
                "uid": deployer.euid,
                "process_identity": None,
                "created_at": cassan.utc_now(),
            },
        )
        recovery = deployer.plan_recovery()
        self.assertEqual(recovery.recovery_status, "incomplete")
        deployer.recover(recovery)
        self.assertFalse(incomplete.exists())
        self.assertTrue(deployer.lock_path.is_file())
        self.assertFalse(deployer.active_transaction_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
