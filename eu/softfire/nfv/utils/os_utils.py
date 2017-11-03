import logging
import traceback

import keystoneclient
import neutronclient
from glanceclient import Client as Glance
from keystoneauth1 import session
from keystoneauth1.identity import v2, v3
from keystoneauth1.exceptions.http import Conflict
from neutronclient.common.exceptions import IpAddressGenerationFailureClient
from neutronclient.v2_0.client import Client as Neutron
from novaclient.client import Client as Nova

from eu.softfire.nfv.utils.exceptions import OpenstackClientError
from eu.softfire.nfv.utils.utils import get_logger, get_config, get_openstack_credentials, get_testbed_name_from_id

logger = get_logger(__name__)

NETWORKS = ["mgmt", "net_a", "net_b", "net_c", "net_d", "private", "softfire-internal"]
sec_group_name = 'ob_sec_group'


class OSClient(object):
    def __init__(self, testbed_name, testbed, tenant_name=None, project_id=None):
        self.testbed_name = testbed_name
        self.tenant_name = None
        self.project_id = None
        self.testbed = testbed
        self.project_domain_name = self.testbed.get('project_domain_name') or 'Default'
        self.user_domain_name = self.testbed.get('user_domain_name') or 'Default'
        self.api_version = self.testbed.get('api_version')
        self.username = self.testbed.get('username')
        self.password = self.testbed.get('password')
        self.auth_url = self.testbed.get("auth_url")
        if self.auth_url.endswith('/'):
            self.auth_url = self.auth_url[:-1]
        self.admin_tenant_name = self.testbed.get("admin_tenant_name")
        self.admin_project_id = self.testbed.get("admin_project_id")
        if not self.admin_tenant_name and not self.admin_project_id:
            raise OpenstackClientError("Missing both adimn project id and admin tenant name")
        if self.api_version == 2 and not self.admin_tenant_name:
            raise OpenstackClientError("Missing tenant name required if using v2")
        if self.api_version == 3 and not self.admin_project_id:
            raise OpenstackClientError("Missing project id required if using v3")

        self.neutron = None
        self.nova = None
        self.glance = None
        self.keypair = None
        self.sec_group = None
        self.os_tenant_id = None

        logger.debug("Log level is: %s and DEBUG is %s" % (logger.getEffectiveLevel(), logging.DEBUG))
        if logger.getEffectiveLevel() == logging.DEBUG:
            logging.basicConfig(level=logging.DEBUG)

        if not tenant_name and not project_id:

            self.keystone = self._create_keystone_client()
            logger.debug("Created Keystone client %s" % self.keystone)
        else:
            self.tenant_name = tenant_name
            self.project_id = project_id

            if self.api_version == 2 and not self.tenant_name:
                raise OpenstackClientError("Missing tenant name required if using v2")
            if self.api_version == 3 and not self.project_id:
                raise OpenstackClientError("Missing project id required if using v3")

            logger.debug("Creating keystone client")
            if self.api_version == 3:
                self.keystone = self._create_keystone_client(project_id)
                self.os_tenant_id = project_id
            else:
                self.keystone = self._create_keystone_client(tenant_name)
                self.os_tenant_id = self.project_id = self._get_tenant_id_from_name(tenant_name)

            logger.debug("Created Keystone client %s" % self.keystone)
            self.set_nova(self.os_tenant_id)
            self.set_neutron(self.os_tenant_id)
            self.set_glance(self.os_tenant_id)

    def _create_keystone_client(self, project_id=None):
        if self.api_version == 3:
            return keystoneclient.v3.client.Client(session=self._get_session(project_id))
        elif self.api_version == 2:
            if not project_id:
                project_id = self.tenant_name or self.admin_tenant_name
            return keystoneclient.v2_0.client.Client(username=self.username,
                                                     password=self.password,
                                                     tenant_name=project_id,
                                                     auth_url=self.auth_url)

    def set_nova(self, os_tenant_id):
        self.nova = Nova('2.1', session=self._get_session(os_tenant_id))

    def _get_session(self, tenant_id=None):
        if self.api_version == 2:
            tenant_name = self.tenant_name or self.admin_tenant_name
            auth = v2.Password(auth_url=self.auth_url,
                               username=self.username,
                               password=self.password,
                               tenant_name=tenant_name)
        elif self.api_version == 3:
            p_id = tenant_id or self.project_id or self.admin_project_id
            auth = v3.Password(auth_url=self.auth_url,
                               username=self.username,
                               password=self.password,
                               project_id=p_id,
                               project_domain_name=self.project_domain_name,
                               user_domain_name=self.user_domain_name)
        else:
            msg = "Wrong api version: %s" % self.api_version
            logger.error(msg)
            raise OpenstackClientError(msg)
        return session.Session(auth=auth)

    def set_neutron(self, os_tenant_id):
        # self.os_tenant_id = os_tenant_id
        if not self.neutron:
            self.neutron = Neutron(session=self._get_session(os_tenant_id))

    def get_user(self, username=None):
        users = self.list_users()
        if username:
            un = username
        else:
            un = self.username
        for user in users:
            if user.name == un:
                return user

    def get_role(self, role_to_find):
        roles = self.list_roles()
        for role in roles:
            if role.name == role_to_find:
                return role

    def list_roles(self):
        return self.keystone.roles.list()

    def list_tenants(self):
        if self.api_version == 3:
            return self.keystone.projects.list()
        else:
            return self.keystone.tenants.list()

    def create_tenant(self, tenant_name, description):
        self.tenant_name = tenant_name
        if self.api_version == 2:
            return self.keystone.tenants.create(tenant_name=tenant_name, description=description)
        else:
            return self.keystone.projects.create(name=tenant_name, description=description,
                                                 domain=self.user_domain_name.lower())

    def add_user_role(self, user, role, tenant):
        if self.api_version == 2:
            try:
                return self.keystone.roles.add_user_role(user=user, role=role, tenant=tenant)
            except Conflict as c:
                if c.http_status == 409:  # role already assigned to user
                    return
                raise c
        else:
            return self.keystone.roles.grant(user=user, role=role, project=tenant)

    def import_keypair(self, os_tenant_id=None):
        if not self.nova and not os_tenant_id:
            raise OpenstackClientError("Both os_tenant_id and nova obj are None")
        if not self.nova:
            self.set_nova(os_tenant_id=os_tenant_id)
        keypair_name = "softfire-key"
        self.keypair = keypair_name
        for keypair in self.list_keypairs(os_tenant_id):
            if keypair.name == keypair_name:
                return keypair
        with open(get_config().get('system', 'softfire-public-key'), "r") as sosftfire_ssh_pub_key:
            kargs = {"name": keypair_name,
                     "public_key": sosftfire_ssh_pub_key.read()}
            return self.nova.keypairs.create(**kargs)

    def get_ext_net(self, ext_net_name='softfire-network'):
        return [ext_net for ext_net in self.neutron.list_networks()['networks'] if
                ext_net['router:external'] and ext_net['name'] == ext_net_name][0]

    def allocate_floating_ips(self, fip_num=0, ext_net='softfire-network'):
        body = {
            "floatingip": {
                "floating_network_id": ext_net['id']
            }
        }
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

    def create_security_group(self, project_id, sec_g_name=None):
        if not sec_g_name:
            sec_g_name = sec_group_name
        sec_group = {}
        for sg in self.list_sec_group(project_id):
            if sg['name'] == sec_g_name:
                sec_group['security_group'] = sg
                break
        if len(sec_group) == 0:
            body = {"security_group": {
                'name': sec_g_name,
                'description': 'openbaton security group',
            }}
            sec_group = self.neutron.create_security_group(body=body)
            self.create_rule(sec_group, 'tcp')
            self.create_rule(sec_group, 'udp')
            self.create_rule(sec_group, 'icmp')
        self.sec_group = sec_group['security_group']
        return self.sec_group

    def list_sec_group(self, os_project_id):
        if not self.neutron:
            self.set_neutron(os_project_id)
        return [sec for sec in self.neutron.list_security_groups()['security_groups'] if
                (sec.get('tenant_id') is not None and sec.get('tenant_id') == os_project_id) or (
                    sec.get('project_id') is not None and sec.get('project_id') == os_project_id)]

    def get_vim_instance(self, tenant_name, username=None, password=None):
        if username:
            un = username
        else:
            un = self.username
        if password:
            pwd = password
        else:
            pwd = self.password

        logger.debug("Using tenant id: %s " % tenant_name)

        return {
            "name": "vim-instance-%s" % self.testbed_name,
            "authUrl": self.auth_url,
            "tenant": tenant_name,
            "username": un,
            "password": pwd,
            "securityGroups": [
                'default', sec_group_name
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
            self.set_glance(tenant_id)
            return self.glance.images.list()

    def _get_tenant_id_from_name(self, tenant_name):
        if self.api_version == 2:
            tenants_list = self.keystone.tenants.list()
        else:
            tenants_list = self.keystone.projects.list()
        for tenant in tenants_list:
            if tenant.name == tenant_name:
                return tenant.id

    def set_glance(self, os_tenant_id):
        self.os_tenant_id = os_tenant_id
        self.glance = Glance('1', session=self._get_session(os_tenant_id))

    def _get_tenant_name_from_id(self, os_tenant_id):
        for t in self.list_tenants():
            if t.id == os_tenant_id:
                return t.name

    def create_user(self, username, password=None, tenant_id=None):
        for u in self.list_users():
            if hasattr(u, 'username'):
                u_username = u.username
            else:
                u_username = u.name
            if u_username == username:
                return u
        if not password:
            raise OpenstackClientError("Paswsord is needed to create user")
        if self.api_version == 2:
            return self.keystone.users.create(username, password, tenant_id=tenant_id)
        else:
            return self.keystone.users.create(name=username, password=password,
                                              project=self.get_project_from_id(tenant_id))

    def list_users(self):
        return self.keystone.users.list()

    def list_networks(self, project_id=None):
        if not self.neutron:
            if not project_id:
                raise OpenstackClientError("Missing project_id!")
            self.set_neutron(project_id)
        return self.neutron.list_networks(tenant_id=project_id)

    def list_subnets(self, project_id):
        if not self.neutron:
            if not project_id:
                raise OpenstackClientError("Missing project_id!")
            self.set_neutron(project_id)
        return self.neutron.list_subnets(tenant_id=project_id)

    def list_floatingips(self, project_id):
        if not self.neutron:
            if not project_id:
                raise OpenstackClientError("Missing project_id!")
            self.set_neutron(project_id)
        return self.neutron.list_floatingips(tenant_id=project_id)

    def list_routers(self, project_id):
        if not self.neutron:
            if not project_id:
                raise OpenstackClientError("Missing project_id!")
            self.set_neutron(project_id)
        return self.neutron.list_routers(tenant_id=project_id)

    def list_ports(self, project_id):
        if not self.neutron:
            if not project_id:
                raise OpenstackClientError("Missing project_id!")
            self.set_neutron(project_id)
        return self.neutron.list_ports(tenant_id=project_id)

    def list_keypairs(self, os_project_id=None):
        if not self.nova:
            if not os_project_id:
                raise OpenstackClientError("Missing project_id!")
            self.set_nova(os_project_id)
        return self.nova.keypairs.list()

    def list_domains(self):
        return self.keystone.domains.list()

    def get_project_from_id(self, tenant_id):
        for p in self.list_tenants():
            if p.id == tenant_id:
                return p
        raise OpenstackClientError("Project with id %s not found")

    def delete_user(self, username):
        try:
            self.keystone.users.delete(self.create_user(username=username))
        except:
            traceback.print_exc()
            logger.error("Not Able to delete user %s" % username)

    def delete_project(self, project_id):
        try:
            if self.api_version == 2:
                self.keystone.tenants.delete(project_id)
            else:
                self.keystone.projects.delete(project_id)
        except:
            traceback.print_exc()
            logger.error("Not Able to delete project %s" % project_id)

    def release_floating_ips(self, project_id):
        fips = self.list_floatingips(project_id).get('floatingips')
        for fip in fips:
            self.neutron.delete_floatingip(fip.get('id'))

    def delete_ports(self, project_id):
        ports = self.list_ports(project_id).get('ports')
        for port in ports:
            try:
                self.neutron.delete_port(port.get('id'))
            except Exception as e:
                pass

    def remove_gateway_routers(self, project_id):
        routers = self.list_routers(project_id).get('routers')
        for router in routers:
            self.neutron.remove_gateway_router(router.get('id'))

    def remove_interface_routers(self, project_id):
        routers = self.list_routers(project_id).get('routers')
        subnets = self.list_subnets(project_id).get('subnets')
        for router in routers:
            for subnet in subnets:
                body_value = {
                    'subnet_id': subnet.get('id'),
                }
                try:
                    self.neutron.remove_interface_router(router.get('id'), body_value)
                    break
                except Exception as e:
                    pass
            else:
                logger.warn('No subnet found that is associated to router {}'.format(router.get('id')))

    def delete_routers(self, project_id):
        routers = self.list_routers(project_id).get('routers')
        for router in routers:
            self.neutron.delete_router(router.get('id'))



    def delete_networks(self, project_id):
        networks = self.list_networks(project_id).get('networks')
        for nw in networks:
            self.neutron.delete_network(nw.get('id'))

    def delete_security_groups(self, project_id):
        sec_groups = self.list_sec_group(project_id)
        for sec_group in sec_groups:
            self.neutron.delete_security_group(sec_group.get('id'))




def _list_images_single_tenant(tenant_name, testbed, testbed_name):
    os_client = OSClient(testbed_name, testbed, tenant_name)
    result = []
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
                continue
    else:
        os_tenant_id, vim_instance = _create_single_project(tenant_name,
                                                            openstack_credentials[testbed_name],
                                                            testbed_name)
        os_tenants[testbed_name] = {'tenant_id': os_tenant_id, 'vim_instance': vim_instance}
    return os_tenants


def _create_single_project(tenant_name, testbed, testbed_name, username, password):
    os_client = OSClient(testbed_name, testbed)
    logger.info("Created OSClient for testbed %s" % testbed_name)
    admin_user = os_client.get_user()

    logger.debug("Got User %s" % admin_user)
    admin_role = os_client.get_role('admin')
    try:
        user_role = os_client.get_role('_member_')
    except:
        user_role = os_client.get_role('member')

    logger.debug("Got Role %s" % admin_role)
    for tenant in os_client.list_tenants():
        if tenant.name == tenant_name:
            logger.warn("Tenant with name or id %s exists already! I assume a double registration i will not do "
                        "anything :)" % tenant_name)
            logger.warn("returning tenant id %s" % tenant.id)

            exp_user = os_client.get_user(username)
            if not exp_user:
                exp_user = os_client.create_user(username, password)
                os_client.add_user_role(user=exp_user, role=user_role, tenant=tenant.id)
                os_client.add_user_role(user=admin_user, role=admin_role, tenant=tenant.id)
            if os_client.api_version == 2:
                vim_instance = os_client.get_vim_instance(tenant_name=tenant_name, username=username, password=password)
            else:
                vim_instance = os_client.get_vim_instance(tenant_name=tenant.id, username=username, password=password)
            return tenant.id, vim_instance

    tenant = os_client.create_tenant(tenant_name=tenant_name, description='softfire tenant for user %s' % tenant_name)
    logger.debug("Created tenant %s" % tenant)
    os_tenant_id = tenant.id
    logger.info("Created tenant with id: %s" % os_tenant_id)

    exp_user = os_client.create_user(username, password, os_tenant_id)
    os_client.add_user_role(user=admin_user, role=admin_role, tenant=os_tenant_id)
    os_client.add_user_role(user=exp_user, role=user_role, tenant=os_tenant_id)

    os_client = OSClient(testbed_name, testbed, project_id=os_tenant_id, tenant_name=tenant_name)

    try:
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

    except:
        logger.warning("Not able to get ext net")

    os_client.create_security_group(os_tenant_id)
    if os_client.api_version == 2:
        vim_instance = os_client.get_vim_instance(tenant_name=tenant_name, username=username, password=password)
    else:
        vim_instance = os_client.get_vim_instance(tenant_name=tenant.id, username=username, password=password)
    return os_tenant_id, vim_instance


def get_username_hash(username):
    return abs(hash(username))


def delete_tenant_and_user(username, testbed_tenants):
    openstack_credentials = get_openstack_credentials()
    for testbed_id, project_id in testbed_tenants.items():
        for testbed_name, credentials in openstack_credentials.items():
            if get_testbed_name_from_id(testbed_id) == testbed_name:
                os_client = OSClient(testbed_name, credentials)
                os_client.delete_security_groups(project_id)
                os_client.release_floating_ips(project_id)
                os_client.remove_gateway_routers(project_id)
                os_client.remove_interface_routers(project_id)
                os_client.delete_ports(project_id)
                os_client.delete_routers(project_id)
                os_client.delete_networks(project_id)
                os_client.delete_user(username)
                os_client.delete_project(project_id)


if __name__ == '__main__':
    for testbed_name, credentials in get_openstack_credentials().items():
        print("Executing list test on testbed %s" % testbed_name)
        client = OSClient(testbed_name, credentials)
        project_id = credentials.get("admin_project_id")
        print(client.list_images(project_id))
        print(client.list_tenants())
        print(client.list_users())
        print(client.list_roles())
        print(client.list_networks(project_id))
        print(client.list_keypairs(project_id))
        print(client.list_domains())
        print(client.list_sec_group(project_id))
