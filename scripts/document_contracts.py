"""Static Markdown links and feature-spec structure/traceability contracts."""

import ast
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

SPEC_SECTIONS = (
    "Problem",
    "Goals",
    "Non-goals",
    "Proposed design",
    "Security and data isolation",
    "Migration, rollout, and rollback",
    "Acceptance criteria",
    "Test traceability",
)


def prose(source: str) -> str:
    """Ignore fenced examples and inline code when looking for Markdown links."""
    lines = []
    fence = None
    for line in source.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(re.sub(r"`[^`]*`", "", line))
    return "\n".join(lines)


def heading_anchors(source: str) -> set[str]:
    counts: dict[str, int] = {}
    anchors = set()
    # Headings retain inline text; strip only formatting punctuation.
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", source):
        slug = re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
        number = counts.get(slug, 0)
        anchors.add(f"{slug}-{number}" if number else slug)
        counts[slug] = number + 1
    return anchors


def link_errors(root: Path, path: Path, source: str) -> list[str]:
    errors = []
    links = re.findall(r"\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+\"[^\"]*\")?\)", prose(source))
    links += [
        (value, "") for value in re.findall(r"(?m)^\s*\[[^]]+\]:\s*<?([^\s>]+)>?", prose(source))
    ]
    for first, second in links:
        target = first or second
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        name = unquote(parsed.path)
        destination = (root / name.lstrip("/")) if name.startswith("/") else (path.parent / name)
        if not name:
            destination = path
        if not destination.exists():
            errors.append(f"{path.relative_to(root)}: broken local link {target}")
        elif parsed.fragment and destination.is_file() and destination.suffix == ".md":
            if unquote(parsed.fragment) not in heading_anchors(
                destination.read_text(encoding="utf-8")
            ):
                errors.append(f"{path.relative_to(root)}: missing heading anchor {target}")
    return errors


def named_test_exists(root: Path, reference: str) -> bool:
    """Resolve explicit Python nodes or literal Node test titles without executing tests."""
    filename, separator, test_name = reference.partition("::")
    path = (root / filename).resolve()
    if not separator or not path.is_relative_to(root.resolve()) or not path.is_file():
        return False
    source = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                names.add(node.name)
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                names.update(node.name + "::" + child.name for child in node.body
                             if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and child.name.startswith("test_"))
        return test_name.split("[", 1)[0] in names
    if path.suffix in {".cjs", ".mjs"}:
        titles = {match[1] for match in re.findall(
            r"(?m)^test\(\s*(['\"])(.*?)\1\s*,", source
        )}
        return test_name in titles
    return False


def spec_errors(root: Path, path: Path, source: str) -> list[str]:
    errors = []
    label = path.relative_to(root)
    for section in SPEC_SECTIONS:
        if not re.search(r"(?m)^## " + re.escape(section) + r"\s*$", source):
            errors.append(f"{label}: missing section {section}")
    status = re.search(
        r"(?m)^- 狀態：(Draft|Accepted|Implemented|Superseded)(?:（[^\n]*）)?\s*$", source
    )
    if not status:
        errors.append(f"{label}: missing or invalid status")
    if not re.search(r"(?m)^- Owner：\S.*$", source):
        errors.append(f"{label}: missing Owner")
    sections = re.split(r"(?m)^## ", source)
    acceptance = next((part for part in sections if part.startswith("Acceptance criteria\n")), "")
    trace = next((part for part in sections if part.startswith("Test traceability\n")), "")
    if not re.search(r"(?m)^- \[[ x]\] .+", acceptance):
        errors.append(f"{label}: acceptance criteria must contain checkboxes")
    if status and status[1] == "Implemented" and re.search(r"(?m)^- \[ \]", acceptance):
        errors.append(f"{label}: Implemented spec has unchecked acceptance criteria")
    if not re.search(r"(?m)^\|.+\|.+\|", trace):
        errors.append(f"{label}: missing test traceability table")
    references = re.findall(r"(?<![\w/])(?:[\w.*-]+/)*[\w.*-]+\.(?:py|cjs|mjs|json|md)\b", trace)
    for reference in references:
        candidates = (
            [root / reference]
            if "/" in reference
            else [
                root / folder / reference
                for folder in ("unit_tests", "scripts", "frontend", "backend", "docs")
            ]
        )
        if not any(any(candidate.parent.glob(candidate.name)) for candidate in candidates):
            errors.append(f"{label}: missing traceability file {reference}")
    # New specifications use explicit, verifiable paths rather than prose-only traceability.
    if int(path.name[:3]) >= 20:
        ids = set(re.findall(r"(?m)^- \[[ x]\] (AC-\d+)：", acceptance))
        traced = set(re.findall(r"AC-\d+", trace))
        for criterion in sorted(ids - traced):
            errors.append(f"{label}: {criterion} has no traceability row")
        for row in trace.splitlines()[2:]:
            if (
                row.startswith("|")
                and "AC-" in row
                and not re.search(r"`(?:unit_tests/|(?:python3 )?scripts/)", row)
            ):
                errors.append(
                    f"{label}: traceability row needs a test path or repository command: {row}"
                )
    if int(path.name[:3]) >= 23:
        for row in trace.splitlines():
            if not row.startswith("|") or "AC-" not in row:
                continue
            named = re.findall(r"`(unit_tests/[^`]+::[^`]+)`", row)
            if not named:
                errors.append(f"{label}: acceptance row needs a named test: {row}")
            for reference in named:
                if not named_test_exists(root, reference):
                    errors.append(f"{label}: missing named test {reference}")
    return errors


# SPEC-053: every module must be findable from the README tree, and every
# application module must be placed somewhere in the SDD.
README_TREE_MODULES = (
    "backend/**/*.py",
    "frontend/app*.js",
    "frontend/runtime/*.mjs",
    "scripts/*.py",
    "scripts/*.cjs",
    "scripts/*.sql",
)
SDD_MODULES = ("backend/**/*.py", "frontend/app*.js", "frontend/runtime/*.mjs")


def repository_modules(root: Path, patterns: tuple[str, ...]) -> list[str]:
    modules = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts and path.name != "__init__.py":
                modules.add(path.relative_to(root).as_posix())
    return sorted(modules)


def readme_tree_paths(readme: str) -> set[str]:
    """Paths listed in the README "目錄結構" tree; directories keep a trailing slash."""
    section = readme.split("## 目錄結構", 1)[1] if "## 目錄結構" in readme else ""
    block = re.search(r"```\n(.*?)```", section, re.DOTALL)
    paths: set[str] = set()
    stack: list[str] = []
    for line in (block[1] if block else "").splitlines():
        marker = re.search(r"[├└]── ", line)
        if not marker:
            continue
        depth = marker.start() // 4
        name = re.split(r"[\s#]", line[marker.end():], maxsplit=1)[0]
        del stack[depth:]
        stack.append(name.rstrip("/"))
        paths.add("/".join(stack) + ("/" if name.endswith("/") else ""))
    return paths


def settings_environment_variables(root: Path) -> list[str]:
    """Environment variable names that ``backend/settings.py`` reads."""
    source = (root / "backend" / "settings.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'(?:env\.get\(|_positive_int\(\s*env,\s*)"([A-Z][A-Z0-9_]+)"', source)))


def inventory_errors(root: Path) -> list[str]:
    errors = []
    readme = (root / "README.md").read_text(encoding="utf-8")
    for name in settings_environment_variables(root):
        if f"`{name}`" not in readme and f"{name}=" not in readme:
            errors.append(f"README.md: environment variable {name} read by backend/settings.py is undocumented")
    listed = readme_tree_paths(readme)
    if not listed:
        return ["README.md: the 目錄結構 tree is missing"]
    for module in repository_modules(root, README_TREE_MODULES):
        if module not in listed:
            errors.append(f"README.md: 目錄結構 does not list {module}")
    for entry in sorted(listed):
        if not (root / entry.rstrip("/")).exists():
            errors.append(f"README.md: 目錄結構 lists a path that does not exist: {entry}")
    architecture = (root / "docs" / "architecture.md").read_text(encoding="utf-8")
    for module in repository_modules(root, SDD_MODULES):
        if module.rsplit("/", 1)[-1] not in architecture:
            errors.append(f"docs/architecture.md: the SDD does not place {module}")
    return errors


def document_errors(root: Path) -> list[str]:
    paths = [
        root / name
        for name in (
            "README.md",
            "AGENTS.md",
            "CLAUDE.md",
            "CHANGELOG.md",
            ".github/pull_request_template.md",
        )
    ]
    paths += sorted((root / "docs").rglob("*.md"))
    errors = []
    for path in paths:
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        errors.extend(link_errors(root, path, source))
        if path.parent == root / "docs" / "specs" and re.match(r"\d{3}-.*\.md$", path.name):
            errors.extend(spec_errors(root, path, source))
    return errors


def api_reference_errors(root: Path) -> list[str]:
    """Every route in the API contract is documented in README as `METHOD /path` (SPEC-058).

    A route matches only when the backtick closes or a query string follows, so
    documenting `GET /api/runs/summary` never stands in for `GET /api/runs`.
    """
    contract = json.loads((root / "unit_tests" / "api_contract.json").read_text(encoding="utf-8"))
    readme = (root / "README.md").read_text(encoding="utf-8")
    return [
        f"README.md: API 一覽 does not document {route}"
        for route in contract
        if not re.search("`" + re.escape(route) + r"(?:`|\?)", readme)
    ]
