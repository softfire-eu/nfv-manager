import logging
import unittest

from eu.softfire.nfv.utils import utils

TESTBED_UNDER_TEST = 'fokus'
TENANTS = {
    'ericsson': 'admin',
    'fokus': '5gcore'
}


class MyTestCase(unittest.TestCase):

    # def test_list_images(self):
    #     self.client = self.get_client()
    #     self.client.list_images(self.client.os_tenant_id)

    def test_get_user(self):
        self.client = self.get_client()
        # assert self.client

    def get_client(self):
        # self.testbed = os_utils.get_openstack_credentials().get(TESTBED_UNDER_TEST)
        # self.username = self.testbed.get('username')
        # self.password = self.testbed.get('password')
        # self.auth_url = self.testbed.get("auth_url")
        # self.admin_tenant_name = self.testbed.get("admin_tenant_name")
        logging.basicConfig(level=logging.DEBUG)
        # os_utils.source_credentials('/opt/softfire/key/%s.sh' % TESTBED_UNDER_TEST)
        credentials = utils.get_openstack_credentials(TESTBED_UNDER_TEST)
        logging.debug(credentials)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
