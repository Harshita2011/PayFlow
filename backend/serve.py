"""Container/cloud entry point: no reload, migration, wildcard proxy trust or raw access logs."""
import os
import uvicorn
import config  # Validate required deployment settings before serving.


if __name__=='__main__':
    try:
        port=int(os.getenv('PORT','8001'))
        workers=int(os.getenv('WEB_CONCURRENCY','1'))
        concurrency=int(os.getenv('PAYFLOW_MAX_CONCURRENCY','16'))
        if not 1<=port<=65535 or not 1<=workers<=8 or not 1<=concurrency<=128: raise ValueError()
    except ValueError:
        raise RuntimeError('Invalid PORT, WEB_CONCURRENCY or PAYFLOW_MAX_CONCURRENCY') from None
    # Container listener is intentional; local exposure is restricted to the frontend proxy.
    uvicorn.run('main:app',host='0.0.0.0',port=port,workers=workers,  # nosec B104
        proxy_headers=False,access_log=False,timeout_graceful_shutdown=30,limit_concurrency=concurrency)
