import os, sys, time, subprocess
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

CONFIGY_ENDPOINT = "https://configy.l42.eu"

session = requests.Session()
session.headers.update({
	"User-Agent": SYSTEM,
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

def get_hosts_zone(hosts):
	template = jinja_env.get_template("s.l42.eu.jinja")
	return template.render(hosts=hosts, serial=int(time.time()))

def get_systems_zone(domain, host_domain_lookup):
	raw_systems = fetch_from_configy("/systems/subdomain/%s" % domain)
	cname_records = []
	a_records = []
	for system in raw_systems:
		subdomain = system['domain']
		host = system['hosts'][0]
		host_domain = host_domain_lookup[host]['domain']
		if subdomain == domain: # The root record can't be a CNAME
			a_records.append({
				"from": "@",
				"to": host_domain_lookup[host]['ipv4'],
			})
		elif subdomain == "dns."+domain: # Don't CNAME DNS records to avoid too many extra lookups
			a_records.append({
				"from": "dns",
				"to": host_domain_lookup[host]['ipv4'],
			})
			a_records.append({ # Also add a secondary DNS record
				"from": "dns2",
				"to": host_domain_lookup[host]['ipv4'],
			})
		else:
			cname_records.append({
				"from": subdomain.removesuffix("."+domain),
				"to": host_domain.removesuffix("."+domain),
			})
	template = jinja_env.get_template("%s.jinja" % domain)
	return template.render(a_records=a_records, cname_records=cname_records, serial=int(time.time()))

def strip_serial_lines(content):
	return "\n".join(
		line
		for line in content.splitlines()
		if not line.rstrip().endswith("; Serial")
	)

def update_zone_config(zone, new_content):
	zonefile_path = Path(ZONES_PATH+zone)
	try:
		with zonefile_path.open("r") as zonefile:
			existing_content = zonefile.read()
	except FileNotFoundError:
		existing_content = ""
	if strip_serial_lines(new_content) == strip_serial_lines(existing_content):
		return
	zonefile_path.write_text(new_content)
	print("DNS Config changed for zone %s, reloading bind"%zone, flush=True)
	subprocess.run(["rndc", "reload", zone]) 
	updateLoganne(type="dns_config_changed", humanReadable="DNS config updated for zone %s"%zone)

if __name__ == "__main__":
	try:
		hosts = fetch_from_configy("/hosts")
		host_domain_lookup = {}
		for host in hosts:
			host_domain_lookup[host['id']] = host
		config_by_zone = {}
		config_by_zone['s.l42.eu'] = get_hosts_zone(hosts)
		config_by_zone['l42.eu'] = get_systems_zone('l42.eu', host_domain_lookup)
		for zone, content in config_by_zone.items():
			update_zone_config(zone, content)
		updateScheduleTracker(success=True, frequency=(15 * 60))
	except Exception as e:
		error_message = f"Sync failure: {e}"
		updateScheduleTracker(success=False, message=error_message, frequency=(15 * 60))
		print(error_message, flush=True)
		raise e