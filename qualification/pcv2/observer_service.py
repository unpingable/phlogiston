"""Real observer ingest and projection API for the isolated PCV2 harness.

Runs the unmodified ``communitywatch`` store, verifying event source and
``communitywatch-web`` projection API against the isolated PDSes. The only
harness-specific part is the transport: instead of a firehose, a loopback
control endpoint polls ``com.atproto.repo.listRecords`` on the repositories it
is told about and feeds each new record to ``VerifyingEventSource`` as a
commit claim, exactly as the phlogiston isolated harness does. Every claim is
still proven against the repository's signed commit before it is ingested.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from community_model import (
    COMMUNITY_COLLECTIONS,
    EventBatch,
    IncomingDelivery,
    RecordRef,
)
from communitywatch import ObserverStore, ProjectionQuery
from communitywatch.repoproof import extract_pds_endpoint
from communitywatch.syncclient import DidResolver, PdsClient, UrllibHttpGetter
from communitywatch.verifying import VerifiedSubjectResolver, VerifyingEventSource
from communitywatch_web.app import WebApp
from communitywatch_web.server import make_server

ADMISSION = "app.phlogiston.community.admission"
REPLY_ADMISSION = "app.phlogiston.community.replyAdmission"


def xrpc_get(origin: str, nsid: str, query: Mapping[str, str]) -> Mapping[str, object]:
    url = f"{origin}/xrpc/{nsid}?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"accept": "application/json"}), timeout=10
    ) as reply:
        return json.loads(reply.read())


class One:
    def __init__(self, item: IncomingDelivery) -> None:
        self.item = item

    def read(self, _cursor: str | None) -> EventBatch[IncomingDelivery]:
        return EventBatch(items=(self.item,), next_cursor=self.item.cursor)


class Poller:
    """Turn the current state of each watched repository into commit claims."""

    def __init__(self, resolver: DidResolver, repos: list[str]) -> None:
        self.resolver = resolver
        self.repos = repos
        self.seen: dict[str, str] = {}  # at-uri -> cid last claimed
        self.sequence = 0

    def claims(self) -> list[IncomingDelivery]:
        result: list[IncomingDelivery] = []
        for repo in self.repos:
            origin = extract_pds_endpoint(self.resolver.resolve(repo))
            rev = xrpc_get(origin, "com.atproto.sync.getLatestCommit", {"did": repo})[
                "rev"
            ]
            present: dict[str, str] = {}
            for collection in COMMUNITY_COLLECTIONS:
                page = xrpc_get(
                    origin,
                    "com.atproto.repo.listRecords",
                    {"repo": repo, "collection": collection, "limit": "100"},
                )
                for entry in page.get("records", []):
                    present[entry["uri"]] = entry["cid"]
                    if self.seen.get(entry["uri"]) == entry["cid"]:
                        continue
                    result.append(
                        self._claim(
                            repo,
                            rev,
                            "update" if entry["uri"] in self.seen else "create",
                            collection,
                            entry["uri"],
                            entry["cid"],
                        )
                    )
            for uri, cid in list(self.seen.items()):
                if uri.startswith(f"at://{repo}/") and uri not in present:
                    collection = uri.split("/")[3]
                    result.append(
                        self._claim(repo, rev, "delete", collection, uri, None)
                    )
                    del self.seen[uri]
            for uri, cid in present.items():
                self.seen[uri] = cid
        return result

    def _claim(
        self,
        repo: str,
        rev: str,
        operation: str,
        collection: str,
        uri: str,
        cid: str | None,
    ) -> IncomingDelivery:
        self.sequence += 1
        envelope: dict[str, object] = {
            "repo": repo,
            "rev": rev,
            "operation": operation,
            "collection": collection,
            "rkey": uri.rsplit("/", 1)[1],
        }
        if cid is not None:
            envelope["cid"] = cid
        return IncomingDelivery(
            source="isolated-pds-poll",
            cursor=str(self.sequence),
            source_event_time=None,
            received_at=datetime.now(UTC),
            raw_envelope=envelope,
            trust_mode="verify_repo",
            verification_outcome="unverified",
            verification_method="isolated-current-state",
            verifier_version="1",
        )


class Ingestor:
    def __init__(
        self, store: ObserverStore, resolver: DidResolver, repos: list[str]
    ) -> None:
        self.store = store
        self.poller = Poller(resolver, repos)
        self.verifier_args = {
            "did_resolver": resolver,
            "pds_client": PdsClient(UrllibHttpGetter(timeout_seconds=10)),
        }
        self.lock = threading.Lock()

    def ingest(self) -> dict[str, object]:
        with self.lock:
            verdicts: list[dict[str, object]] = []
            subjects: list[dict[str, object]] = []
            for claim in self.poller.claims():
                for verified in VerifyingEventSource(
                    One(claim), **self.verifier_args
                ).verify_delivery(claim):
                    ingested = self.store.ingest(verified)
                    envelope = verified.raw_envelope
                    assert isinstance(envelope, Mapping)
                    verdicts.append(
                        {
                            "repo": envelope.get("repo"),
                            "collection": envelope.get("collection"),
                            "rkey": envelope.get("rkey"),
                            "operation": envelope.get("operation"),
                            "cid": envelope.get("cid"),
                            "outcome": verified.verification_outcome,
                            "method": verified.verification_method,
                        }
                    )
                    # Root and reply admissions both name an exact subject post;
                    # the real runner resolves it in its resolve stage.
                    if (
                        envelope.get("collection") in (ADMISSION, REPLY_ADMISSION)
                        and verified.verification_outcome == "verified"
                        and envelope.get("operation") == "create"
                    ):
                        record = getattr(
                            ingested, "record", None
                        ) or self._admission_record(envelope)
                        subject = (
                            record.get("subject")
                            if isinstance(record, Mapping)
                            else None
                        )
                        if isinstance(subject, Mapping):
                            resolved = VerifiedSubjectResolver(
                                **self.verifier_args
                            ).resolve_exact(
                                RecordRef(
                                    uri=str(subject["uri"]), cid=str(subject["cid"])
                                )
                            )
                            self.store.record_subject_observation(
                                resolved, triggering_event_variant_key=ingested.key
                            )
                            subjects.append(
                                {
                                    "uri": subject["uri"],
                                    "cid": subject["cid"],
                                    "status": getattr(
                                        resolved.status, "value", str(resolved.status)
                                    ),
                                }
                            )
            return {"verdicts": verdicts, "subjects": subjects}

    def _admission_record(
        self, envelope: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        repo = str(envelope["repo"])
        origin = extract_pds_endpoint(self.poller.resolver.resolve(repo))
        found = xrpc_get(
            origin,
            "com.atproto.repo.getRecord",
            {
                "repo": repo,
                "collection": str(envelope["collection"]),
                "rkey": str(envelope["rkey"]),
            },
        )
        value = found.get("value")
        return value if isinstance(value, Mapping) else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plc", required=True)
    parser.add_argument("--community-did", required=True)
    parser.add_argument("--administrator-did", required=True)
    parser.add_argument("--repos", required=True, help="comma-separated DIDs to poll")
    parser.add_argument("--slug", default="isolated")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    resolver = DidResolver(UrllibHttpGetter(timeout_seconds=10), args.plc)
    store = ObserverStore(
        args.root / "observer.sqlite3",
        community_did=args.community_did,
        administrator_did=args.administrator_did,
    )
    ingestor = Ingestor(store, resolver, args.repos.split(","))
    web = WebApp(
        ProjectionQuery(store, slug=args.slug),
        community_did=args.community_did,
        slug=args.slug,
        stale_threshold_seconds=0,
    )
    projection = make_server(web, host="127.0.0.1", port=0)
    threading.Thread(target=projection.serve_forever, daemon=True).start()

    class Control(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/ingest":
                self.send_error(404)
                return
            try:
                body = json.dumps(ingestor.ingest(), sort_keys=True).encode()
                status = 200
            except Exception as exc:  # noqa: BLE001 - reported to the driver verbatim
                body = json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode()
                status = 500
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    control = ThreadingHTTPServer(("127.0.0.1", 0), Control)
    sys.stdout.write(
        json.dumps(
            {
                "projection": f"http://127.0.0.1:{projection.server_address[1]}",
                "control": f"http://127.0.0.1:{control.server_address[1]}",
            }
        )
        + "\n"
    )
    sys.stdout.flush()
    control.serve_forever()


if __name__ == "__main__":
    main()
