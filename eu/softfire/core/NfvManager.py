import json

from org.openbaton.cli.agents.agents import OpenBatonAgentFactory
from org.openbaton.cli.openbaton import LIST_PRINT_KEY

import eu.softfire.utils.os_utils as os_utils
from eu.softfire.messaging.grpc import messages_pb2
from eu.softfire.utils.os_utils import create_os_project
from eu.softfire.utils.utils import get_config, get_logger

logger = get_logger('eu.softfire.core')

AVAILABLE_AGENTS = LIST_PRINT_KEY.keys()
AVAILABLE_NSD = {
    'openimscore': {
        'description': "The Open IMS Core is an Open Source implementation of IMS Call Session Control Functions ("
                       "CSCFs) and a lightweight Home Subscriber Server (HSS), which together form the core elements "
                       "of all IMS/NGN architectures as specified today within 3GPP, 3GPP2, ETSI TISPAN and the PacketCable"
                       " intiative. The four components are all based upon Open Source software(e.g. the SIP Express Router"
                       " (SER) or MySQL).",
        "cardinality": -1,
        "node_type": 'NfvResource',
        "testbed": None
    },
    'open5gcore': {
        'description': "Open5GCore is a prototype implementation of the pre-standard 5G network. The software is "
                       "available from November 2014 and its main features are described on www.open5gcore.net. "
                       "Open5GCore represents the continuation of the OpenEPC project towards R&D testbed "
                       "deployments. It has been used over the years in multiple projects as a reference vEPC "
                       "implementation.",
        'cardinality': -1,
        "node_type": 'NfvResource',
        'testbed': messages_pb2.FOKUS
    },
}
CARDINALITY = {
    'open5gcore': 1,
}

TESTBED_MAPPING = {
    'fokus': messages_pb2.FOKUS,
    'fokus-dev': messages_pb2.FOKUS_DEV,
    'ericsson': messages_pb2.ERICSSON,
    'ericsson-dev': messages_pb2.ERICSSON_DEV,
    'surrey': messages_pb2.SURREY,
    'surrey-dev': messages_pb2.SURREY_DEV,
    'ads': messages_pb2.ADS,
    'ads-dev': messages_pb2.ADS_DEV,
    'dt': messages_pb2.DT,
    'dt-dev': messages_pb2.DT_DEV,
}


class OBClient(object):
    def __init__(self, project_name=None):
        """
        If username and password are passed, it will create a openbaton agent using these ones. if not it will use the 
        configuration parameter ones.
        
        :param project_name: the project of a specific user.
        """
        config = get_config()
        https = config.getboolean("nfvo", "https")

        username = config.get("nfvo", "username")

        password = config.get("nfvo", "password")

        self.agent = OpenBatonAgentFactory(nfvo_ip=config.get("nfvo", "ip"),
                                           nfvo_port=config.get("nfvo", "port"),
                                           https=https,
                                           version=1,
                                           username=username,
                                           password=password,
                                           project_id=None)
        if project_name:
            self.project_id = self._get_project_id(project_name)
            # self.agent._client.project_id = self.project_id

    def _get_project_id(self, project_name):
        project_agent = self.agent.get_project_agent()
        for project in json.loads(project_agent.find()):
            if project.get('name') == project_name:
                return project.get('id')
        return None

    def list_nsds(self):
        return self.agent.get_ns_descriptor_agent(self.project_id).find()

    def create_nsr(self, nsd_id):
        return self.agent.get_ns_records_agent(self.project_id).create(nsd_id)

    def delete_nsr(self, nsr_id):
        return self.agent.get_ns_records_agent(self.project_id).delete(nsr_id)

    def create_project(self, project):
        for p in json.loads(self.list_projects()):
            if p.get('name') == project.get('name'):
                return p
        if isinstance(project, dict):
            project = json.dumps(project)
        ob_project = self.agent.get_project_agent().create(project)
        self.project_id = ob_project.get('id')
        return ob_project

    def create_user(self, user):

        for us in json.loads(self.list_users()):
            if us.get('username') == user.get('username'):
                return us

        if isinstance(user, dict):
            user = json.dumps(user)
        return self.agent.get_user_agent(self.project_id).create(user)

    def create_vim_instance(self, vim_instance):
        for vi in json.loads(self.list_vim_instances()):
            if vi.get('name') == vim_instance.get('name'):
                return vi
        if isinstance(vim_instance, dict):
            vim_instance = json.dumps(vim_instance)
        return self.agent.get_vim_instance_agent(self.project_id).create(vim_instance)

    def list_users(self):
        return self.agent.get_user_agent(self.project_id).find()

    def list_projects(self):
        return self.agent.get_project_agent().find()

    def list_vim_instances(self):
        return self.agent.get_vim_instance_agent(self.project_id).find()


def list_images(tenant_name):
    result = []
    for image in os_utils.list_images(tenant_name):
        testbed = image.get('testbed')
        resource_id = image.get('name')
        result.append(messages_pb2.ResourceMetadata(resource_id=resource_id,
                                                    description='',
                                                    cardinality=-1,
                                                    node_type='NfvImage',
                                                    testbed=TESTBED_MAPPING.get(testbed)))
    return result


def list_resources(payload, user_info):
    result = []

    if user_info and user_info.name:
        ob_client = OBClient(user_info.name)

        for nsd in ob_client.list_nsds():
            result.append(messages_pb2.ResourceMetadata(nsd.name,
                                                        nsd.get('description') or AVAILABLE_NSD[nsd.name.lower()].get(
                                                            'description'),
                                                        CARDINALITY[nsd.name.lower()]))

            result.extend(list_images(user_info.name))

    for k, v in AVAILABLE_NSD.items():
        testbed = v.get('testbed')
        node_type = v.get('node_type')
        cardinality = int(v.get('cardinality'))
        description = v.get('description')
        resource_id = k
        result.append(messages_pb2.ResourceMetadata(resource_id=resource_id,
                                                    description=description,
                                                    cardinality=cardinality,
                                                    node_type=node_type,
                                                    testbed=testbed))

    return result


def provide_resources(payload, user_info):
    ob_client = OBClient(user_info.name)
    nsr = ob_client.create_nsr(payload.get("nsd-id"))
    return messages_pb2.ProvideResourceResponse(resources=nsr)


def release_resources(payload, user_info):
    ob_client = OBClient(user_info.name)
    ob_client.delete_nsr(payload.get("nsr-id"))


def create_user(name, password):
    os_tenants = create_os_project(tenant_name=name)
    ob_client = OBClient()
    project = {
        'name': name,
        'description': 'the project for user %s' % name
    }
    project = ob_client.create_project(project)
    user = {
        'username': name,
        'password': password,
        'enabled': True,
        'email': None,
        'roles': [
            {
                'role': 'USER',
                'project': project.get('name')
            }
        ]
    }
    logger.debug("Create openbaton project %s" % project)
    ob_client = OBClient(project.get('name'))
    user = ob_client.create_user(user)
    logger.debug("Create openbaton user %s" % user)

    user_info = messages_pb2.UserInfo(
        name=name,
        password=password,
        ob_project_id=project.get('id'),
        testbed_tenants={}
    )

    testbed_tenants = {}

    for testbed_name, v in os_tenants.items():
        # v == {'tenant_id': os_tenant_id, 'vim_instance': vim_instance}
        tenant_id = v.get('tenant_id')
        vim_instance = v.get('vim_instance')
        vi = ob_client.create_vim_instance(vim_instance)
        logger.debug("created vim instance with id: %s" % vi.get('id'))
        testbed_tenants[TESTBED_MAPPING[testbed_name]] = tenant_id

    for k, v in testbed_tenants.items():
        user_info.testbed_tenants[k] = v
    logger.debug("Updated user_info %s" % user_info)

    return user_info
