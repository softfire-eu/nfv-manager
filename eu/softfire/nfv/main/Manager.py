from sdk.softfire.main import start_manager

from eu.softfire.nfv.core.NfvManager import NfvManager, UpdateStatusThread


def start():
    nfv_manager = NfvManager('/etc/softfire/nfv-manager.ini')
    thread = UpdateStatusThread(nfv_manager)
    thread.start()
    try:
        start_manager(nfv_manager)
    finally:
        thread.stop()
        thread.join()

if __name__ == '__main__':
    start()
