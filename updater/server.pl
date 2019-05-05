#!/usr/bin/perl
use IO::Socket qw(:DEFAULT :crlf);
use Config::Simple;
use HTTP::Request;     # For simple http requests
use LWP::UserAgent;
use JSON qw( decode_json ); # For decoding json

local($/) = LF;
my $port = $ARGV[0];
my $servicesdomain = $ARGV[1];

Config::Simple->import_from('config', \%Config);
my $serverfilename = $Config{serverfilename};
my $servicefilename = $Config{servicefilename};

my $apikey = $ENV{'APIKEY'};
my $emailaddr = $ENV{'ADMINEMAIL'};
if (!$apikey) { die "Missing environment variable APIKEY\n"; }
if (!$emailaddr) { die "Missing environment variable ADMINEMAIL\n"; }

# Get a list of all the services running in lucos
my $hostsurl = "http://$servicesdomain/api/hosts";
my $request = HTTP::Request->new(GET => $hostsurl);
my $ua = LWP::UserAgent->new;
my $response = $ua->request($request);
my $service_domains = decode_json( $response->content );
$nameserver = $service_domains->{'dnsupdater'};
$rootdomain = $service_domains->{'root'};
$domainname = "s.$rootdomain";

$currenthostname = `hostname -s`;
chomp($currenthostname);
%aliases = ();
while (my($host, $address) = each %service_domains) {

	if ($address eq $rootdomain) {
		$rel = "@";
	} elsif ($address =~ /\.${rootdomain}$/) {
		$rel = $address;
		$rel =~ s/\.${rootdomain}$//
	} else {
		$rel = "$address.";
	}
	$aliases{$rel} = "$currenthostname";
}

# Parse the existing bind config
my %addresses = parseServers();

# Rewrite service config to include all the CNAMES for services running in lucos
outputAllConfig();

my $server = new IO::Socket::INET (
	LocalPort => $port,
	Proto => 'tcp',
	Listen => 1,
	Reuse => 1,
);

$| = 1; # Make sure stdout isn't buffered, so output gets seen by service module



die "Could not create serveret: $!\n" unless $server;
print "Server running on port $port\n";
while($client = $server->accept()) {
   $client->autoflush(1);
	my $path;
	my %headers = ();
	my $ipaddress;
	$ipaddress = $client->peerhost;
	while(<$client>) {
		s/$CR?$LF/\n/;
		if (!(defined $path)) { 
			@parts = split(/\s/, $_);
			$method = uc(@parts[0]);
			$path = @parts[1];
		} elsif ($_ =~ m/^(.+?): (.+)$/) {
			$headers{$1} = $2;
		}
		elsif ($_ eq "\n") { last; }
	}
	if ($ipaddress == "127.0.0.1" and $headers{'X-Forwarded-For'} =~ /^[\.0-9]+$/) {
		$ipaddress = $headers{'X-Forwarded-For'};
	}
	if ($path =~ m~/servers/(\w+)~) {
		$host = $1;
		if ($method eq "PUT") {
			if ($headers{'Authorization'} ne "Key $apikey") {
				print $client "HTTP/1.1 403 Forbidden\n";
				print $client "Content-type: text/plain\n\n";
				print $client "Access denied\n";
				print STDERR "Failed attempt from $ipaddress to change host $host.\n";
				close $client;
				next;
			}
			
			# Only update if there's been a change
			if ($addresses{$host} ne $ipaddress) {
				$addresses{$host} = $ipaddress;
				print "update triggered by $host\n";
				outputAllConfig();
			}
		}
		my $address = $addresses{$host};
		if ($address) {
			print $client "HTTP/1.1 200 Found\n";
			print $client "Content-type: text/plain\n\n";
			print $client "The address for $host.$domainname is $address.\n\n";
		} else {
			print $client "HTTP/1.1 404 Server not Found\n";
			print $client "Content-type: text/plain\n\n";
			print $client "Can't find an address for $host.$domainname.\n\n";
		}
	} else {
		print $client "HTTP/1.1 404 Not Found\n";
		print $client "\n";
		print $client "Not Found\n";
		print STDERR "Not found: $path\n";
	}
	close $client;
}

sub parseServers {
	my %addresses = ();
	$file = open FILE, $serverfilename or return %addresses;
	while (my $line = <FILE>) {
		$line =~ s/;.*//;
		if (!$line) { next; }
		if ($line =~ m/(.+)\s+IN\s+A\s+([\d\.]+)/i) {
			$addresses{$1} = $2;
			print "Found address for host $1 ($2)\n";
		}
	}
	close FILE;
	return %addresses;
}

sub outputServers {
	my $timestamp = time;
	my $output = ";
; BIND data file for lucOS servers
; NB: This file is modified automatically by lucOS
;
@       IN      SOA     $domainname. $emailaddr (
$timestamp	; Serial
604800 		; Refresh
86400 		; Retry
2419200		; Expire
60 )		; Negative Cache TTL
;\n";
	$output .= "@       IN      NS      $nameserver.\n";
	while (my($host, $address) = each %addresses) {
		if (!$address) { next; }
		$output .= "$host\t\IN\tA\t$address\n";
	}
	open FILE, ">", $serverfilename or die "Could not write to server file: $!\n";
	print FILE $output;
	close FILE;
	print "Updated servers config file\n";
}


sub outputServices {
	my $timestamp = time;
	my $output = ";
; BIND data file for lucOS services
; NB: This file is modified automatically by lucOS
;
@       IN      SOA     $rootdomain. $emailaddr (
$timestamp	; Serial
604800 		; Refresh
86400 		; Retry
2419200		; Expire
60 )		; Negative Cache TTL
;\n";
	$output .= "@       IN      NS      example.org.\n";
	while (my($host, $server) = each %aliases) {
		
		# Ideally a CNAME would be used here, but bind doesn't like CNAMEs for the root domain
		$address = $addresses{$server};
		if (!$address) { next; }
		$output .= "$host\t\IN\tA\t$address\n";
	}
	open FILE, ">", $servicefilename or die "Could not write to service file: $!\n";
	print FILE $output;
	close FILE;
	print "Updated services config file\n";
}

sub outputAllConfig {
	outputServers();
	outputServices();
	system("/usr/sbin/rndc", "reload");
	if ( $? == 0) {
		print "Bind reloaded\n";
	} else {
		print STDERR "Error reloading bind $?\n";
	}
}