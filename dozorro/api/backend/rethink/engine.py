import rethinkdb as r


async def cleanup(app):
    await app['db'].close()


async def init_engine(app):
    r.set_loop_type('asyncio')
    conn = await r.connect(db='sandbox')
    app['db'] = conn
    app.on_cleanup.append(cleanup)


async def get_list(conn, offset=None, limit=100, table='data'):
    minval = r.epoch_time(float(offset)) if offset else r.minval
    cursor = await (r.table(table)
        .between(minval, r.maxval, index='ts', left_bound='open')
        .order_by(index='ts')
        .limit(limit)
        .pluck('id', 'ts')
        .run(conn))
    items_list = list()
    last_offset = None
    while await cursor.fetch_next():
        doc = await cursor.next()
        last_offset = doc.pop('ts')
        items_list.append(doc)
    return (items_list, last_offset.timestamp())


async def get_item(conn, item_id, table='data'):
    doc = await r.table(table).get(item_id).run(conn)
    if doc:
        doc.pop('ts')
    return doc


async def get_many(conn, items_list, table='data'):
    if len(items_list) == 1:
        doc = await get_item(conn, items_list[0], table)
        return list(doc) if doc else []
    cursor = await r.table(table).get_all(*items_list).run(conn)
    docs = list()
    while await cursor.fetch_next():
        doc = await cursor.next()
        doc.pop('ts')
        docs.append(doc)
    return docs


async def check_exists(conn, item_id, table='data', model=None):
    doc = await r.table(table).get(item_id).run(conn)
    assert doc, '{} not found'.format(item_id)
    if model and model != doc['envelope']['model']:
        assert False, 'bad model ref'


async def put_item(conn, data, table='data'):
    doc = await r.table(table).get(data['id']).run(conn)
    assert not doc, 'already exists'
    data['ts'] = r.now()
    doc = await r.table(table).insert(data).run(conn)
    return doc
