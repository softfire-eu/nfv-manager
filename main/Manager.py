import socket

from sdk.softfire.main import start_manager

from core.NfvManager import NfvManager
from utils.utils import get_logger


def is_ex_man__running(ex_man_bind_ip, ex_man_bind_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex((ex_man_bind_ip, int(ex_man_bind_port)))
    return result == 0


def start():
    # ex_man_bind_ip = config.get('system', 'experiment_manager_ip')
    # ex_man_bind_port = config.get('system', 'experiment_manager_port')
    # while not is_ex_man__running(ex_man_bind_ip, ex_man_bind_port):
    #     time.sleep(1)
    logger = get_logger(__name__)
    # logger.info("Starting NFV Manager.")

    start_manager(NfvManager(), '/etc/softfire/nfv-manager.ini')


if __name__ == '__main__':
    start()
