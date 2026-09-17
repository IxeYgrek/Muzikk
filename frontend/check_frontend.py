"""Static checks for the SPA: import resolution and translation key coverage.

Node is not available on the development machine, so this stands in for a
`tsc --noEmit` run on the two things that break the app at runtime.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"
EXTENSIONS = (".ts", ".tsx", ".css", ".svg", ".json")

problems: list[str] = []


# --------------------------------------------------------------- imports


def resolve(source: Path, target: str) -> bool:
    if target.startswith("@/"):
        base = SRC / target[2:]
    elif target.startswith("."):
        base = (source.parent / target).resolve()
    else:
        return True  # package import

    if base.suffix and base.exists():
        return True
    for extension in EXTENSIONS:
        if base.with_suffix(extension).exists():
            return True
        if (base / f"index{extension}").exists():
            return True
    return base.exists()


import_pattern = re.compile(r"""(?:from|import)\s+['"]([^'"]+)['"]""")

for file in sorted(SRC.rglob("*.ts*")):
    for target in import_pattern.findall(file.read_text(encoding="utf-8")):
        if not resolve(file, target):
            problems.append(f"unresolved import {target!r} in {file.relative_to(ROOT)}")


# ---------------------------------------------------------- translations


def collect_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    stack: list[str] = []
    opener = re.compile(r"^\s*([A-Za-z_][\w]*)\s*:\s*\{\s*$")
    # A value may sit on the next line when prettier wraps a long string.
    leaf = re.compile(r"^\s*([A-Za-z_][\w]*)\s*:\s*(?:['\"`]|$)")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        match = opener.match(line)
        if match:
            stack.append(match.group(1))
            continue
        if stripped.startswith("}"):
            if stack:
                stack.pop()
            continue
        match = leaf.match(line)
        if match and stack:
            keys.add(".".join([*stack, match.group(1)]))
    return keys


fr_keys = collect_keys(SRC / "i18n" / "fr.ts")
en_keys = collect_keys(SRC / "i18n" / "en.ts")

for key in sorted(fr_keys - en_keys):
    problems.append(f"missing english translation for {key}")
for key in sorted(en_keys - fr_keys):
    problems.append(f"missing french translation for {key}")

# Keys built at runtime from a variable prefix are checked by prefix only.
dynamic_prefixes = ("status.", "providers.", "admin.sections.", "admin.jobKinds.", "fields.")
used_pattern = re.compile(r"""\bt\(\s*['"]([a-zA-Z0-9_.]+)['"]""")

# Keys assembled in a template literal, such as t(`metadata.issue.${kind}`): the
# suffix is only known at runtime, so the namespace is what can be checked.
template_pattern = re.compile(r"""\bt\(\s*`([a-zA-Z0-9_.]+)\.\$\{""")

for file in sorted(SRC.rglob("*.tsx")):
    contents = file.read_text(encoding="utf-8")
    for key in used_pattern.findall(contents):
        if key in fr_keys:
            continue
        if any(key.startswith(prefix) for prefix in dynamic_prefixes):
            continue
        problems.append(f"unknown translation key {key!r} in {file.relative_to(ROOT)}")

    for prefix in template_pattern.findall(contents):
        if not any(existing.startswith(f"{prefix}.") for existing in fr_keys):
            problems.append(
                f"empty translation namespace {prefix!r} in {file.relative_to(ROOT)}"
            )

# ------------------------------------------------------------- artwork
#
# Cover art is missing often enough in MusicBrainz that a bare <img> shows a
# broken box instead of a record sleeve. AlbumCover falls back on its own, so
# it is the only place allowed to render one.

for file in sorted(SRC.rglob("*.tsx")):
    if file.name == "AlbumCard.tsx":
        continue
    if "<img" in file.read_text(encoding="utf-8"):
        problems.append(f"raw <img> in {file.relative_to(ROOT)}, use AlbumCover instead")

# Every admin form field must have a label in fr.ts, they are looked up by key.
form = (SRC / "components" / "admin" / "SettingsForm.tsx").read_text(encoding="utf-8")
schema = form.split("export const SECTION_FIELDS", 1)[1].split("\ntype Values", 1)[0]
section = ""
for line in schema.splitlines():
    header = re.match(r"^  ([a-z_]+): \[", line)
    if header:
        section = header.group(1)
        continue
    field = re.search(r"key: '([a-z_0-9]+)'", line)
    if field and section:
        expected = f"fields.{section}.{field.group(1)}"
        if expected not in fr_keys:
            problems.append(f"missing label {expected}")

print(f"{len(fr_keys)} translation keys, {len(list(SRC.rglob('*.ts*')))} source files")
for problem in problems:
    print("PROBLEM:", problem)
print("OK" if not problems else f"{len(problems)} problem(s)")
sys.exit(1 if problems else 0)
