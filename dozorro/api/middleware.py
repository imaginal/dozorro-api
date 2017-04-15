from rapidjson import dumps
from aiohttp.web import json_response, HTTPException
import logging

logger = logging.getLogger(__name__)


def json_error(status, message):
    return json_response({'error': message}, status=status, dumps=dumps)


async def error_middleware(app, handler):
    async def middleware_handler(request):
        try:
            response = await handler(request)
            return response
        except HTTPException as e:
            if e.status >= 400:
                logger.exception('HTTPException')
                return json_error(e.status, e.reason)
            raise
        except (AssertionError, LookupError, TypeError, ValueError) as e:
            logger.exception('AssertionError')
            return json_error(400, '{}: {}'.format(e.__class__.__name__, e))
        except Exception as e:
            logger.exception('UnhandledException')
            return json_error(500, 'Unhandled: {}'.format(e))
    return middleware_handler
