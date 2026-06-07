"""
ADR-0011 consumer tests for config-sync.py.

Exercises the real lucos_loganne_pythonclient (>=2.0.0) and
lucos_schedule_tracker_pythonclient (>=2.0.0) against a stubbed HTTP
transport — no real network calls leave the test process.

Reference: https://github.com/lucas42/lucos/blob/main/docs/adr/0011-consumer-tests-real-shared-library-interface.md
"""
import json
import os
import importlib.util
from pathlib import Path

import pytest
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
        # dns + dns2 → A records pointing at xwing's IP
        assert "1.2.3.4" in output

    @rsps.activate
    def test_a_record_for_root_subdomain(self):
        rsps.add(rsps.GET, "http://fake-configy/systems/subdomain/l42.eu", json=FIXTURE_SYSTEMS)
        output = cs.strip_serial_lines(cs.get_systems_zone("l42.eu", FIXTURE_HOST_LOOKUP))
        # empty subdomain → root A record pointing at salvare's IP
        assert "5.6.7.8" in output


# ---------------------------------------------------------------------------
# update_zone_config — exercises real loganne v2 client via stubbed transport
# ---------------------------------------------------------------------------


class TestUpdateZoneConfig:
    @rsps.activate
    def test_writes_zonefile_and_calls_loganne_when_zone_changes(self, tmp_path, monkeypatch):
        rsps.add(rsps.POST, "http://fake-loganne/events", status=200)
        monkeypatch.setattr(cs, "ZONES_PATH", str(tmp_path) + "/")
        monkeypatch.setattr(cs.subprocess, "run", lambda *args, **kwargs: None)

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
