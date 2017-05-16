import asyncio
import socket
import time
from concurrent.futures import ProcessPoolExecutor

from eu.softfire.messaging.MessagingAgent import receive_forever, register, unregister
from eu.softfire.utils.utils import get_config, get_logger


def is_ex_man__running(ex_man_bind_ip, ex_man_bind_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex((ex_man_bind_ip, int(ex_man_bind_port)))
    return result == 0


def start():
    """
    Start the ExperimentManager
    """
    config = get_config()
    ex_man_bind_ip = config.get('system', 'experiment_manager_ip')
    ex_man_bind_port = config.get('system', 'experiment_manager_port')
    while not is_ex_man__running(ex_man_bind_ip, ex_man_bind_port):
        time.sleep(1)
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
