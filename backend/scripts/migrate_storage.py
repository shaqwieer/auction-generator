"""Move the application's files from a Docker named volume onto a bind mount.

Run once, on the VPS, when upgrading a deployment that still keeps ``/app/var``
in the ``matbaa_api_var`` named volume. Afterwards the same files live in an
ordinary host directory that survives ``docker compose down``, that backups can
reach, and that no deployment has to ``docker compose cp`` into.

    # 1. look, change nothing
    docker compose run --rm \\
      -v matbaa_api_var:/old:ro -v /srv/matbaa/var:/new \\
      api python scripts/migrate_storage.py --from /old --to /new

    # 2. do it
    docker compose run --rm \\
      -v matbaa_api_var:/old:ro -v /srv/matbaa/var:/new \\
      api python scripts/migrate_storage.py --from /old --to /new --apply

Nothing is deleted and nothing is overwritten. A file already at the
destination is compared by content: identical means it is left alone and
counted as done, different means it is reported as a conflict and skipped, so a
second run after a partial copy is safe and a re-run is a no-op. Every file it
writes is read back and checksummed before it counts as copied.

The old volume is left intact. Remove it yourself, once you have looked at the
new directory and taken a backup:

    docker volume rm matbaa_api_var
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

CHUNK = 1024 * 1024


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            sha.update(chunk)
    return sha.hexdigest()


@dataclass
class Report:
    copied: int = 0
    copied_bytes: int = 0
    already_there: int = 0
    conflicts: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.failed


def migrate(source: Path, target: Path, *, apply: bool) -> Report:
    report = Report()
    files = sorted(p for p in source.rglob("*") if p.is_file())
    if not files:
        print(f"  {source} holds no files — nothing to move.")
        return report

    for item in files:
        relative = item.relative_to(source)
        destination = target / relative

        if destination.exists():
            # A previous run, or a redeployment that already wrote here. Same
            # content is fine; different content is somebody's data and this
            # script will not choose between them.
            if destination.stat().st_size == item.stat().st_size and digest(
                destination
            ) == digest(item):
                report.already_there += 1
            else:
                report.conflicts.append(relative)
            continue

        size = item.stat().st_size
        if not apply:
            report.copied += 1
            report.copied_bytes += size
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".partial")
        try:
            shutil.copy2(item, temporary)
            # Read it back before it counts. A truncated copy that is never
            # verified is the one way this script could lose data.
            if digest(temporary) != digest(item):
                temporary.unlink(missing_ok=True)
                report.failed.append((relative, "checksum mismatch after copy"))
                continue
            temporary.replace(destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            report.failed.append((relative, str(exc)))
            continue

        report.copied += 1
        report.copied_bytes += size

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from", dest="source", type=Path, default=Path("/old"),
        help="the old named volume, mounted read-only (default: /old)",
    )
    parser.add_argument(
        "--to", dest="target", type=Path, default=Path("/new"),
        help="the bind-mounted host directory (default: /new)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="actually copy; without it nothing is written",
    )
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"  {args.source} is not a directory — is the old volume mounted?")
        return 2
    args.target.mkdir(parents=True, exist_ok=True)

    print(f"{'moving' if args.apply else 'DRY RUN — inspecting'} "
          f"{args.source} -> {args.target}\n")
    report = migrate(args.source, args.target, apply=args.apply)

    verb = "copied" if args.apply else "would copy"
    print(f"  {verb:12s} {report.copied:5d} files "
          f"({report.copied_bytes / 1e6:.1f} MB)")
    print(f"  {'already there':12s} {report.already_there:5d} files")

    for relative in report.conflicts:
        print(f"  ! conflict   {relative} — differs at the destination, skipped")
    for relative, why in report.failed:
        print(f"  ! failed     {relative} — {why}")

    if not report.ok:
        print("\n  Nothing was lost: the source is untouched. Resolve the files "
              "above and run again.")
        return 1
    if not args.apply:
        print("\n  Re-run with --apply to move them.")
    else:
        print("\n  Done. Check the new directory, take a backup, then:"
              "\n    docker volume rm matbaa_api_var")
    return 0


if __name__ == "__main__":
    sys.exit(main())
