import logging
from time import time
from struct import pack, unpack
from motor import motor_asyncio
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure
from pymongo.son_manipulator import SONManipulator


logger = logging.getLogger(__name__)


class RefTransform(SONManipulator):

    def need_transform(self, son, collection):
        return son.get('envelope', {}).get('model') == "admin/schema"

    def transform_incoming(self, son, collection):
        for key in list(son.keys()):
            # if the key is named $ref change it to _ref
            if key == '$ref':
                son['_ref'] = son.pop('$ref')
                key = '_ref'
            if key == '$schema':
                son['_schema'] = son.pop('$schema')
                key = '_schema'
            # if the value is a dict, recursively go through its keys
            value = son[key]
            if isinstance(value, dict):
                son[key] = self.transform_incoming(value, collection)

        return son

    def transform_outgoing(self, son, collection):
        for key in list(son.keys()):
            if key == '_ref':
                son['$ref'] = son.pop('_ref')
                key = '$ref'
            if key == '_schema':
                son['$schema'] = son.pop('_schema')
                key = '$schema'
            value = son[key]
            if isinstance(value, dict):
                son[key] = self.transform_outgoing(value, collection)

        return son


class MongoEngine(object):
    async def init_engine(self, app):
        self.options = dict(app['config']['database'])
        assert self.options.pop('engine', 'mongo') == 'mongo'
        self.db_name = self.options.pop('name', 'dozorro')
        self.client = motor_asyncio.AsyncIOMotorClient(**self.options)
        self.db = self.client[self.db_name]
        self.son = RefTransform()
        app['db'] = self

    async def close(self):
        self.client.close()

    async def check_open(self):
        await self.db.list_collection_names()

    def pack_offset(self, offset):
        if not offset:
            return offset
        return pack('d', offset).hex()

    def unpack_offset(self, offset):
        if not offset or len(offset) != 16:
            return None
        return unpack('d', bytes.fromhex(offset))[0]

    async def get_list(self, offset=None, limit=100, reverse=False, table='data'):
        if offset:
            offset = self.unpack_offset(offset)
            cond = {'ts': {'$lt': offset}} if reverse else {'ts': {'$gt': offset}}
        else:
            cond = None
        proj = {'_id': 1, 'ts': 1}
        sort = ('ts', DESCENDING) if reverse else ('ts', ASCENDING)
        cursor = self.db[table].find(cond, proj).sort(*sort)
        items_list = list()
        first_ts = None
        last_ts = None
        for doc in await cursor.to_list(length=limit):
            last_ts = doc['ts']
            if not first_ts:
                first_ts = last_ts
            items_list.append({'id': doc['_id']})
        first_ts = self.pack_offset(first_ts)
        last_ts = self.pack_offset(last_ts)
        return (items_list, first_ts, last_ts)

    async def get_item(self, item_id, table='data'):
        doc = await self.db[table].find_one({'_id': item_id})
        if doc:
            if self.son.need_transform(doc, self.db[table]):
                self.son.transform_incoming(doc, self.db[table])
            doc['id'] = doc.pop('_id')
            doc.pop('ts')
        return doc

    async def get_many(self, items_list, table='data', limit=100):
        if len(items_list) > limit:
            raise ValueError('items_list is too big')
        if len(items_list) == 1:
            doc = await self.get_item(items_list[0], table=table)
            return [doc] if doc else []
        cond = {'_id': {'$in': items_list}}
        cursor = self.db[table].find(cond)
        collection = self.db[table]
        items_list = list()
        for doc in await cursor.to_list(length=limit):
            doc['id'] = doc.pop('_id')
            doc.pop('ts')
            if self.son.need_transform(doc, collection):
                self.son.transform_incoming(doc, collection)
            items_list.append(doc)
        return items_list

    async def check_exists(self, item_id, table='data', model=None):
        count = await self.db[table].count_documents({'_id': item_id})
        assert count == 1, '{} not found in {}'.format(item_id, table)
        return True

    async def put_item(self, data, table='data'):
        if self.son.need_transform(data, self.db[table]):
            self.son.transform_incoming(data, self.db[table])
        data['ts'] = time()
        if '_id' not in data:
            data['_id'] = data.pop('id')
        try:
            await self.db[table].insert_one(data)
        except DuplicateKeyError as e:
            logger.error('DuplicateKeyError {} for {}'.format(e, data['_id']))
            raise ValueError('{} already exists'.format(data['_id']))
        except OperationFailure as e:
            logger.error('{} {} for {}'.format(e.__class__.__name__, e, data['_id']))
            raise RuntimeError('insert error') from e
        return True

    async def init_tables(self, drop_database=False):
        if drop_database:
            await self.client.drop_database(self.db_name)
        self.db = self.client[self.db_name]
        await self.db.create_collection('data')
        table = self.db['data']
        await table.create_index('ts')
