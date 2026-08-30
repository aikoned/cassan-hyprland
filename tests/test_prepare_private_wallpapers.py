#!/usr/bin/env python3

import os
import pathlib
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
PREPARE = ROOT / "scripts/prepare-private-wallpapers.sh"
SWITCHER = ROOT / "waybar/scripts/theme-switcher.sh"
EXPECTED = "b795a1231176884c2b144ddf38ffbc436505df03592fa2d4010df26100867277"


class PrivateWallpaperTests(unittest.TestCase):
    def test_expected_private_wallpaper_checksum_is_fixed(self) -> None:
        self.assertIn(f"expected={EXPECTED}", PREPARE.read_text(encoding="utf-8"))

    def make_environment(self, root: pathlib.Path, good: pathlib.Path) -> dict[str, str]:
        fake_bin = root / "bin"
        fake_bin.mkdir(parents=True)
        sha = fake_bin / "sha256sum"
        sha.write_text(
            textwrap.dedent(
                f"""#!/bin/sh
                if cmp -s "$1" "$HYPRLAND_DOTS_TEST_GOOD"; then
                  printf '{EXPECTED}  %s\n' "$1"
                else
                  printf '{"0" * 64}  %s\n' "$1"
                fi
                """
            ),
            encoding="utf-8",
        )
        sha.chmod(0o755)
        flock = fake_bin / "flock"
        flock.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        flock.chmod(0o755)

        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(root / "home"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "HYPRLAND_DOTS_TEST_GOOD": str(good),
                "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            }
        )
        return environment

    def run_prepare(
        self, environment: dict[str, str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PREPARE)],
            check=check,
            env=environment,
            text=True,
            capture_output=True,
        )

    def test_copy_permissions_idempotency_and_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = (
                root
                / "home/cassan-hyprland/assets/nighthowler/wallpaper.jpg"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"private Reze test wallpaper\n")
            environment = self.make_environment(root, source)
            destination = root / "data/hyprland-dots/wallpapers/reze.jpg"

            result = self.run_prepare(environment)
            self.assertEqual(pathlib.Path(result.stdout.strip()), destination)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

            destination.chmod(0o644)
            self.run_prepare(environment)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

            destination.write_bytes(b"different wallpaper\n")
            refused = self.run_prepare(environment, check=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("refusing to replace a different file", refused.stderr)
            self.assertEqual(destination.read_bytes(), b"different wallpaper\n")

    def test_backup_recovery_and_symlink_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = (
                root
                / "state/hyprland-dots/legacy-cassan/20260829"
                / "home-config/cassan/assets/nighthowler/wallpaper.jpg"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"private backup wallpaper\n")
            environment = self.make_environment(root, source)
            destination = root / "data/hyprland-dots/wallpapers/reze.jpg"

            self.run_prepare(environment)
            self.assertEqual(destination.read_bytes(), source.read_bytes())

            destination.unlink()
            destination.symlink_to(source)
            refused = self.run_prepare(environment, check=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("refusing to use a symlink", refused.stderr)

    def test_theme_prepare_preserves_reze_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = (
                root
                / "home/cassan-hyprland/assets/nighthowler/wallpaper.jpg"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"private switcher wallpaper\n")
            environment = self.make_environment(root, source)

            subprocess.run(
                [str(SWITCHER), "prepare"],
                check=True,
                env=environment,
                text=True,
                capture_output=True,
            )
            cache = root / "cache/hyprland-dots"
            destination = root / "data/hyprland-dots/wallpapers/reze.jpg"
            active = cache / "active-theme"
            self.assertEqual(
                (active / "wallpaper").resolve(),
                ROOT / "assets/after_school_stroll_gruvbox.png",
            )
            self.assertEqual(
                (active / "current-theme").read_text(encoding="utf-8").strip(),
                "after-school",
            )

            active.unlink()
            active.symlink_to((cache / "themes/reze").resolve())
            subprocess.run(
                [str(SWITCHER), "prepare"],
                check=True,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual((active / "wallpaper").resolve(), destination.resolve())
            self.assertEqual(
                (active / "current-theme").read_text(encoding="utf-8").strip(),
                "reze",
            )
            for slug in ("after-school", "reze"):
                theme = cache / "themes" / slug
                self.assertTrue(theme.is_symlink())
                for icon in (ROOT / "wlogout/icons").glob("*.png"):
                    self.assertEqual(
                        (theme / "icons" / icon.name).read_bytes(),
                        icon.read_bytes(),
                    )
            generations = [
                path
                for path in (cache / "themes").iterdir()
                if path.name.startswith((".after-school.", ".reze."))
            ]
            self.assertEqual(len(generations), 2)

    def test_failed_wallpaper_change_does_not_publish_theme_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = (
                root
                / "home/cassan-hyprland/assets/nighthowler/wallpaper.jpg"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"private transaction wallpaper\n")
            environment = self.make_environment(root, source)
            fake_bin = root / "bin"
            awww = fake_bin / "awww"
            awww.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = query ]; then exit 0; fi\n"
                "if [ \"$1\" = img ]; then exit \"$HYPRLAND_DOTS_TEST_AWWW_EXIT\"; fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            awww.chmod(0o755)
            notify = fake_bin / "notify-send"
            notify.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            notify.chmod(0o755)

            subprocess.run(
                [str(SWITCHER), "prepare"],
                check=True,
                env=environment,
                text=True,
                capture_output=True,
            )
            cache = root / "cache/hyprland-dots"
            active = cache / "active-theme"
            before_wallpaper = (active / "wallpaper").resolve()
            before_theme = active.resolve()

            environment["HYPRLAND_DOTS_TEST_AWWW_EXIT"] = "1"
            failed = subprocess.run(
                [str(SWITCHER), "next"],
                check=False,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual((active / "wallpaper").resolve(), before_wallpaper)
            self.assertEqual(active.resolve(), before_theme)

            environment["HYPRLAND_DOTS_TEST_AWWW_EXIT"] = "0"
            subprocess.run(
                [str(SWITCHER), "next"],
                check=True,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(
                (active / "wallpaper").resolve(),
                (root / "data/hyprland-dots/wallpapers/reze.jpg").resolve(),
            )
            self.assertEqual(
                (active / "current-theme").read_text(encoding="utf-8").strip(),
                "reze",
            )


if __name__ == "__main__":
    unittest.main()
