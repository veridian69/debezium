"""Host port and health failure checks; no Docker daemon required."""
import contextlib
import io
import json
import subprocess
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from verify import host_health, verify


def configuration():
    return {"services": {
        "receiver": {"ports": [{"target": 8080, "published": "18080", "protocol": "tcp", "host_ip": "127.0.0.1"}]},
        "debezium": {"ports": [{"target": 8080, "published": "18081", "protocol": "tcp", "host_ip": "127.0.0.1"}]},
    }}


def response(status=200):
    result = MagicMock()
    result.__enter__.return_value.status = status
    result.__enter__.return_value.read.return_value = b'{"status":"UP"}'
    return result


class HostHealthTests(unittest.TestCase):
    def test_nondefault_published_ports_and_unrelated_mappings(self):
        config = configuration()
        config["services"]["receiver"]["ports"].extend([
            {"target": 8080, "published": "19080", "protocol": "udp"},
            {"target": 9000, "published": "19000"},
        ])
        self.assertEqual(host_health.health_urls(config), {
            "receiver": "http://127.0.0.1:18080/health",
            "debezium": "http://127.0.0.1:18081/q/health",
        })

    def test_missing_or_nonfixed_published_port_is_a_configuration_error(self):
        for ports in ([], [{"target": 8080}], [{"target": 8080, "published": "18080-18090"}],
                      [{"target": 8080, "published": "0"}]):
            with self.subTest(ports=ports):
                config = configuration()
                config["services"]["receiver"]["ports"] = ports
                with self.assertRaisesRegex(host_health.ConfigurationError, "receiver"):
                    host_health.health_urls(config)

    def test_compose_resolution_failure_and_invalid_output(self):
        results = [subprocess.CompletedProcess([], 1, "", "bad interpolation"),
                   subprocess.CompletedProcess([], 0, "not JSON", ""),
                   subprocess.CompletedProcess([], 0, "{}", "")]
        for result in results:
            with self.subTest(result=result), patch.object(host_health.subprocess, "run", return_value=result):
                with self.assertRaises(host_health.ConfigurationError):
                    host_health.load_health_urls()
        with patch.object(host_health.subprocess, "run", side_effect=FileNotFoundError("docker")):
            with self.assertRaisesRegex(host_health.ConfigurationError, "cannot resolve"):
                host_health.load_health_urls()

    def test_verifier_resolves_once_and_polls_nondefault_urls(self):
        result = subprocess.CompletedProcess([], 0, json.dumps(configuration()), "")
        with patch.object(host_health.subprocess, "run", return_value=result) as run, \
             patch.object(verify, "container_state", return_value=("running", 0, "healthy")), \
             patch.object(host_health.urllib.request, "urlopen", side_effect=lambda *a, **kw: response()) as get:
            verifier = verify.Verifier()
            self.assertTrue(verifier._receiver_up())
            self.assertTrue(verifier._all_healthy())
        run.assert_called_once_with(
            ["docker", "compose", "--project-directory", str(host_health.ROOT), "config", "--format", "json"],
            capture_output=True, text=True)
        self.assertEqual([call.args[0] for call in get.call_args_list], [
            "http://127.0.0.1:18080/health", "http://127.0.0.1:18080/health",
            "http://127.0.0.1:18081/q/health",
        ])

    def test_health_cli_checks_both_endpoints_and_returns_failure(self):
        urls = host_health.health_urls(configuration())
        for failure in (urllib.error.URLError("connection refused"), response(503)):
            with self.subTest(failure=failure), \
                 patch.object(host_health, "load_health_urls", return_value=urls), \
                 patch.object(host_health.urllib.request, "urlopen", side_effect=[failure, response()]) as get, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(host_health.main(), 1)
                self.assertEqual(get.call_count, 2)

    def test_health_cli_succeeds_without_reading_event_logs(self):
        with patch.object(host_health, "load_health_urls", return_value=host_health.health_urls(configuration())), \
             patch.object(host_health.urllib.request, "urlopen", side_effect=lambda *a, **kw: response()), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(host_health.main(), 0)

    def test_cli_configuration_errors_are_concise_and_nonzero(self):
        for module in (host_health, verify):
            stderr = io.StringIO()
            with self.subTest(module=module.__name__), \
                 patch.object(module, "load_health_urls", side_effect=host_health.ConfigurationError("missing mapping")), \
                 patch.object(verify.sys, "argv", ["verify.py", "health"]), \
                 contextlib.redirect_stderr(stderr):
                self.assertEqual(module.main(), 1)
                self.assertIn("configuration error", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
