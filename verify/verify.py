#!/usr/bin/env python3
"""Host-side verification for the Debezium plumbing proof.

Run from the project root with ``python3 verify/verify.py all``.  This file
intentionally has no third-party dependencies: it is also useful on a fresh
WSL installation where only Docker and Python are present.
"""
from __future__ import annotations

import argparse
import http.client
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
RUNS = ROOT / "runs"


class VerificationError(RuntimeError):
    pass


class Timeout(VerificationError):
    pass


def compose(*args: str, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "--project-directory", str(ROOT), *args]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode and not allow_failure:
        raise VerificationError(
            "compose command failed (%s):\nstdout:\n%s\nstderr:\n%s"
            % (" ".join(command), result.stdout, result.stderr)
        )
    return result


def psql(sql: str) -> list[str]:
    result = compose(
        "exec", "-T", "postgres", "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1",
        "-U", "dbz", "-d", "appdb", "-c", sql,
    )
    return result.stdout.splitlines()


def container_state(service: str) -> tuple[str, int | None, str]:
    result = compose("ps", "-a", "--format", "json", service)
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if not rows:
        return "missing", None, ""
    row = rows[0]
    raw_code = row.get("ExitCode")
    try:
        code = int(raw_code) if raw_code not in (None, "") else None
    except (TypeError, ValueError):
        code = None
    return str(row.get("State", "unknown")).lower(), code, str(row.get("Health") or "").lower()


def _read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    result: list[tuple[int, dict[str, Any]]] = []
    for number, line in enumerate(lines, 1):
        if not line.endswith(("\n", "\r")) and number == len(lines):
            continue  # A concurrent receiver write may leave its final line incomplete.
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            if number == len(lines):
                continue
            raise VerificationError("invalid JSON at %s:%d" % (path, number))
        if not isinstance(value, dict):
            raise VerificationError("JSON object required at %s:%d" % (path, number))
        result.append((number, value))
    return result


def read_events() -> list[tuple[int, dict[str, Any]]]:
    return _read_jsonl(LOGS / "events.jsonl")


def read_receipts() -> list[tuple[int, dict[str, Any]]]:
    return _read_jsonl(LOGS / "receipts.jsonl")


def wait_until(predicate: Callable[[], Any], timeout_s: float,
               interval_s: float = 1.0, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while True:
        last = predicate()
        if last:
            return last
        if time.monotonic() >= deadline:
            raise Timeout("timed out after %.0fs waiting for %s; last observation: %r" %
                          (timeout_s, what, last))
        time.sleep(interval_s)


def load_run(run_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    directory = RUNS / run_id
    expected_path = directory / "expected.jsonl"
    manifest_path = directory / "manifest.json"
    if not expected_path.is_file() or not manifest_path.is_file():
        raise VerificationError("missing run artifacts under %s" % directory)
    expected = [value for _, value in _read_jsonl(expected_path)]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise VerificationError("manifest is not a JSON object: %s" % manifest_path)
    return expected, manifest


def generate(run_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    compose("--profile", "tools", "run", "--rm", "-e", "RUN_ID=" + run_id, "generator")
    return load_run(run_id)


def _object(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def match(expected: dict[str, Any], envelope: dict[str, Any]) -> bool:
    source = _object(envelope.get("source"))
    if not source or envelope.get("op") != expected.get("op"):
        return False
    if source.get("schema") != expected.get("schema") or source.get("table") != expected.get("table"):
        return False
    side = "before" if expected.get("op") == "d" else "after"
    actual = _object(envelope.get(side))
    key = _object(expected.get("key"))
    if not actual or not key or actual.get("id") != key.get("id"):
        return False
    for side in ("before", "after"):
        wanted = expected.get(side)
        actual_side = envelope.get(side)
        if wanted is None:
            if actual_side is not None:
                return False
        else:
            if not isinstance(wanted, dict) or not isinstance(actual_side, dict):
                return False
            if any(actual_side.get(column) != value for column, value in wanted.items()):
                return False
    return True


def mismatch_reason(expected: dict[str, Any], envelope: dict[str, Any]) -> str:
    source = _object(envelope.get("source")) or {}
    if envelope.get("op") != expected.get("op"):
        return "op expected %r observed %r" % (expected.get("op"), envelope.get("op"))
    if source.get("schema") != expected.get("schema") or source.get("table") != expected.get("table"):
        return "table expected %s.%s observed %s.%s" % (expected.get("schema"), expected.get("table"), source.get("schema"), source.get("table"))
    side = "before" if expected.get("op") == "d" else "after"
    actual = _object(envelope.get(side)) or {}
    if actual.get("id") != (_object(expected.get("key")) or {}).get("id"):
        return "key id expected %r observed %r" % ((_object(expected.get("key")) or {}).get("id"), actual.get("id"))
    return "before/after subset differs"


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def utc_id(prefix: str) -> str:
    return "%s-%s" % (prefix, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))


class Verifier:
    def __init__(self) -> None:
        self.observations: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat(), "checks": {}}
        self.delivery_samples: list[float] = []

    def note(self, name: str, passed: bool, evidence: str, **details: Any) -> bool:
        if not passed and "inspect logs/events.jsonl" not in evidence:
            evidence += "; inspect logs/events.jsonl and docker compose logs debezium"
        self.observations["checks"][name] = {"passed": passed, "evidence": evidence, **details}
        print(("PASS " if passed else "FAIL ") + name + ": " + evidence)
        return passed

    def _fail(self, name: str, error: Exception) -> bool:
        return self.note(name, False, "%s; inspect logs/events.jsonl and docker compose logs debezium" % error)

    def receipt_headers(self) -> None:
        for _, receipt in read_receipts():
            if receipt.get("kind") == "event":
                self.observations["first_event_receipt_headers"] = receipt.get("headers", {})
                return

    def wait_expected(self, expected: list[dict[str, Any]], timeout: float) -> list[tuple[int, dict[str, Any]]]:
        def found() -> list[tuple[int, dict[str, Any]]] | bool:
            events = read_events()
            return events if all(any(match(item, event) for _, event in events) for item in expected) else False
        return wait_until(found, timeout, what="all expected events")

    def expected_detail(self, expected: list[dict[str, Any]], events: list[tuple[int, dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], list[tuple[int, dict[str, Any]]]]]]:
        detail, matched = [], []
        for item in expected:
            hits = [(line, event) for line, event in events if match(item, event)]
            candidate = next((event for _, event in events if (_object(event.get("source")) or {}).get("schema") == item.get("schema") and (_object(event.get("source")) or {}).get("table") == item.get("table")), None)
            detail.append({"seq": item.get("seq"), "matched": bool(hits), "lines": [line for line, _ in hits], "first_mismatch": None if hits else (mismatch_reason(item, candidate) if candidate else "no event from expected table")})
            matched.append((item, hits))
        return detail, matched

    def duplicates(self, events: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
        seen: dict[tuple[Any, ...], list[int]] = {}
        for line, event in events:
            source = _object(event.get("source")) or {}
            side = "before" if event.get("op") == "d" else "after"
            row = _object(event.get(side)) or {}
            key = (source.get("lsn"), source.get("schema"), source.get("table"), event.get("op"), row.get("id"))
            seen.setdefault(key, []).append(line)
        return [{"key": list(key), "lines": lines} for key, lines in seen.items() if len(lines) > 1]

    def delivery_times(self, matched: list[tuple[dict[str, Any], list[tuple[int, dict[str, Any]]]]]) -> dict[str, Any]:
        receipts = [receipt for _, receipt in read_receipts() if receipt.get("kind") == "event"]
        samples: list[float] = []
        for item, hits in matched:
            if item.get("op") == "r":
                continue
            for line, event in hits[:1]:
                if line > len(receipts):
                    continue
                timestamp = (_object(event.get("source")) or {}).get("ts_ms")
                received_at = receipts[line - 1].get("received_at")
                if timestamp is None or received_at is None:
                    continue
                try:
                    received = datetime.fromisoformat(str(received_at).replace("Z", "+00:00"))
                    samples.append(received.timestamp() * 1000 - float(timestamp))
                except (KeyError, TypeError, ValueError):
                    continue
        self.delivery_samples.extend(samples)
        if not samples:
            return {"label": "local observation, not a benchmark", "count": 0}
        return {"label": "local observation, not a benchmark", "count": len(samples), "min_ms": min(samples), "median_ms": statistics.median(samples), "max_ms": max(samples)}

    def health(self) -> bool:
        try:
            def get(url: str) -> tuple[int, str]:
                with urllib.request.urlopen(url, timeout=5) as response:
                    return response.status, response.read().decode("utf-8")
            receiver_status, receiver_body = get("http://127.0.0.1:8080/health")
            debezium_status, _ = get("http://127.0.0.1:8081/q/health")
            decoded = json.loads(receiver_body)
            tail = subprocess.run(["tail", "-n", "1", str(LOGS / "events.jsonl")], capture_output=True, text=True, check=True)
            json.loads(tail.stdout)
            ok = receiver_status == 200 and decoded.get("status") == "UP" and debezium_status == 200 and (LOGS / "events.jsonl").is_file()
            return self.note("health", ok, "receiver=%s status=%s, debezium=%s, tail is JSON" % (receiver_status, decoded.get("status"), debezium_status))
        except (OSError, ValueError, urllib.error.URLError, subprocess.CalledProcessError) as error:
            return self._fail("health", error)

    def snapshot(self) -> bool:
        try:
            wanted = json.loads((ROOT / "postgres" / "expected_snapshot.json").read_text(encoding="utf-8"))
            def counts() -> dict[str, int] | bool:
                actual: dict[str, int] = {}
                valid = True
                for _, event in read_events():
                    if event.get("op") == "r":
                        source = _object(event.get("source")) or {}
                        table = "%s.%s" % (source.get("schema"), source.get("table"))
                        actual[table] = actual.get(table, 0) + 1
                        # Debezium 3.x marks snapshot rows with several values, not only true/last.
                        valid = valid and source.get("snapshot") in {
                            "true", "first", "last", "first_in_data_collection", "last_in_data_collection",
                        }
                return actual if valid and all(actual.get(key, 0) >= value for key, value in wanted.items()) else False
            actual = wait_until(counts, 90, what="initial snapshot counts")
            exact = {key: actual.get(key, 0) for key in wanted}
            return self.note("snapshot", exact == wanted, "fresh-volume precondition; expected=%s observed=%s" % (wanted, exact), counts=actual)
        except Exception as error:
            return self._fail("snapshot", error)

    def scenario(self, run_id: str | None = None) -> tuple[bool, str | None]:
        run_id = run_id or utc_id("scn")
        try:
            expected, manifest = generate(run_id)
            events = self.wait_expected(expected, 60)
            detail, matched = self.expected_detail(expected, events)
            missing = [row for row in detail if not row["matched"]]
            before_bad = []
            for item, hits in matched:
                if item.get("op") in {"u", "d"} and any(not isinstance(event.get("before"), dict) for _, event in hits):
                    before_bad.append(item.get("seq"))
            t1 = [hits for item, hits in matched if item.get("tx") == "T1"]
            t1_events = [hit for hits in t1 for hit in hits]
            txids = {(_object(event.get("source")) or {}).get("txId") for _, event in t1_events}
            tx_ok = len(t1_events) == 4 and len(txids) == 1 and None not in txids
            timing = self.delivery_times(matched)
            for row in detail:
                status = "matched" if row["matched"] else "missing"
                suffix = "" if row["matched"] else "; first mismatch: " + str(row["first_mismatch"])
                print("  expected seq=%s %s%s" % (row["seq"], status, suffix))
            ok = not missing and not before_bad and tx_ok
            evidence = "run=%s matched=%d/%d; T1 envelopes=%d txIds=%s" % (run_id, len(detail) - len(missing), len(detail), len(t1_events), sorted(map(str, txids)))
            self.note("scenario", ok, evidence, run_id=run_id, manifest=manifest, expected=detail, replica_identity_before_missing=before_bad, timing=timing)
            return ok, run_id
        except Exception as error:
            return self._fail("scenario", error), None

    def bulk(self, run_id: str) -> bool:
        try:
            expected, _ = load_run(run_id)
            self.wait_expected(expected, 60)  # establishes captured stream catch-up before inspection
            marker = sql_literal(run_id)
            pending = int(psql("select count(*) from bulk.pending_records where run_id=%s" % marker)[0])
            jobs = int(psql("select count(*) from bulk.batch_jobs where run_id=%s" % marker)[0])
            processed = int(psql("select count(*) from bulk.pending_records where run_id=%s and processed" % marker)[0])
            no_bulk_before = not any((_object(event.get("source")) or {}).get("schema") == "bulk" for _, event in read_events())
            baseline = len(read_events())
            psql("update bulk.batch_jobs set status='DONE' where run_id=%s" % marker)
            psql("update timecritical.customers set name=name where external_ref='cust-' || %s" % marker)
            def after_marker() -> list[tuple[int, dict[str, Any]]] | bool:
                events = read_events()
                return events if any(line > baseline and event.get("op") == "u" and (_object(event.get("source")) or {}).get("table") == "customers" for line, event in events) else False
            events = wait_until(after_marker, 60, what="time-critical marker event after bulk update")
            between_bulk = [line for line, event in events if line > baseline and (_object(event.get("source")) or {}).get("schema") == "bulk"]
            ok = pending == 2 and jobs == 1 and processed == 1 and no_bulk_before and not between_bulk
            return self.note("bulk", ok, "run=%s pending=%d jobs=%d processed=%d; marker crossed after line %d" % (run_id, pending, jobs, processed, baseline), bulk_event_lines=between_bulk)
        except Exception as error:
            return self._fail("bulk", error)

    def outage_short(self) -> bool:
        name, run_id = "outage-short", utc_id("short")
        started = time.monotonic()
        states: list[tuple[float, str, int | None]] = []
        try:
            compose("stop", "receiver")
            expected, _ = generate(run_id)
            for _ in range(10):
                state, code, _ = container_state("debezium")
                states.append((time.monotonic() - started, state, code))
                time.sleep(1)  # Contractual 10-second outage; not proof of delivery.
            compose("start", "receiver")
            def delivered_while_running() -> list[tuple[int, dict[str, Any]]] | bool:
                state, code, _ = container_state("debezium")
                states.append((time.monotonic() - started, state, code))
                if state != "running":
                    raise VerificationError("debezium stopped during short outage recovery: %s exit=%s" % (state, code))
                events = read_events()
                return events if all(any(match(item, event) for _, event in events) for item in expected) else False
            wait_until(delivered_while_running, 90, what="all short-outage expected events")
            state, code, _ = container_state("debezium")
            states.append((time.monotonic() - started, state, code))
            running = all(state == "running" for _, state, _ in states)
            duplicates = self.duplicates(read_events())
            return self.note(name, running, "recovered in %.1fs; debezium remained running=%s; duplicates=%d" % (time.monotonic() - started, running, len(duplicates)), states=states, duplicates=duplicates)
        except Exception as error:
            return self._fail(name, error)
        finally:
            compose("start", "receiver", allow_failure=True)

    def outage_long(self) -> bool:
        name, run_id = "outage-long", utc_id("long")
        observed: list[tuple[str, int | None, str]] = []
        try:
            compose("stop", "receiver")
            expected, _ = generate(run_id)
            started = time.monotonic()
            since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            def engine_stopped() -> tuple[str, int | None, str] | bool:
                state, code, health = container_state("debezium")
                observed.append((state, code, health))
                if state == "exited" or health == "unhealthy":
                    return state, code, health
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8081/q/health", timeout=3) as response:
                        healthy = response.status == 200
                except urllib.error.HTTPError:
                    healthy = False
                except (urllib.error.URLError, OSError, http.client.HTTPException):
                    # Connection refused/reset while the engine or Quarkus transitions: keep polling.
                    return False
                return (state, code, health) if not healthy else False

            state, code, health = wait_until(
                engine_stopped, 150, interval_s=2,
                what="Debezium engine to stop after finite HTTP retry budget",
            )
            elapsed = time.monotonic() - started
            # Only this outage's log lines, so the attempt count is per run and not cumulative.
            logs = compose("logs", "--no-color", "--since", since, "debezium").stdout.splitlines()
            failed_sends = sum("Failed to send event" in line for line in logs)
            engine_failure = next((line for line in logs if "ERROR" in line and "Engine has failed" in line), None)
            attempts_exceeded = next((line for line in logs if "Exceeded maximum number of attempts" in line), None)
            compose("start", "receiver")
            wait_until(lambda: self._receiver_up(), 60, what="receiver health")
            compose("restart", "debezium")
            wait_until(self._all_healthy, 90, what="postgres, receiver, and debezium healthy after recovery")
            self.wait_expected(expected, 120)
            duplicates = self.duplicates(read_events())
            evidence = ("engine stopped after %d send attempts in %.1f s; container stayed running with health DOWN/unhealthy; "
                        "recovered by explicit `docker compose restart debezium`, not by sink retries; duplicates=%d" %
                        (failed_sends, elapsed, len(duplicates)))
            return self.note(name, True, evidence, elapsed_seconds=elapsed,
                             terminal_state_health_exit=(state, health, code), observed_states=observed,
                             failed_send_attempts=failed_sends, engine_failure_line=engine_failure,
                             attempts_exceeded_line=attempts_exceeded, debezium_logs=logs,
                             duplicates=duplicates)
        except Timeout as error:
            state, code, health = container_state("debezium")
            logs = compose("logs", "--no-color", "debezium", allow_failure=True).stdout.splitlines()
            return self.note(name, False, "%s; observed state=%s health=%s exit=%s; inspect logs/events.jsonl and docker compose logs debezium" % (error, state, health, code), observed_states=observed, terminal_state_health_exit=(state, health, code), debezium_logs=logs)
        except Exception as error:
            return self._fail(name, error)
        finally:
            compose("start", "receiver", allow_failure=True)
            if not self._all_healthy():
                compose("restart", "debezium", allow_failure=True)

    @staticmethod
    def _receiver_up() -> bool:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            return False

    def restart(self) -> bool:
        name, pre, post = "restart", utc_id("pre"), utc_id("post")
        try:
            wait_until(self._all_healthy, 60, what="stack healthy before restart check")
            expected, _ = generate(pre)
            self.wait_expected(expected, 90)
            snapshots_before = sum(1 for _, event in read_events() if event.get("op") == "r")
            lines_before = len(read_events())
            compose("restart")
            wait_until(lambda: self._all_healthy(), 120, what="postgres, receiver, and debezium healthy")
            marker = sql_literal(pre)
            customer = int(psql("select count(*) from timecritical.customers where external_ref='cust-' || %s" % marker)[0])
            bulk_rows = int(psql("select count(*) from bulk.pending_records where run_id=%s" % marker)[0])
            snapshots_after = sum(1 for _, event in read_events() if event.get("op") == "r")
            post_expected, _ = generate(post)
            self.wait_expected(post_expected, 90)
            duplicates = self.duplicates(read_events())
            ok = customer == 1 and bulk_rows == 2 and snapshots_before == snapshots_after
            return self.note(name, ok, "pre-lines=%d customer=%d bulk=%d snapshot=%d->%d; duplicates=%d" % (lines_before, customer, bulk_rows, snapshots_before, snapshots_after, len(duplicates)), duplicates=duplicates)
        except Exception as error:
            return self._fail(name, error)

    def _all_healthy(self) -> bool:
        states = [container_state(service)[0] for service in ("postgres", "receiver", "debezium")]
        if states != ["running", "running", "running"] or not self._receiver_up():
            return False
        try:
            with urllib.request.urlopen("http://127.0.0.1:8081/q/health", timeout=3) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            return False

    def write_report(self) -> Path:
        self.receipt_headers()
        self.observations["finished_at"] = datetime.now(timezone.utc).isoformat()
        if self.delivery_samples:
            self.observations["delivery_times"] = {"label": "local observation, not a benchmark", "min_ms": min(self.delivery_samples), "median_ms": statistics.median(self.delivery_samples), "max_ms": max(self.delivery_samples)}
        RUNS.mkdir(exist_ok=True)
        path = RUNS / ("verify-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
        path.write_text(json.dumps(self.observations, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    sub.add_parser("snapshot")
    scenario = sub.add_parser("scenario")
    scenario.add_argument("--run-id")
    bulk = sub.add_parser("bulk")
    bulk.add_argument("--run-id", required=True)
    sub.add_parser("outage-short")
    sub.add_parser("outage-long")
    sub.add_parser("restart")
    sub.add_parser("all")
    args = parser.parse_args()
    verifier = Verifier()
    if args.command == "health": ok = verifier.health()
    elif args.command == "snapshot": ok = verifier.snapshot()
    elif args.command == "scenario": ok, _ = verifier.scenario(args.run_id)
    elif args.command == "bulk": ok = verifier.bulk(args.run_id)
    elif args.command == "outage-short": ok = verifier.outage_short()
    elif args.command == "outage-long": ok = verifier.outage_long()
    elif args.command == "restart": ok = verifier.restart()
    else:
        names = ["health", "snapshot", "scenario", "bulk", "outage-short", "outage-long", "restart"]
        results = [verifier.health(), verifier.snapshot()]
        scenario_ok, run_id = verifier.scenario()
        results.append(scenario_ok)
        results.append(verifier.bulk(run_id) if run_id else verifier.note("bulk", False, "scenario did not create a run; inspect logs/events.jsonl and docker compose logs debezium"))
        results.extend([verifier.outage_short(), verifier.outage_long(), verifier.restart()])
        ok = all(results)
        print("SUMMARY:")
        for name, result in zip(names, results):
            print("  %-14s %s" % (name, "PASS" if result else "FAIL"))
        if verifier.delivery_samples:
            print("delivery time (local observation, not a benchmark): min=%.1fms median=%.1fms max=%.1fms" % (min(verifier.delivery_samples), statistics.median(verifier.delivery_samples), max(verifier.delivery_samples)))
        else:
            print("delivery time (local observation, not a benchmark): no matched live samples")
    report = verifier.write_report()
    print("report: %s" % report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
