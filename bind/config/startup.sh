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

# Write TSIG key file for zone transfer authentication (primary<->secondary)
# The TSIG_SECRET env var holds the base64-encoded HMAC-SHA256 secret.
# If unset, an empty key file is written so the include in named.conf doesn't fail.
TSIG_KEYFILE=/etc/bind/generated-zones/tsig.key
if [ -n "$TSIG_SECRET" ]; then
    printf 'key "tsig-transfer" {\n    algorithm hmac-sha256;\n    secret "%s";\n};\n' "$TSIG_SECRET" > $TSIG_KEYFILE
    echo "TSIG key written to $TSIG_KEYFILE"
else
    # Empty file - tsig-transfer key will not be defined, zone transfers disabled
    : > $TSIG_KEYFILE
fi

# Generate named.conf.local based on DNS_MODE.
# DNS_MODE=secondary: BIND acts as secondary, slaving all zones from avalon primary.
# DNS_MODE=primary (or unset): BIND acts as primary for all zones.
CONF_LOCAL=/etc/bind/generated-zones/named.conf.local

if [ "${DNS_MODE}" = "secondary" ]; then
    if [ -z "$TSIG_SECRET" ]; then
        echo "ERROR: DNS_MODE=secondary requires TSIG_SECRET to be set" >&2
        exit 1
    fi

    # Create writable directory for AXFR-received zone files
    mkdir -p /etc/bind/generated-zones/secondary/

    cat > $CONF_LOCAL << 'ENDCONF'
// Secondary nameserver - all zones slaved from avalon primary via TSIG-authenticated AXFR
zone "lukeblaney.co.uk" {
    type secondary;
    primaries { 178.32.218.44 key "tsig-transfer"; };
    file "/etc/bind/generated-zones/secondary/lukeblaney.co.uk";
};

zone "l42.eu" {
    type secondary;
    primaries { 178.32.218.44 key "tsig-transfer"; };
    file "/etc/bind/generated-zones/secondary/l42.eu";
};

zone "rowanblaney.co.uk" {
    type secondary;
    primaries { 178.32.218.44 key "tsig-transfer"; };
    file "/etc/bind/generated-zones/secondary/rowanblaney.co.uk";
};

zone "tfluke.uk" {
    type secondary;
    primaries { 178.32.218.44 key "tsig-transfer"; };
    file "/etc/bind/generated-zones/secondary/tfluke.uk";
};

zone "s.l42.eu" {
    type secondary;
    primaries { 178.32.218.44 key "tsig-transfer"; };
    file "/etc/bind/generated-zones/secondary/s.l42.eu";
};
ENDCONF

    echo "Named configured as secondary (slaving from avalon 178.32.218.44)"

else
    # Primary mode (default when DNS_MODE is unset or "primary")
    if [ -n "$TSIG_SECRET" ]; then
        ALLOW_TRANSFER='allow-transfer { key "tsig-transfer"; };'
        ALSO_NOTIFY='also-notify { 152.37.104.10; 2a01:4b00:8598:5a00:ba27:ebff:fe83:e1ee; };'
    else
        ALLOW_TRANSFER='allow-transfer { none; };'
        ALSO_NOTIFY=''
    fi

    cat > $CONF_LOCAL << ENDCONF
zone "lukeblaney.co.uk" {
    type primary;
    file "/etc/bind/zones/lukeblaney.co.uk";
    $ALLOW_TRANSFER
    $ALSO_NOTIFY
};

zone "l42.eu" {
    type primary;
    file "/etc/bind/generated-zones/l42.eu";
    $ALLOW_TRANSFER
    $ALSO_NOTIFY
};

zone "rowanblaney.co.uk" {
    type primary;
    file "/etc/bind/zones/rowanblaney.co.uk";
    $ALLOW_TRANSFER
    $ALSO_NOTIFY
};

zone "tfluke.uk" {
    type primary;
    file "/etc/bind/zones/tfluke.uk";
    $ALLOW_TRANSFER
    $ALSO_NOTIFY
};

zone "s.l42.eu" {
    type primary;
    file "/etc/bind/generated-zones/s.l42.eu";
    $ALLOW_TRANSFER
    $ALSO_NOTIFY
};
ENDCONF

    ALLOW_LABEL="${TSIG_SECRET:+TSIG-restricted}"
    echo "Named configured as primary (allow-transfer: ${ALLOW_LABEL:-none})"
fi

/usr/sbin/named -c /etc/bind/named.conf -g
