"""The image must declare everything the service needs to start.

This file exists because of a real outage. The ticket-history upload endpoint
declares `UploadFile = File(...)`, which FastAPI refuses to register unless
`python-multipart` is installed — and it refuses at *app creation*, not at
request time. So a missing entry in requirements.txt did not degrade one
endpoint: the whole BFF failed to boot, and the console reported it only as
"Failed to fetch" on the login screen.

Every test passed while that was broken, because the development container
happened to have the package already. The suite was therefore testing a richer
environment than the one that ships, which is the actual defect these tests
guard against.
"""

from __future__ import annotations

import ast
import re
from importlib.metadata import PackageNotFoundError, distribution, packages_distributions
from pathlib import Path

from fastapi import routing

from app.main import create_app

APP = Path(__file__).resolve().parents[1]
REQUIREMENTS = APP.parent / "requirements.txt"


def _declared() -> set[str]:
    names = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        # "SQLAlchemy[asyncio]==2.0.36" -> "sqlalchemy"
        name = re.split(r"[\[<>=!;]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def _closure(roots: set[str]) -> set[str]:
    """Declared packages plus everything they pull in.

    A transitive dependency is legitimately undeclared — starlette arrives with
    fastapi and nobody should pin it separately. What is not legitimate is a
    package that arrives from neither.
    """
    seen: set[str] = set()
    queue = list(roots)
    while queue:
        name = queue.pop().lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = distribution(name).requires or []
        except PackageNotFoundError:
            continue
        for spec in requires:
            # Skip optional extras: "foo; extra == 'bar'" is not installed by
            # default, which is exactly how python-multipart was missed.
            if "extra ==" in spec:
                continue
            dep = re.split(r"[\[<>=!;(\s]", spec, maxsplit=1)[0].strip()
            if dep:
                queue.append(dep)
    return seen


def test_python_multipart_is_declared_while_an_upload_route_exists():
    """The specific failure, pinned to the thing that causes it.

    If the upload endpoint is ever removed, this test stops requiring the
    dependency rather than enforcing a pin nobody needs.
    """
    app = create_app()
    has_upload = any(
        "multipart/form-data" in (route.body_field.alias if route.body_field else "")
        or any(
            getattr(param.field_info, "media_type", None) == "multipart/form-data"
            for param in getattr(route.dependant, "body_params", [])
            if hasattr(param, "field_info")
        )
        for route in app.routes
        if isinstance(route, routing.APIRoute) and route.dependant
    )
    # Fall back to a source scan — the introspection above differs across
    # FastAPI versions and a false negative here would silently retire the test.
    if not has_upload:
        has_upload = any(
            "UploadFile" in path.read_text(encoding="utf-8")
            for path in (APP / "routers").glob("*.py")
        )

    if has_upload:
        assert "python-multipart" in _declared(), (
            "a route accepts an upload, so python-multipart must be in "
            "requirements.txt — without it FastAPI refuses to start the whole app"
        )


def test_every_package_the_app_imports_ships_in_the_image():
    """Catches the general case: something present in development, absent in the image."""
    modules: set[str] = set()
    for path in APP.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])

    import sys

    third_party = modules - set(sys.stdlib_module_names) - {"app", "__future__"}
    available = _closure(_declared())
    mapping = packages_distributions()

    missing = []
    for module in sorted(third_party):
        providers = {d.lower().replace("_", "-") for d in mapping.get(module, [])}
        if not providers:
            continue  # not an installed distribution — a local or namespace module
        if not providers & available:
            missing.append(f"{module} (from {', '.join(sorted(providers))})")

    assert not missing, (
        "these are imported but reachable from nothing in requirements.txt, so "
        f"they exist in development and not in the image: {missing}"
    )
