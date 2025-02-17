FROM alpine:3.21.3

RUN apk --update add bind bind-tools

WORKDIR /etc/bind
RUN rm named.conf.*
COPY config .

EXPOSE 53
EXPOSE 53/udp
EXPOSE 953

CMD ["./startup.sh"]