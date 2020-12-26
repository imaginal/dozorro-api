import logging
from time import time
from struct import pack, unpack
from aiocouch import CouchDB, ConflictError, NotFoundError
from contextlib import suppress

logger = logging.getLogger(__name__)


class CouchEngine(object):
    async def init_engine(self, app):
        self.options = dict(app['config']['database'])
        assert self.options.pop('engine', 'couch') == 'couch'
        self.db_name = self.options.pop('name', 'dozorro')
        self.couch = CouchDB(**self.options)
        with suppress(NotFoundError):
            self.db = await self.couch[self.db_name]
            self.view = self.db.view('data', 'by_ts')
        app['db'] = self

    async def close(self):
        await self.couch.close()

    def pack_offset(self, offset):
        if offset is None:
            return offset
        return pack('d', offset).hex()

    def unpack_offset(self, offset):
        if not offset or len(offset) != 16:
            raise ValueError('bad offset')
        return unpack('d', bytes.fromhex(offset))[0]

    async def get_list(self, offset=None, limit=100, reverse=False, table='data'):
        params = {'limit': limit}
        if offset:
            offset = self.unpack_offset(offset)
            params['startkey'] = offset
            params['limit'] += 1
        if reverse:
            params['descending'] = 'true'
        items_list = list()
        first_ts = None
        last_ts = None

        async for res in self.view.get(**params):
            last_ts = res['key']
            if not first_ts:
                first_ts = last_ts
                if offset and offset == first_ts:
                    continue
            doc = {"id": res["id"]}
            items_list.append(doc)

        if items_list:
            first_ts = self.pack_offset(first_ts)
            last_ts = self.pack_offset(last_ts)
        elif last_ts:
            first_ts, last_ts = None, None
        return (items_list, first_ts, last_ts)

    def transform_outgoing(self, doc):
        doc['id'] = doc.pop('_id')
        doc.pop('type')
        doc.pop('_rev')
        doc.pop('ts')

    async def get_item(self, item_id, table='data'):
        doc = await self.db.get(item_id)
        data = doc.data.copy()
        self.transform_outgoing(data)
        return data

    async def get_many(self, items_list, table='data'):
        if len(items_list) == 1:
            doc = await self.get_item(items_list[0], table=table)
            return [doc] if doc else []
        docs_ids = [dict(id=i) for i in items_list]
        res = await self.db._bulk_get(docs_ids)
        if 'results' not in res:
            return []
        docs_list = list()
        for result in res['results']:
            for doc in result['docs']:
                if 'ok' not in doc:
                    continue
                data = doc['ok']
                self.transform_outgoing(data)
                docs_list.append(data)
        return docs_list

    async def check_exists(self, item_id, table='data', model=None):
        await self.db.get(item_id)
        return True

    async def put_item(self, data, table='data'):
        data['ts'] = time()
        data['type'] = table
        doc_id = data.pop('id')
        try:
            doc = await self.db.create(doc_id, data=data)
            await doc.save()
        except ConflictError as e:
            logger.error('ConflictError {} for {}'.format(e, doc_id))
            raise ValueError('{} already exists'.format(doc_id))
        return True

    async def create_views(self):
        map_func = '''function (doc) {
            if (doc.type == 'data') {
                data = {id: doc.id}
                emit(doc.ts, data)
            }
        }'''
        db = await self.couch[self.db_name]
        ddoc = await db.design_doc('data')
        await ddoc.create_view('by_ts', map_func)

    async def init_tables(self, drop_database=False):
        dbs_list = await self.couch.keys()
        if drop_database and self.db_name in dbs_list:
            db = await self.couch[self.db_name]
            await db.delete()
        await self.couch.create(self.db_name)
        await self.create_views()
        self.db = await self.couch[self.db_name]
        self.view = self.db.view('data', 'by_ts')
