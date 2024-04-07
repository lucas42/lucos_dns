#!/usr/bin/perl
use IO::Socket qw(:DEFAULT :crlf);
use JSON;
use HTTP::Request;
use LWP::UserAgent;
use Time::Piece;
local($/) = LF;

my $apikey = $ENV{'APIKEY'};
my $emailaddr = $ENV{'ADMINEMAIL'};
my $port = $ENV{'PORT'} or 80;
if (!$apikey) { die "Missing environment variable APIKEY\n"; }
if (!$emailaddr) { die "Missing environment variable ADMINEMAIL\n"; }

my $rootdomain = "l42.eu";
my $nameserver = "dns.$rootdomain";
my $serverdomainsuffix = "s.$rootdomain";
my $serverfilename = "/etc/bind/dynamic/$serverdomainsuffix";

my $loganneuseragent = LWP::UserAgent->new();

# Parse the existing bind config
my %addresses = parseServers();

# Rewrite config to ensure config dosen't contain any unparsed info
outputServers();

my $server = new IO::Socket::INET (
	LocalPort => $port,
	Proto => 'tcp',
	Listen => 1,
	Reuse => 1,
);

$| = 1; # Make sure stdout isn't buffered

die "Could not create serveret: $!\n" unless $server;
writeLog("Server running on port $port");
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

	if ($path =~ m~/servers/(\w+)~) {
		$host = $1;
		if ($method eq "PUT") {
			if ($headers{'Authorization'} ne "Key $apikey") {
				print $client "HTTP/1.1 403 Forbidden\n";
				print $client "Content-type: text/plain\n\n";
				print $client "Access denied\n";
				writeLog("Failed attempt from $ipaddress (XFF: $headers{'X-Forwarded-For'}) to change host $host.", true);
				close $client;
				next;
			}

			# If there's an X-Forwarded-For header, use that instead
			# We can trust this as the Authorization header has already been checked
			if ($headers{'X-Forwarded-For'} =~ /^[\.0-9]+$/) {
				$ipaddress = $headers{'X-Forwarded-For'};
			}
			
			# Only update if there's been a change
			if ($addresses{$host} ne $ipaddress) {
				$addresses{$host} = $ipaddress;
				writeLog("update triggered by $host");
				outputServers();
				
				my %loganne_data = (
					type          => "dnsChange",
					source        => 'lucos_dns_updater',
					host          => $host,
					ipAddress     => $ipaddress,
					humanReadable => "IP Address for host $host changed to $ipaddress",
				);
				my $logannerequest = HTTP::Request->new(
					'POST',
					'https://loganne.l42.eu/events',
					['Content-Type' => 'application/json; charset=UTF-8'],
					encode_json(\%loganne_data),
				);
				my $loganneresponse = $loganneuseragent->request($logannerequest);
				if (!$loganneresponse->is_success) {
					writeLog("Error updating loganne: ${loganneresponse->status_line}", true);
				}
			}
		}
		my $address = $addresses{$host};
		if ($address) {
			print $client "HTTP/1.1 200 Found\n";
			print $client "Content-type: text/plain\n\n";
			print $client "The address for $host.$serverdomainsuffix is $address.\n\n";
		} else {
			print $client "HTTP/1.1 404 Server not Found\n";
			print $client "Content-type: text/plain\n\n";
			print $client "Can't find an address for $host.$serverdomainsuffix.\n\n";
		}
	} elsif ($path == "/_info") {
		my %checks = ();
		my %metric = ();
		my %ci = (
			circle => "gh/lucas42/lucos_dns",
		);
		my %info = (
			system  => "lucos_dns_updater",
			checks  => \%checks,
			metrics => \%metrics,
			ci      => \%ci,
		);
		$output = encode_json \%info;
		print $client "HTTP/1.1 200 Found\n";
		print $client "Content-Type: application/json; charset=UTF-8\n\n";
		print $client "$output\n";
	} else {
		print $client "HTTP/1.1 404 Not Found\n";
		print $client "\n";
		print $client "Not Found\n";
		writeLog("Not found: $path", true);
	}
	close $client;
}

sub parseServers {
	my %addresses = ();
	$file = open FILE, $serverfilename or return %addresses;
	while (my $line = <FILE>) {
		$line =~ s/;.*//;
		if (!$line) { next; }
		if ($line =~ m/(.+?)\s+IN\s+A\s+([\d\.]+)/i) {
			$addresses{$1} = $2;
			writeLog("Found address for host \"$1\" ($2)");
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
@       IN      SOA     $serverdomainsuffix. $emailaddr (
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
	writeLog("Updated servers config file");

	system("/usr/sbin/rndc", "reload", $serverdomainsuffix);
	if ( $? == 0) {
		writeLog("Bind reloaded");
	} else {
		writeLog("Error reloading bind $?", true);
	}
}

sub writeLog {
	my ($message, $error) = @_;
	my $now_string = localtime->datetime;
	my $handle = $error ? *STDERR : *STDOUT;
	my $bash_colour = $error ? "0;31" : "1;37";  # Make errors red; everything else white
	print $handle "\033[${bash_colour}m${now_string} ${message}\033[0m\n";
}