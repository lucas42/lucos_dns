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
# Note: xwing's IPv6 (2a01:4b00:8598:5a00:ba27:ebff:fe83:e1ee) is NOT included in
# also-notify because the lucos_dns_bind container runs on a Docker bridge network
# with no IPv6 routing — NOTIFY to IPv6 always fails with "network unreachable".
# IPv4 NOTIFY is sufficient; BIND secondary falls back to SOA polling for any missed
# NOTIFYs. See lucos_dns#105.

NAMED_CONF_LOCAL=/etc/bind/generated-zones/named.conf.local

# Helper function to emit a single zone block.
# Usage: write_zone <zone-name> <zone-file-path>
write_zone() {
    echo "zone \"$1\" {"
    echo "        type primary;"
    echo "        file \"$2\";"
    if [ -n "$TSIG_SECRET" ]; then
        echo "        allow-transfer { key \"lucos-tsig\"; };"
        echo "        also-notify { $SECONDARY_IPV4; };"
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


/usr/sbin/named -c /etc/bind/named.conf -g
