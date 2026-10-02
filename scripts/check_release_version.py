"""Fail a tagged package build when its tag and project version disagree."""

from __future__ import annotations

import os
if __package__:
    from .desktop_release import project_version
else:
    from desktop_release import project_version


def main() -> None:
    version = project_version()
    tag = os.environ.get("GITHUB_REF_NAME", "")
    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    if ref_type == "tag" and tag != f"v{version}":
        raise SystemExit(f"Release tag {tag!r} does not match project version v{version}")
    print(f"Release version verified: {version}")


if __name__ == "__main__":
    main()
