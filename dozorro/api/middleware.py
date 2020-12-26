from rapidjson import dumps
from aiohttp.web import json_response, HTTPException
from jsonschema.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)


async def dump_request(request):
    request_headers = "\n".join(["{}: {}".format(k, v)
        for k, v in request.headers.items()])
    if hasattr(request, 'raw_body_data'):
        request_body = request.raw_body_data
    else:
        request_body = await request.text()
    if hasattr(request_body, 'decode'):
        request_body = request_body.decode('utf-8')
    if request_body:
        request_body = "\n{}\n\n".format(request_body)
    return "{} {}\n{}\n{}".format(request.method,
                                  request.raw_path,
                                  request_headers,
                                  request_body)


def json_error(status, message):
    return json_response({'error': message}, status=status, dumps=dumps)


async def error_middleware(app, handler):
    async def middleware_handler(request):
        try:
            response = await handler(request)
            return response
        except HTTPException as e:
            if e.status >= 400:
                method, path = request.method, request.raw_path
                logger.error('HTTPException {} on {} {}'.format(e, method, path))
                return json_error(e.status, e.reason)
            raise               # pragma: no cover
        except (AssertionError, LookupError, TypeError, ValueError, ValidationError) as e:
            request_dump = await dump_request(request)
            logger.exception('ValidateError on {}'.format(request_dump))
            return json_error(400, '{}: {}'.format(e.__class__.__name__, str(e)[:100]))
        except Exception as e:  # pragma: no cover
            request_dump = await dump_request(request)
            logger.exception('Unhandled Exception on {}'.format(request_dump))
            return json_error(500, 'Unhandled error: {}'.format(str(e)[:50]))
    return middleware_handler
