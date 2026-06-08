#!/bin/sh

# Make sure an rndc key exists
# stored in a volume so it can be shared with updater
KEYFILE=/etc/bind/generated-zones/rndc.key
if [ ! -f $KEYFILE ]; then
    echo "Generating new rndc key"

    # Only bother with the `key` stanza - everything else is already in the config
    rndc-confgen | head -n 5 | tail -n 4 > $KEYFILE
    echo "New rndc key stored in $KEYFILE"
fi

# Write TSIG key file (used for zone-transfer authentication with the secondary).
# The secret is stored in lucos_creds; we write it here so named.conf can include it.
TSIG_KEYFILE=/etc/bind/generated-zones/tsig.key
if [ -n "$TSIG_SECRET" ]; then
    cat > $TSIG_KEYFILE << EOF
key "lucos-tsig" {
    algorithm hmac-sha256;
    secret "$TSIG_SECRET";
};
EOF
else
    # Write a comment-only file so named.conf's include succeeds even without a secret.
    # Per-zone allow-transfer will remain { none; } in this case (see named.conf.local below).
    echo "/* No TSIG_SECRET configured — zone transfers disabled */" > $TSIG_KEYFILE
fi

# Generate named.conf.local with per-zone allow-transfer and also-notify settings.
# When TSIG_SECRET is set, each zone allows TSIG-authenticated transfers and notifies
# the secondary nameserver (lucos_dns_secondary on xwing) on every serial bump.
#
# xwing's addresses (from configy):
SECONDARY_IPV4=152.37.104.10
SECONDARY_IPV6=2a01:4b00:8598:5a00:ba27:ebff:fe83:e1ee

NAMED_CONF_LOCAL=/etc/bind/generated-zones/named.conf.local

# Helper function to emit a single zone block.
# Usage: write_zone <zone-name> <zone-file-path>
write_zone() {
    echo "zone \"$1\" {"
    echo "        type primary;"
    echo "        file \"$2\";"
    if [ -n "$TSIG_SECRET" ]; then
        echo "        allow-transfer { key \"lucos-tsig\"; };"
        echo "        also-notify { $SECONDARY_IPV4; $SECONDARY_IPV6; };"
    else
        echo "        allow-transfer { none; };"
    fi
    echo "};"
    echo ""
}

{
    write_zone "lukeblaney.co.uk" "/etc/bind/zones/lukeblaney.co.uk"
    write_zone "l42.eu"           "/etc/bind/generated-zones/l42.eu"
    write_zone "rowanblaney.co.uk" "/etc/bind/zones/rowanblaney.co.uk"
    write_zone "tfluke.uk"        "/etc/bind/zones/tfluke.uk"
    write_zone "s.l42.eu"         "/etc/bind/generated-zones/s.l42.eu"
} > $NAMED_CONF_LOCAL

# Validate generated zone files before starting named.
# A broken generated zone (e.g. stale file from an older generator) will cause
# named to silently drop the entire zone on startup, with no in-memory fallback.
# If a zone fails validation:
#   - restore from the .last-known-good backup written by config-sync on each
#     successful install, if one exists; or
#   - remove the bad file so named fails with a clean "file not found" rather
#     than a parse error that drops the apex zone.
# Static zones (lukeblaney.co.uk, rowanblaney.co.uk, tfluke.uk) are checked into
# git and are not validated here — only the generated zones can be stale/corrupted.
validate_or_restore_generated_zone() {
    zone="$1"
    zonefile="$2"
    backupfile="${zonefile}.last-known-good"

    [ -f "$zonefile" ] || return 0  # Not yet generated — skip

    if named-checkzone "$zone" "$zonefile" > /dev/null 2>&1; then
        return 0  # Zone is valid — nothing to do
    fi

    echo "WARN: Generated zone file for $zone failed validation"
    if [ -f "$backupfile" ]; then
        echo "INFO: Restoring $zone from last-known-good backup"
        cp "$backupfile" "$zonefile"
    else
        echo "ERROR: No last-known-good backup for $zone — removing invalid zone file"
        rm "$zonefile"
    fi
}

validate_or_restore_generated_zone "l42.eu"   "/etc/bind/generated-zones/l42.eu"
validate_or_restore_generated_zone "s.l42.eu" "/etc/bind/generated-zones/s.l42.eu"

/usr/sbin/named -c /etc/bind/named.conf -g
