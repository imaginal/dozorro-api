#!/bin/sh
if [ x$BUILD = x ] ; then
  exec docker run -it --rm -e BUILD=Y -v `pwd`:/app alpine /app/build.sh $1
fi
apk update
apk add python3 py3-pip py3-wheel
cd /app
python3 setup.py bdist_wheel
if [ x$1 = xfull ] ; then
  apk add python3-dev gcc g++ musl-dev libc-dev libffi-dev
  cd dist
  pip3 wheel -r ../requirements.txt
fi
