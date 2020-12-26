# -*- coding: utf-8 -*-
import os
import sys
import json
import pytz
import asyncio
import ed25519
import pytest
from datetime import datetime
from unittest.mock import patch
from aiohttp.client_exceptions import ClientConnectorError
from dozorro.api.main import cdb_init, cdb_put, init_app, cleanup
from dozorro.api.validate import dumps, hash_id
from dozorro.api.utils import load_schemas


ROOTJS = "tests/keyring/root.json"
SECKEY = "tests/keypair.pem"
COMMENT_SCHEMA = "tests/comment_schema.json"
COMMENT_SAMPLE = "tests/comment_sample.json"
FORM113_SCHEMA = "tests/form113_schema.json"
FORM113_SAMPLE = "tests/form113_sample.json"
TMPDIR = "tests/temp"
PREFIX = "/api/v1"
TZ = pytz.timezone('Europe/Kiev')


def test_hash_id():
    data = {"envelope": {}, "id": "c74f3008fdd2f7c5ae5446ab2e522629"}
    assert hash_id(dump_bson(data)) == data['id']
    data = {"envelope": {"owner": "example-owner"}, "id": "f78e26a9166e7812987f9aec721ba2a2"}
    assert hash_id(dump_bson(data)) == data['id']
    data = {"envelope": {"date": "2017-04-20T01:55:21.358240+03:00", "owner": "example-owner",
            "payload": "тест"}, "id": "061002ffb700a3d7cad59da4457c3af0"}
    assert hash_id(dump_bson(data)) == data['id']


def get_now():
    return TZ.localize(datetime.now())


def dump_bson(data):
    bson = dumps(data['envelope'],
        skipkeys=False,
        ensure_ascii=False,
        sort_keys=True).encode('utf-8')
    return bson


def data_sign(data, sk):
    data_bin = dump_bson(data)
    data['id'] = hash_id(data_bin)
    data['sign'] = sk.sign(data_bin, encoding='base64').decode()


async def find_tender_contract(app):
    for n in range(50):
        await asyncio.sleep(0.1)
        tenders_list = await app['tenders'].get_tenders()
        if n < 10:
            continue
        for tender in tenders_list:
            await asyncio.sleep(0.1)
            tender_data = await app['tenders'].get_tender(tender['id'])
            if tender_data.get('contracts'):
                return tender_data['id'], tender_data['contracts'][0]['id']

    assert False, "Contract not found"


def create_cdb(loop, config):
    testargs = ["cdb_init", "--dropdb", "--config", config, ROOTJS]
    with patch.object(sys, 'argv', testargs):
        cdb_init()

    testargs = ["cdb_put", COMMENT_SCHEMA]
    with patch.object(sys, 'argv', testargs):
        with pytest.raises(ClientConnectorError):
            cdb_put()


async def api_tests(test_client, loop, config):
    app = await init_app(config)
    client = await test_client(app)

    # send comment schema (outdated)
    with open(COMMENT_SCHEMA) as fp:
        data = json.load(fp)

    url = PREFIX + '/data/' + data['id']
    ua = {'User-Agent': 'test root'}

    # first test readony mode
    app['config']['readonly'] = True
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 405
    text = await resp.text()
    assert 'Method Not Allowed' in text

    # back to read-write app
    app['config'].pop('readonly')

    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'bad envelope date' in text

    resp = await client.put(url, data="data", headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'must be application/json' in text

    data['envelope']['unknown'] = 'abc'
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'bad data structure' in text

    data['envelope'].pop('unknown')
    data['envelope']['date'] = get_now().isoformat()
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'bad hash id' in text

    bson = dump_bson(data)
    data['id'] = hash_id(bson)

    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'sign not verified' in text

    # sign comment schema
    with open(ROOTJS) as fp:
        root_key = json.load(fp)
    with open(SECKEY) as fp:
        keydata = fp.read().encode()
    sk = ed25519.SigningKey(keydata, encoding="base64")
    vk = sk.get_verifying_key()
    vk_s = vk.to_ascii(encoding='hex').decode()
    assert root_key['envelope']['payload']['publicKey'] == vk_s

    data_sign(data, sk)

    url = PREFIX + '/data/' + "00000000000000000000000000000000"
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'id in uri and data mismatch' in text

    url = PREFIX + '/data/' + data['id']
    badua = {'User-Agent': 'some bad ua'}
    resp = await client.put(url, json=data, headers=badua)
    assert resp.status == 400
    text = await resp.text()
    assert 'must include owner' in text

    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 201
    text = await resp.text()
    assert 'created' in text
    comment_schema = data

    # send tender113 schema
    with open(FORM113_SCHEMA) as fp:
        data = json.load(fp)

    data['envelope']['date'] = get_now().isoformat()
    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    url = PREFIX + '/data/' + data['id']

    data_sign(data, sk)

    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 201
    text = await resp.text()
    assert 'created' in text
    form113_schema = data

    # append 2 schemas to app[schemas]
    tmpdir = TMPDIR
    os.makedirs(tmpdir, exist_ok=True)
    cs_filename = tmpdir + '/comment.json'
    with open(cs_filename, 'wt') as fp:
        json.dump(comment_schema, fp, ensure_ascii=False, indent=2)
    fs_filename = tmpdir + '/form113.json'
    with open(fs_filename, 'wt') as fp:
        json.dump(form113_schema, fp, ensure_ascii=False, indent=2)
    app['config']['schemas'] = tmpdir
    await load_schemas(app)
    os.remove(cs_filename)
    os.remove(fs_filename)

    # send sample comment
    with open(COMMENT_SAMPLE) as fp:
        data = json.load(fp)
    data['envelope']['date'] = get_now().isoformat()
    data['envelope']['payload'].pop('tender', None)

    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)
    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'required property' in text

    # some non existing tender
    data['envelope']['payload']['tender'] = "00000000000000000000000000000000"
    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)
    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'not found' in text

    data['envelope']['payload']['parentForm'] = comment_schema['id']
    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)
    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'tender not found' in text

    app['tenders'].params['mode'] = 'test'
    tenders_list = await app['tenders'].get_tenders()
    test_tender_id = tenders_list[-1]['id']

    # tender in mode=test
    data['envelope']['payload']['tender'] = test_tender_id
    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)
    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'mode=test' in text

    app['tenders'].params['mode'] = ''
    tenders_list = await app['tenders'].get_tenders()
    some_tender_id = tenders_list[-1]['id']

    # some existing tender
    data['envelope']['payload']['tender'] = some_tender_id
    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)
    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 201
    text = await resp.text()
    assert 'created' in text

    comment_sample = data

    # put existing twice
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'already exists' in text

    # put existing twice with nosave option
    url += '?nosave=1'
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 200
    text = await resp.text()
    assert 'validated' in text

    # put form113 with bad contract reference
    with open(FORM113_SAMPLE) as fp:
        data = json.load(fp)
    data['envelope']['date'] = get_now().isoformat()
    data['envelope']['payload']['tender'] = "00000000000000000000000000000000"
    data['envelope']['payload']['tenderContract'] = "00000000000000000000000000000000"

    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)

    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'tender not found' in text

    tender_id, contract_id = await find_tender_contract(app)

    # fix only tender reference
    data['envelope']['payload']['tender'] = tender_id
    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)

    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 400
    text = await resp.text()
    assert 'contract not found' in text

    # fix contract reference
    data['envelope']['payload']['tenderContract'] = contract_id
    bson = dump_bson(data)
    data['id'] = hash_id(bson)
    data_sign(data, sk)

    url = PREFIX + '/data/' + data['id']
    resp = await client.put(url, json=data, headers=ua)
    assert resp.status == 201
    text = await resp.text()
    assert 'created' in text

    form113_sample = data

    url = PREFIX + '/data'
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert set(data.keys()) == set(['data', 'prev_page', 'next_page'])
    assert data['data'][0]['id'] == root_key['id']
    assert data['data'][1]['id'] == comment_schema['id']
    assert data['data'][2]['id'] == form113_schema['id']
    assert data['data'][3]['id'] == comment_sample['id']
    assert data['data'][4]['id'] == form113_sample['id']

    url = PREFIX + '/data?limit=1000000'
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert len(data['data']) == 5

    next_page_offset = data['next_page']['offset']

    url = PREFIX + '/data?offset=' + next_page_offset
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert len(data['data']) == 0

    url = PREFIX + '/data?reverse=1&offset=' + next_page_offset
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert len(data['data']) != 0

    url = PREFIX + '/data?limit=3'
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert len(data['data']) == 3

    next_page_offset = data['next_page']['offset']

    url = PREFIX + '/data?limit=3&offset=%s' % next_page_offset
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert len(data['data']) == 2

    url = PREFIX + '/data/' + (root_key['id'] * 150)
    resp = await client.get(url)
    assert resp.status == 400
    text = await resp.text()
    assert 'bad id length' in text

    url = PREFIX + '/data/' + 'welcome'
    resp = await client.get(url)
    assert resp.status == 400
    text = await resp.text()
    assert 'bad id chars' in text

    url = PREFIX + '/data/' + ('abc,' * 150)
    resp = await client.get(url)
    assert resp.status == 400
    text = await resp.text()
    assert 'too many ids' in text

    url = PREFIX + '/data/' + '00000000000000000000000000000000,00000000000000000000000000000000'
    resp = await client.get(url)
    assert resp.status == 404

    url = PREFIX + '/data/' + root_key['id']
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert data['data'][0]['envelope']['payload']['publicKey'] == \
        root_key['envelope']['payload']['publicKey']

    url = PREFIX + '/data/' + comment_schema['id']
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert data['data'][0]['envelope']['payload']['schema']['title'] == \
        comment_schema['envelope']['payload']['schema']['title']

    url = PREFIX + '/data/' + comment_sample['id']
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert data['data'][0]['envelope']['payload']['comment'] == \
        comment_sample['envelope']['payload']['comment']

    url = "{}/data/{},{}".format(PREFIX, comment_sample['id'],
        comment_schema['id'])
    resp = await client.get(url)
    assert resp.status == 200
    data = await resp.json()
    assert len(data['data']) == 2

    await cleanup(app)


def wsgi_import(loop, config):
    os.environ["API_CONFIG"] = config
    from dozorro.api.wsgi import app
    assert 'config' in app
    loop.run_until_complete(cleanup(app))


# # # start test matrix # # #


async def test_init_no_config(loop):
    if "API_CONFIG" in os.environ:
        os.environ["API_CONFIG"] = None
    with pytest.raises(ValueError):
        await init_app()


async def test_unknown_backend(loop):
    with pytest.raises(ValueError):
        await init_app("tests/api_unknown.yaml")


def test_create_rethink(loop):
    create_cdb(loop, "tests/api_rethink.yaml")


async def test_api_rethink(test_client, loop):
    await api_tests(test_client, loop, "tests/api_rethink.yaml")


def test_create_mongo(loop):
    create_cdb(loop, "tests/api_mongo.yaml")


async def test_api_mongo(test_client, loop):
    await api_tests(test_client, loop, "tests/api_mongo.yaml")


def test_create_couch(loop):
    create_cdb(loop, "tests/api_couch.yaml")


async def test_api_couch(test_client, loop):
    await api_tests(test_client, loop, "tests/api_couch.yaml")


def test_wsgi_rethink(loop):
    wsgi_import(loop, "tests/api_rethink.yaml")


def test_wsgi_mongo(loop):
    wsgi_import(loop, "tests/api_mongo.yaml")


def test_wsgi_couch(loop):
    wsgi_import(loop, "tests/api_couch.yaml")
