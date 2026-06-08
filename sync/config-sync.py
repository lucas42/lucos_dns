import json
import os, sys, time, subprocess, tempfile
from pathlib import Path
from loganne import updateLoganne
from schedule_tracker import updateScheduleTracker
import requests, jinja2

try:
	SYSTEM = os.environ["SYSTEM"]
except KeyError:
	sys.exit("\033[91mSYSTEM environment variable not set\033[0m")

try:
	ZONES_PATH = os.environ["ZONES_PATH"]
except KeyError:
	sys.exit("\033[91mZONES_PATH environment variable not set - should be the path of a volume to place generated zonefiles in\033[0m")

CONFIGY_ENDPOINT = os.environ.get("CONFIGY_ENDPOINT", "https://configy.l42.eu")
CACHE_PATH = Path("/var/cache/lucos_dns_sync/configy-cache.json")

session = requests.Session()
session.headers.update({
	"User-Agent": "lucos_dns_sync",
	"Accept": "application/json",
})

jinja_env = jinja2.Environment(
    loader= jinja2.FileSystemLoader('%s/templates/' % os.path.dirname(__file__)),
    lstrip_blocks=True,
    trim_blocks=True,
)

def fetch_from_configy(path):
	response = session.get(CONFIGY_ENDPOINT + path)
	response.raise_for_status()
	return response.json()

def write_configy_cache(payload):
	"""Persist configy responses to disk for use as fallback during a DNS outage.

	Written atomically: written to a temp file in the same directory, then
	renamed — so a partial write never leaves a corrupt cache file.
	"""
	CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
	tmp_fd, tmp_name = tempfile.mkstemp(dir=CACHE_PATH.parent)
	try:
		with os.fdopen(tmp_fd, 'w') as f:
			json.dump(payload, f)
		os.replace(tmp_name, CACHE_PATH)
	except Exception:
		try:
			os.unlink(tmp_name)
		except OSError:
			pass
		raise

def load_configy_cache():
	"""Load the cached configy payload from disk.

	Returns the parsed JSON dict if the cache file exists and is valid JSON,
	or None if the file does not exist or cannot be parsed.
	"""
	try:
		with CACHE_PATH.open('r') as f:
			return json.load(f)
	except (FileNotFoundError, json.JSONDecodeError):
		return None

def get_hosts_zone(hosts, zone):
	in_zone = [
		h for h in hosts
		if h.get('domain') == zone or (h.get('domain') or '').endswith('.' + zone)
	]
	template = jinja_env.get_template(f"{zone}.jinja")
	return template.render(hosts=in_zone, serial=int(time.time()))

def render_systems_zone(domain, systems, host_domain_lookup):
	"""Render the zone file for a domain from pre-fetched configy systems data."""
	cname_records = []
	a_records = []
	aaaa_records = []
	for system in systems:
		subdomain = system['subdomain']
		host = system['hosts'][0]
		host_domain = host_domain_lookup[host]['domain']
		if not subdomain: # The root record can't be a CNAME
			a_records.append({
				"from": "@",
				"to": host_domain_lookup[host]['ipv4'],
			})
		elif subdomain in ("dns", "dns2"): # Don't CNAME nameserver records — use A/AAAA glue directly
			a_records.append({
				"from": subdomain,
				"to": host_domain_lookup[host]['ipv4'],
			})
			host_ipv6 = host_domain_lookup[host].get('ipv6')
			if host_ipv6:
				aaaa_records.append({
					"from": subdomain,
					"to": host_ipv6,
				})
		else:
			cname_records.append({
				"from": subdomain,
				"to": host_domain.removesuffix("."+domain),
			})
	template = jinja_env.get_template("%s.jinja" % domain)
	return template.render(a_records=a_records, aaaa_records=aaaa_records, cname_records=cname_records, serial=int(time.time()))

def get_systems_zone(domain, host_domain_lookup):
	"""Fetch systems data from configy and render the zone file.

	Thin wrapper around render_systems_zone for callers that want to fetch
	and render in one step.
	"""
	systems = fetch_from_configy("/systems/subdomain/%s" % domain)
	return render_systems_zone(domain, systems, host_domain_lookup)

def strip_serial_lines(content):
	return "\n".join(
		line
		for line in content.splitlines()
		if not line.rstrip().endswith("; Serial")
	)

def validate_zone(zone, content):
	"""Validate zone content with named-checkzone.

	Writes content to a temp file and runs named-checkzone against it so the
	live zone file is never touched during validation.

	Returns (True, None) if valid, (False, error_message) if invalid.
	"""
	with tempfile.NamedTemporaryFile(mode='w', suffix='.zone', delete=False) as f:
		tmp_path = f.name  # assign before write so finally can always clean up
		f.write(content)
	try:
		result = subprocess.run(
			["named-checkzone", zone, tmp_path],
			capture_output=True, text=True
		)
		if result.returncode != 0:
			error = result.stderr.strip() or result.stdout.strip() or "named-checkzone returned non-zero exit code"
			return False, error
		return True, None
	finally:
		os.unlink(tmp_path)

def update_zone_config(zone, new_content):
	zonefile_path = Path(ZONES_PATH+zone)
	backup_path = Path(ZONES_PATH+zone+".last-known-good")
	try:
		with zonefile_path.open("r") as zonefile:
			existing_content = zonefile.read()
	except FileNotFoundError:
		existing_content = ""
	if strip_serial_lines(new_content) == strip_serial_lines(existing_content):
		return

	valid, error = validate_zone(zone, new_content)
	if not valid:
		error_msg = f"Zone validation failed for {zone}: {error}"
		print(error_msg, flush=True)
		updateLoganne(type="dns_zone_validation_failed", humanReadable=error_msg, level="headline")
		return

	zonefile_path.write_text(new_content)
	backup_path.write_text(new_content)
	print("DNS Config changed for zone %s, reloading bind"%zone, flush=True)
	subprocess.run(["rndc", "reload", zone])
	updateLoganne(type="dns_config_changed", humanReadable="DNS config updated for zone %s"%zone, level="notable")

def run_sync():
	try:
		try:
			hosts = fetch_from_configy("/hosts")
			systems_l42 = fetch_from_configy("/systems/subdomain/l42.eu")
		except requests.exceptions.ConnectionError:
			cache = load_configy_cache()
			if cache is None:
				print("configy unreachable and no cache available — cannot generate zone", flush=True)
				raise
			print("configy unreachable — using cached data from previous successful run", flush=True)
			hosts = cache["/hosts"]
			systems_l42 = cache["/systems/subdomain/l42.eu"]
		else:
			write_configy_cache({"/hosts": hosts, "/systems/subdomain/l42.eu": systems_l42})

		host_domain_lookup = {h['id']: h for h in hosts}
		config_by_zone = {}
		config_by_zone['s.l42.eu'] = get_hosts_zone(hosts, 's.l42.eu')
		config_by_zone['l42.eu'] = render_systems_zone('l42.eu', systems_l42, host_domain_lookup)
		for zone, content in config_by_zone.items():
			update_zone_config(zone, content)
		updateScheduleTracker(success=True, job_name="config-sync", frequency=(15 * 60))
	except Exception as e:
		error_message = f"Sync failure: {e}"
		updateScheduleTracker(success=False, job_name="config-sync", message=error_message, frequency=(15 * 60))
		print(error_message, flush=True)
		raise e

if __name__ == "__main__":
	run_sync()
