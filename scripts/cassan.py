#!/usr/bin/env python3
"""Safely deploy, inspect, back up, and restore Cassan configuration files.

The configuration is copied rather than symlinked.  Every destination is
managed individually so Cassan never replaces an application directory or
silently overwrites an unrelated file.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


SCHEMA = 1
REPO_DIR = Path(__file__).resolve().parent.parent
STATE_DIRECTORY = "cassan"
BACKUP_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9@._+:-]*$")
MUTATING_ACTIONS = frozenset(("create", "update", "replace", "remove"))
STATE_ACTIONS = frozenset(("adopt", "forget", "reconcile"))
TRANSACTIONAL_ACTIONS = MUTATING_ACTIONS | STATE_ACTIONS
PACMAN_PATH = Path("/usr/bin/pacman")
SUDO_PATH = Path("/usr/bin/sudo")


class CassanError(Exception):
    """Base class for a user-facing failure with a stable exit code."""

    exit_code = 3


class PreflightError(CassanError):
    """The host, repository, or state is unsafe to use."""

    exit_code = 3


class ConflictError(CassanError):
    """A destination contains data Cassan will not overwrite by default."""

    exit_code = 4


class PackageError(CassanError):
    """Package inspection or installation failed."""

    exit_code = 5


class TransactionError(CassanError):
    """A deployment or restore transaction failed."""

    exit_code = 6


@dataclasses.dataclass(frozen=True)
class Deployment:
    """One repository file and its logical destination."""

    source: str
    root: str
    relative: str
    mode: int = 0o644
    component: str = "core"

    @property
    def key(self) -> str:
        return "%s:%s" % (self.root, self.relative)


# Keep this list explicit.  It is the complete ownership boundary of Cassan's
# current runtime deployment and must be reviewed whenever files are added.
# Assets and generated themes come first, followed by imported modules and
# styles.  Application entrypoints come later, and Hyprland's entrypoint is
# deliberately last so a transaction never exposes it before its dependencies.
DEPLOYMENTS: Tuple[Deployment, ...] = (
    Deployment(
        "assets/nighthowler/wallpaper.jpg",
        "home_config",
        "cassan/assets/nighthowler/wallpaper.jpg",
    ),
    Deployment("hypr/theme.lua", "xdg_config", "hypr/theme.lua"),
    Deployment("kitty/theme.conf", "xdg_config", "kitty/theme.conf"),
    Deployment("waybar/theme.css", "xdg_config", "waybar/theme.css"),
    Deployment("wofi/theme.css", "xdg_config", "wofi/theme.css"),
    Deployment("swaync/theme.css", "xdg_config", "swaync/theme.css"),
    Deployment("yazi/theme.toml", "xdg_config", "yazi/theme.toml"),
    Deployment(
        "btop/themes/nighthowler.theme",
        "xdg_config",
        "btop/themes/nighthowler.theme",
    ),
    Deployment(
        "cava/themes/nighthowler",
        "xdg_config",
        "cava/themes/nighthowler",
        component="cava",
    ),
    Deployment("hypr/hyprpaper.conf", "xdg_config", "hypr/hyprpaper.conf"),
    Deployment("hypr/hyprlock.conf", "xdg_config", "hypr/hyprlock.conf"),
    Deployment("hypr/environment.lua", "xdg_config", "hypr/environment.lua"),
    Deployment("hypr/monitor.lua", "xdg_config", "hypr/monitor.lua"),
    Deployment("hypr/looknfeel.lua", "xdg_config", "hypr/looknfeel.lua"),
    Deployment("hypr/input.lua", "xdg_config", "hypr/input.lua"),
    Deployment("hypr/animation.lua", "xdg_config", "hypr/animation.lua"),
    Deployment("hypr/rules.lua", "xdg_config", "hypr/rules.lua"),
    Deployment("hypr/startup.lua", "xdg_config", "hypr/startup.lua"),
    Deployment("hypr/bind.lua", "xdg_config", "hypr/bind.lua"),
    Deployment("hypr/hypridle.conf", "xdg_config", "hypr/hypridle.conf"),
    Deployment("kitty/kitty.conf", "xdg_config", "kitty/kitty.conf"),
    Deployment("btop/btop.conf", "xdg_config", "btop/btop.conf"),
    Deployment("waybar/style.css", "xdg_config", "waybar/style.css"),
    Deployment("waybar/config.jsonc", "xdg_config", "waybar/config.jsonc"),
    Deployment("wofi/style.css", "xdg_config", "wofi/style.css"),
    Deployment("wofi/config", "xdg_config", "wofi/config"),
    Deployment(
        "networkmanager-dmenu/config.ini",
        "xdg_config",
        "networkmanager-dmenu/config.ini",
    ),
    Deployment("swaync/style.css", "xdg_config", "swaync/style.css"),
    Deployment("swaync/config.json", "xdg_config", "swaync/config.json"),
    Deployment("yazi/yazi.toml", "xdg_config", "yazi/yazi.toml"),
    Deployment("cava/config", "xdg_config", "cava/config", component="cava"),
    Deployment(
        "fastfetch/config.jsonc",
        "xdg_config",
        "fastfetch/config.jsonc",
        component="fastfetch",
    ),
    Deployment("hypr/hyprland.lua", "xdg_config", "hypr/hyprland.lua"),
)

if len(DEPLOYMENTS) != 33:  # pragma: no cover - protects future edits at import time
    raise RuntimeError("the Cassan runtime deployment must contain exactly 33 files")

OPTIONAL_DEPLOYMENT_COMPONENTS = ("cava", "fastfetch")

# All 33 configuration files are always deployed so ownership never changes
# merely because an accessory package was omitted.  The Cava and Fastfetch
# files are inert until their corresponding executables are installed.  Package
# selection is therefore modular without making deployment state ambiguous.
CORE_PACKAGE_NAMES = frozenset(
    (
        "hyprland",
        "waybar",
        "kitty",
        "wofi",
        "swaync",
        "hyprpaper",
        "hyprlock",
        "hypridle",
        "xdg-desktop-portal-hyprland",
        "hyprpolkitagent",
        "git",
        "python",
        "less",
        "yazi",
        "btop",
        "grim",
        "slurp",
        "swappy",
        "brightnessctl",
        "playerctl",
        "networkmanager-dmenu",
        "nm-connection-editor",
        "pavucontrol",
        "libnotify",
        "networkmanager",
        "pipewire",
        "pipewire-pulse",
        "wireplumber",
        "bluez",
        "bluez-utils",
        "blueman",
        "ttf-iosevka-nerd",
    )
)
OPTIONAL_PACKAGE_GROUPS = {
    "apps": frozenset(("firefox", "discord", "spotify-launcher")),
    "cava": frozenset(("cava",)),
    "fastfetch": frozenset(("fastfetch",)),
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def new_backup_id() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "%s-%s" % (stamp, secrets.token_hex(4))


def process_identity(pid: int) -> Optional[str]:
    """Return a Linux boot/process-start identity when procfs is available."""

    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="ascii"
        ).strip()
        stat_line = Path("/proc/%d/stat" % pid).read_text(encoding="ascii")
        closing_parenthesis = stat_line.rfind(")")
        if closing_parenthesis < 0:
            return None
        # Fields after comm begin with process state (field 3); starttime is
        # field 22, therefore index 19 in this post-comm list.
        fields = stat_line[closing_parenthesis + 2 :].split()
        start_time = fields[19]
    except (OSError, IndexError, UnicodeError):
        return None
    return "%s:%s" % (boot_id, start_time)


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def safe_relative(value: str) -> Path:
    """Return a normalized relative path or reject unsafe state data."""

    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise PreflightError("unsafe empty or control-character path in deployment state")
    path = Path(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise PreflightError("unsafe relative path: %s" % value)
    return path


def canonical_root(raw: str, label: str) -> Path:
    if not raw:
        raise PreflightError("%s is empty" % label)
    lexical = Path(raw)
    if not lexical.is_absolute():
        raise PreflightError("%s must be an absolute path" % label)
    if ".." in lexical.parts:
        raise PreflightError("%s must not contain '..'" % label)
    resolved = lexical.resolve(strict=False)
    if resolved == Path("/"):
        raise PreflightError("%s must not resolve to the filesystem root" % label)
    return resolved


ROOT_IDENTITY_KEYS = ("xdg_config", "home_config", "state")


def validate_root_identity(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(ROOT_IDENTITY_KEYS):
        raise PreflightError("Cassan state has no valid deployment-root identity")
    normalized: Dict[str, str] = {}
    for key in ROOT_IDENTITY_KEYS:
        raw = value.get(key)
        if not isinstance(raw, str):
            raise PreflightError("invalid %s deployment root identity" % key)
        normalized[key] = str(canonical_root(raw, "%s deployment root" % key))
    return normalized


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


@dataclasses.dataclass(frozen=True)
class Roots:
    home: Path
    xdg_config: Path
    home_config: Path
    state: Path

    @classmethod
    def from_environ(cls, environ: Optional[Mapping[str, str]] = None) -> "Roots":
        values = os.environ if environ is None else environ
        home_value = values.get("HOME", "")
        home = canonical_root(home_value, "HOME")

        config_value = values.get("XDG_CONFIG_HOME")
        if config_value:
            xdg_config = canonical_root(config_value, "XDG_CONFIG_HOME")
        else:
            xdg_config = (home / ".config").resolve(strict=False)

        state_value = values.get("XDG_STATE_HOME")
        if state_value:
            state_base = canonical_root(state_value, "XDG_STATE_HOME")
        else:
            state_base = (home / ".local" / "state").resolve(strict=False)

        home_config = (home / ".config").resolve(strict=False)
        state = state_base / STATE_DIRECTORY
        if xdg_config == home:
            raise PreflightError("XDG_CONFIG_HOME must not be the home directory itself")
        if state_base == home:
            raise PreflightError("XDG_STATE_HOME must not be the home directory itself")
        for target in set((xdg_config, home_config)):
            if is_relative_to(state, target) or is_relative_to(target, state):
                raise PreflightError(
                    "Cassan's state directory must not overlap a configuration root"
                )
        return cls(home, xdg_config, home_config, state)

    def by_name(self, name: str) -> Path:
        if name == "xdg_config":
            return self.xdg_config
        if name == "home_config":
            return self.home_config
        raise PreflightError("unknown deployment root in state: %s" % name)


def ensure_directory_chain(root: Path, relative_parent: Path, create: bool) -> None:
    """Reject symlink traversal below a trusted canonical root."""

    if root.exists():
        root_stat = os.lstat(str(root))
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ConflictError("configuration root is not a directory: %s" % root)
        if create:
            fsync_directory(root.parent)
    elif create:
        durable_mkdir_chain(root, 0o755)

    cursor = root
    for part in relative_parent.parts:
        cursor = cursor / part
        if os.path.lexists(str(cursor)):
            item_stat = os.lstat(str(cursor))
            if stat.S_ISLNK(item_stat.st_mode):
                raise ConflictError("refusing to traverse destination symlink: %s" % cursor)
            if not stat.S_ISDIR(item_stat.st_mode):
                raise ConflictError("destination parent is not a directory: %s" % cursor)
            if create:
                fsync_directory(cursor.parent)
        elif create:
            os.mkdir(str(cursor), 0o755)
            fsync_directory(cursor.parent)


def durable_mkdir_chain(path: Path, mode: int) -> None:
    """Create every missing directory and durably record each parent entry."""

    if not path.is_absolute():
        raise PreflightError("directory creation target must be absolute: %s" % path)
    missing: List[Path] = []
    cursor = path
    while not os.path.lexists(str(cursor)):
        parent = cursor.parent
        if parent == cursor:
            raise PreflightError("cannot find an existing parent for %s" % path)
        missing.append(cursor)
        cursor = parent
    existing_stat = os.lstat(str(cursor))
    if stat.S_ISLNK(existing_stat.st_mode) or not stat.S_ISDIR(existing_stat.st_mode):
        raise PreflightError("directory parent is not a real directory: %s" % cursor)
    if cursor.parent != cursor:
        fsync_directory(cursor.parent)

    for directory in reversed(missing):
        try:
            os.mkdir(str(directory), mode)
        except FileExistsError:
            directory_stat = os.lstat(str(directory))
            if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(
                directory_stat.st_mode
            ):
                raise PreflightError(
                    "concurrently created path is not a real directory: %s"
                    % directory
                )
        fsync_directory(directory.parent)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclasses.dataclass(frozen=True)
class Snapshot:
    kind: str
    sha256: Optional[str] = None
    mode: Optional[int] = None

    @property
    def exists(self) -> bool:
        return self.kind != "missing"

    def to_json(self, backup: Optional[str] = None) -> Dict[str, Any]:
        value: Dict[str, Any] = {"exists": self.exists}
        if self.exists:
            value.update({"sha256": self.sha256, "mode": self.mode})
            if backup is not None:
                value["backup"] = backup
        return value


MISSING = Snapshot("missing")


def inspect_path(path: Path) -> Snapshot:
    if not os.path.lexists(str(path)):
        return MISSING
    item_stat = os.lstat(str(path))
    mode = stat.S_IMODE(item_stat.st_mode)
    if stat.S_ISLNK(item_stat.st_mode):
        return Snapshot("symlink", mode=mode)
    if not stat.S_ISREG(item_stat.st_mode):
        if stat.S_ISDIR(item_stat.st_mode):
            return Snapshot("directory", mode=mode)
        return Snapshot("special", mode=mode)
    return Snapshot("file", file_sha256(path), mode)


def snapshot_matches(left: Snapshot, right: Snapshot) -> bool:
    if left.kind != right.kind:
        return False
    if left.kind == "missing":
        return True
    return left.sha256 == right.sha256 and left.mode == right.mode


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        unsupported = (errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", -1))
        if sys.platform.startswith("linux") or error.errno not in unsupported:
            raise
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            unsupported = (
                errno.EINVAL,
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", -1),
            )
            if sys.platform.startswith("linux") or error.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes, mode: int) -> None:
    if not os.path.lexists(str(path.parent)):
        raise OSError("atomic write parent does not exist: %s" % path.parent)
    parent_stat = os.lstat(str(path.parent))
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise OSError("atomic write parent is not a real directory: %s" % path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s.cassan-" % path.name, dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fchmod(target.fileno(), mode)
            os.fsync(target.fileno())
        os.replace(str(temporary), str(path))
        fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_copy(source: Path, destination: Path, mode: int) -> None:
    with source.open("rb") as handle:
        atomic_write_bytes(destination, handle.read(), mode)


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write_json(path: Path, value: Mapping[str, Any], mode: int = 0o600) -> None:
    atomic_write_bytes(path, json_bytes(value), mode)


def state_entry_snapshot(entry: Mapping[str, Any]) -> Snapshot:
    checksum = entry.get("sha256")
    mode = entry.get("mode")
    if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
        raise PreflightError("invalid checksum in Cassan deployment state")
    if not isinstance(mode, int) or isinstance(mode, bool) or not 0 <= mode <= 0o777:
        raise PreflightError("invalid file mode in Cassan deployment state")
    return Snapshot("file", checksum, mode)


def validate_state_document(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise PreflightError("unsupported or invalid Cassan deployment state")
    files = value.get("files")
    if not isinstance(files, list):
        raise PreflightError("Cassan deployment state has no valid file list")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise PreflightError("invalid file entry in Cassan deployment state")
        root = entry.get("root")
        relative = entry.get("relative")
        if root not in ("xdg_config", "home_config") or not isinstance(relative, str):
            raise PreflightError("invalid destination in Cassan deployment state")
        safe_relative(relative)
        key = "%s:%s" % (root, relative)
        if key in seen:
            raise PreflightError("duplicate destination in Cassan deployment state: %s" % key)
        seen.add(key)
        state_entry_snapshot(entry)
    validate_root_identity(value.get("roots"))
    transaction_id = value.get("transaction_id")
    if transaction_id is not None and not (
        isinstance(transaction_id, str) and BACKUP_ID_RE.fullmatch(transaction_id)
    ):
        raise PreflightError("invalid transaction identifier in Cassan deployment state")
    restored_from = value.get("restored_from")
    if restored_from is not None and not (
        isinstance(restored_from, str) and BACKUP_ID_RE.fullmatch(restored_from)
    ):
        raise PreflightError("invalid restore lineage in Cassan deployment state")
    return value


def load_json_document(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, ValueError) as error:
        raise PreflightError("cannot read %s: %s" % (path, error)) from error


@dataclasses.dataclass
class PlanItem:
    root: str
    relative: str
    action: str
    before: Snapshot
    after: Snapshot
    source: Optional[Path] = None
    detail: str = ""

    @property
    def key(self) -> str:
        return "%s:%s" % (self.root, self.relative)


@dataclasses.dataclass
class Plan:
    items: List[PlanItem]
    state_change: bool = False
    state_fingerprint: Optional[str] = None
    state_snapshot: Snapshot = MISSING
    replace: bool = False
    kind: str = "deploy"
    backup_id: Optional[str] = None
    target_state_fingerprint: Optional[str] = None
    target_state_snapshot: Snapshot = MISSING
    recovery_status: Optional[str] = None

    @property
    def conflicts(self) -> List[PlanItem]:
        return [item for item in self.items if item.action == "conflict"]

    @property
    def mutations(self) -> List[PlanItem]:
        return [item for item in self.items if item.action in MUTATING_ACTIONS]

    @property
    def state_changes(self) -> List[PlanItem]:
        return [item for item in self.items if item.action in STATE_ACTIONS]

    @property
    def transactional(self) -> List[PlanItem]:
        return [item for item in self.items if item.action in TRANSACTIONAL_ACTIONS]

    @property
    def drift(self) -> bool:
        return self.state_change or any(item.action != "unchanged" for item in self.items)


class Deployer:
    """Plan and execute Cassan's per-user configuration transactions."""

    def __init__(
        self,
        repo: Path = REPO_DIR,
        roots: Optional[Roots] = None,
        deployments: Sequence[Deployment] = DEPLOYMENTS,
        validate_repository: bool = True,
        euid: Optional[int] = None,
    ) -> None:
        self.repo = repo.resolve(strict=False)
        self.roots = Roots.from_environ() if roots is None else roots
        self.deployments = tuple(deployments)
        self.validate_repository_enabled = validate_repository
        self.euid = os.geteuid() if euid is None else euid
        self.state_file = self.roots.state / "manifest.json"
        self.backups_directory = self.roots.state / "backups"
        self._validate_deployment_manifest()

    def root_identity(self) -> Dict[str, str]:
        return {
            "xdg_config": str(self.roots.xdg_config.resolve(strict=False)),
            "home_config": str(self.roots.home_config.resolve(strict=False)),
            "state": str(self.roots.state.resolve(strict=False)),
        }

    def _require_root_identity(self, value: Any, context: str) -> None:
        recorded = validate_root_identity(value)
        if recorded != self.root_identity():
            raise PreflightError(
                "%s was created for different deployment roots" % context
            )

    def _validate_deployment_manifest(self) -> None:
        keys = set()
        sources = set()
        for deployment in self.deployments:
            if deployment.component not in ("core",) + OPTIONAL_DEPLOYMENT_COMPONENTS:
                raise PreflightError(
                    "unknown deployment component: %s" % deployment.component
                )
            if deployment.root not in ("xdg_config", "home_config"):
                raise PreflightError("unknown deployment root: %s" % deployment.root)
            safe_relative(deployment.source)
            safe_relative(deployment.relative)
            if deployment.key in keys:
                raise PreflightError("duplicate deployment destination: %s" % deployment.key)
            if deployment.source in sources:
                raise PreflightError("duplicate deployment source: %s" % deployment.source)
            keys.add(deployment.key)
            sources.add(deployment.source)
            if deployment.mode != 0o644:
                raise PreflightError("runtime configuration files must install with mode 0644")

    def source_path(self, deployment: Deployment) -> Path:
        relative = safe_relative(deployment.source)
        source = self.repo / relative
        if not is_relative_to(source, self.repo):
            raise PreflightError("deployment source escapes the repository")
        cursor = self.repo
        for part in relative.parts[:-1]:
            cursor = cursor / part
            if not os.path.lexists(str(cursor)):
                raise PreflightError("missing deployment source parent: %s" % cursor)
            cursor_stat = os.lstat(str(cursor))
            if stat.S_ISLNK(cursor_stat.st_mode):
                raise PreflightError(
                    "deployment source traverses a symlinked directory: %s" % cursor
                )
            if not stat.S_ISDIR(cursor_stat.st_mode):
                raise PreflightError("deployment source parent is not a directory: %s" % cursor)
        try:
            resolved = source.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise PreflightError(
                "cannot strictly resolve deployment source %s: %s"
                % (deployment.source, error)
            ) from error
        if not is_relative_to(resolved, self.repo):
            raise PreflightError(
                "resolved deployment source escapes the repository: %s"
                % deployment.source
            )
        source_stat = os.lstat(str(source))
        if stat.S_ISLNK(source_stat.st_mode):
            raise PreflightError(
                "deployment source must not be a symlink: %s" % deployment.source
            )
        return resolved

    def destination(self, root: str, relative: str) -> Path:
        base = self.roots.by_name(root)
        destination = base / safe_relative(relative)
        if not is_relative_to(destination, base):
            raise PreflightError("deployment destination escapes its configuration root")
        return destination

    def validate_sources(self) -> None:
        for deployment in self.deployments:
            source = self.source_path(deployment)
            if not os.path.lexists(str(source)):
                raise PreflightError("missing deployment source: %s" % deployment.source)
            source_stat = os.lstat(str(source))
            if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
                raise PreflightError(
                    "deployment source must be a regular, non-symlink file: %s"
                    % deployment.source
                )
            destination = self.destination(deployment.root, deployment.relative)
            if source.resolve(strict=False) == destination.resolve(strict=False):
                raise PreflightError(
                    "repository source and deployment destination are identical: %s"
                    % deployment.source
                )

    def validate_repo(self, allow_dirty: bool) -> None:
        self.validate_sources()
        if not self.validate_repository_enabled:
            return
        if sys.version_info < (3, 9):  # pragma: no cover - cannot run on older Python
            raise PreflightError("Cassan requires Python 3.9 or newer")
        check_script = self.repo / "scripts" / "check.sh"
        if not check_script.is_file():
            raise PreflightError("missing repository validator: scripts/check.sh")
        result = subprocess.run(
            [str(check_script)],
            cwd=str(self.repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stdout.strip()
            raise PreflightError("repository validation failed:\n%s" % detail)
        git = shutil.which("git")
        if git is None:
            raise PreflightError("git is required to verify the deployment source")
        status = subprocess.run(
            [git, "-C", str(self.repo), "status", "--porcelain", "--untracked-files=normal"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if status.returncode != 0:
            raise PreflightError("cannot inspect repository state: %s" % status.stderr.strip())
        if status.stdout.strip() and not allow_dirty:
            raise PreflightError(
                "repository has uncommitted files; review them or pass --allow-dirty"
            )

    def source_information(self) -> Dict[str, Any]:
        information: Dict[str, Any] = {"repository": str(self.repo)}
        git = shutil.which("git")
        if git is None:
            information.update({"commit": None, "branch": None, "dirty": None})
            return information

        def git_output(arguments: Sequence[str]) -> Optional[str]:
            result = subprocess.run(
                [git, "-C", str(self.repo)] + list(arguments),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else None

        information["commit"] = git_output(("rev-parse", "HEAD"))
        information["branch"] = git_output(("branch", "--show-current"))
        dirty = git_output(("status", "--porcelain", "--untracked-files=normal"))
        information["dirty"] = None if dirty is None else bool(dirty)
        return information

    def _validate_state_root_for_read(self) -> None:
        if not os.path.lexists(str(self.roots.state)):
            return
        state_stat = os.lstat(str(self.roots.state))
        if stat.S_ISLNK(state_stat.st_mode) or not stat.S_ISDIR(state_stat.st_mode):
            raise PreflightError("Cassan's state path must be a real directory")

    def load_state_observation(self) -> Tuple[Optional[Dict[str, Any]], Snapshot]:
        self._validate_state_root_for_read()
        if not os.path.lexists(str(self.state_file)):
            return None, MISSING
        path_stat = os.lstat(str(self.state_file))
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise PreflightError("Cassan deployment state must be a regular file")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(str(self.state_file), flags)
            descriptor_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_dev != path_stat.st_dev
                or descriptor_stat.st_ino != path_stat.st_ino
            ):
                os.close(descriptor)
                raise PreflightError("Cassan deployment state changed while opening")
            with os.fdopen(descriptor, "rb") as source:
                data = source.read()
            final_path_stat = os.lstat(str(self.state_file))
            if (
                final_path_stat.st_dev != descriptor_stat.st_dev
                or final_path_stat.st_ino != descriptor_stat.st_ino
            ):
                raise PreflightError("Cassan deployment state changed while reading")
        except OSError as error:
            raise PreflightError("cannot read %s: %s" % (self.state_file, error)) from error
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise PreflightError("cannot parse %s: %s" % (self.state_file, error)) from error
        observation = Snapshot(
            "file",
            hashlib.sha256(data).hexdigest(),
            stat.S_IMODE(descriptor_stat.st_mode),
        )
        validated = validate_state_document(value)
        self._require_root_identity(validated.get("roots"), "deployment state")
        return validated, observation

    def load_state_snapshot(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        state, observation = self.load_state_observation()
        return state, observation.sha256 if observation.kind == "file" else None

    def load_state(self) -> Optional[Dict[str, Any]]:
        state, _observation = self.load_state_observation()
        return state

    @staticmethod
    def state_entries(state_document: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        if state_document is None:
            return {}
        return {
            "%s:%s" % (entry["root"], entry["relative"]): dict(entry)
            for entry in state_document["files"]
        }

    def plan(self, replace: bool = False) -> Plan:
        self.validate_sources()
        previous_state, state_observation = self.load_state_observation()
        state_fingerprint = (
            state_observation.sha256 if state_observation.kind == "file" else None
        )
        previous = self.state_entries(previous_state)
        desired_keys = set()
        items: List[PlanItem] = []

        for deployment in self.deployments:
            desired_keys.add(deployment.key)
            source = self.source_path(deployment)
            desired = Snapshot("file", file_sha256(source), deployment.mode)
            destination = self.destination(deployment.root, deployment.relative)
            ensure_directory_chain(
                self.roots.by_name(deployment.root),
                safe_relative(deployment.relative).parent,
                create=False,
            )
            current = inspect_path(destination)
            previous_entry = previous.get(deployment.key)

            if current.kind in ("symlink", "directory", "special"):
                items.append(
                    PlanItem(
                        deployment.root,
                        deployment.relative,
                        "conflict",
                        current,
                        desired,
                        source,
                        "destination is a %s" % current.kind,
                    )
                )
            elif current.kind == "missing":
                items.append(
                    PlanItem(
                        deployment.root,
                        deployment.relative,
                        "create",
                        current,
                        desired,
                        source,
                    )
                )
            elif snapshot_matches(current, desired):
                if previous_entry is None:
                    action = "adopt"
                    detail = "record ownership of matching destination"
                elif snapshot_matches(state_entry_snapshot(previous_entry), desired):
                    action = "unchanged"
                    detail = ""
                else:
                    action = "reconcile"
                    detail = "stored ownership snapshot differs from desired state"
                items.append(
                    PlanItem(
                        deployment.root,
                        deployment.relative,
                        action,
                        current,
                        desired,
                        source,
                        detail,
                    )
                )
            elif previous_entry is not None and snapshot_matches(
                current, state_entry_snapshot(previous_entry)
            ):
                items.append(
                    PlanItem(
                        deployment.root,
                        deployment.relative,
                        "update",
                        current,
                        desired,
                        source,
                    )
                )
            else:
                action = "replace" if replace else "conflict"
                detail = (
                    "managed destination was modified locally"
                    if previous_entry is not None
                    else "unmanaged destination already exists"
                )
                items.append(
                    PlanItem(
                        deployment.root,
                        deployment.relative,
                        action,
                        current,
                        desired,
                        source,
                        detail,
                    )
                )

        for key, previous_entry in previous.items():
            if key in desired_keys:
                continue
            root = previous_entry["root"]
            relative = previous_entry["relative"]
            destination = self.destination(root, relative)
            ensure_directory_chain(
                self.roots.by_name(root), safe_relative(relative).parent, create=False
            )
            current = inspect_path(destination)
            previous_snapshot = state_entry_snapshot(previous_entry)
            if current.kind == "missing":
                items.append(PlanItem(root, relative, "forget", current, MISSING))
            elif current.kind != "file":
                items.append(
                    PlanItem(
                        root,
                        relative,
                        "conflict",
                        current,
                        MISSING,
                        detail="stale managed destination is a %s" % current.kind,
                    )
                )
            elif snapshot_matches(current, previous_snapshot) or replace:
                detail = "remove stale managed file"
                if not snapshot_matches(current, previous_snapshot):
                    detail += " after --replace"
                items.append(PlanItem(root, relative, "remove", current, MISSING, detail=detail))
            else:
                items.append(
                    PlanItem(
                        root,
                        relative,
                        "conflict",
                        current,
                        MISSING,
                        detail="stale managed destination was modified locally",
                    )
                )

        return Plan(
            items,
            state_fingerprint=state_fingerprint,
            state_snapshot=state_observation,
            replace=replace,
            kind="deploy",
        )

    def _ensure_private_state_directories(self) -> None:
        if os.path.lexists(str(self.roots.state)):
            state_stat = os.lstat(str(self.roots.state))
            if stat.S_ISLNK(state_stat.st_mode) or not stat.S_ISDIR(state_stat.st_mode):
                raise PreflightError("Cassan's state path must be a real directory")
            fsync_directory(self.roots.state.parent)
        else:
            durable_mkdir_chain(self.roots.state, 0o700)
        os.chmod(str(self.roots.state), 0o700)
        if os.path.lexists(str(self.backups_directory)):
            backup_stat = os.lstat(str(self.backups_directory))
            if stat.S_ISLNK(backup_stat.st_mode) or not stat.S_ISDIR(backup_stat.st_mode):
                raise PreflightError("Cassan's backup path must be a real directory")
            fsync_directory(self.backups_directory.parent)
        else:
            durable_mkdir_chain(self.backups_directory, 0o700)
        os.chmod(str(self.backups_directory), 0o700)

    @property
    def lock_path(self) -> Path:
        return self.roots.state / "transaction.lock"

    @property
    def active_transaction_path(self) -> Path:
        return self.roots.state / "active-transaction.json"

    def _load_active_transaction(self) -> Optional[Dict[str, Any]]:
        path = self.active_transaction_path
        if not os.path.lexists(str(path)):
            return None
        path_stat = os.lstat(str(path))
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise TransactionError("Cassan's active transaction marker is not a regular file")
        if path_stat.st_uid != os.geteuid() or stat.S_IMODE(path_stat.st_mode) & 0o077:
            raise TransactionError("Cassan's active transaction marker has unsafe ownership or mode")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(str(path), flags)
            descriptor_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_dev != path_stat.st_dev
                or descriptor_stat.st_ino != path_stat.st_ino
            ):
                os.close(descriptor)
                raise TransactionError(
                    "Cassan's active transaction marker changed while opening"
                )
            with os.fdopen(descriptor, "rb") as source:
                raw = source.read()
            final_path_stat = os.lstat(str(path))
            if (
                final_path_stat.st_dev != descriptor_stat.st_dev
                or final_path_stat.st_ino != descriptor_stat.st_ino
            ):
                raise TransactionError(
                    "Cassan's active transaction marker changed while reading"
                )
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise TransactionError("Cassan's active transaction marker is corrupt") from error
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            raise TransactionError("Cassan's active transaction marker is invalid")
        status_value = value.get("status")
        if status_value != "active":
            raise TransactionError("Cassan's active transaction marker has an unknown status")
        operation_id = value.get("operation_id")
        pid = value.get("pid")
        uid = value.get("uid")
        identity = value.get("process_identity")
        if not isinstance(operation_id, str) or not BACKUP_ID_RE.fullmatch(operation_id):
            raise TransactionError("Cassan's active transaction marker has an invalid operation id")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise TransactionError("Cassan's active transaction marker has an invalid process id")
        if not isinstance(uid, int) or isinstance(uid, bool) or uid < 0:
            raise TransactionError("Cassan's active transaction marker has an invalid owner id")
        if identity is not None and not isinstance(identity, str):
            raise TransactionError("Cassan's active transaction marker has an invalid process identity")
        self._require_root_identity(
            value.get("roots"), "active transaction marker"
        )
        return value

    def _clear_active_transaction(self) -> None:
        path = self.active_transaction_path
        if not os.path.lexists(str(path)):
            return
        path_stat = os.lstat(str(path))
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise TransactionError("refusing to remove an unsafe active transaction marker")
        if path_stat.st_uid != os.geteuid():
            raise TransactionError("refusing to remove a foreign active transaction marker")
        path.unlink()
        fsync_directory(path.parent)

    def _open_lock_file(self, create: bool) -> int:
        flags = os.O_RDWR
        if create:
            flags |= os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(str(self.lock_path), flags, 0o600)
        except FileNotFoundError as error:
            raise PreflightError("no interrupted Cassan transaction was found") from error
        except OSError as error:
            raise TransactionError("cannot open Cassan's transaction lock: %s" % error) from error
        try:
            lock_stat = os.fstat(descriptor)
            if not stat.S_ISREG(lock_stat.st_mode):
                raise TransactionError("Cassan's transaction lock must be a regular file")
            if lock_stat.st_uid != os.geteuid():
                raise TransactionError("Cassan's transaction lock has an unexpected owner")
            if stat.S_IMODE(lock_stat.st_mode) & 0o077:
                raise TransactionError("Cassan's transaction lock must have mode 0600")
            if create:
                fsync_directory(self.lock_path.parent)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _flock_exclusive(descriptor: int) -> None:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise TransactionError("another Cassan transaction is active") from error
            raise TransactionError("cannot lock Cassan's transaction state: %s" % error) from error

    def _acquire_transaction_lock(self, operation_id: str) -> int:
        descriptor = self._open_lock_file(create=True)
        try:
            self._flock_exclusive(descriptor)
            existing = self._load_active_transaction()
            if existing is not None:
                raise TransactionError(
                    "an interrupted Cassan transaction requires `cassan.py recover --apply`"
                )
            atomic_write_json(
                self.active_transaction_path,
                {
                    "schema": SCHEMA,
                    "status": "active",
                    "operation_id": operation_id,
                    "pid": os.getpid(),
                    "uid": self.euid,
                    "process_identity": process_identity(os.getpid()),
                    "created_at": utc_now(),
                    "roots": self.root_identity(),
                },
            )
        except BaseException:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
            raise
        return descriptor

    def _acquire_recovery_lock(self) -> Tuple[int, Dict[str, Any]]:
        descriptor = self._open_lock_file(create=False)
        try:
            self._flock_exclusive(descriptor)
            value = self._load_active_transaction()
            if value is None:
                raise PreflightError("no interrupted Cassan transaction was found")
            if value.get("uid") != self.euid:
                raise TransactionError(
                    "interrupted transaction belongs to a different effective user"
                )
            pid = value["pid"]
            if process_is_alive(pid):
                stored_identity = value.get("process_identity")
                current_identity = process_identity(pid)
                if (
                    stored_identity is None
                    or current_identity is None
                    or stored_identity == current_identity
                ):
                    raise TransactionError(
                        "interrupted transaction's recorded process is still alive"
                    )
            return descriptor, value
        except BaseException:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
            raise

    def _release_transaction_lock(self, descriptor: int, clear: bool) -> None:
        try:
            if clear:
                self._clear_active_transaction()
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _check_race(self, item: PlanItem) -> Path:
        destination = self.destination(item.root, item.relative)
        ensure_directory_chain(
            self.roots.by_name(item.root), safe_relative(item.relative).parent, create=False
        )
        current = inspect_path(destination)
        if not snapshot_matches(current, item.before):
            raise TransactionError("destination changed after planning: %s" % destination)
        return destination

    def _verify_final_target(self, item: PlanItem) -> None:
        destination = self.destination(item.root, item.relative)
        ensure_directory_chain(
            self.roots.by_name(item.root),
            safe_relative(item.relative).parent,
            create=False,
        )
        if not snapshot_matches(inspect_path(destination), item.after):
            raise TransactionError(
                "destination changed before transaction commit: %s" % destination
            )

    def _require_state_snapshot(self, expected: Snapshot) -> None:
        _state, current = self.load_state_observation()
        if not snapshot_matches(current, expected):
            raise TransactionError("Cassan deployment state changed after planning")

    def _verify_plan_snapshot(self, plan: Plan) -> None:
        self._require_state_snapshot(plan.state_snapshot)
        for item in plan.items:
            self._check_race(item)
            if item.source is not None and item.after.kind == "file":
                current_source = inspect_path(item.source)
                if not snapshot_matches(current_source, item.after):
                    raise TransactionError(
                        "source changed after planning: %s" % item.source
                    )

    def desired_state_from_plan(self, plan: Plan) -> Dict[str, Any]:
        planned = {item.key: item for item in plan.items}
        files = []
        for deployment in self.deployments:
            item = planned.get(deployment.key)
            if item is None or item.after.kind != "file":
                raise TransactionError(
                    "deployment plan is missing desired state for %s" % deployment.key
                )
            files.append(
                {
                    "root": deployment.root,
                    "relative": deployment.relative,
                    "sha256": item.after.sha256,
                    "mode": item.after.mode,
                }
            )
        return {
            "schema": SCHEMA,
            "installed_at": utc_now(),
            "transaction_id": None,
            "roots": self.root_identity(),
            "source": self.source_information(),
            "files": files,
        }

    def _operation_requires_recovery(self, operation_id: str) -> bool:
        transaction = self.backups_directory / operation_id / "transaction.json"
        if not os.path.lexists(str(transaction)):
            return False
        try:
            value = load_json_document(transaction)
        except CassanError:
            return True
        return not (
            isinstance(value, dict)
            and value.get("id") == operation_id
            and value.get("status") in ("completed", "rolled-back")
        )

    def _transaction_locked(
        self,
        plan: Plan,
        final_state: Dict[str, Any],
        kind: str,
        backup_id: str,
        restored_from: Optional[str] = None,
    ) -> str:
        items = plan.transactional
        backup_directory = self.backups_directory / backup_id
        staged_directory = backup_directory / "staged"
        stored_directory = backup_directory / "files"
        prior_manifest = backup_directory / "manifest.before.json"
        final_manifest = backup_directory / "manifest.after.json"
        metadata: Dict[str, Any] = {}
        prepared: List[Tuple[PlanItem, Optional[Path], Optional[Path]]] = []
        backup_created = False

        try:
            if os.path.lexists(str(backup_directory)):
                raise TransactionError("transaction backup identifier already exists")
            durable_mkdir_chain(backup_directory, 0o700)
            backup_created = True
            durable_mkdir_chain(staged_directory, 0o700)
            durable_mkdir_chain(stored_directory, 0o700)
            self._verify_plan_snapshot(plan)
            had_manifest = os.path.lexists(str(self.state_file))
            if had_manifest != plan.state_snapshot.exists:
                raise TransactionError("Cassan deployment state changed during preparation")
            if had_manifest:
                state_stat = os.lstat(str(self.state_file))
                if stat.S_ISLNK(state_stat.st_mode) or not stat.S_ISREG(
                    state_stat.st_mode
                ):
                    raise TransactionError(
                        "Cassan deployment state changed into a non-file"
                    )
                prior_mode = (
                    plan.state_snapshot.mode
                    if plan.state_snapshot.mode is not None
                    else 0o600
                )
                atomic_copy(self.state_file, prior_manifest, prior_mode)
                if not snapshot_matches(
                    inspect_path(prior_manifest), plan.state_snapshot
                ):
                    raise TransactionError("could not verify prior deployment state")

            final_state = dict(final_state)
            final_state["transaction_id"] = backup_id
            if restored_from is not None:
                final_state["restored_from"] = restored_from
            atomic_write_json(final_manifest, final_state, 0o600)
            final_manifest_snapshot = inspect_path(final_manifest)

            staged_sources: Dict[str, Path] = {}
            for source_index, observed in enumerate(plan.items):
                if observed.source is None or observed.after.kind != "file":
                    continue
                staged_source = staged_directory / ("source-%03d" % source_index)
                observed_mode = (
                    observed.after.mode
                    if observed.after.mode is not None
                    else 0o644
                )
                atomic_copy(observed.source, staged_source, observed_mode)
                if not snapshot_matches(inspect_path(staged_source), observed.after):
                    raise TransactionError(
                        "source changed while staging: %s" % observed.source
                    )
                staged_sources[observed.key] = staged_source

            metadata = {
                "schema": SCHEMA,
                "id": backup_id,
                "kind": kind,
                "created_at": utc_now(),
                "status": "preparing",
                "source": self.source_information(),
                "roots": self.root_identity(),
                "restored_from": restored_from,
                "had_manifest": had_manifest,
                "manifest_before": plan.state_snapshot.to_json(),
                "manifest_after": final_manifest_snapshot.to_json(),
                "operations": [],
            }
            for index, item in enumerate(items):
                destination = self._check_race(item)
                stage_path: Optional[Path] = None
                backup_path: Optional[Path] = None
                backup_name: Optional[str] = None
                state_only = item.action in STATE_ACTIONS
                if not state_only:
                    if item.after.kind == "file":
                        stage_path = staged_sources.get(item.key)
                        if stage_path is None:
                            raise TransactionError(
                                "transaction has no staged source for %s" % item.key
                            )
                    if item.before.kind == "file":
                        backup_name = "%03d" % index
                        backup_path = stored_directory / backup_name
                        before_mode = (
                            item.before.mode
                            if item.before.mode is not None
                            else 0o644
                        )
                        atomic_copy(destination, backup_path, before_mode)
                        if not snapshot_matches(inspect_path(backup_path), item.before):
                            raise TransactionError(
                                "could not verify backup for %s" % destination
                            )
                metadata["operations"].append(
                    {
                        "root": item.root,
                        "relative": item.relative,
                        "action": item.action,
                        "state_only": state_only,
                        "before": item.before.to_json(backup_name),
                        "after": item.after.to_json(),
                    }
                )
                prepared.append((item, stage_path, backup_path))

            metadata["status"] = "prepared"
            atomic_write_json(backup_directory / "transaction.json", metadata)
        except BaseException as error:
            if backup_created:
                shutil.rmtree(str(backup_directory), ignore_errors=True)
                fsync_directory(self.backups_directory)
            if isinstance(error, TransactionError):
                raise
            raise TransactionError(
                "transaction preparation failed: %s" % error
            ) from error

        applied: List[Tuple[PlanItem, Optional[Path], Optional[Path]]] = []
        manifest_written = False
        try:
            for item, stage_path, backup_path in prepared:
                destination = self._check_race(item)
                if item.action in STATE_ACTIONS:
                    continue
                ensure_directory_chain(
                    self.roots.by_name(item.root),
                    safe_relative(item.relative).parent,
                    create=True,
                )
                # Mark the operation before touching its destination.  If a
                # write succeeds and a following fsync fails, rollback must
                # still restore the original bytes.
                applied.append((item, stage_path, backup_path))
                if item.after.kind == "file":
                    if stage_path is None:
                        raise TransactionError("missing staged file for %s" % item.key)
                    after_mode = (
                        item.after.mode if item.after.mode is not None else 0o644
                    )
                    atomic_copy(stage_path, destination, after_mode)
                elif item.after.kind == "missing":
                    if destination.exists():
                        destination.unlink()
                        fsync_directory(destination.parent)
                else:
                    raise TransactionError("unsupported transaction target for %s" % item.key)

            for observed in plan.items:
                self._verify_final_target(observed)
            self._require_state_snapshot(plan.state_snapshot)
            if not snapshot_matches(inspect_path(final_manifest), final_manifest_snapshot):
                raise TransactionError("staged final deployment state changed")
            atomic_copy(final_manifest, self.state_file, 0o600)
            manifest_written = True
            metadata["status"] = "completed"
            atomic_write_json(backup_directory / "transaction.json", metadata)
            shutil.rmtree(str(staged_directory), ignore_errors=True)
            return backup_id
        except BaseException as error:
            rollback_errors = []
            for item, _stage_path, backup_path in reversed(applied):
                destination = self.destination(item.root, item.relative)
                try:
                    ensure_directory_chain(
                        self.roots.by_name(item.root),
                        safe_relative(item.relative).parent,
                        create=True,
                    )
                    current = inspect_path(destination)
                    if snapshot_matches(current, item.before):
                        continue
                    if not snapshot_matches(current, item.after):
                        raise TransactionError(
                            "rollback target has an unknown concurrent change: %s"
                            % destination
                        )
                    if item.before.kind == "file":
                        if backup_path is None:
                            raise TransactionError("missing rollback backup for %s" % item.key)
                        before_mode = (
                            item.before.mode
                            if item.before.mode is not None
                            else 0o644
                        )
                        atomic_copy(backup_path, destination, before_mode)
                    elif os.path.lexists(str(destination)):
                        destination.unlink()
                        fsync_directory(destination.parent)
                except BaseException as rollback_error:  # pragma: no cover - rare I/O failure
                    rollback_errors.append("%s: %s" % (item.key, rollback_error))

            try:
                _current_state, current_observation = self.load_state_observation()
                if manifest_written:
                    if not snapshot_matches(
                        current_observation, final_manifest_snapshot
                    ):
                        raise TransactionError(
                            "deployment state differs from the exact transaction result"
                        )
                    if prior_manifest.exists():
                        prior_mode = (
                            plan.state_snapshot.mode
                            if plan.state_snapshot.mode is not None
                            else 0o600
                        )
                        atomic_copy(prior_manifest, self.state_file, prior_mode)
                    elif os.path.lexists(str(self.state_file)):
                        self.state_file.unlink()
                        fsync_directory(self.state_file.parent)
                elif not snapshot_matches(
                    current_observation, plan.state_snapshot
                ):
                    raise TransactionError(
                        "deployment state changed concurrently before rollback"
                    )
            except BaseException as rollback_error:  # pragma: no cover - rare I/O failure
                rollback_errors.append("manifest: %s" % rollback_error)

            metadata["status"] = "rollback-failed" if rollback_errors else "rolled-back"
            metadata["error"] = str(error)
            metadata["rollback_errors"] = rollback_errors
            try:
                atomic_write_json(backup_directory / "transaction.json", metadata)
            except OSError:
                pass
            shutil.rmtree(str(staged_directory), ignore_errors=True)
            detail = "transaction failed and was rolled back: %s" % error
            if rollback_errors:
                detail += "; rollback also failed: %s" % "; ".join(rollback_errors)
            raise TransactionError(detail) from error

    def apply(self, plan: Plan) -> Optional[str]:
        if plan.conflicts:
            raise ConflictError("deployment contains unresolved destination conflicts")
        if plan.kind != "deploy":
            raise TransactionError("apply received a non-deployment plan")
        if self.euid == 0:
            raise PreflightError("do not run Cassan's per-user deployment as root")
        operation_id = new_backup_id()
        descriptor: Optional[int] = None
        clear_lock = True
        try:
            try:
                self._ensure_private_state_directories()
                descriptor = self._acquire_transaction_lock(operation_id)
            except CassanError:
                raise
            except OSError as error:
                raise TransactionError("transaction setup failed: %s" % error) from error

            fresh = self.plan(plan.replace)
            if fresh != plan:
                raise TransactionError(
                    "deployment changed after review; generate and review a new plan"
                )
            self._verify_plan_snapshot(fresh)
            if fresh.conflicts:
                raise ConflictError("deployment contains unresolved destination conflicts")
            if not fresh.transactional:
                return None
            desired = self.desired_state_from_plan(fresh)
            try:
                return self._transaction_locked(
                    fresh, desired, "apply", operation_id
                )
            except BaseException:
                clear_lock = not self._operation_requires_recovery(operation_id)
                raise
        finally:
            if descriptor is not None:
                self._release_transaction_lock(descriptor, clear_lock)

    def list_backups(self) -> List[Dict[str, Any]]:
        self._validate_state_root_for_read()
        if not os.path.lexists(str(self.backups_directory)):
            return []
        backups_stat = os.lstat(str(self.backups_directory))
        if stat.S_ISLNK(backups_stat.st_mode) or not stat.S_ISDIR(backups_stat.st_mode):
            raise PreflightError("Cassan's backup path must be a real directory")
        backups = []
        for directory in sorted(self.backups_directory.iterdir(), reverse=True):
            directory_stat = os.lstat(str(directory))
            if (
                stat.S_ISLNK(directory_stat.st_mode)
                or not stat.S_ISDIR(directory_stat.st_mode)
                or not BACKUP_ID_RE.fullmatch(directory.name)
            ):
                continue
            transaction = directory / "transaction.json"
            if not os.path.lexists(str(transaction)):
                continue
            transaction_stat = os.lstat(str(transaction))
            if stat.S_ISLNK(transaction_stat.st_mode) or not stat.S_ISREG(
                transaction_stat.st_mode
            ):
                continue
            value = load_json_document(transaction)
            if isinstance(value, dict) and value.get("id") == directory.name:
                backups.append(value)
        return backups

    def _load_transaction(
        self, backup_id: str, allowed_statuses: Sequence[str]
    ) -> Tuple[Path, Dict[str, Any]]:
        if not BACKUP_ID_RE.fullmatch(backup_id):
            raise PreflightError("invalid backup identifier")
        self._validate_state_root_for_read()
        if not os.path.lexists(str(self.backups_directory)):
            raise PreflightError("no Cassan backups are installed")
        backups_stat = os.lstat(str(self.backups_directory))
        if stat.S_ISLNK(backups_stat.st_mode) or not stat.S_ISDIR(backups_stat.st_mode):
            raise PreflightError("Cassan's backup path must be a real directory")
        directory = self.backups_directory / backup_id
        if not os.path.lexists(str(directory)):
            raise PreflightError("unknown backup: %s" % backup_id)
        directory_stat = os.lstat(str(directory))
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            raise PreflightError("backup path is not a real directory: %s" % backup_id)
        transaction_path = directory / "transaction.json"
        if not os.path.lexists(str(transaction_path)):
            raise PreflightError("backup has no transaction metadata: %s" % backup_id)
        transaction_stat = os.lstat(str(transaction_path))
        if stat.S_ISLNK(transaction_stat.st_mode) or not stat.S_ISREG(
            transaction_stat.st_mode
        ):
            raise PreflightError("backup transaction metadata is not a regular file")
        value = load_json_document(transaction_path)
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            raise PreflightError("invalid backup metadata: %s" % backup_id)
        if value.get("id") != backup_id or value.get("status") not in allowed_statuses:
            raise PreflightError(
                "transaction %s is not in an allowed state: %s"
                % (backup_id, value.get("status"))
            )
        self._require_root_identity(value.get("roots"), "transaction backup")
        operations = value.get("operations")
        if not isinstance(operations, list):
            raise PreflightError("backup has no valid operations: %s" % backup_id)
        manifest_after = self._snapshot_from_backup_value(value.get("manifest_after"))
        if manifest_after.kind != "file":
            raise PreflightError("backup has no valid final manifest snapshot")
        final_manifest = directory / "manifest.after.json"
        if not snapshot_matches(inspect_path(final_manifest), manifest_after):
            raise PreflightError("stored final manifest failed verification")
        had_manifest = value.get("had_manifest")
        if not isinstance(had_manifest, bool):
            raise PreflightError("backup has no valid had_manifest marker: %s" % backup_id)
        prior_manifest = directory / "manifest.before.json"
        prior_present = os.path.lexists(str(prior_manifest))
        if had_manifest != prior_present:
            raise PreflightError(
                "backup manifest presence disagrees with had_manifest: %s" % backup_id
            )
        if prior_present:
            manifest_stat = os.lstat(str(prior_manifest))
            if stat.S_ISLNK(manifest_stat.st_mode) or not stat.S_ISREG(
                manifest_stat.st_mode
            ):
                raise PreflightError(
                    "stored pre-transaction manifest is not a regular file"
                )
        manifest_before = self._snapshot_from_backup_value(
            value.get("manifest_before")
        )
        if manifest_before.exists != had_manifest:
            raise PreflightError(
                "backup manifest snapshot disagrees with had_manifest: %s" % backup_id
            )
        if prior_present and not snapshot_matches(
            inspect_path(prior_manifest), manifest_before
        ):
            raise PreflightError("stored pre-transaction manifest failed verification")
        return directory, value

    def _load_backup(self, backup_id: str) -> Tuple[Path, Dict[str, Any]]:
        return self._load_transaction(backup_id, ("completed",))

    @staticmethod
    def _snapshot_from_backup_value(value: Any) -> Snapshot:
        if not isinstance(value, dict) or not isinstance(value.get("exists"), bool):
            raise PreflightError("invalid file snapshot in backup metadata")
        if not value["exists"]:
            return MISSING
        return state_entry_snapshot(value)

    @staticmethod
    def _stored_backup_source(
        directory: Path, backup_name: Any, expected: Snapshot
    ) -> Path:
        if not isinstance(backup_name, str) or Path(backup_name).name != backup_name:
            raise PreflightError("invalid stored file name in backup metadata")
        files_directory = directory / "files"
        if not os.path.lexists(str(files_directory)):
            raise PreflightError("backup has no stored file directory")
        files_stat = os.lstat(str(files_directory))
        if stat.S_ISLNK(files_stat.st_mode) or not stat.S_ISDIR(files_stat.st_mode):
            raise PreflightError("stored file directory is not a real directory")
        source = files_directory / backup_name
        if not snapshot_matches(inspect_path(source), expected):
            raise PreflightError("stored backup file failed verification")
        return source

    def plan_restore(self, backup_id: str, replace: bool = False) -> Tuple[Plan, Dict[str, Any]]:
        directory, metadata = self._load_backup(backup_id)
        current_state, state_observation = self.load_state_observation()
        state_fingerprint = (
            state_observation.sha256 if state_observation.kind == "file" else None
        )
        if current_state is not None and current_state.get("restored_from") == backup_id:
            already_restored = True
        else:
            already_restored = False
        if not already_restored:
            current_transaction = (
                current_state.get("transaction_id") if current_state is not None else None
            )
            if current_transaction != backup_id:
                raise ConflictError(
                    "backup is not the current transaction in Cassan's restore lineage"
                )

        items: List[PlanItem] = []
        seen = set()
        for operation in metadata["operations"]:
            if not isinstance(operation, dict):
                raise PreflightError("invalid operation in backup metadata")
            root = operation.get("root")
            relative = operation.get("relative")
            if root not in ("xdg_config", "home_config") or not isinstance(relative, str):
                raise PreflightError("invalid destination in backup metadata")
            safe_relative(relative)
            key = "%s:%s" % (root, relative)
            if key in seen:
                raise PreflightError("duplicate destination in backup metadata")
            seen.add(key)
            state_only = operation.get("state_only", False)
            if not isinstance(state_only, bool):
                raise PreflightError("invalid state_only marker in backup metadata")
            before_value = operation.get("before")
            after_value = operation.get("after")
            before = self._snapshot_from_backup_value(before_value)
            after = self._snapshot_from_backup_value(after_value)
            source: Optional[Path] = None
            if isinstance(after_value, dict) and "backup" in after_value:
                raise PreflightError("after snapshot must not reference stored backup data")
            if state_only:
                if isinstance(before_value, dict) and "backup" in before_value:
                    raise PreflightError(
                        "state-only operation must not reference stored backup data"
                    )
            elif before.kind == "file":
                backup_name = before_value.get("backup")
                try:
                    source = self._stored_backup_source(
                        directory, backup_name, before
                    )
                except PreflightError as error:
                    raise PreflightError("%s: %s" % (error, key)) from error
            elif isinstance(before_value, dict) and "backup" in before_value:
                raise PreflightError("missing snapshot must not reference backup data")
            destination = self.destination(root, relative)
            ensure_directory_chain(
                self.roots.by_name(root), safe_relative(relative).parent, create=False
            )
            current = inspect_path(destination)
            if current.kind in ("symlink", "directory", "special"):
                items.append(
                    PlanItem(
                        root,
                        relative,
                        "conflict",
                        current,
                        before,
                        detail="restore destination is a %s" % current.kind,
                    )
                )
                continue
            if state_only:
                if not snapshot_matches(current, after):
                    items.append(
                        PlanItem(
                            root,
                            relative,
                            "conflict",
                            current,
                            before,
                            detail="state-only destination changed after the transaction",
                        )
                    )
                else:
                    action = "unchanged" if already_restored else "reconcile"
                    items.append(
                        PlanItem(
                            root,
                            relative,
                            action,
                            current,
                            before,
                            detail="restore the previous ownership snapshot",
                        )
                    )
                continue
            if snapshot_matches(current, before):
                items.append(
                    PlanItem(root, relative, "unchanged", current, before, source)
                )
                continue
            can_replace_changed_file = replace and current.kind == "file"
            if not snapshot_matches(current, after) and not can_replace_changed_file:
                items.append(
                    PlanItem(
                        root,
                        relative,
                        "conflict",
                        current,
                        before,
                        detail="destination changed after this backup was created",
                    )
                )
                continue

            if before.kind == "file":
                action = "create" if current.kind == "missing" else "update"
            else:
                action = "remove"
            items.append(PlanItem(root, relative, action, current, before, source))

        prior_manifest = directory / "manifest.before.json"
        if os.path.lexists(str(prior_manifest)):
            desired_state = validate_state_document(load_json_document(prior_manifest))
            desired_state = dict(desired_state)
        else:
            desired_state = {
                "schema": SCHEMA,
                "installed_at": metadata.get("created_at", "restored"),
                "transaction_id": None,
                "roots": self.root_identity(),
                "source": {"repository": str(self.repo), "restored": True},
                "files": [],
            }
        target_fingerprint = hashlib.sha256(json_bytes(desired_state)).hexdigest()
        return (
            Plan(
                items,
                state_change=not already_restored,
                state_fingerprint=state_fingerprint,
                state_snapshot=state_observation,
                replace=replace,
                kind="restore",
                backup_id=backup_id,
                target_state_fingerprint=target_fingerprint,
            ),
            desired_state,
        )

    def restore(
        self, backup_id: str, plan: Plan, desired_state: Dict[str, Any]
    ) -> Optional[str]:
        if plan.conflicts:
            raise ConflictError("restore contains unresolved destination conflicts")
        if plan.kind != "restore" or plan.backup_id != backup_id:
            raise TransactionError("restore received a plan for a different operation")
        if hashlib.sha256(json_bytes(desired_state)).hexdigest() != (
            plan.target_state_fingerprint
        ):
            raise TransactionError("restore target state changed after review")
        if self.euid == 0:
            raise PreflightError("do not run Cassan's per-user deployment as root")
        operation_id = new_backup_id()
        descriptor: Optional[int] = None
        clear_lock = True
        try:
            try:
                self._ensure_private_state_directories()
                descriptor = self._acquire_transaction_lock(operation_id)
            except CassanError:
                raise
            except OSError as error:
                raise TransactionError("transaction setup failed: %s" % error) from error

            fresh, fresh_state = self.plan_restore(backup_id, plan.replace)
            if fresh != plan:
                raise TransactionError(
                    "restore lineage or files changed after review; review a new plan"
                )
            if hashlib.sha256(json_bytes(fresh_state)).hexdigest() != (
                fresh.target_state_fingerprint
            ):
                raise TransactionError("restore target state changed while planning")
            self._verify_plan_snapshot(fresh)
            if fresh.conflicts:
                raise ConflictError("restore contains unresolved destination conflicts")
            if not fresh.transactional and not fresh.state_change:
                return None
            try:
                return self._transaction_locked(
                    fresh,
                    fresh_state,
                    "restore",
                    operation_id,
                    backup_id,
                )
            except BaseException:
                clear_lock = not self._operation_requires_recovery(operation_id)
                raise
        finally:
            if descriptor is not None:
                self._release_transaction_lock(descriptor, clear_lock)

    def _build_recovery_plan(
        self, lock_value: Mapping[str, Any]
    ) -> Tuple[Plan, Optional[Path], Optional[Dict[str, Any]]]:
        operation_id = lock_value["operation_id"]
        backup_directory = self.backups_directory / operation_id
        if not os.path.lexists(str(backup_directory)):
            return (
                Plan(
                    [],
                    kind="recover",
                    backup_id=operation_id,
                    recovery_status="incomplete",
                ),
                None,
                None,
            )
        backup_stat = os.lstat(str(backup_directory))
        if stat.S_ISLNK(backup_stat.st_mode) or not stat.S_ISDIR(backup_stat.st_mode):
            raise TransactionError("interrupted transaction backup is not a real directory")
        transaction_path = backup_directory / "transaction.json"
        if not os.path.lexists(str(transaction_path)):
            return (
                Plan(
                    [],
                    kind="recover",
                    backup_id=operation_id,
                    recovery_status="incomplete",
                ),
                backup_directory,
                None,
            )

        directory, metadata = self._load_transaction(
            operation_id,
            (
                "preparing",
                "prepared",
                "rollback-failed",
                "rolled-back",
                "completed",
                "recovered-rolled-back",
            ),
        )
        recovery_status = metadata["status"]
        if recovery_status == "preparing":
            return (
                Plan(
                    [],
                    kind="recover",
                    backup_id=operation_id,
                    recovery_status="incomplete",
                ),
                directory,
                metadata,
            )
        if recovery_status in ("rolled-back", "completed", "recovered-rolled-back"):
            return (
                Plan(
                    [],
                    kind="recover",
                    backup_id=operation_id,
                    recovery_status=recovery_status,
                ),
                directory,
                metadata,
            )

        _current_state, state_observation = self.load_state_observation()
        state_fingerprint = (
            state_observation.sha256 if state_observation.kind == "file" else None
        )
        target_state_snapshot = self._snapshot_from_backup_value(
            metadata["manifest_before"]
        )
        final_state_snapshot = self._snapshot_from_backup_value(
            metadata["manifest_after"]
        )
        target_state_fingerprint = (
            target_state_snapshot.sha256
            if target_state_snapshot.kind == "file"
            else None
        )

        if not snapshot_matches(
            state_observation, target_state_snapshot
        ) and not snapshot_matches(state_observation, final_state_snapshot):
            raise ConflictError(
                "deployment state is neither the exact interrupted result nor its baseline"
            )

        items: List[PlanItem] = []
        seen = set()
        for operation in metadata["operations"]:
            if not isinstance(operation, dict):
                raise PreflightError("invalid operation in interrupted transaction")
            root = operation.get("root")
            relative = operation.get("relative")
            if root not in ("xdg_config", "home_config") or not isinstance(
                relative, str
            ):
                raise PreflightError("invalid destination in interrupted transaction")
            safe_relative(relative)
            key = "%s:%s" % (root, relative)
            if key in seen:
                raise PreflightError("duplicate interrupted transaction destination")
            seen.add(key)
            state_only = operation.get("state_only", False)
            if not isinstance(state_only, bool):
                raise PreflightError("invalid state_only marker in interrupted transaction")
            before_value = operation.get("before")
            after_value = operation.get("after")
            before = self._snapshot_from_backup_value(before_value)
            after = self._snapshot_from_backup_value(after_value)
            source: Optional[Path] = None
            if state_only:
                if not snapshot_matches(before, after):
                    raise PreflightError(
                        "state-only interrupted operation changes file contents"
                    )
            elif before.kind == "file":
                backup_name = before_value.get("backup")
                try:
                    source = self._stored_backup_source(
                        directory, backup_name, before
                    )
                except PreflightError as error:
                    raise PreflightError("%s: %s" % (error, key)) from error
            elif isinstance(before_value, dict) and "backup" in before_value:
                raise PreflightError("missing recovery snapshot references stored data")

            destination = self.destination(root, relative)
            ensure_directory_chain(
                self.roots.by_name(root), safe_relative(relative).parent, create=False
            )
            current = inspect_path(destination)
            if state_only:
                action = "unchanged" if snapshot_matches(current, before) else "conflict"
                detail = (
                    "state-only destination differs from its recovery baseline"
                    if action == "conflict"
                    else ""
                )
            elif snapshot_matches(current, before):
                action = "unchanged"
                detail = ""
            elif snapshot_matches(current, after):
                if before.kind == "file":
                    action = "create" if current.kind == "missing" else "update"
                else:
                    action = "remove"
                detail = "roll back interrupted transaction"
            else:
                action = "conflict"
                detail = "destination is neither the transaction baseline nor result"
            items.append(PlanItem(root, relative, action, current, before, source, detail))

        return (
            Plan(
                items,
                state_change=not snapshot_matches(
                    state_observation, target_state_snapshot
                ),
                state_fingerprint=state_fingerprint,
                state_snapshot=state_observation,
                kind="recover",
                backup_id=operation_id,
                target_state_fingerprint=target_state_fingerprint,
                target_state_snapshot=target_state_snapshot,
                recovery_status=recovery_status,
            ),
            directory,
            metadata,
        )

    def plan_recovery(self) -> Plan:
        self._validate_state_root_for_read()
        descriptor, lock_value = self._acquire_recovery_lock()
        try:
            plan, _directory, _metadata = self._build_recovery_plan(lock_value)
            return plan
        finally:
            self._release_transaction_lock(descriptor, clear=False)

    def _recover_prepared_locked(
        self, plan: Plan, directory: Path, metadata: Dict[str, Any]
    ) -> None:
        self._verify_plan_snapshot(plan)
        temporary = Path(tempfile.mkdtemp(prefix=".recover-", dir=str(directory)))
        fsync_directory(directory)
        staged: Dict[str, Path] = {}
        try:
            for index, item in enumerate(plan.items):
                if item.source is None or item.after.kind != "file":
                    continue
                stage_path = temporary / ("%03d" % index)
                target_mode = item.after.mode if item.after.mode is not None else 0o644
                atomic_copy(item.source, stage_path, target_mode)
                if not snapshot_matches(inspect_path(stage_path), item.after):
                    raise TransactionError("recovery source changed: %s" % item.source)
                staged[item.key] = stage_path

            self._verify_plan_snapshot(plan)
            for item in plan.mutations:
                destination = self._check_race(item)
                ensure_directory_chain(
                    self.roots.by_name(item.root),
                    safe_relative(item.relative).parent,
                    create=True,
                )
                if item.after.kind == "file":
                    source = staged.get(item.key)
                    if source is None:
                        raise TransactionError("missing staged recovery file for %s" % item.key)
                    target_mode = (
                        item.after.mode if item.after.mode is not None else 0o644
                    )
                    atomic_copy(source, destination, target_mode)
                elif item.after.kind == "missing":
                    if os.path.lexists(str(destination)):
                        if inspect_path(destination).kind != "file":
                            raise TransactionError(
                                "recovery destination became non-regular: %s" % destination
                            )
                        destination.unlink()
                        fsync_directory(destination.parent)
                else:
                    raise TransactionError("unsupported recovery target: %s" % item.key)

            for item in plan.items:
                self._verify_final_target(item)
            self._require_state_snapshot(plan.state_snapshot)
            prior_manifest = directory / "manifest.before.json"
            if metadata["had_manifest"]:
                target_mode = (
                    plan.target_state_snapshot.mode
                    if plan.target_state_snapshot.mode is not None
                    else 0o600
                )
                atomic_copy(prior_manifest, self.state_file, target_mode)
            elif os.path.lexists(str(self.state_file)):
                if inspect_path(self.state_file).kind != "file":
                    raise TransactionError("deployment state became non-regular during recovery")
                self.state_file.unlink()
                fsync_directory(self.state_file.parent)
            _state, recovered_observation = self.load_state_observation()
            if not snapshot_matches(
                recovered_observation, plan.target_state_snapshot
            ):
                raise TransactionError("recovered deployment state failed verification")

            metadata = dict(metadata)
            metadata["status"] = "recovered-rolled-back"
            metadata["recovered_at"] = utc_now()
            atomic_write_json(directory / "transaction.json", metadata)
            staged_directory = directory / "staged"
            if os.path.lexists(str(staged_directory)):
                staged_stat = os.lstat(str(staged_directory))
                if stat.S_ISDIR(staged_stat.st_mode) and not stat.S_ISLNK(
                    staged_stat.st_mode
                ):
                    shutil.rmtree(str(staged_directory))
        finally:
            shutil.rmtree(str(temporary), ignore_errors=True)

    def recover(self, plan: Plan) -> None:
        if plan.kind != "recover" or plan.backup_id is None:
            raise TransactionError("recover received an invalid plan")
        if self.euid == 0:
            raise PreflightError("do not run Cassan's per-user recovery as root")
        descriptor, lock_value = self._acquire_recovery_lock()
        clear_lock = False
        try:
            fresh, directory, metadata = self._build_recovery_plan(lock_value)
            if fresh != plan:
                raise TransactionError(
                    "interrupted transaction changed after review; review recovery again"
                )
            if fresh.conflicts:
                raise ConflictError("recovery contains unresolved destination conflicts")
            if fresh.recovery_status == "incomplete":
                if directory is not None:
                    shutil.rmtree(str(directory))
                    fsync_directory(self.backups_directory)
            elif fresh.recovery_status in ("prepared", "rollback-failed"):
                if directory is None or metadata is None:
                    raise TransactionError("recovery metadata disappeared")
                self._recover_prepared_locked(fresh, directory, metadata)
            elif fresh.recovery_status not in (
                "preparing",
                "rolled-back",
                "completed",
                "recovered-rolled-back",
            ):
                raise TransactionError("unsupported recovery status")
            clear_lock = True
        finally:
            self._release_transaction_lock(descriptor, clear_lock)


def print_plan(plan: Plan, title: str) -> None:
    print(title)
    for item in plan.items:
        detail = " — %s" % item.detail if item.detail else ""
        print("  %-9s %s%s" % (item.action.upper(), item.key, detail))
    counts: Dict[str, int] = {}
    for item in plan.items:
        counts[item.action] = counts.get(item.action, 0) + 1
    if plan.state_change:
        print("  %-9s %s" % ("RECONCILE", "state:manifest.json"))
        counts["state"] = counts.get("state", 0) + 1
    summary = ", ".join(
        "%s %s" % (count, action) for action, count in sorted(counts.items())
    )
    print("Summary: %s" % (summary or "no managed files"))


def load_official_packages(repo: Path = REPO_DIR) -> List[str]:
    path = repo / "packages" / "official.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise PreflightError("cannot read package manifest: %s" % error) from error
    packages = []
    seen = set()
    for line_number, source_line in enumerate(lines, 1):
        value = source_line.strip()
        if not value or value.startswith("#"):
            continue
        if not PACKAGE_RE.fullmatch(value):
            raise PreflightError(
                "invalid package token at packages/official.txt:%d" % line_number
            )
        if value in seen:
            raise PreflightError("duplicate official package: %s" % value)
        seen.add(value)
        packages.append(value)
    if not packages:
        raise PreflightError("official package manifest is empty")
    return packages


def select_packages(
    manifest_packages: Sequence[str], optional_groups: Sequence[str]
) -> List[str]:
    selected_groups = set(optional_groups)
    unknown = selected_groups.difference(OPTIONAL_PACKAGE_GROUPS)
    if unknown:
        raise PreflightError(
            "unknown optional package group: %s" % ", ".join(sorted(unknown))
        )
    wanted = set(CORE_PACKAGE_NAMES)
    for group in selected_groups:
        wanted.update(OPTIONAL_PACKAGE_GROUPS[group])
    manifest_set = set(manifest_packages)
    missing_from_manifest = wanted.difference(manifest_set)
    if missing_from_manifest:
        raise PreflightError(
            "selected packages are absent from packages/official.txt: %s"
            % ", ".join(sorted(missing_from_manifest))
        )
    return [package for package in manifest_packages if package in wanted]


def is_arch_linux() -> bool:
    return Path("/etc/arch-release").is_file()


def verified_system_executable(path: Path, label: str) -> str:
    if not path.is_absolute():  # pragma: no cover - constants are absolute
        raise PreflightError("%s path must be absolute" % label)
    if not os.path.lexists(str(path)):
        raise PreflightError("required system executable is missing: %s" % path)
    executable_stat = os.lstat(str(path))
    if (
        stat.S_ISLNK(executable_stat.st_mode)
        or not stat.S_ISREG(executable_stat.st_mode)
        or executable_stat.st_uid != 0
        or executable_stat.st_mode & 0o111 == 0
    ):
        raise PreflightError(
            "%s must be a root-owned executable regular file: %s" % (label, path)
        )
    return str(path)


def inspect_packages(packages: Sequence[str]) -> List[str]:
    if not is_arch_linux():
        raise PreflightError("package inspection is supported only on Arch Linux")
    pacman = verified_system_executable(PACMAN_PATH, "pacman")
    result = subprocess.run(
        [pacman, "-T"] + list(packages),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 127):
        raise PackageError("pacman dependency check failed: %s" % result.stderr.strip())
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def install_packages(packages: Sequence[str], euid: Optional[int] = None) -> None:
    current_euid = os.geteuid() if euid is None else euid
    if current_euid == 0:
        raise PreflightError("run package installation as a regular user, not root")
    if not is_arch_linux():
        raise PreflightError("package installation is supported only on Arch Linux")
    pacman = verified_system_executable(PACMAN_PATH, "pacman")
    sudo = verified_system_executable(SUDO_PATH, "sudo")
    result = subprocess.run(
        [sudo, pacman, "-Syu", "--needed", "--"] + list(packages), check=False
    )
    if result.returncode != 0:
        raise PackageError("pacman failed with exit status %d" % result.returncode)


def parser() -> argparse.ArgumentParser:
    description = (
        "Deploy Cassan's reviewed runtime configuration with per-file backups. "
        "Most components follow XDG_CONFIG_HOME; the wallpaper intentionally "
        "installs to $HOME/.config/cassan/assets/nighthowler/wallpaper.jpg because "
        "the generated Hyprpaper and Hyprlock configuration references that path."
    )
    result = argparse.ArgumentParser(description=description)
    subparsers = result.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="validate and preview without writing")
    plan_parser.add_argument(
        "--replace", action="store_true", help="preview replacement of conflicts"
    )
    plan_parser.add_argument(
        "--allow-dirty", action="store_true", help="allow an uncommitted source tree"
    )

    apply_parser = subparsers.add_parser("apply", help="apply the reviewed deployment plan")
    apply_parser.add_argument(
        "--replace",
        action="store_true",
        help="back up and replace conflicting regular files",
    )
    apply_parser.add_argument(
        "--allow-dirty", action="store_true", help="allow an uncommitted source tree"
    )
    apply_parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without changing files"
    )

    subparsers.add_parser("status", help="report installed drift without writing")
    subparsers.add_parser("backups", help="list retained transaction backups")

    restore_parser = subparsers.add_parser(
        "restore", help="preview or apply one backup restoration"
    )
    restore_parser.add_argument("backup_id", help="identifier shown by the backups command")
    restore_parser.add_argument(
        "--apply", action="store_true", help="perform the displayed restoration"
    )
    restore_parser.add_argument(
        "--replace",
        action="store_true",
        help="override later regular-file changes after backing them up",
    )

    packages_parser = subparsers.add_parser(
        "packages", help="report or explicitly install official packages"
    )
    packages_parser.add_argument(
        "--install", action="store_true", help="run sudo pacman -Syu --needed"
    )
    packages_parser.add_argument(
        "--with",
        dest="optional_groups",
        action="append",
        choices=tuple(sorted(OPTIONAL_PACKAGE_GROUPS)),
        default=[],
        metavar="ACCESSORY",
        help=(
            "include an optional configured package group; repeat to combine "
            "apps, cava, and fastfetch (all 33 inert config files are always deployed)"
        ),
    )

    recover_parser = subparsers.add_parser(
        "recover",
        help="inspect or roll back an interrupted transaction after its process exited",
    )
    recover_parser.add_argument(
        "--apply", action="store_true", help="perform the displayed recovery"
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "packages":
            packages = select_packages(
                load_official_packages(), arguments.optional_groups
            )
            if arguments.install:
                install_packages(packages)
                print("Cassan official packages are installed.")
            else:
                missing = inspect_packages(packages)
                if missing:
                    print("Missing official packages:")
                    for package in missing:
                        print("  %s" % package)
                else:
                    print("All Cassan official packages are installed.")
            return 0

        deployer = Deployer()
        if arguments.command in ("plan", "apply"):
            deployer.validate_repo(arguments.allow_dirty)
            plan = deployer.plan(arguments.replace)
            print_plan(plan, "Cassan deployment plan")
            if plan.conflicts:
                raise ConflictError(
                    "resolve the conflicts or review the plan again with --replace"
                )
            if arguments.command == "plan" or arguments.dry_run:
                print("Dry run complete; no files were changed.")
                return 0
            missing = inspect_packages(select_packages(load_official_packages(), ()))
            if missing:
                raise PreflightError(
                    "required packages are missing; run `python3 scripts/cassan.py "
                    "packages --install` first: %s" % ", ".join(missing)
                )
            backup_id = deployer.apply(plan)
            if backup_id is None:
                print("Cassan is already current; no file backup was needed.")
            else:
                print("Cassan applied successfully. Backup: %s" % backup_id)
            return 0

        if arguments.command == "status":
            plan = deployer.plan(False)
            print_plan(plan, "Cassan deployment status")
            return 1 if plan.drift else 0

        if arguments.command == "backups":
            backups = deployer.list_backups()
            if not backups:
                print("No Cassan transaction backups found.")
            for backup in backups:
                source = backup.get("source") or {}
                commit = source.get("commit") or "unknown"
                print(
                    "%s  %-12s %-15s %s"
                    % (
                        backup["id"],
                        backup.get("kind", "unknown"),
                        backup.get("status", "unknown"),
                        commit,
                    )
                )
            return 0

        if arguments.command == "restore":
            plan, desired_state = deployer.plan_restore(
                arguments.backup_id, arguments.replace
            )
            print_plan(plan, "Cassan restore plan for %s" % arguments.backup_id)
            if plan.conflicts:
                raise ConflictError(
                    "restore conflicts with later changes; inspect them before --replace"
                )
            if not arguments.apply:
                print("Restore preview complete; no files were changed. Add --apply to proceed.")
                return 0
            backup_id = deployer.restore(arguments.backup_id, plan, desired_state)
            if backup_id is None:
                print("This backup is already restored; no files were changed.")
            else:
                print("Restore completed. Pre-restore backup: %s" % backup_id)
            return 0

        if arguments.command == "recover":
            recovery_plan = deployer.plan_recovery()
            print_plan(
                recovery_plan,
                "Cassan recovery plan for %s (%s)"
                % (recovery_plan.backup_id, recovery_plan.recovery_status),
            )
            if recovery_plan.conflicts:
                raise ConflictError(
                    "recovery conflicts with unknown file changes; inspect them manually"
                )
            if not arguments.apply:
                print("Recovery preview complete; no files were changed. Add --apply to proceed.")
                return 0
            deployer.recover(recovery_plan)
            print("Interrupted Cassan transaction was recovered.")
            return 0

        raise PreflightError("unsupported command")  # pragma: no cover
    except CassanError as error:
        print("cassan: %s" % error, file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
