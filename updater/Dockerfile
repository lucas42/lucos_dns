FROM alpine:latest

RUN apk --update add bind # Needed for rndc package (bind server itself has it own container)
RUN apk --update add perl perl-config-simple perl-libwww perl-json

WORKDIR /usr/src/app
COPY server.pl .
COPY rndc.conf /etc/bind/

RUN echo "serverfilename    /etc/bind/dynamic/s.l42.eu" >> config

EXPOSE 8080

CMD ["perl", "server.pl", "8080"]