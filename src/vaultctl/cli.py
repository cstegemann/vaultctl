#!/usr/bin/env python3

# =============================================================================
# Standard Python modules
# =============================================================================
import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
import tomllib  # Python 3.11+
import logging

# =============================================================================
# External Python modules
# =============================================================================

# =============================================================================
# Extension modules
# =============================================================================

# =====================================
# script-wide declarations
# =====================================
logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.DEBUG)

@dataclass(frozen=True)
class Config:
    config_version: int
    vault_root: Path
    project_vault_dir: str
    mount_dir: str
    auto_mount: tuple[str, ...]
    create_desktop_launcher: bool
    desktop_launcher_name: str
    editor: str

DEFAULTS = {
    "config_version": 1,
    "vault_root": str(Path.home() / "vaults"),
    "project_vault_dir": ".vault",
    "mount_dir": "_m",
    "auto_mount": ["global"],
    "create_desktop_launcher": True,
    "desktop_launcher_name": "Open Project Vault.desktop",
    "editor": "obsidian",
}

# ----------------------------
# Config loading
# ----------------------------

def default_config_path() -> Path:
    env = os.environ.get("VAULTCTL_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "vaultctl" / "config.toml"


def load_config() -> Config:
    cfg_path = default_config_path()
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"No config file found at: {cfg_path}\n"
            f"See readme"
        )

    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))

    return Config(
        config_version=data.get("config_version", DEFAULTS["config_version"]),
        vault_root=Path(data.get("vault_root", DEFAULTS["vault_root"])).expanduser(),
        project_vault_dir=data.get("project_vault_dir", DEFAULTS["project_vault_dir"]),
        mount_dir=data.get("mount_dir", DEFAULTS["mount_dir"]),
        auto_mount=tuple(data.get("auto_mount", DEFAULTS["auto_mount"])),
        create_desktop_launcher=bool(data.get("create_desktop_launcher", DEFAULTS["create_desktop_launcher"])),
        desktop_launcher_name=data.get("desktop_launcher_name", DEFAULTS["desktop_launcher_name"]),
        editor=data.get("editor", DEFAULTS["editor"]),
    )


# ----------------------------
# Global vault discovery & rules
# ----------------------------

def is_ignored_root_entry(p: Path) -> bool:
    # Ignore hidden and underscore-prefixed root folders (your rule)
    return p.name.startswith(".") or p.name.startswith("_")


def is_mountable_global(cfg: Config, p: Path) -> bool:
    """
    A mountable global vault is:
      - a real directory
      - direct child of vault_root
      - not ignored (_ / . prefix)
      - not a symlink (optional, but keeps things predictable)
      - does NOT contain mount_dir (enforces 'globals cannot mount anything')
    """
    if not p.exists() or not p.is_dir():
        return False
    if is_ignored_root_entry(p):
        return False
    if p.is_symlink():
        return False
    try:
        p.relative_to(cfg.vault_root)
    except ValueError:
        return False
    # must be immediate child
    if p.parent != cfg.vault_root:
        return False
    # enforce "no mount folder ever" in globals
    if (p / cfg.mount_dir).exists():
        return False
    return True


def discover_globals(cfg: Config) -> dict[str, Path]:
    root = cfg.vault_root.expanduser()
    root.mkdir(parents=True, exist_ok=True)

    out: dict[str, Path] = {}
    for child in root.iterdir():
        if is_mountable_global(cfg, child):
            out[child.name] = child
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


# ----------------------------
# Project vault helpers
# ----------------------------

def project_paths(cfg: Config, project_root: Path) -> tuple[Path, Path]:
    vault = project_root / cfg.project_vault_dir
    mount = vault / cfg.mount_dir
    return vault, mount


def ensure_project_vault(cfg: Config, project_root: Path) -> tuple[Path, Path]:
    vault, mount = project_paths(cfg, project_root)
    vault.mkdir(parents=True, exist_ok=True)
    mount.mkdir(parents=True, exist_ok=True)

    index = vault / "index.md"
    if not index.exists():
        index.write_text(
            "# Project Notes\n\n",
            encoding="utf-8",
        )
    return vault, mount


def ensure_global_vault(cfg: Config, name: str) -> Path:
    if name.startswith("_") or name.startswith("."):
        raise ValueError("Global vault name cannot start with '_' or '.'")

    target = (cfg.vault_root / name).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    # enforce rule: no mount folder inside global vaults, ever
    mount_dir = target / cfg.mount_dir
    if mount_dir.exists():
        raise RuntimeError(
            f"Refusing to create/use global vault '{name}': "
            f"found forbidden mount dir inside: {mount_dir}"
        )

    index = target / "index.md"
    if not index.exists():
        index.write_text(
            f"# {name}\n\n",
            encoding="utf-8",
        )
    return target


def ensure_gitignore(project_root: Path, cfg: Config) -> None:
    if not (project_root / ".git").exists():
        return
    gi = project_root / ".gitignore"
    entries = [
        f"{cfg.project_vault_dir}/{cfg.mount_dir}/\n",
        f"{cfg.project_vault_dir}/.{cfg_editor}/\n",# works for obsidian!
    ]
    if gi.exists():
        existing = gi.read_text(encoding="utf-8")
        for entry in entries:
            if entry.strip() in existing:
                continue
            gi.write_text(existing + entry, encoding="utf-8")
    else:
        for entry in entries:
            gi.write_text(entry, encoding="utf-8")


def create_desktop_launcher(vault: Path, cfg: Config) -> None:
    """
    Creates a per-project launcher file to open this vault in Obsidian.
    Uses absolute path for reliability on Ubuntu.
    """
    if cfg.editor != "obsidian":
        return

    launcher = vault / cfg.desktop_launcher_name
    abs_vault = str(vault.resolve())

    content = f"""[Desktop Entry]
Type=Application
Name=Open Project Vault
Exec=obsidian "{abs_vault}"
Terminal=false
Icon=obsidian
"""
    launcher.write_text(content, encoding="utf-8")
    launcher.chmod(0o755)


def is_inside_global_vault(cfg: Config, path: Path) -> bool:
    """
    True if `path` is inside any mountable global vault folder (direct child of vault_root).
    This prevents accidental "project vault inside global vault" and also blocks mount actions there.
    """
    path = path.resolve()
    if not cfg.vault_root.exists():
        return False
    try:
        rel = path.relative_to(cfg.vault_root.resolve())
    except ValueError:
        return False
    # rel parts like ("llm", "..."); if first part is a mountable global, you're inside it
    if not rel.parts:
        return False
    candidate = cfg.vault_root / rel.parts[0]
    return is_mountable_global(cfg, candidate)


# ----------------------------
# Mounting
# ----------------------------

def mount_global_into_project(cfg: Config, project_root: Path, name: str) -> None:
    if is_inside_global_vault(cfg, project_root):
        raise RuntimeError("Refusing to mount inside a global vault. Mounting is only for project vaults.")

    globals_map = discover_globals(cfg)
    if name not in globals_map:
        raise FileNotFoundError(
            f"Global vault '{name}' not found under {cfg.vault_root} "
            f"(or it is ignored/invalid)."
        )

    vault, mount_dir = ensure_project_vault(cfg, project_root)
    target = globals_map[name]
    link = mount_dir / name

    if link.exists() or link.is_symlink():
        # If already correct symlink, do nothing; else fail loudly.
        if link.is_symlink() and link.resolve() == target.resolve():
            return
        raise FileExistsError(f"Mountpoint already exists: {link}")

    link.symlink_to(target, target_is_directory=True)


# ----------------------------
# CLI commands
# ----------------------------

def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()

    if args.global_name:
        # create global vault under vault_root
        ensure_global_vault(cfg, args.global_name)
        logging.info(cfg.vault_root / args.global_name)
        return 0

    project_root = Path(args.path).expanduser().resolve()

    if is_inside_global_vault(cfg, project_root):
        raise RuntimeError(
            "You appear to be inside vault_root (or one of its global vaults). "
            "Use: vaultctl init --global NAME  (to create a global vault), "
            "or run init from a project directory."
        )

    vault, _mount_dir = ensure_project_vault(cfg, project_root)

    # auto-mount configured globals if they exist
    globals_map = discover_globals(cfg)
    for name in cfg.auto_mount:
        if name in globals_map:
            mount_global_into_project(cfg, project_root, name)

    ensure_gitignore(project_root, cfg)

    if cfg.create_desktop_launcher:
        create_desktop_launcher(vault, cfg)

    logging.info(vault)
    return 0


def cmd_mount(args: argparse.Namespace) -> int:
    cfg = load_config()
    project_root = Path(args.path).expanduser().resolve()
    mount_global_into_project(cfg, project_root, args.name)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    globals_map = discover_globals(cfg)

    print(f"vault_root: {cfg.vault_root}")
    if not globals_map:
        print("(no global vaults found)")
    else:
        print("global vaults:")
        for name, path in globals_map.items():
            print(f"  - {name}\t{path}")

    # If this looks like a project root, show mounts status
    project_root = Path(args.path).expanduser().resolve()
    vault, mount_dir = project_paths(cfg, project_root)

    if vault.exists() and mount_dir.exists():
        print(f"\nproject vault: {vault}")
        mounts = []
        for p in sorted(mount_dir.iterdir(), key=lambda x: x.name.lower()):
            if p.is_symlink():
                try:
                    mounts.append((p.name, str(p.resolve())))
                except FileNotFoundError:
                    mounts.append((p.name, "(broken symlink)"))
            else:
                mounts.append((p.name, "(not a symlink)"))

        if mounts:
            print("mounted:")
            for name, dest in mounts:
                print(f"  - {name}\t{dest}")
        else:
            print("mounted: (none)")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="vaultctl")
    sub = p.add_subparsers(required=True)

    p_init = sub.add_parser("init", help="Initialize a project vault OR create a global vault under vault_root")
    p_init.add_argument("path", nargs="?", default=".", help="Project root (default: .)")
    p_init.add_argument("-g", "--global", dest="global_name", help="Create a global vault under vault_root with this NAME")
    p_init.set_defaults(func=cmd_init)

    p_mount = sub.add_parser("mount", help="Mount a global vault into the project vault")
    p_mount.add_argument("name", help="Name of global vault folder under vault_root")
    p_mount.add_argument("--path", default=".", help="Project root (default: .)")
    p_mount.set_defaults(func=cmd_mount)

    p_list = sub.add_parser("list", help="List discovered global vaults; if in a project, also show current mounts")
    p_list.add_argument("--path", default=".", help="Project root (default: .)")
    p_list.set_defaults(func=cmd_list)

    args = p.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
