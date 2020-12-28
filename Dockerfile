FROM alpine

COPY dist /dist/

ENV TZ=Europe/Kiev
ENV LANG=en_US.UTF-8

RUN apk add --no-cache python3 py3-pip py3-wheel \
    libtls-standalone libstdc++ libffi tzdata \
 && cp /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ >/etc/timezone \
 && pip3 install --no-index -f /dist dozorro.api gunicorn

# Please choose one of these database connectors:
# RUN pip3 install --no-index -f /dist aiocouch
# RUN pip3 install --no-index -f /dist pymongo motor
# RUN pip3 install --no-index -f /dist rethinkdb

# For paranoid setup uncomment the next few lines:
# RUN rm -rf /dist /var/cache/apk \
#  && chmod -R 700 /bin /sbin /usr/bin /usr/sbin /usr/local/*bin \
#  && chmod 711 /usr/bin && chmod 755 /usr/bin/python3 /usr/bin/gunicorn \
#  && apk del --no-cache alpine-baselayout busybox ssl_client apk-tools

USER 33:33

CMD ["/usr/bin/gunicorn", "-c", "/etc/dozorro/web.py", "dozorro.api.wsgi:app"]
