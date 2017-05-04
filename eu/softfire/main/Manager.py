import asyncio
from concurrent.futures import ProcessPoolExecutor

from eu.softfire.messaging.MessagingAgent import receive_forever, register, unregister
from eu.softfire.utils.utils import get_config, get_logger


def start():
    """
    Start the ExperimentManager
    """
    get_config()
    logger = get_logger(__name__)
    logger.info("Starting NFV Manager.")

    executor = ProcessPoolExecutor(5)
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(loop.run_in_executor(executor, receive_forever))
    asyncio.ensure_future(loop.run_in_executor(executor, register))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("received ctrl-c, shutting down...")
        loop.close()
        unregister()


if __name__ == '__main__':
    start()
