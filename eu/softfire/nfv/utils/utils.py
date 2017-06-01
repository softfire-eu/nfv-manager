import json
import logging
import logging.config
import os

from sdk.softfire.utils import get_config

from eu.softfire.nfv.utils.static_config import CONFIG_FILE_PATH


def get_logger(name):
    logging.config.fileConfig(CONFIG_FILE_PATH)
    if name.startswith("eu.softfire.nfv"):
        return logging.getLogger(name)
    return logging.getLogger("eu.softfire.nfv.%s" % name)


logger = get_logger(__name__)


def get_available_nsds():
    with open(get_config('system', 'available-nsds-file-path', CONFIG_FILE_PATH), 'r') as f:
        return json.loads(f.read())


def get_openstack_credentials():
    openstack_credential_file_path = get_config('system', 'openstack-credentials-file', CONFIG_FILE_PATH)
    # logger.debug("Openstack cred file is: %s" % openstack_credential_file_path)
    if os.path.exists(openstack_credential_file_path):
        with open(openstack_credential_file_path, "r") as f:
            return json.loads(f.read())
    else:
        raise FileNotFoundError("Openstack credentials file not found")
