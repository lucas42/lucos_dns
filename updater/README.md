# lucos DNS Updater
A lightweight dynamic DNS tool for updating bind config.

## Dependancies
* perl
* [perl Config::Simple](https://metacpan.org/module/Config::Simple)
* A bind server running on the same machine

## Environment Variables
The script accepts the following environment varibles.

* **APIKEY** is the key used to authenticate incoming PUT requests to the updater.  Required.
* **ADMINEMAIL**: Email address of person responsible for the zone. Format is mailbox-name.domain.com (like in a standard bind config).  Required.
* **PORT** the tcp port to listen for http requests on.  Defaults to 80
* **ROUTERIP** is the IP address of a trusted reverse proxy server running in front of the updater.  Defaults to 127.0.0.1

## API Usage
Each machine wishing to register itself with the service should send a HTTP PUT request to "/servers/<machinename>", where <machinename> is the name of the machine sending the message.  Each machine using the system should have a unique machinename.  The resulting domain for the machine will be machinename.s.l42.eu.
Requests must include a HTTP Authorization header whose value is "key <apikey>" where <apikey> is the value specified in the above environment variable.

## Proxy Servers
Requests shouldn't be routed through proxy servers as this will result in the proxy server's IP address being recorded rather than the original machine.
The only exception to this is where the proxy server: a) has an IP address matching the environment variable ROUTERIP (defaults to 127.0.0.1), and b) adds an X-Forwarded-For header to the request

## Security
Security here is minimal.  Using it outside of networks you control is inadvisable, as the current setup is vunerable to replay attacks.  You should run any requests on external networks over https to avoid evesdropping.
