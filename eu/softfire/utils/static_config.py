"""
Contains the static configuration of the system
"""
import os

if os.path.exists('/etc/softfire/nfv-manager.ini'):
    CONFIG_FILE_PATH = '/etc/softfire/nfv-manager.ini'
else:
    CONFIG_FILE_PATH = 'etc/nfv-manager.ini'
