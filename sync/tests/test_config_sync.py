"""
ADR-0011 consumer tests for config-sync.py.

Exercises the real lucos_loganne_pythonclient (>=2.0.0) and
lucos_schedule_tracker_pythonclient (>=2.0.0) against a stubbed HTTP
transport — no real network calls leave the test process.

Reference: https://github.com/lucas42/lucos/blob/main/docs/adr/0011-consumer-tests-real-shared-library-interface.md
"""
import json
import os
import subprocess
import importlib.util
from pathlib import Path

import pytest
import requests
import responses as rsps

# Set required env vars BEFORE importing config-sync.
# config-sync imports loganne and schedule_tracker at module level; both
# clients sys.exit() if their endpoint env vars are absent.
os.environ.setdefault("SYSTEM", "lucos_dns")
os.environ.setdefault("LOGANNE_ENDPOINT", "http://fake-loganne/events")
os.environ.setdefault("SCHEDULE_TRACKER_ENDPOINT", "http://fake-tracker/v2/report-status")
os.environ.setdefault("CONFIGY_ENDPOINT", "http://fake-configy")
os.environ.setdefault("ZONES_PATH", "/tmp/")

# config-sync.py has a hyphenated filename — use importlib to load it.
_HERE = Path(__file__).parent
_SPEC = importlib.util.spec_from_file_location(
    "config_sync", _HERE.parent / "config-sync.py"
)
cs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cs)

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

FIXTURE_HOSTS = [
    {
        "id": "xwing",
        "domain": "xwing.s.l42.eu",
        "ipv4": "1.2.3.4",
        "ipv6": "2001:db8::1",
        "ipv4_nat": None,
    },
    {
        "id": "salvare",
        "domain": "salvare.s.l42.eu",
        "ipv4": "5.6.7.8",
        "ipv6": None,
        "ipv4_nat": "10.0.0.2",
    },
]

FIXTURE_HOST_LOOKUP = {h["id"]: h for h in FIXTURE_HOSTS}

FIXTURE_SYSTEMS = [
    {"subdomain": "photos", "hosts": ["xwing"]},
    {"subdomain": "dns",    "hosts": ["xwing"]},
    {"subdomain": "",       "hosts": ["salvare"]},
]

# Systems fixture that also includes a dns2 entry on a distinct host (salvare),
# used to verify dns2 glue is derived from its own system data, not the dns host.
FIXTURE_SYSTEMS_WITH_DNS2 = FIXTURE_SYSTEMS + [
    {"subdomain": "dns2", "hosts": ["salvare"]},
]

# ---------------------------------------------------------------------------
# get_hosts_zone — pure function (no HTTP stubs required)
# ---------------------------------------------------------------------------


class TestGetHostsZone:
    def test_ipv4_records_present(self):
        output = cs.strip_serial_lines(cs.get_hosts_zone(FIXTURE_HOSTS, "s.l42.eu"))
        assert "1.2.3.4" in output
        assert "5.6.7.8" in output

    def test_ipv6_record_present(self):
        output = cs.strip_serial_lines(cs.get_hosts_zone(FIXTURE_HOSTS, "s.l42.eu"))
        assert "2001:db8::1" in output

    def test_ipv4_nat_record_present(self):
        output = cs.strip_serial_lines(cs.get_hosts_zone(FIXTURE_HOSTS, "s.l42.eu"))
        assert "salvare-v4" in output
        assert "10.0.0.2" in output

    def test_host_ids_appear_in_output(self):
        output = cs.strip_serial_lines(cs.get_hosts_zone(FIXTURE_HOSTS, "s.l42.eu"))
        assert "xwing" in output
        assert "salvare" in output

    def test_host_outside_zone_is_excluded(self):
        other = {
            "id": "ext",
            "domain": "ext.example.com",
            "ipv4": "9.9.9.9",
            "ipv6": None,
            "ipv4_nat": None,
        }
        output = cs.get_hosts_zone(FIXTURE_HOSTS + [other], "s.l42.eu")
        assert "9.9.9.9" not in output


# ---------------------------------------------------------------------------
# get_systems_zone — stubs CONFIGY_ENDPOINT via responses
# ---------------------------------------------------------------------------


class TestGetSystemsZone:
    @rsps.activate
    def test_cname_for_regular_subdomain(self):
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # photos → CNAME to xwing.s (host domain xwing.s.l42.eu minus .l42.eu suffix)
        assert "photos" in output
        assert "xwing.s" in output

    @rsps.activate
    def test_a_records_for_dns_subdomain(self):
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # dns → A record pointing at xwing's IP
        assert "1.2.3.4" in output

    @rsps.activate
    def test_aaaa_record_for_dns_subdomain(self):
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # dns → AAAA record because xwing has ipv6
        assert "2001:db8::1" in output

    @rsps.activate
    def test_a_record_for_dns2_from_own_host(self):
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS_WITH_DNS2)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # dns2 is on salvare (5.6.7.8) — must NOT inherit dns's host (xwing, 1.2.3.4)
        assert "dns2" in output
        assert "5.6.7.8" in output

    @rsps.activate
    def test_dns2_does_not_inherit_dns_host_ip(self):
        # Arrange: dns on xwing (1.2.3.4), dns2 on salvare (5.6.7.8)
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS_WITH_DNS2)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # Count occurrences: xwing's IP should appear exactly once (for dns), not twice
        assert output.count("1.2.3.4") == 1

    @rsps.activate
    def test_no_aaaa_for_dns2_when_host_has_no_ipv6(self):
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS_WITH_DNS2)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # salvare has no ipv6 in the fixture — dns2 AAAA must not appear
        # The only AAAA in output should be for dns (xwing's IPv6)
        aaaa_lines = [line for line in output.splitlines() if "AAAA" in line and "dns2" in line]
        assert aaaa_lines == []

    @rsps.activate
    def test_a_record_for_root_subdomain(self):
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # empty subdomain → root A record pointing at salvare's IP
        assert "5.6.7.8" in output


# ---------------------------------------------------------------------------
# validate_zone — unit tests using mocked subprocess
# (named-checkzone is not available in the CI test container)
# ---------------------------------------------------------------------------


class TestValidateZone:
    def test_returns_true_for_valid_zone(self, monkeypatch):
        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=0, stdout="OK\n", stderr="")
        monkeypatch.setattr(cs.subprocess, "run", fake_run)
        valid, error = cs.validate_zone("l42.eu", "$TTL 300\n@ IN SOA l42.eu. bind.l42.eu. (1 604800 86400 2419200 60)\n")
        assert valid is True
        assert error is None

    def test_returns_false_for_invalid_zone(self, monkeypatch):
        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="dns2.l42.eu: CNAME and other data\n")
        monkeypatch.setattr(cs.subprocess, "run", fake_run)
        valid, error = cs.validate_zone("l42.eu", "broken zone content\n")
        assert valid is False
        assert "CNAME" in error

    def test_uses_stderr_for_error_message(self, monkeypatch):
        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="syntax error at line 5")
        monkeypatch.setattr(cs.subprocess, "run", fake_run)
        valid, error = cs.validate_zone("l42.eu", "bad\n")
        assert "syntax error" in error

    def test_falls_back_to_stdout_when_stderr_empty(self, monkeypatch):
        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=1, stdout="some stdout error", stderr="")
        monkeypatch.setattr(cs.subprocess, "run", fake_run)
        valid, error = cs.validate_zone("l42.eu", "bad\n")
        assert "some stdout error" in error


# ---------------------------------------------------------------------------
# update_zone_config — exercises real loganne v2 client via stubbed transport
# ---------------------------------------------------------------------------


class TestUpdateZoneConfig:
    @rsps.activate
    def test_writes_zonefile_and_calls_loganne_when_zone_changes(self, tmp_path, monkeypatch):
        rsps.add(rsps.POST, "http://fake-loganne/events", status=200)
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs.subprocess, "run", lambda *args, **kwargs: None)
        monkeypatch.setattr(cs, "validate_zone", lambda zone, content: (True, None))

        cs.update_zone_config("l42.eu", "new content\n12345678; Serial")

        assert len(rsps.calls) == 1
        body = json.loads(rsps.calls[0].request.body)
        assert body["type"] == "dns_config_changed"
        assert body["level"] == "notable"
        assert "l42.eu" in body["humanReadable"]
        assert (tmp_path / "l42.eu").exists()

    @rsps.activate
    def test_no_loganne_call_when_zone_content_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs.subprocess, "run", lambda *args, **kwargs: None)
        # Write an existing zone file
        (tmp_path / "l42.eu").write_text("stable content\n11111111; Serial")
        # Call with the same stable content but a different serial — should be a no-op
        cs.update_zone_config("l42.eu", "stable content\n22222222; Serial")

        assert len(rsps.calls) == 0

    @rsps.activate
    def test_last_known_good_backup_written_on_successful_update(self, tmp_path, monkeypatch):
        rsps.add(rsps.POST, "http://fake-loganne/events", status=200)
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs.subprocess, "run", lambda *args, **kwargs: None)
        monkeypatch.setattr(cs, "validate_zone", lambda zone, content: (True, None))

        cs.update_zone_config("l42.eu", "new valid content\n12345678; Serial")

        backup = tmp_path / "l42.eu.last-known-good"
        assert backup.exists(), "last-known-good backup was not written on a valid update"
        assert cs.strip_serial_lines(backup.read_text()) == cs.strip_serial_lines("new valid content\n12345678; Serial")

    @rsps.activate
    def test_validation_failure_leaves_existing_zone_untouched(self, tmp_path, monkeypatch):
        rsps.add(rsps.POST, "http://fake-loganne/events", status=200)
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs, "validate_zone", lambda zone, content: (False, "CNAME and other data"))

        (tmp_path / "l42.eu").write_text("existing good content\n11111111; Serial")

        cs.update_zone_config("l42.eu", "new invalid content\n22222222; Serial")

        assert (tmp_path / "l42.eu").read_text() == "existing good content\n11111111; Serial"

    @rsps.activate
    def test_validation_failure_emits_dns_zone_validation_failed_loganne_event(self, tmp_path, monkeypatch):
        rsps.add(rsps.POST, "http://fake-loganne/events", status=200)
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs, "validate_zone", lambda zone, content: (False, "CNAME and other data"))

        cs.update_zone_config("l42.eu", "new invalid content\n22222222; Serial")

        assert len(rsps.calls) == 1
        body = json.loads(rsps.calls[0].request.body)
        assert body["type"] == "dns_zone_validation_failed"
        assert body["level"] == "headline"
        assert "l42.eu" in body["humanReadable"]

    def test_validation_failure_does_not_call_rndc(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs, "validate_zone", lambda zone, content: (False, "syntax error"))

        rndc_calls = []
        monkeypatch.setattr(cs.subprocess, "run", lambda args, **kwargs: rndc_calls.append(args))

        cs.update_zone_config("l42.eu", "new invalid content\n22222222; Serial")

        assert rndc_calls == [], "rndc reload must not be called when zone validation fails"


# ---------------------------------------------------------------------------
# updateScheduleTracker — exercises real schedule_tracker v2 client
# (calls the imported function exactly as config-sync.py does in __main__)
# ---------------------------------------------------------------------------


class TestUpdateScheduleTracker:
    @rsps.activate
    def test_reports_success(self):
        rsps.add(rsps.POST, "http://fake-tracker/v2/report-status", status=200)
        cs.updateScheduleTracker(success=True, job_name="config-sync", frequency=(15 * 60))

        assert len(rsps.calls) == 1
        body = json.loads(rsps.calls[0].request.body)
        assert body["status"] == "success"
        assert body["job_name"] == "config-sync"
        assert body["frequency"] == 15 * 60

    @rsps.activate
    def test_reports_failure_with_message(self):
        rsps.add(rsps.POST, "http://fake-tracker/v2/report-status", status=200)
        cs.updateScheduleTracker(
            success=False,
            job_name="config-sync",
            message="Sync failure: connection refused",
            frequency=(15 * 60),
        )

        assert len(rsps.calls) == 1
        body = json.loads(rsps.calls[0].request.body)
        assert body["status"] == "error"
        assert body["message"] == "Sync failure: connection refused"


# ---------------------------------------------------------------------------
# run_sync — cache fallback behaviour
# ---------------------------------------------------------------------------


class TestRunSync:
    """Tests for the main sync loop — configy cache fallback behaviour."""

    def test_cache_written_after_successful_fetch(self, tmp_path, monkeypatch):
        """After a successful sync, the configy payload is persisted to the cache file."""
        cache_file = tmp_path / "configy-cache.json"

        monkeypatch.setattr(cs, "CACHE_PATH", cache_file)
        monkeypatch.setattr(cs, "fetch_from_configy", lambda path: {
            "/hosts": FIXTURE_HOSTS,
            "/systems/subdomain/l42.eu": FIXTURE_SYSTEMS,
        }[path])
        monkeypatch.setattr(cs, "update_zone_config", lambda zone, content: None)
        monkeypatch.setattr(cs, "updateScheduleTracker", lambda **kwargs: None)

        cs.run_sync()

        assert cache_file.exists(), "cache file was not written after a successful sync"
        payload = json.loads(cache_file.read_text())
        assert payload["/hosts"] == FIXTURE_HOSTS
        assert payload["/systems/subdomain/l42.eu"] == FIXTURE_SYSTEMS

    def test_cache_fallback_produces_valid_zone_output(self, tmp_path, monkeypatch):
        """When configy is unreachable but a valid cache exists, zones are generated."""
        cache_file = tmp_path / "configy-cache.json"
        cache_file.write_text(json.dumps({
            "/hosts": FIXTURE_HOSTS,
            "/systems/subdomain/l42.eu": FIXTURE_SYSTEMS,
        }))

        def raise_connection_error(path):
            raise requests.exceptions.ConnectionError("DNS resolution failed")

        monkeypatch.setattr(cs, "CACHE_PATH", cache_file)
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs, "fetch_from_configy", raise_connection_error)
        monkeypatch.setattr(cs, "updateLoganne", lambda **kwargs: None)
        monkeypatch.setattr(cs, "updateScheduleTracker", lambda **kwargs: None)
        monkeypatch.setattr(cs.subprocess, "run", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "validate_zone", lambda zone, content: (True, None))

        cs.run_sync()  # Must not raise

        assert (tmp_path / "l42.eu").exists(), "l42.eu zone file not written from cache"
        assert (tmp_path / "s.l42.eu").exists(), "s.l42.eu zone file not written from cache"

    def test_no_cache_raises_on_connection_error(self, tmp_path, monkeypatch):
        """When configy is unreachable and no cache file exists, the error propagates."""
        cache_file = tmp_path / "configy-cache.json"  # deliberately not created

        def raise_connection_error(path):
            raise requests.exceptions.ConnectionError("DNS resolution failed")

        monkeypatch.setattr(cs, "CACHE_PATH", cache_file)
        monkeypatch.setattr(cs, "fetch_from_configy", raise_connection_error)
        monkeypatch.setattr(cs, "updateScheduleTracker", lambda **kwargs: None)

        with pytest.raises(requests.exceptions.ConnectionError):
            cs.run_sync()

    @rsps.activate
    def test_http_error_does_not_trigger_cache_fallback(self, tmp_path, monkeypatch):
        """HTTP 4xx/5xx from configy raises and does not fall back to the cache."""
        cache_file = tmp_path / "configy-cache.json"
        cache_file.write_text(json.dumps({
            "/hosts": FIXTURE_HOSTS,
            "/systems/subdomain/l42.eu": FIXTURE_SYSTEMS,
        }))

        rsps.add(rsps.GET, "http://fake-configy/hosts", status=503)
        rsps.add(rsps.POST, "http://fake-tracker/v2/report-status", status=200)

        monkeypatch.setattr(cs, "CACHE_PATH", cache_file)

        with pytest.raises(requests.exceptions.HTTPError):
            cs.run_sync()
