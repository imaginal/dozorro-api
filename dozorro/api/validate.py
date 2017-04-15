import os
import pytz
import hashlib
import ed25519
import iso8601
import jsonschema
from rapidjson import dumps
from datetime import datetime, timedelta
from .backend import check_exists


TZ = pytz.timezone(os.environ.get('TZ', 'Europe/Kiev'))


def hash_id(bdata):
    h1 = hashlib.sha256(bdata).digest()
    h2 = hashlib.sha256(h1).hexdigest()
    return h2[:32]


async def validate_sign(data, app):
    bdata = dumps(data['envelope'],
        skipkeys=False,
        ensure_ascii=False,
        sort_keys=True).encode('utf-8')
    if data['id'] != hash_id(bdata):
        raise ValueError('bad hash id')
    try:
        sign = data['sign']
        owner = data['envelope']['owner']
        vkey_hex = app['keyring'][owner]
        vk = ed25519.VerifyingKey(vkey_hex, encoding='hex')
        vk.verify(sign, bdata, encoding='base64')
    except Exception as e:
        raise ValueError('sign error', e)
    try:
        date = iso8601.parse_date(data['envelope']['date'])
        today = TZ.localize(datetime.now())
        # assert date > today - timedelta(days=1), 'date is too soon'
        # assert date < today + timedelta(days=1), 'date is too late'
    except Exception as e:
        raise ValueError('bad envelope date')
    if len(data) > 3 or len(data['envelope']) > 5:
        raise ValueError('too many keys')


async def check_reference(conn, refid, reference):
    if reference == 'tender':
        return  #  await check_exists(conn, refid, table='tender')
    else:
        await check_exists(conn, refid, model=reference)


async def validate_form(envelope, app):
    try:
        payload = envelope['payload']
        schema = envelope['schema']
    except Exception as e:
        raise ValueError('bad model', e)
    formschema = app['schemas'][schema]
    jsonschema.validate(payload, formschema)
    for key, value in formschema['properties'].items():
        if 'reference' in value and key in payload:
            await check_reference(app['db'], payload[key], value['reference'])


async def validate_comment(envelope, app):
    await validate_form(envelope, app)
