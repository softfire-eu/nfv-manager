import configparser
import json
import logging
import logging.config
import os

from utils.static_config import CONFIG_FILE_PATH


def get_logger(name):
    logging.config.fileConfig(CONFIG_FILE_PATH)
    return logging.getLogger("eu.softfire.nfv.manager.%s" % name)


def get_config():
    """
    Get the ConfigParser object containing the system configurations

    :return: ConfigParser object containing the system configurations
    """
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE_PATH) and os.path.isfile(CONFIG_FILE_PATH):
        config.read(CONFIG_FILE_PATH)
        return config
    else:
        logging.error("Config file not found, create %s" % CONFIG_FILE_PATH)
        exit(1)


def get_available_nsds():
    with open(get_config().get('system', 'available-nsds-file-path'), 'r') as f:
        return json.loads(f.read())


def get_openstack_credentials(testbed_name):
    openstack_credential_file_path = get_config().get('system', 'openstack-credentials-file')
    if os.path.exists(openstack_credential_file_path):
        with open(openstack_credential_file_path + ("/%s.json" % testbed_name), "r") as f:
            return json.loads(f.read())
    else:
        raise FileNotFoundError("Openstack credentials file not found")
