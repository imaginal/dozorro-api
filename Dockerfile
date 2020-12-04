FROM python:3.7

ENV TZ=Europe/Kiev
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo LANG="en_US.UTF-8" >/etc/default/locale \
 && echo $TZ >/etc/timezone \
 && update-ca-certificates

COPY requirements.txt dist/dozorro.api-* /tmp/

RUN pip install -U pip setuptools wheel \
 && pip install -r /tmp/requirements.txt \
 && pip install /tmp/dozorro.api-*

RUN chmod -R o-rwx /bin /sbin /usr/bin /usr/sbin \
 && apt-get autoremove --purge -yq cpp g++ gcc m4 make \
 && rm -rf /var/lib/apt/lists /var/cache/apt/archives /tmp

USER www-data

CMD ["/usr/local/bin/gunicorn", "-c", "/etc/dozorro/web.conf", "dozorro.api.wsgi:app"]
