# lucos DNS
DNS tooling & configuration for lucos services.

Consists of 2 components:
* **bind** - a DNS server, with config for lucos services
* **lucos DNS Updater** - a tool for dynamically updating DNS addresses

See each component's README.md for more details

## Running
Uses docker-compose:

`APIKEY=apikeygoeshere ROUTERIP=127.0.0.1 docker-compose up -d`

**APIKEY** is the key used to authenticate incoming PUT requests to the updater
**ROUTERIP** is the IP address of a trusted reverse proxy server running in front of the updater 

## Building

To build all componets, run `docker-compose build`

To combine building & running in a single command, run `APIKEY=apikeygoeshere ROUTERIP=127.0.0.1 docker-compose --build up`

Both components are configured to build in Dockerhub when a commit is pushed to the master branch in github.