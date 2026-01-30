FROM lucas42/lucos_scheduled_scripts

RUN apk --update add bind # Needed for rndc package (bind server itself has it own container)
COPY rndc.conf /etc/bind/

COPY pyproject.toml .
RUN pip install .

COPY config-sync.py .
RUN echo "*/15 * * * * python config-sync.py" | crontab -

COPY templates ./templates