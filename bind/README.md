# lucos Bind Config
Holds the static DNS configuration used for lucos services (and a few other side projects)

## File structure
Each zone lives in its own file in the `config/master` directory.  Zones are included by the file `master/named.conf.local`.  Global options live in `master/named.conf`

## Building
The build process is in `Dockerfile`, which installs bind and adds the configuration files.