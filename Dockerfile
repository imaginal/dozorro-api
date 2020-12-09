FROM alpine

COPY dist /dist/

ENV TZ=Europe/Kiev
ENV LANG=en_US.UTF-8

RUN apk add --no-cache python3 py3-pip py3-wheel \
    libtls-standalone libstdc++ libffi tzdata \
 && cp /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ >/etc/timezone \
 && pip3 install --no-index -f /dist dozorro.api gunicorn

RUN rm -rf /dist /var/cache/apk \
 && chmod -R 700 /bin /sbin /usr/sbin /usr/local/*bin \
 && chmod 711 /usr/bin \
 && apk del --no-cache alpine-baselayout busybox ssl_client apk-tools

CMD ["/usr/bin/gunicorn", "-c", "/etc/dozorro/web.py", "dozorro.api.wsgi:app"]
