import logging
import traceback

import neutronclient
from glanceclient import Client as Glance
from keystoneauth1 import session
from keystoneauth1.identity import v2
from keystoneclient.v2_0 import client as ks_client
from neutronclient.common.exceptions import IpAddressGenerationFailureClient
from neutronclient.v2_0.client import Client as Neutron
from novaclient.client import Client as Nova

from eu.softfire.nfv.utils.exceptions import OpenstackClientError
from eu.softfire.nfv.utils.utils import get_logger, get_config, get_openstack_credentials

logger = get_logger(__name__)

NETWORKS = ["mgmt", "net_a", "net_b", "net_c", "net_d", "private", "softfire-internal"]


class OSClient(object):
    def __init__(self, testbed_name, testbed, tenant_name=None):
        self.testbed_name = testbed_name
        self.testbed = testbed
        self.username = self.testbed.get('username')
        self.password = self.testbed.get('password')
        self.auth_url = self.testbed.get("auth_url")
        self.admin_tenant_name = self.testbed.get("admin_tenant_name")
        self.neutron = None
        self.nova = None
        self.glance = None
        self.keypair = None
        self.sec_group = None
        self.os_tenant_id = None
        logger.debug("Log level is: %s and DEBUG is %s" % (logger.getEffectiveLevel(), logging.DEBUG))
        if logger.getEffectiveLevel() == logging.DEBUG:
            logging.basicConfig(level=logging.DEBUG)
        if not tenant_name:
            logger.debug("Creating keystone client")
            self.keystone = ks_client.Client(auth_url=self.auth_url,
                                             username=self.username,
                                             password=self.password,
                                             tenant_name=self.admin_tenant_name)
            logger.debug("Created Keystone client %s" % self.keystone)
        else:
            self.tenant_name = tenant_name
            logger.debug("Creating keystone client")
            self.keystone = ks_client.Client(auth_url=self.auth_url,
                                             username=self.username,
                                             password=self.password,
                                             tenant_name=tenant_name)
            logger.debug("Created Keystone client %s" % self.keystone)
            self.os_tenant_id = self._get_tenant_id_from_name(self.tenant_name)
            self.set_nova(self.os_tenant_id)
            self.set_neutron(self.os_tenant_id)
            self.set_glance(self.os_tenant_id)

    def set_nova(self, os_tenant_id):
        self.os_tenant_id = os_tenant_id
        if not self.nova:
            self.nova = Nova('2', self.username, self.password, self.os_tenant_id, self.auth_url)

    def set_neutron(self, os_tenant_id):
        self.os_tenant_id = os_tenant_id
        if not self.neutron:
            self.neutron = Neutron(username=self.username,
                                   password=self.password,
                                   tenant_id=self.os_tenant_id,
                                   auth_url=self.auth_url)

    def get_user(self, username=None):
        users = self.keystone.users.list()
        if username:
            un = username
        else:
            un = self.username
        for user in users:
            if user.name == un:
                return user

    def get_role(self, role_to_find):
        roles = self.keystone.roles.list()
        for role in roles:
            if role.name == role_to_find:
                return role

    def list_tenants(self):
        return self.keystone.tenants.list()

    def create_tenant(self, tenant_name, description):
        self.tenant_name = tenant_name
        return self.keystone.tenants.create(tenant_name=tenant_name, description=description)

    def add_user_role(self, user, role, tenant):
        return self.keystone.roles.add_user_role(user=user, role=role, tenant=tenant)

    def import_keypair(self, os_tenant_id=None):
        if not self.nova and not os_tenant_id:
            raise OpenstackClientError("Both os_tenant_id and nova obj are None")
        if not self.nova:
            self.set_nova(os_tenant_id=os_tenant_id)
        keypair_name = "softfire-key"
        self.keypair = keypair_name
        for keypair in self.nova.keypairs.list():
            if keypair.name == keypair_name:
                return keypair
        kargs = {"name": keypair_name,
                 "public_key": open(get_config().get('system', 'softfire-public-key'), "r").read()}
        return self.nova.keypairs.create(**kargs)

    def get_ext_net(self, ext_net_name='softfire-network'):
        return [ext_net for ext_net in self.neutron.list_networks()['networks'] if
                ext_net['router:external'] and ext_net['name'] == ext_net_name][0]

    def allocate_floating_ips(self, fip_num=0, ext_net='softfire-network'):
        body = {"floatingip": {"floating_network_id": ext_net['id']}}
        for i in range(fip_num):
            try:
                self.neutron.create_floatingip(body=body)
            except IpAddressGenerationFailureClient as e:
                logger.error("Not able to allocate floatingips :(")
                raise OpenstackClientError("Not able to allocate floatingips :(")

    def create_networks_and_subnets(self, ext_net, router_name='ob_router'):
        networks = []
        subnets = []
        ports = []
        router_id = None
        exist_net = [network for network in self.neutron.list_networks()['networks']]
        exist_net_names = [network['name'] for network in exist_net]
        net_name_to_create = [net for net in NETWORKS if net not in exist_net_names]
        networks.extend(network for network in exist_net if network['name'] in NETWORKS)
        index = 1
        for net in net_name_to_create:
            kwargs = {'network': {
                'name': net,
                'shared': False,
                'admin_state_up': True
            }}
            logger.debug("Creating net %s" % net)
            network_ = self.neutron.create_network(body=kwargs)['network']
            networks.append(network_)
            kwargs = {
                'subnets': [
                    {
                        'name': "subnet_%s" % net,
                        'cidr': "192.%s.%s.0/24" % ((get_username_hash(self.username) % 254) + 1, index),
                        'gateway_ip': '192.%s.%s.1' % ((get_username_hash(self.username) % 254) + 1, index),
                        'ip_version': '4',
                        'enable_dhcp': True,
                        'dns_nameservers': ['8.8.8.8'],
                        'network_id': network_['id']
                    }
                ]
            }
            logger.debug("Creating subnet subnet_%s" % net)
            subnet = self.neutron.create_subnet(body=kwargs)
            subnets.append(subnet)

            router = self.get_router_from_name(router_name, ext_net)
            router_id = router['router']['id']

            body_value = {
                'subnet_id': subnet['subnets'][0]['id'],
            }
            try:
                ports.append(self.neutron.add_interface_router(router=router_id, body=body_value))
            except Exception as e:
                pass
            index += 1

        return networks, subnets, router_id

    def get_router_from_name(self, router_name, ext_net):
        for router in self.neutron.list_routers()['routers']:
            if router['name'] == router_name:
                return self.neutron.show_router(router['id'])
        request = {'router': {'name': router_name, 'admin_state_up': True}}
        router = self.neutron.create_router(request)
        body_value = {"network_id": ext_net['id']}
        self.neutron.add_gateway_router(router=router['router']['id'], body=body_value)
        return router

    def create_rule(self, sec_group, protocol):
        body = {"security_group_rule": {
            "direction": "ingress",
            "port_range_min": "1",
            "port_range_max": "65535",
            # "name": sec_group['security_group']['name'],
            "security_group_id": sec_group['security_group']['id'],
            "remote_ip_prefix": "0.0.0.0/0",
            "protocol": protocol,
        }}
        if protocol == 'icmp':
            body['security_group_rule'].pop('port_range_min', None)
            body['security_group_rule'].pop('port_range_max', None)
        try:
            self.neutron.create_security_group_rule(body=body)
        except neutronclient.common.exceptions.Conflict as e:
            logger.error("error while creating a rule: %s" % e.message)
            pass

    def create_security_group(self, sec_group_name='ob_sec_group'):
        sec_group = {}
        for sg in self.neutron.list_security_groups()['security_groups']:
            if sg['name'] == sec_group_name:
                sec_group['security_group'] = sg
                break
        if len(sec_group) == 0:
            body = {"security_group": {
                'name': sec_group_name,
                'description': 'openbaton security group',
            }}
            sec_group = self.neutron.create_security_group(body=body)
            self.create_rule(sec_group, 'tcp')
            self.create_rule(sec_group, 'udp')
            self.create_rule(sec_group, 'icmp')
        self.sec_group = sec_group['security_group']
        return self.sec_group

    def get_vim_instance(self, tenant_name=None, username=None, password=None):
        if username:
            un = username
        else:
            un = self.username
        if password:
            pwd = password
        else:
            pwd = self.password
        if tenant_name:
            self.tenant_name = tenant_name
        tenant_id_from_name = self._get_tenant_id_from_name(tenant_name)
        if not self.keypair:
            self.keypair = self.import_keypair(os_tenant_id=tenant_id_from_name).name
        if not self.sec_group:
            self.set_neutron(tenant_id_from_name)
            self.sec_group = self.create_security_group()
        return {
            "name": "vim-instance-%s" % self.testbed_name,
            "authUrl": self.auth_url,
            "tenant": self.tenant_name,
            "username": un,
            "password": pwd,
            "keyPair": self.keypair,
            "securityGroups": [
                self.sec_group['name']
            ],
            "type": "openstack",
            "location": {
                "name": "Berlin",
                "latitude": "52.525876",
                "longitude": "13.314400"
            }
        }

    def list_images(self, tenant_id=None):
        if not self.nova:
            if not tenant_id:
                logger.error("Missing tenant_id!")
                raise OpenstackClientError('Missing tenant_id!')
            self.set_nova(tenant_id)
        try:
            imgs = self.nova.images.list()
            return imgs
        except:
            return self.glance.images.list()

    def _get_tenant_id_from_name(self, tenant_name):
        for tenant in self.keystone.tenants.list():
            if tenant.name == tenant_name:
                return tenant.id

    def set_glance(self, os_tenant_id):
        self.os_tenant_id = os_tenant_id
        auth = v2.Password(auth_url=self.auth_url,
                           username=self.username,
                           password=self.password,
                           tenant_name=self.tenant_name)
        sess = session.Session(auth=auth)
        self.glance = Glance('1', session=sess)

    def _get_tenant_name_from_id(self, os_tenant_id):
        for t in self.list_tenants():
            if t.id == os_tenant_id:
                return t.name

    def create_user(self, username, password, tenant_id=None):
        return self.keystone.users.create(username, password, tenant_id=tenant_id)


def _list_images_single_tenant(tenant_name, testbed, testbed_name):
    os_client = OSClient(testbed_name, testbed, tenant_name)
    result = []
    # TODO filter images per experimenter
    for image in os_client.list_images():
        logger.debug("%s" % image.name)
        result.append({
            'name': image.name,
            'testbed': testbed_name
        })
    return result


def list_images(tenant_name, testbed_name=None):
    openstack_credentials = get_openstack_credentials()
    images = []
    if not testbed_name:
        for name, testbed in openstack_credentials.items():
            logger.info("listing images for testbed %s" % name)
            try:
                images.extend(_list_images_single_tenant(tenant_name, testbed, name))
            except Exception as e:
                traceback.print_exc()
                logger.error("Error listing images for testbed: %s" % name)
                continue
    else:
        images = _list_images_single_tenant(tenant_name, openstack_credentials.get(testbed_name), testbed_name)
    return images


def create_os_project(username, password, tenant_name, testbed_name=None):
    openstack_credentials = get_openstack_credentials()
    os_tenants = {}
    if not testbed_name:
        for name, testbed in openstack_credentials.items():
            try:
                logger.info("Creating project on testbed: %s" % name)
                os_tenant_id, vim_instance = _create_single_project(tenant_name, testbed, name, username, password)
                logger.info("Created project %s on testbed: %s" % (os_tenant_id, name))
                os_tenants[name] = {'tenant_id': os_tenant_id, 'vim_instance': vim_instance}
            except:
                logger.error("Not able to create project in testbed %s" % name)
                traceback.print_exc()
                return
    else:
        os_tenant_id, vim_instance = _create_single_project(tenant_name,
                                                            openstack_credentials[testbed_name],
                                                            testbed_name)
        os_tenants[testbed_name] = {'tenant_id': os_tenant_id, 'vim_instance': vim_instance}
    return os_tenants


def _create_single_project(tenant_name, testbed, testbed_name, username, password):
    os_client = OSClient(testbed_name, testbed)
    logger.info("Created OSClient")
    os_tenant_id = None
    user = os_client.get_user()
    logger.debug("Got User %s" % user)
    role = os_client.get_role('admin')
    logger.debug("Got Role %s" % role)
    for tenant in os_client.list_tenants():
        if tenant.name == tenant_name:
            logger.warn("Tenant with name or id %s exists already! I assume a double registration i will not do "
                        "anything :)" % tenant_name)
            logger.warn("returning tenant id %s" % tenant.id)

            exp_user = os_client.get_user(username)
            if not exp_user:
                exp_user = os_client.create_user(username, password)
                role = os_client.get_role('_member_')
                os_client.add_user_role(user=exp_user, role=role, tenant=tenant.id)
            return tenant.id, os_client.get_vim_instance(tenant_name, username, password)
    if os_tenant_id is None:
        tenant = os_client.create_tenant(tenant_name=tenant_name,
                                         description='openbaton tenant for user %s' % tenant_name)
        logger.debug("Created tenant %s" % tenant)
        os_tenant_id = tenant.id
        logger.info("Created tenant with id: %s" % os_tenant_id)

    user = os_client.create_user(username, password)
    role = os_client.get_role('_member_')
    os_client.add_user_role(user=user, role=role, tenant=os_tenant_id)
    os_client = OSClient(testbed_name, testbed, tenant_name)

    keypair = os_client.import_keypair(os_tenant_id=os_tenant_id)
    logger.debug("imported keypair %s " % keypair)
    ext_net = os_client.get_ext_net(testbed.get('ext_net_name'))

    if ext_net is None:
        logger.error(
            "A shared External Network called %s must exist! "
            "Please create one in your openstack instance" % testbed.get('ext_net_name')
        )
        raise OpenstackClientError("A shared External Network called softfire-network must exist! "
                                   "Please create one in your openstack instance")
    # networks, subnets, router_id = os_client.create_networks_and_subnets(ext_net)
    # logger.debug("Created Network %s, Subnet %s, Router %s" % (networks, subnets, router_id))

    fips = testbed.get("allocate-fip")
    if fips is not None and int(fips) > 0:
        try:
            os_client.allocate_floating_ips(int(fips), ext_net)
        except OpenstackClientError as e:
            logger.warn(e.args)

    sec_group = os_client.create_security_group()
    vim_instance = os_client.get_vim_instance()
    return os_tenant_id, vim_instance


def get_username_hash(username):
    return abs(hash(username))


if __name__ == '__main__':
    res = list_images('5gcore', 'fokus')
    print(res)
