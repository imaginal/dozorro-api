import asyncio
import logging
from time import time
from rethinkdb import r
from rethinkdb.errors import ReqlDriverError, ReqlOpFailedError
from struct import pack, unpack

logger = logging.getLogger(__name__)


class RethinkEngine(object):
    async def init_engine(self, app):
        r.set_loop_type('asyncio')
        self.options = dict(app['config']['database'])
        assert self.options.pop('engine', 'rethink') == 'rethink'
        self.options['db'] = self.options.pop('name', 'dozorro')
        self.read_mode = self.options.pop('read_mode', 'single')
        keep_alive = self.options.pop('keep_alive', False)
        self.conn = await r.connect(**self.options)
        self.keep_alive_task = None
        if keep_alive:
            loop = asyncio.get_event_loop()
            coro = self.keep_alive(loop)
            self.keep_alive_task = loop.create_task(coro)
        app['db'] = self

    async def close(self):
        if self.keep_alive_task:
            self.keep_alive_task.cancel()
            await self.keep_alive_task
            self.keep_alive_task = None
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def check_open(self):
        try:
            self.conn.check_open()
        except (AttributeError, ReqlDriverError) as e:  # pragma: no cover
            logger.error('Connection error: {}'.format(e))
            self.conn = await r.connect(**self.options)

    async def keep_alive(self, loop):
        while loop.is_running():
            try:
                await asyncio.sleep(1)
                await self.check_open()
            except asyncio.CancelledError:
                break
            except Exception:   # pragma: no cover
                logger.exception('RethinkEngine.KeepAlive')

    def pack_offset(self, offset):
        if offset is None:
            return offset
        return pack('d', offset).hex()

    def unpack_offset(self, offset):
        if not offset or len(offset) != 16:
            raise ValueError('bad offset')
        return unpack('d', bytes.fromhex(offset))[0]

    async def get_list(self, offset=None, limit=100, reverse=False, table='data'):
        minval, maxval, oindex = r.minval, r.maxval, 'ts'
        if offset:
            offset = self.unpack_offset(offset)
            if reverse:
                maxval = offset
            else:
                minval = offset
        if reverse:
            oindex = r.desc(oindex)
        cursor = await (r.table(table, read_mode=self.read_mode)
            .between(minval, maxval, index='ts', left_bound='open')
            .order_by(index=oindex)
            .limit(limit)
            .pluck('id', 'ts')
            .run(self.conn))
        items_list = list()
        first_ts = None
        last_ts = None
        # for doc in cursor:
        while await cursor.fetch_next():
            doc = await cursor.next()
            last_ts = doc.pop('ts')
            if not first_ts:
                first_ts = last_ts
            items_list.append(doc)
        first_ts = self.pack_offset(first_ts)
        last_ts = self.pack_offset(last_ts)
        return (items_list, first_ts, last_ts)

    async def get_item(self, item_id, table='data'):
        doc = await (r.table(table, read_mode=self.read_mode)
            .get(item_id).run(self.conn))
        if doc:
            doc.pop('ts')
        return doc

    async def get_many(self, items_list, table='data'):
        if len(items_list) == 1:
            doc = await self.get_item(items_list[0], table)
            return [doc, ] if doc else []
        cursor = await (r.table(table, read_mode=self.read_mode)
                .get_all(*items_list).run(self.conn))
        docs = list()
        while await cursor.fetch_next():
            doc = await cursor.next()
            doc.pop('ts')
            docs.append(doc)
        return docs

    async def check_exists(self, item_id, table='data', model=None):
        doc = await (r.table(table, read_mode=self.read_mode).get(item_id)
                .run(self.conn))
        assert doc is not None, '{} not found in {}'.format(item_id, table)
        # assert not model or model == doc['envelope']['model'], 'bad model ref'
        return True

    async def put_item(self, data, table='data'):
        data['ts'] = time()
        status = await r.table(table).insert(data).run(self.conn)
        if status['errors']:
            first_error = status.get('first_error', 'insert error')
            logger.error('{} status {}'.format(first_error, status))
            if first_error.startswith('Duplicate primary key'):
                raise ValueError('{} already exists'.format(data['id']))
            raise RuntimeError('insert error')  # pragma: no cover
        return True

    async def init_tables(self, drop_database=False):
        if drop_database:
            try:
                await r.db_drop(self.options['db']).run(self.conn)
            except ReqlOpFailedError:   # pragma: no cover
                pass
        await r.db_create(self.options['db']).run(self.conn)
        await r.table_create('data').run(self.conn)
        await r.table('data').index_create('ts').run(self.conn)
