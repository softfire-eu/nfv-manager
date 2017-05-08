import json

import neutronclient
from neutronclient.common.exceptions import IpAddressGenerationFailureClient

from eu.softfire.utils.exceptions import OpenstackClientError
from eu.softfire.utils.utils import get_logger, get_config
from keystoneclient.v2_0.client import Client as Keystone
from neutronclient.v2_0.client import Client as Neutron
from novaclient.client import Client as Nova

logger = get_logger('eu.softfire.util.openstack')

NETWORKS = ["mgmt", "net_a", "net_b", "net_c", "net_d", "private", "softfire-internal"]


def get_user_by_username(username, keystone):
    users = keystone.users.list()
    for user in users:
        if user.name == username:
            return user


def get_role(role_to_find, keystone):
    roles = keystone.roles.list()
    for role in roles:
        if role.name == role_to_find:
            return role


def create_project(tenant_name, testbed_name=None):
    openstack_credentials = get_openstack_credentials()
    os_tenants = {}
    if not testbed_name:
        for name, testbed in openstack_credentials.items():
            os_tenant_id, vim_instance = _create_single_project(tenant_name, testbed, name)
            os_tenants[name] = {'tenant_id': os_tenant_id, 'vim_instance': vim_instance}
    else:
        os_tenant_id, vim_instance = _create_single_project(tenant_name,
                                                            openstack_credentials[testbed_name],
                                                            testbed_name)
        os_tenants[testbed_name] = {'tenant_id': os_tenant_id, 'vim_instance': vim_instance}
    return os_tenants


def _create_single_project(tenant_name, testbed, testbed_name):
    username = testbed.get('username')
    password = testbed.get('password')
    auth_url = testbed.get("auth_url")
    keystone = Keystone(username=username,
                        password=password,
                        auth_url=auth_url,
                        tenant_name=tenant_name)
    os_tenant = None
    user = get_user_by_username(username, keystone)
    role = get_role('admin', keystone)
    for tenant in keystone.tenants.list():
        if tenant.name == tenant_name:
            logger.warn("Tenant with name or id %s exists already! I assume a double registration i will not do "
                        "anything :)" % tenant_name)
            logger.warn("returning tenant id %s" % tenant.id)
            return tenant.id
    if os_tenant is None:
        tenant = keystone.tenants.create(tenant_name=tenant_name,
                                         description='openbaton tenant for user %s' % tenant_name)
        os_tenant = tenant.id
        logger.debug("Created tenant with id: %s" % os_tenant)
    keystone.roles.add_user_role(user=user, role=role, tenant=os_tenant)

    neutron = Neutron(username=username,
                      password=password,
                      project_name=tenant_name,
                      auth_url=auth_url)

    nova = Nova('2', username, password, os_tenant, auth_url)

    keypair = import_keypair(nova=nova)
    logger.debug("imported keypair")

    ext_net = get_ext_net(neutron, testbed.get('ext_net_name'))
    if ext_net is None:
        logger.error(
            "A shared External Network called softfire-network must exist! "
            "Please create one in your openstack instance"
        )
        raise OpenstackClientError("A shared External Network called softfire-network must exist! "
                                   "Please create one in your openstack instance")
    logger.debug("Created Network %s, Subnet %s, Router %s" % create_networks_and_subnets(neutron, ext_net))
    fips = testbed.get("allocate-fip")
    if fips is not None and int(fips) > 0:
        allocate_floating_ips(neutron, int(fips), ext_net)
    sec_group = create_security_group(neutron)
    vim_instance = {
        "name": "vim-instance-%s" % testbed_name,
        "authUrl": auth_url,
        "tenant": tenant_name,
        "username": username,
        "password": password,
        "keyPair": keypair.name,
        "securityGroups": [
            sec_group['name']
        ],
        "type": "openstack",
        "location": {
            "name": "Berlin",
            "latitude": "52.525876",
            "longitude": "13.314400"
        }
    }
    return os_tenant, vim_instance


def get_openstack_credentials():
    openstack_credential_file_path = get_config().get('system', 'openstack-credentials-file')
    with open(openstack_credential_file_path, "r") as f:
        return json.loads(f.read())


def get_ext_net(neutron, ext_net_name='softfire-network'):
    return [ext_net for ext_net in neutron.list_networks()['networks'] if
            ext_net['router:external'] and ext_net['name'] == ext_net_name][0]


def import_keypair(nova):
    for keypair in nova.keypairs.list():
        if keypair.name == "softfire-key":
            return keypair
    kargs = {"name": "softfire-key", "public_key": open(get_config().get('system', 'softfire-public-key'), "r").read()}
    return nova.keypairs.create(**kargs)


def create_networks_and_subnets(neutron, ext_net, router_name='ob_router'):
    networks = []
    subnets = []
    ports = []
    router_id = None
    exist_net = [network for network in neutron.list_networks()['networks']]
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
        network_ = neutron.create_network(body=kwargs)['network']
        networks.append(network_)
        kwargs = {
            'subnets': [
                {
                    'name': "subnet_%s" % net,
                    'cidr': "192.168.%s.0/24" % index,
                    'gateway_ip': '192.168.%s.1' % index,
                    'ip_version': '4',
                    'enable_dhcp': True,
                    'dns_nameservers': ['8.8.8.8'],
                    'network_id': network_['id']
                }
            ]
        }
        logger.debug("Creating subnet subnet_%s" % net)
        subnet = neutron.create_subnet(body=kwargs)
        subnets.append(subnet)

        router = get_router_from_name(neutron, router_name, ext_net)
        router_id = router['router']['id']

        body_value = {
            'subnet_id': subnet['subnets'][0]['id'],
        }
        try:
            ports.append(neutron.add_interface_router(router=router_id, body=body_value))
        except Exception as e:
            pass
        index += 1

    return networks, subnets, router_id


def get_router_from_name(neutron, router_name, ext_net):
    for router in neutron.list_routers()['routers']:
        if router['name'] == router_name:
            return neutron.show_router(router['id'])
    request = {'router': {'name': router_name, 'admin_state_up': True}}
    router = neutron.create_router(request)
    body_value = {"network_id": ext_net['id']}
    neutron.add_gateway_router(router=router['router']['id'], body=body_value)
    return router


def allocate_floating_ips(neutron, fip_num, ext_net):
    body = {"floatingip": {"floating_network_id": ext_net['id']}}
    for i in range(fip_num):
        try:
            neutron.create_floatingip(body=body)
        except IpAddressGenerationFailureClient as e:
            logger.error("Not able to allocate floatingips :(")
            raise OpenstackClientError("Not able to allocate floatingips :(")


def create_rule(neutron, sec_group, protocol):
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
        neutron.create_security_group_rule(body=body)
    except neutronclient.common.exceptions.Conflict as e:
        logger.error("error while creating a rule: %s" % e.message)
        pass


def create_security_group(neutron, sec_group_name='ob_sec_group'):
    sec_group = {}
    for sg in neutron.list_security_groups()['security_groups']:
        if sg['name'] == sec_group_name:
            sec_group['security_group'] = sg
            break
    if len(sec_group) == 0:
        body = {"security_group": {
            'name': sec_group_name,
            'description': 'openbaton security group',
        }}
        sec_group = neutron.create_security_group(body=body)
    create_rule(neutron, sec_group, 'tcp')
    create_rule(neutron, sec_group, 'udp')
    create_rule(neutron, sec_group, 'icmp')
    return sec_group['security_group']

# def associate_router_to_subnets(networks, neutron, router_name='ob_router'):
#     router = get_router_from_name(neutron, router_name, ext_net)
#     router_id = router['router']['id']
#
#     ports = []
#     for network in networks:
#         logger.dubug("checking net: %s" % network['name'])
#         net_has_int = False
#         for port in neutron.list_ports()['ports']:
#             logger.dubug("Checking port:\n%s" % port)
#             if port['network_id'] == network['id']:
#                 body_value = {
#                     'subnet_id': network['subnets'][0],
#                 }
#                 try:
#                     ports.append(neutron.add_interface_router(router=router_id, body=body_value))
#                 except Exception as e:
#                     print
#                     e.message
#                 net_has_int = True
#         if not net_has_int:
#             body_value = {'port': {
#                 'admin_state_up': True,
#                 'device_id': router_id,
#                 'name': 'ob_port',
#                 'network_id': network['id'],
#
#                 # 'network_id': subnet['id'],
#             }}
#             logger.dubug("Creating port: %s" % body_value['port']['name'])
#             ports.append(neutron.create_port(body=body_value))
#
#     return router, ports
