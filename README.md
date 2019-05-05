# lucos DNS
DNS tooling & configuration for lucos services.

Consists of 2 components:
* **bind** - an DNS server, with config for lucos services
* **lucos DNS Updater** - a tool for dynamically updating DNS addresses

See each component's README.md for more details

## Running
Uses docker-compose:

`APIKEY=apikeygoeshere docker-compose up -d`

**APIKEY** is the key used to authenticate incoming PUT requests to the updater

## Building

To build all componets, run `docker-compose build`

To combine building & running in a single command, run `APIKEY=apikeygoeshere docker-compose --build up`