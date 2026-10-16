"""Environment allow-list: the web process never retains daemon variables."""

from __future__ import annotations

from communitywatch_web.cli import scrub_environment


def test_scrub_environment_drops_everything_not_allow_listed() -> None:
    environ = {
        "PATH": "/usr/bin",
        "HOME": "/home/observer",
        "TZ": "UTC",
        "COMMUNITYD_CREDENTIAL_REF": "fake://communityd-admin",
        "COMMUNITYD_CONFIG": "/etc/communityd.toml",
        "AWS_SECRET_ACCESS_KEY": "not-a-real-secret",
        "DATABASE_URL": "postgres://example.invalid/db",
    }
    scrubbed = scrub_environment(environ)
    assert scrubbed == {"PATH": "/usr/bin", "HOME": "/home/observer", "TZ": "UTC"}
    for key in environ:
        if key not in scrubbed:
            assert (
                "CREDENTIAL" in key
                or "SECRET" in key
                or key
                in (
                    "COMMUNITYD_CONFIG",
                    "DATABASE_URL",
                )
            )
