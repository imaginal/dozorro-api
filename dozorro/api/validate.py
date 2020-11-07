import os
import pytz
import asyncio
import aiohttp
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
    if len(data) > 3 or len(data['envelope']) > 4:
        raise ValidateError('bad data structure')
    try:
        now = TZ.localize(datetime.now())
        env_date = iso8601.parse_date(data['envelope']['date'])
        assert env_date > now - timedelta(days=3)
        assert env_date < now + timedelta(days=1)
    except Exception as e:
        raise ValidateError('bad envelope date') from e

    bin_data = dumps(data['envelope'],
        skipkeys=False,
        ensure_ascii=False,
        sort_keys=True).encode('utf-8')

    if data['id'] != hash_id(bin_data):
        raise ValidateError('bad hash id')

    try:
        sign = data['sign']
        owner = data['envelope']['owner']
        verified = False
        last_exc = None
        if owner not in keyring:
            raise KeyError('key not found')
        for keydata in keyring[owner]:
            if keydata['validSince'] < env_date < keydata['validTill']:
                vkey_hex = keydata['publicKey']
                vk = ed25519.VerifyingKey(vkey_hex, encoding='hex')
                try:
                    vk.verify(sign, bin_data, encoding='base64')
                    logger.info("Sign verified {} pubkey {}/{}".format(
                                data['id'], keydata['owner'], vkey_hex[:8]))
                    verified = True
                    break
                except ed25519.BadSignatureError as exc:
                    last_exc = exc
        if not verified:
            raise last_exc if last_exc else IndexError('key not found')
    except Exception as e:
        raise ValidateError('sign not verified') from e


async def validate_tender_reference(tender_id, app):
    client = app['tenders']
    for n in range(5):
        try:
            return await client.get_tender(tender_id)
        except aiohttp.ClientError as exc:
            if exc.code // 100 == 4 or n == 4:
                if 'archive' in app and client != app['archive']:
                    client = app['archive']
                    continue
                raise ValidateError('tender not found')
            await asyncio.sleep(n + 1)


async def validate_contract_reference(reference, app):
    tender_id, contract_id = reference.split('/', 1)
    tender = await validate_tender_reference(tender_id, app)
    assert tender.get('contracts', None), 'tender has no contracts'
    assert [c for c in tender['contracts'] if c['id'] == contract_id], 'contract not found'


async def validate_references(payload, formschema, app):
    for key, value in formschema['properties'].items():
        if 'reference' in value and key in payload:
            if value['reference'] == 'tenders/contracts':
                await validate_contract_reference(payload[key], app)
            elif value['reference'] == 'tenders':
                await validate_tender_reference(payload[key], app)
            else:
                await app['db'].check_exists(payload[key], model=value['reference'])


async def validate_schema(envelope, app):
    model, schema = envelope['model'].split('/', 1)
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
