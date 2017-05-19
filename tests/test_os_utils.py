import unittest

from utils import os_utils
from utils.os_utils import OSClient

TESTBED_UNDER_TEST = 'ericsson'
TENANTS = {
    'ericsson': 'admin',
    'fokus': '5gcore'
}


class MyTestCase(unittest.TestCase):
    def test_get_user(self):
        self.client = self.get_client()
        assert self.client

    def get_client(self):
        self.testbed = os_utils.get_openstack_credentials().get(TESTBED_UNDER_TEST)
        self.username = self.testbed.get('username')
        self.password = self.testbed.get('password')
        self.auth_url = self.testbed.get("auth_url")
        self.admin_tenant_name = self.testbed.get("admin_tenant_name")

        os_client = OSClient(testbed_name=TESTBED_UNDER_TEST, testbed=self.testbed, tenant_name=self.admin_tenant_name)
        return os_client


if __name__ == '__main__':
    unittest.main()
