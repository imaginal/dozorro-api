import os
import pytz
import hashlib
import ed25519
import iso8601
import logging
import jsonschema
from rapidjson import dumps
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

TZ = pytz.timezone(os.environ.get('TZ', 'Europe/Kiev'))


class ValidateError(ValueError):
    pass


def hash_id(bdata):
    h1 = hashlib.sha256(bdata).digest()
    h2 = hashlib.sha256(h1).hexdigest()
    return h2[:32]


def validate_envelope(data, keyring):
    bdata = dumps(data['envelope'],
        skipkeys=False,
        ensure_ascii=False,
        sort_keys=True).encode('utf-8')
    if data['id'] != hash_id(bdata):
        raise ValidateError('bad hash id')
    try:
        sign = data['sign']
        owner = data['envelope']['owner']
        vkey_hex = keyring[owner]['publicKey']
        vk = ed25519.VerifyingKey(vkey_hex, encoding='hex')
        vk.verify(sign, bdata, encoding='base64')
    except Exception as e:
        raise ValidateError('sign not verified') from e
    try:
        date = iso8601.parse_date(data['envelope']['date'])
        now = TZ.localize(datetime.now())
        assert date > now - timedelta(days=365)
        assert date < now + timedelta(days=1)
    except Exception as e:
        raise ValidateError('bad envelope date') from e
    if len(data) > 3 or len(data['envelope']) > 4:
        raise ValidateError('too many keys')


async def validate_references(payload, formschema, app):
    for key, value in formschema['properties'].items():
        if 'reference' in value and key in payload:
            if value['reference'] == 'tenders':
                await app['db'].check_exists(payload[key], table='tenders')
            else:
                await app['db'].check_exists(payload[key], model=value['reference'])


async def validate_schema(envelope, app):
    model, schema = envelope['model'].split('/')
    payload = envelope['payload']
    if model not in ('form', 'admin'):
        raise ValidateError('bad model name')
    if model == 'admin':
        assert envelope['owner'] == 'root'
        return
    if schema not in app['schemas']:
        raise ValidateError('unknown schema name "{}"'.format(schema))
    formschema = app['schemas'][schema]
    jsonschema.validate(payload, formschema)
    await validate_references(payload, formschema, app)


async def validate_comment(envelope, app):
    await validate_form(envelope, app)
