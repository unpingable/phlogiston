from __future__ import annotations

import ast
import email.parser
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import venv
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"
PYTHON_REQUIRES = ">=3.12,<3.13"


@dataclass(frozen=True)
class Distribution:
    directory: str
    name: str
    import_name: str
    dependencies: tuple[str, ...]
    allowed_imports: frozenset[str]
    forbidden_imports: frozenset[str]
    forbidden_internal_parts: frozenset[str]
    # Import names of sibling distributions this one depends on.
    dependency_imports: frozenset[str] = frozenset()
    # Declared dependencies that are not built from this repository and are
    # therefore absent from the local wheelhouse (installed with --no-deps).
    external_dependencies: frozenset[str] = frozenset()

    @property
    def root(self) -> Path:
        return ROOT / "packages" / self.directory


DISTRIBUTIONS = (
    Distribution(
        directory="community-model",
        name="community-model",
        import_name="community_model",
        dependencies=(),
        allowed_imports=frozenset({"community_model"}),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "signer",
                "signing",
                "transport",
                "writer",
            }
        ),
    ),
    Distribution(
        directory="community-space-model",
        name="community-space-model",
        import_name="community_space_model",
        dependencies=("community-model==0.1.0",),
        allowed_imports=frozenset({"community_model", "community_space_model"}),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "signer",
                "signing",
                "storage",
                "transport",
                "writer",
            }
        ),
    ),
    Distribution(
        directory="community-space-projection",
        name="community-space-projection",
        import_name="community_space_projection",
        dependencies=(
            "community-model==0.1.0",
            "community-space-model==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_model",
                "community_space_model",
                "community_space_projection",
            }
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "rank",
                "ranking",
                "server",
                "signer",
                "signing",
                "storage",
                "transport",
                "web",
                "writer",
            }
        ),
        dependency_imports=frozenset({"community_space_model"}),
    ),
    Distribution(
        directory="community-space-wire",
        name="community-space-wire",
        import_name="community_space_wire",
        dependencies=(
            "community-model==0.1.0",
            "community-space-model==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_model",
                "community_space_model",
                "community_space_wire",
            }
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "projection",
                "rank",
                "ranking",
                "server",
                "signer",
                "signing",
                "storage",
                "transport",
                "web",
                "writer",
            }
        ),
        dependency_imports=frozenset({"community_space_model"}),
    ),
    Distribution(
        directory="community-space-artifact",
        name="community-space-artifact",
        import_name="community_space_artifact",
        dependencies=(
            "community-model==0.1.0",
            "community-space-model==0.1.0",
            "community-space-projection==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_model",
                "community_space_artifact",
                "community_space_model",
                "community_space_projection",
            }
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "cache",
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "rank",
                "ranking",
                "recommendation",
                "renderer",
                "server",
                "signer",
                "signing",
                "storage",
                "transport",
                "web",
                "wire",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {"community_space_model", "community_space_projection"}
        ),
    ),
    Distribution(
        directory="community-space-renderer",
        name="community-space-renderer",
        import_name="community_space_renderer",
        dependencies=("community-space-artifact==0.1.0",),
        allowed_imports=frozenset(
            {"community_space_artifact", "community_space_renderer"}
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "auth",
                "authority",
                "cache",
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "fetch",
                "membership",
                "moderator",
                "network",
                "rank",
                "ranking",
                "recommendation",
                "server",
                "session",
                "signer",
                "signing",
                "storage",
                "transport",
                "web",
                "wire",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_model",
                "community_space_projection",
            }
        ),
    ),
    Distribution(
        directory="community-space-feed",
        name="community-space-feed",
        import_name="community_space_feed",
        dependencies=("community-space-artifact==0.1.0",),
        allowed_imports=frozenset({"community_space_artifact", "community_space_feed"}),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "auth",
                "authority",
                "cache",
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "fetch",
                "membership",
                "moderator",
                "network",
                "rank",
                "ranking",
                "recommendation",
                "renderer",
                "server",
                "session",
                "signer",
                "signing",
                "storage",
                "transport",
                "web",
                "wire",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_model",
                "community_space_projection",
            }
        ),
    ),
    Distribution(
        directory="community-space-prototype",
        name="community-space-prototype",
        import_name="community_space_prototype",
        dependencies=(
            "community-space-feed==0.1.0",
            "community-space-renderer==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_space_feed",
                "community_space_prototype",
                "community_space_renderer",
            }
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "auth",
                "authority",
                "cache",
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "fetch",
                "membership",
                "moderator",
                "network",
                "rank",
                "ranking",
                "recommendation",
                "server",
                "session",
                "signer",
                "signing",
                "storage",
                "transport",
                "web",
                "wire",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_feed",
                "community_space_model",
                "community_space_projection",
                "community_space_renderer",
            }
        ),
    ),
    Distribution(
        directory="community-space-comprehension",
        name="community-space-comprehension",
        import_name="community_space_comprehension",
        dependencies=("community-space-prototype==0.1.0",),
        allowed_imports=frozenset(
            {
                "community_space_comprehension",
                "community_space_prototype",
            }
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "ai",
                "analytics",
                "auth",
                "authority",
                "browser",
                "cache",
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "fetch",
                "membership",
                "model_inference",
                "moderator",
                "network",
                "rank",
                "ranking",
                "recommendation",
                "server",
                "session",
                "signer",
                "signing",
                "storage",
                "telemetry",
                "transport",
                "web",
                "wire",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_comprehension",
                "community_space_feed",
                "community_space_model",
                "community_space_projection",
                "community_space_prototype",
                "community_space_renderer",
            }
        ),
    ),
    Distribution(
        directory="community-space-demo",
        name="community-space-demo",
        import_name="community_space_demo",
        dependencies=(
            "community-space-artifact==0.1.0",
            "community-space-comprehension==0.1.0",
            "community-space-feed==0.1.0",
            "community-space-prototype==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_comprehension",
                "community_space_demo",
                "community_space_feed",
                "community_space_prototype",
            }
        ),
        forbidden_imports=frozenset(
            {
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "analytics",
                "auth",
                "authority",
                "cache",
                "client",
                "credential",
                "credentials",
                "database",
                "db",
                "fetch",
                "membership",
                "moderator",
                "network",
                "rank",
                "ranking",
                "recommendation",
                "server",
                "session",
                "signer",
                "signing",
                "telemetry",
                "transport",
                "web",
                "wire",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_comprehension",
                "community_space_demo",
                "community_space_feed",
                "community_space_model",
                "community_space_projection",
                "community_space_prototype",
                "community_space_renderer",
            }
        ),
    ),
    Distribution(
        directory="communitywatch",
        name="communitywatch",
        import_name="communitywatch",
        dependencies=("community-model==0.1.0",),
        allowed_imports=frozenset({"community_model", "communitywatch"}),
        forbidden_imports=frozenset(),
        forbidden_internal_parts=frozenset(
            {
                "authority_client",
                "authority_writer",
                "credential",
                "credentials",
                "signer",
                "signing",
                "writer",
            }
        ),
    ),
    Distribution(
        directory="communitywatch-spaces-alpha",
        name="communitywatch-spaces-alpha",
        import_name="communitywatch_spaces_alpha",
        dependencies=("community-model==0.1.0",),
        allowed_imports=frozenset({"community_model", "communitywatch_spaces_alpha"}),
        # SA9a permits bounded stdlib HTTP. SA10b additionally permits sqlite3
        # for the observer-only evidence ledger; it remains forbidden from the
        # authority-bearing package dependency graph.
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "ssl",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "authority_client",
                "authority_writer",
                "signer",
                "signing",
                "transport",
                "writer",
            }
        ),
    ),
    Distribution(
        directory="communitywatch-space-publisher",
        name="communitywatch-space-publisher",
        import_name="communitywatch_space_publisher",
        dependencies=(
            "community-model==0.1.0",
            "community-space-model==0.1.0",
            "community-space-projection==0.1.0",
            "community-space-wire==0.1.0",
            "community-space-artifact==0.1.0",
            "community-space-feed==0.1.0",
            "communitywatch-spaces-alpha==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_model",
                "community_space_artifact",
                "community_space_feed",
                "community_space_model",
                "community_space_projection",
                "community_space_wire",
                "communitywatch_space_publisher",
                "communitywatch_spaces_alpha",
            }
        ),
        forbidden_imports=frozenset(
            {
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "sqlite3",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "authority_client",
                "authority_writer",
                "credential",
                "credentials",
                "fetch",
                "network",
                "server",
                "signer",
                "signing",
                "transport",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_feed",
                "community_space_model",
                "community_space_projection",
                "community_space_wire",
                "communitywatch_spaces_alpha",
            }
        ),
    ),
    Distribution(
        directory="communitywatch-live",
        name="communitywatch-live",
        import_name="communitywatch_live",
        dependencies=(
            "community-model==0.1.0",
            "community-space-model==0.1.0",
            "community-space-artifact==0.1.0",
            "communitywatch-spaces-alpha==0.1.0",
            "communitywatch-space-publisher==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_model",
                "community_space_artifact",
                "community_space_model",
                "communitywatch_live",
                "communitywatch_space_publisher",
                "communitywatch_spaces_alpha",
            }
        ),
        forbidden_imports=frozenset({"sqlite3"}),
        forbidden_internal_parts=frozenset(
            {
                "authority_client",
                "authority_writer",
                "credential",
                "credentials",
                "signer",
                "signing",
                "writer",
            }
        ),
        dependency_imports=frozenset(
            {
                "community_space_artifact",
                "community_space_feed",
                "community_space_model",
                "community_space_projection",
                "community_space_wire",
                "communitywatch_space_publisher",
                "communitywatch_spaces_alpha",
            }
        ),
    ),
    Distribution(
        directory="communitywatch-archive",
        name="communitywatch-archive",
        import_name="communitywatch_archive",
        dependencies=(
            "community-model==0.1.0",
            "communitywatch==0.1.0",
            "duckdb>=1.5,<2",
            "pyarrow>=25,<26",
        ),
        allowed_imports=frozenset(
            {
                "community_model",
                "communitywatch",
                "communitywatch_archive",
                "duckdb",
                "pyarrow",
            }
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "http",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "ssl",
                "urllib",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "authority_client",
                "authority_writer",
                "credential",
                "credentials",
                "server",
                "signer",
                "signing",
                "transport",
                "web",
                "writer",
            }
        ),
        dependency_imports=frozenset({"communitywatch"}),
        external_dependencies=frozenset({"duckdb", "pyarrow"}),
    ),
    Distribution(
        directory="communitywatch-web",
        name="communitywatch-web",
        import_name="communitywatch_web",
        dependencies=(
            "community-model==0.1.0",
            "communitywatch==0.1.0",
        ),
        # The web surface serves HTTP and percent-decodes paths, so http and
        # urllib.parse are inherent; it may not open sockets or TLS itself.
        allowed_imports=frozenset(
            {"community_model", "communitywatch", "communitywatch_web"}
        ),
        forbidden_imports=frozenset(
            {
                "dbm",
                "ftplib",
                "imaplib",
                "poplib",
                "smtplib",
                "socket",
                "ssl",
            }
        ),
        forbidden_internal_parts=frozenset(
            {
                "archive",
                "authority_client",
                "authority_writer",
                "credential",
                "credentials",
                "duckdb",
                "manifest",
                "parquet",
                "signer",
                "signing",
                "transport",
                "writer",
            }
        ),
        dependency_imports=frozenset({"communitywatch"}),
    ),
    Distribution(
        directory="communityd",
        name="communityd",
        import_name="communityd",
        dependencies=(
            "community-model==0.1.0",
            "community-space-model==0.1.0",
            "community-space-wire==0.1.0",
        ),
        allowed_imports=frozenset(
            {
                "community_model",
                "community_space_model",
                "community_space_wire",
                "communityd",
            }
        ),
        # PCV0 gives the sole authority writer a private SQLite operation
        # journal for idempotency and ambiguous-write recovery. It remains
        # forbidden from observer/projection stores and packages.
        forbidden_imports=frozenset(),
        forbidden_internal_parts=frozenset(
            {"duckdb", "manifest", "observer", "parquet", "projection", "sqlite"}
        ),
        dependency_imports=frozenset({"community_space_model", "community_space_wire"}),
    ),
    Distribution(
        directory="community-submit",
        name="community-submit",
        import_name="community_submit",
        dependencies=("community-model==0.1.0",),
        # Participant-side only: it may not import the community's authority
        # writer, the observer, or the archive tool.  Its whole job is one
        # submission record in the participant's own repository.
        allowed_imports=frozenset({"community_model", "community_submit"}),
        forbidden_imports=frozenset({"sqlite3"}),
        forbidden_internal_parts=frozenset(
            {
                "admission",
                "authority",
                "authority_writer",
                "duckdb",
                "manifest",
                "moderation",
                "observer",
                "parquet",
                "projection",
                "signer",
                "signing",
                "sqlite",
            }
        ),
    ),
)


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"command failed ({result.returncode}): {command!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _normalized_requirement(requirement: str) -> str:
    compact = re.sub(r"\s+", "", requirement)
    match = re.match(r"^([A-Za-z0-9_.-]+?)([<>=!~].*)?$", compact)
    assert match is not None
    specifiers = match.group(2) or ""
    return match.group(1) + ",".join(sorted(specifiers.split(",")))


def _wheel_metadata(archive: zipfile.ZipFile) -> email.message.Message:
    metadata_paths = [
        name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
    ]
    assert len(metadata_paths) == 1
    raw = archive.read(metadata_paths[0]).decode("utf-8")
    return email.parser.Parser().parsestr(raw)


@pytest.fixture(scope="session")
def wheelhouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("package-builds")
    output = build_root / "wheelhouse"
    output.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
    )

    for distribution in DISTRIBUTIONS:
        source_copy = build_root / distribution.directory
        shutil.copytree(
            distribution.root,
            source_copy,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.egg-info",
                ".pytest_cache",
                ".ruff_cache",
                "build",
                "dist",
            ),
        )
        _run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(output),
            ],
            cwd=source_copy,
            environment=environment,
        )

    assert len(tuple(output.glob("*.whl"))) == len(DISTRIBUTIONS)
    return output


def test_root_configuration_is_not_a_distribution() -> None:
    root_configuration = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "project" not in root_configuration
    assert "build-system" not in root_configuration


@pytest.mark.parametrize("distribution", DISTRIBUTIONS, ids=lambda item: item.name)
def test_project_metadata_declares_only_the_permitted_edge(
    distribution: Distribution,
) -> None:
    configuration = tomllib.loads(
        (distribution.root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["build-system"] == {
        "requires": ["setuptools>=68", "wheel"],
        "build-backend": "setuptools.build_meta",
    }
    assert configuration["project"]["name"] == distribution.name
    assert configuration["project"]["version"] == VERSION
    assert configuration["project"]["requires-python"] == PYTHON_REQUIRES
    assert configuration["project"]["dependencies"] == list(distribution.dependencies)
    assert configuration["tool"]["setuptools"]["package-dir"] == {"": "src"}
    assert configuration["tool"]["setuptools"]["packages"]["find"] == {
        "where": ["src"],
        "include": [distribution.import_name, f"{distribution.import_name}.*"],
        "namespaces": False,
    }


@pytest.mark.parametrize("distribution", DISTRIBUTIONS, ids=lambda item: item.name)
def test_source_imports_follow_the_one_way_graph(distribution: Distribution) -> None:
    source_root = distribution.root / "src" / distribution.import_name
    source_files = sorted(source_root.rglob("*.py"))
    assert source_files, f"no Python sources found under {source_root}"

    violations: list[str] = []
    dynamic_imports: list[str] = []
    forbidden_internal: list[str] = []
    permitted = set(sys.stdlib_module_names) | set(distribution.allowed_imports)

    for source_file in source_files:
        source_parts = {
            part.lower()
            for part in source_file.relative_to(source_root).with_suffix("").parts
        }
        forbidden_path_parts = source_parts & distribution.forbidden_internal_parts
        if forbidden_path_parts:
            forbidden_internal.append(
                f"{source_file.relative_to(ROOT)} has forbidden module parts "
                f"{sorted(forbidden_path_parts)!r}"
            )
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        for node in ast.walk(tree):
            imported_roots: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported_roots = tuple(
                    alias.name.partition(".")[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported_roots = (node.module.partition(".")[0],)

            for imported_root in imported_roots:
                if (
                    imported_root not in permitted
                    or imported_root in distribution.forbidden_imports
                ):
                    relative = source_file.relative_to(ROOT)
                    violations.append(
                        f"{relative}:{node.lineno} imports {imported_root!r}"
                    )

            if isinstance(node, ast.ImportFrom) and node.module:
                module_parts = {part.lower() for part in node.module.split(".")}
                forbidden_parts = module_parts & distribution.forbidden_internal_parts
                if forbidden_parts:
                    forbidden_internal.append(
                        f"{source_file.relative_to(ROOT)}:{node.lineno} imports "
                        f"forbidden internal parts {sorted(forbidden_parts)!r}"
                    )

            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {
                    "__import__",
                    "import_module",
                }:
                    dynamic_imports.append(
                        f"{source_file.relative_to(ROOT)}:{node.lineno} "
                        f"calls {node.func.id}"
                    )
                elif (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                ):
                    dynamic_imports.append(
                        f"{source_file.relative_to(ROOT)}:{node.lineno} calls import_module"
                    )

    assert not violations, "forbidden package imports:\n" + "\n".join(violations)
    assert not dynamic_imports, (
        "dynamic imports evade the boundary graph:\n" + "\n".join(dynamic_imports)
    )
    assert not forbidden_internal, (
        "forbidden internal authority/boundary modules:\n"
        + "\n".join(forbidden_internal)
    )


@pytest.mark.parametrize("distribution", DISTRIBUTIONS, ids=lambda item: item.name)
def test_built_wheel_has_exact_metadata_and_namespace(
    distribution: Distribution, wheelhouse: Path
) -> None:
    wheel_prefix = distribution.name.replace("-", "_")
    candidates = tuple(wheelhouse.glob(f"{wheel_prefix}-{VERSION}-*.whl"))
    assert len(candidates) == 1

    with zipfile.ZipFile(candidates[0]) as archive:
        names = archive.namelist()
        metadata = _wheel_metadata(archive)
        metadata_name = _normalized_distribution_name(metadata["Name"])
        assert metadata_name == _normalized_distribution_name(distribution.name)
        assert metadata["Version"] == VERSION
        assert frozenset(
            specifier.strip() for specifier in metadata["Requires-Python"].split(",")
        ) == frozenset(specifier.strip() for specifier in PYTHON_REQUIRES.split(","))
        metadata_dependencies = tuple(
            _normalized_requirement(requirement)
            for requirement in metadata.get_all("Requires-Dist", [])
        )
        assert metadata_dependencies == tuple(
            _normalized_requirement(requirement)
            for requirement in distribution.dependencies
        )

        top_level_entries = {name.partition("/")[0] for name in names}
        import_roots = {
            name
            for name in top_level_entries
            if not name.endswith(".dist-info") and not name.endswith(".data")
        }
        assert import_roots == {distribution.import_name}
        assert f"{distribution.import_name}/py.typed" in names
        if distribution.import_name == "community_model":
            expected_schemas = {
                f"community_model/schemas/app.phlogiston.community.{record}.json"
                for record in ("profile", "submit", "admission", "modAction")
            }
            assert expected_schemas <= set(names)
            assert "community_model/UNICODE-LICENSE.txt" in names
        assert not any("/tests/" in name or name.startswith("tests/") for name in names)
        assert not any(name.endswith((".pyc", ".pyo")) for name in names)
        sibling_imports = {
            item.import_name
            for item in DISTRIBUTIONS
            if item.import_name != distribution.import_name
        }
        leaked_siblings = {
            part
            for name in names
            for part in PurePosixPath(name).parts
            if part in sibling_imports
        }
        assert not leaked_siblings

        wheel_paths = [name for name in names if name.endswith(".dist-info/WHEEL")]
        assert len(wheel_paths) == 1
        wheel_metadata = email.parser.Parser().parsestr(
            archive.read(wheel_paths[0]).decode("utf-8")
        )
        assert wheel_metadata["Root-Is-Purelib"].lower() == "true"
        assert "py3-none-any" in wheel_metadata.get_all("Tag", [])


@pytest.mark.parametrize("distribution", DISTRIBUTIONS, ids=lambda item: item.name)
def test_wheel_installs_without_a_forbidden_sibling(
    distribution: Distribution, wheelhouse: Path, tmp_path: Path
) -> None:
    environment_root = tmp_path / "environment"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment_root)
    binary_directory = "Scripts" if os.name == "nt" else "bin"
    environment_python = environment_root / binary_directory / "python"

    environment = os.environ.copy()
    environment.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    install = [
        str(environment_python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
    ]
    if distribution.external_dependencies:
        # DuckDB/PyArrow are not built from this repository, so the clean
        # wheelhouse cannot provide them; install the internal edges first
        # and the archive tool without its external dependencies.
        internal = [
            item
            for item in DISTRIBUTIONS
            if item.import_name != distribution.import_name
            and item.import_name
            in (distribution.dependency_imports | {"community_model"})
        ]
        _run(
            [*install, *[f"{item.name}=={VERSION}" for item in internal]],
            cwd=tmp_path,
            environment=environment,
        )
        _run(
            [*install, "--no-deps", f"{distribution.name}=={VERSION}"],
            cwd=tmp_path,
            environment=environment,
        )
    else:
        _run(
            [*install, f"{distribution.name}=={VERSION}"],
            cwd=tmp_path,
            environment=environment,
        )

    boundary_modules = (
        "community_model",
        "community_space_model",
        "community_space_projection",
        "community_space_wire",
        "community_space_artifact",
        "community_space_renderer",
        "community_space_feed",
        "community_space_prototype",
        "community_space_comprehension",
        "community_space_demo",
        "communitywatch",
        "communitywatch_spaces_alpha",
        "communitywatch_space_publisher",
        "communitywatch_live",
        "communitywatch_archive",
        "communityd",
        "duckdb",
        "pyarrow",
    )
    present = {
        "community_model",
        distribution.import_name,
        *distribution.dependency_imports,
    }
    expected = {name: name in present for name in boundary_modules}
    smoke_test = "\n".join(
        (
            "import importlib.util",
            f"expected = {expected!r}",
            "actual = {name: importlib.util.find_spec(name) is not None for name in expected}",
            "assert actual == expected, (actual, expected)",
            f"__import__({distribution.import_name!r})",
            "__import__('community_model')",
            *(
                f"__import__({name!r})"
                for name in sorted(distribution.dependency_imports)
            ),
        )
    )
    _run(
        [str(environment_python), "-I", "-c", smoke_test],
        cwd=tmp_path,
        environment=environment,
    )


def test_web_read_only_store_cannot_mutate_sqlite(tmp_path: Path) -> None:
    """The web layer opens the observer database URI mode=ro + query_only."""

    import sqlite3

    from communitywatch import ObserverStore, ReadOnlyStoreError

    path = tmp_path / "observer.sqlite3"
    ObserverStore(
        path,
        community_did="did:web:community.invalid",
        administrator_did="did:web:admin.invalid",
    )
    store = ObserverStore(
        path,
        community_did="did:web:community.invalid",
        read_only=True,
    )
    # Application-level write paths refuse before touching the database.
    with pytest.raises(ReadOnlyStoreError):
        store.rebuild()
    with pytest.raises(ReadOnlyStoreError):
        store.ingest_batch(())
    # The connection itself enforces PRAGMA query_only on top of mode=ro.
    with store.read_connection() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO meta(key, value) VALUES ('k', 'v')")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute(
                "UPDATE meta SET value = '9' WHERE key = 'schema_version'"
            )


def test_live_alpha_observer_node_process_has_no_authority_write_surface() -> None:
    """The secret-bearing live observer is read-only and custody-isolated."""

    root = ROOT / "packages" / "communitywatch-alpha-node"
    package = json.loads((root / "package.json").read_text())
    dependencies = set(package["dependencies"])
    assert "juniper-communityd-alpha" not in dependencies
    assert "communityd" not in dependencies

    sources = "\n".join(
        path.read_text() for path in sorted((root / "src").glob("*.ts"))
    )
    assert "com.atproto.space.createRecord" not in sources
    assert "com.atproto.space.putRecord" not in sources
    assert "com.atproto.space.deleteRecord" not in sources
    assert "communityd" not in sources
    assert "getDelegationToken" in sources
    assert "getSpaceCredential" in sources
    assert "getRepo" in sources
    assert "listRepoOps" in sources


def test_juniper_bootstrap_is_one_time_and_not_an_observer_dependency() -> None:
    """The authority bootstrap cannot leak into read or community-write paths."""

    root = ROOT / "packages" / "juniper-bootstrap-alpha-node"
    package = json.loads((root / "package.json").read_text())
    assert package["name"] == "juniper-bootstrap-alpha"
    assert not any(
        name in package["dependencies"]
        for name in ("communitywatch", "communityd", "juniper-commons-live")
    )

    sources = "\n".join(
        path.read_text() for path in sorted((root / "src").glob("*.ts"))
    )
    assert "com.atproto.lexicon.schema" in sources
    assert "com.atproto.simplespace.createSpace" in sources
    assert "com.atproto.space.createRecord" not in sources

    for dependent in (
        ROOT / "apps" / "juniper-live",
        ROOT / "packages" / "communitywatch-alpha-node",
        ROOT / "packages" / "communitywatch-live",
        ROOT / "packages" / "communityd-alpha-node",
    ):
        text = "\n".join(
            path.read_text()
            for path in sorted(dependent.rglob("*"))
            if path.is_file()
            and path.suffix in {".json", ".py", ".toml", ".ts"}
            and "node_modules" not in path.parts
            and "dist" not in path.parts
            and "build" not in path.parts
        )
        assert "juniper-bootstrap-alpha" not in text


def test_juniper_fallback_pds_is_isolated_from_existing_pds() -> None:
    """The disposable PDS has exact names, port, image, and secret placeholders."""

    root = ROOT / "deploy" / "juniper-live-alpha"
    environment = (root / "pds.env.example").read_text()
    caddy = (root / "Caddyfile.fragment").read_text()
    service = (root / "juniper-spaces-pds.service").read_text()
    readme = (root / "README.md").read_text()
    installer = (root / "install-pds.sh").read_text()

    assert "PDS_HOSTNAME=juniper-pds.sp00ky.net" in environment
    assert "PDS_PORT=3001" in environment
    assert environment.count("GENERATE_ON_HOST") == 5
    assert "juche.social" not in environment
    assert "PDS_CRAWLERS=\n" in environment

    expected_names = {
        "juniper-pds.sp00ky.net",
        "authority.juniper-pds.sp00ky.net",
        "author.juniper-pds.sp00ky.net",
        "moderator.juniper-pds.sp00ky.net",
    }
    assert expected_names <= set(re.findall(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", caddy))
    assert "*." not in caddy
    assert "on_demand" not in caddy
    assert "127.0.0.1:3001" in caddy

    assert "juniper-spaces-pds-alpha" in service
    assert "pds-spaces-alpha@sha256:bc8ad28e" in readme
    assert "port 3000" in readme
    assert "not read" in readme
    assert 'docker pull "$image" >/dev/null' in installer
    assert "docker create" in installer
    assert "docker start" not in installer
    assert '--volume "$data:/pds"' in installer
    assert '--volume "$image_data:/app/data"' in installer
    assert "--read-only" in installer
    assert "--cap-drop ALL" in installer
    assert 'chmod 600 "$environment"' in installer
    assert 'cat "$environment"' not in installer


def test_juniper_account_provisioner_does_not_persist_session_tokens() -> None:
    source = (ROOT / "deploy/juniper-live-alpha/provision-accounts.py").read_text()

    assert "accessJwt" not in source
    assert "refreshJwt" not in source
    assert "account-credentials.json" in source
    assert "O_EXCL" in source
    assert "print(json.dumps(identities" in source
