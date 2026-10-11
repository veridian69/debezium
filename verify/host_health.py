#!/usr/bin/env python3
"""Resolve host health URLs through Compose, and check them without event logs."""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HEALTH_PATHS = {"receiver": "/health", "debezium": "/q/health"}


class ConfigurationError(RuntimeError):
    pass


def health_urls(config: dict[str, Any]) -> dict[str, str]:
    """Select the published TCP port for each service's internal HTTP port."""
    urls = {}
    try:
        for service, path in HEALTH_PATHS.items():
            ports = config["services"][service].get("ports", [])
            matches = [port for port in ports
                       if str(port.get("target")) == "8080"
                       and port.get("protocol", "tcp") == "tcp"]
            if len(matches) != 1:
                raise ConfigurationError("%s requires one published TCP port for target 8080" % service)
            published = str(matches[0].get("published", ""))
            if not published.isdecimal() or not 1 <= int(published) <= 65535:
                raise ConfigurationError("%s has no fixed valid published port for target 8080" % service)
            urls[service] = "http://127.0.0.1:%s%s" % (published, path)
    except (KeyError, TypeError, AttributeError) as error:
        raise ConfigurationError("invalid Compose services/ports configuration: %s" % error) from error
    return urls


def load_health_urls() -> dict[str, str]:
    """Resolve .env, environment overrides and Compose override files once."""
    command = ["docker", "compose", "--project-directory", str(ROOT), "config", "--format", "json"]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as error:
        raise ConfigurationError("cannot resolve Compose configuration: %s" % error) from error
    if result.returncode:
        raise ConfigurationError("cannot resolve Compose configuration: %s" %
                                 (result.stderr.strip() or result.stdout.strip() or "exit %d" % result.returncode))
    try:
        config = json.loads(result.stdout)
    except ValueError as error:
        raise ConfigurationError("Compose config did not return valid JSON: %s" % error) from error
    return health_urls(config)


def main() -> int:
    try:
        urls = load_health_urls()
    except ConfigurationError as error:
        print("health configuration error: %s" % error, file=sys.stderr)
        return 1
    ok = True
    for service, url in urls.items():
        print("%s:" % service)
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                print(response.read().decode("utf-8"))
                if response.status != 200:
                    print("%s health failed: HTTP %s" % (service, response.status), file=sys.stderr)
                    ok = False
        except (OSError, urllib.error.URLError, http.client.HTTPException, UnicodeError) as error:
            print("%s health failed: %s" % (service, error), file=sys.stderr)
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
