# lucos DNS
DNS server & configuration for lucos services.

## Running
Uses docker-compose:

`docker compose up -d`

## Building

To build, run `docker compose build`

To combine building & running in a single command, run `docker compose up --build`

Configured to build in Dockerhub when a commit is pushed to the master branch in github.