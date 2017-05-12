from org.openbaton.cli.agents.agents import OpenBatonAgentFactory
from org.openbaton.cli.openbaton import LIST_PRINT_KEY

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
        "testbed": None
    },
    'open5gcore': {
        'description': "the description goes here",
        'cardinality': -1,
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
        for project in project_agent.find():
            if project.name == project_name:
                return project.id
        return None

    def list_nsds(self):
        return self.agent.get_ns_descriptor_agent(self.project_id).find()

    def create_nsr(self, nsd_id):
        return self.agent.get_ns_records_agent(self.project_id).create(nsd_id)

    def delete_nsr(self, nsr_id):
        return self.agent.get_ns_records_agent(self.project_id).delete(nsr_id)

    def create_project(self, project):
        ob_project = self.agent.get_project_agent().create(project)
        self.project_id = ob_project.id
        return ob_project

    def create_user(self, user):
        return self.agent.get_user_agent(self.project_id).create(user)

    def create_vim_instance(self, vim_instance):
        return self.agent.get_vim_instance_agent(self.project_id).create(vim_instance)


def list_resources(payload, user_info):
    result = []

    if not user_info or not user_info.name:
        for k, v in AVAILABLE_NSD.items():
            result.append(messages_pb2.ResourceMetadata(resource_id=k,
                                                        description=v.get('description'),
                                                        cardinality=int(v.get('cardinality')),
                                                        testbed=v.get('testbed')))
        return result

    ob_client = OBClient(user_info.name)

    for nsd in ob_client.list_nsds():
        result.append(messages_pb2.ResourceMetadata(nsd.name,
                                                    nsd.get('description') or AVAILABLE_NSD[nsd.name.lower()].get(
                                                        'description'),
                                                    CARDINALITY[nsd.name.lower()]))

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
        'name': name,
        'password': password,
        'enabled': True,
        'email': None,
        'roles': [
            {
                'role': 'USER',
                'project': project.id
            }
        ]
    }
    logger.debug("Create openbaton project %s" % project)
    user = ob_client.create_user(user)
    logger.debug("Create openbaton user %s" % user)

    user_info = messages_pb2.UserInfo()
    user_info.name = name
    user_info.password = password
    user_info.ob_project_id = project.id

    testbed_tenants = {}

    for testbed_name, v in os_tenants.items():
        # v == {'tenant_id': os_tenant_id, 'vim_instance': vim_instance}
        tenant_id = v.get('tenant_id')
        vim_instance = v.get('vim_instance')
        vi = ob_client.create_vim_instance(vim_instance)
        logger.debug("created vim instance with id: %s" % vi.id)
        testbed_tenants[TESTBED_MAPPING[testbed_name]] = tenant_id

    user_info.testbed_tenants = testbed_tenants
    logger.debug("Updated user_info %s" % user_info)

    # experimenter = Experimenter()
    # experimenter.name = name
    # experimenter.password = password
    # experimenter.role = 'experimenter'
    # experimenter.testbed_tenants = testbed_tenants
    #
    # logger.debug("Create Experimenter %s" % experimenter)
    # save(experimenter)
    # logger.debug("Saved Experimenter")

    return user_info
