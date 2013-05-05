#lucos DNS
A lightweight dynamic DNS tool for updating bind config.

## Dependancies
* perl
* [perl Config::Simple](https://metacpan.org/module/Config::Simple)
* A bind server running on the same machine

## Setup
The script depends on a config file being added to the root of the project called "config".  It consists of key/value pairs - each pair on a separate line with whitespace separating the key from the value.
The following settings are needed:
* **apikey**: A key used by machines to show that they're trusted.
* **serverfilename**: The path of the bind config file to edit (the user running the program needs permission to read and write to/from this file)
* **emailaddr**: Email address of person responsible for the zone. Format is mailbox-name.domain.com (like in a standard bind config)

## Running
The web server is designed to be run within lucos_services, but can be run standalone by running ./server.pl port servicedomain where port is the TCP port number the server should listen to and servicedomain is the domain of a running lucos_services instance.

## Using
Each machine wishing to register itself with the service should send a HTTP PUT request to "/servers/<machinename>", where <machinename> is the name of the machine sending the message.  Each machine using the system should have a unique machinename.  The resulting domain for the machine will be machinename.domainname (where domainname is the one specified in the config file).
Requests must include a HTTP Authorization header whose value is "key <apikey>" where <apikey> is the value specified in the config file.

## Proxy Servers
Requests shouldn't be routed through any proxy servers as this will result in the proxy server's IP address being recorded rather than the original machine.
The only exception to this is where the proxy server: a) is running on the same machine as this script, and b) adds an X-Forwarded-For header to the request

## Security
Security here is minimal.  Using it outside of networks you control is inadvisable, as the current setup is vunerable to reply attacks.  Consider running any requests on external networks over https to avoid evesdropping.
