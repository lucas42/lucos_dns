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


/usr/sbin/named -c /etc/bind/named.conf -g