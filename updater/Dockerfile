FROM alpine:latest

RUN apk --update add bind # Needed for rndc package (bind server itself has it own container)
RUN apk --update add perl perl-json perl-http-message perl-libwww

WORKDIR /usr/src/app
COPY server.pl .
COPY rndc.conf /etc/bind/

ENV PORT 8012
EXPOSE $PORT

CMD ["perl", "server.pl"]