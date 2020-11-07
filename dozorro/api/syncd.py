import signal
import logging
import asyncio
import argparse
import logging.config
from functools import partial
from . import backend, utils

logger = logging.getLogger('dozorro.api.sync')


async def save_tender(db, tender):
    try:
        await db.check_exists(tender['id'], table='tenders')
    except AssertionError:
        return await db.put_item(tender, table='tenders')


async def run_once(app, loop, query_limit=2000):
    await backend.init_engine(app)
    db = app['db']
    config = app['config']['client']

    fwd_client = await utils.Client.create(config, loop)
    bwd_client = await utils.Client.create(config, loop)

    await fwd_client.get_tenders()
    fwd_client.params.pop('descending')

    if 'sync_tenders' in app['config']:
        sync_config = app['config']['sync_config']
        query_limit = int(sync_config['query_limit'])

    while loop.is_running() and query_limit > 0:
        fwd_list = await fwd_client.get_tenders()
        if bwd_client:
            bwd_list = await bwd_client.get_tenders()
            if not bwd_list:
                bwd_client = None

        if not fwd_list and not bwd_list:
            query_limit -= 1
            logger.info('Nothing for update, query_limit %d', query_limit)
            await asyncio.sleep(10)
            continue

        if fwd_list:
            updated = 0
            for tender in fwd_list:
                updated += await save_tender(db, tender)

            logger.info('Forward fetched %d updated %d last %s',
                len(fwd_list), updated, tender.get('dateModified'))

        if bwd_list:
            updated = 0
            for tender in bwd_list:
                updated += await save_tender(db, tender)

            logger.info('Backward fetched %d updated %d last %s',
                len(bwd_list), updated, tender.get('dateModified'))

        await asyncio.sleep(1)


async def run_loop(loop, config):
    app = utils.FakeApp(loop)
    app['config'] = utils.load_config(config)

    while loop.is_running():
        try:
            await run_once(app, loop)
        except (asyncio.CancelledError, SystemExit, KeyboardInterrupt):
            break
        except Exception:
            logger.exception('Unhandled Exception')
            await utils.Client.close()
            await asyncio.sleep(10)

    try:
        await utils.Client.close()
        await app['db'].close()
    except Exception:
        pass
    if loop.is_running():
        loop.stop()
    logger.info('Leave loop')


def shutdown(loop, task):
    loop.remove_signal_handler(signal.SIGTERM)
    task.cancel()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', default='config/api.yaml')
    parser.add_argument('-l', '--logfile')
    parser.add_argument('-p', '--pidfile')
    parser.add_argument('-d', '--daemon', default=False, action='store_true')
    args = parser.parse_args()
    if args.daemon:
        utils.daemonize(args.logfile)
    if args.pidfile:
        utils.write_pidfile(args.pidfile)

    loop = asyncio.get_event_loop()
    main_task = loop.create_task(run_loop(loop, args.config))
    shutdown_loop = partial(shutdown, loop, main_task)
    loop.add_signal_handler(signal.SIGHUP, shutdown_loop)
    loop.add_signal_handler(signal.SIGTERM, shutdown_loop)
    loop.run_until_complete(main_task)
    loop.close()

if __name__ == '__main__':
    main()
