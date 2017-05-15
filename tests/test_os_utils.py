import unittest
from eu.softfire.utils import os_utils
from keystoneauth1.identity import v2
from keystoneauth1 import session
from keystoneclient.v2_0 import client as ks_client

TESTBED_UNDER_TEST = 'fokus'


class MyTestCase(unittest.TestCase):
    def test_get_user(self):
        self.keystone = self.get_keystone()
        os_utils.get_user_by_username(self.username, self.keystone)



    def get_keystone(self):
        self.testbed = os_utils.get_openstack_credentials().get(TESTBED_UNDER_TEST)
        self.username = self.testbed.get('username')
        self.password = self.testbed.get('password')
        self.auth_url = self.testbed.get("auth_url")
        self.admin_tenant_name = self.testbed.get("admin_tenant_name")

        auth = v2.Password(auth_url=self.auth_url,
                           username=self.username,
                           password=self.password,
                           tenant_name='5gcore',
                           # user_domain_id="default",
                           # project_domain_id="default"
                           )
        sess = session.Session(auth=auth)
        return ks_client.Client(auth_url=self.auth_url,
                                username=self.username,
                                password=self.password,
                                tenant_name='5gcore',
                                )


if __name__ == '__main__':
    unittest.main()
