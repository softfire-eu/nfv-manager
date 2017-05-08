import json

from org.openbaton.cli.agents.agents import OpenBatonAgentFactory
from org.openbaton.cli.openbaton import LIST_PRINT_KEY

from eu.softfire.messaging.grpc import messages_pb2
from eu.softfire.utils.utils import get_config, get_logger

logger = get_logger('eu.softfire.core')
config = get_config()
agent = OpenBatonAgentFactory(nfvo_ip=config.get("nfvo", "ip"),
                              nfvo_port=config.get("nfvo", "port"),
                              https=config.get("nfvo", "https"),
                              version=1,
                              username=config.get("nfvo", "username"),
                              password=config.get("nfvo", "password"),
                              project_id=None)

AVAILABLE_AGENTS = LIST_PRINT_KEY.keys()
DESCRIPTIONS = {
    'openimscore': "The Open IMS Core is an Open Source implementation of IMS Call Session Control Functions ("
                   "CSCFs) and a lightweight Home Subscriber Server (HSS), which together form the core elements "
                   "of all IMS/NGN architectures as specified today within 3GPP, 3GPP2, ETSI TISPAN and the PacketCable"
                   " intiative. The four components are all based upon Open Source software(e.g. the SIP Express Router"
                   " (SER) or MySQL).",
    'open5gcore': "the description goes here",
}
CARDINALITY = {
    'open5gcore': 1,
}


def list_resources(payload, user_info):
    project_id = _get_project_id(user_info)

    result = []
    for nsd in agent.get_agent("nsd", project_id=project_id).find():
        result.append(messages_pb2.ResourceMetadata(nsd.name, nsd.get('description') or DESCRIPTIONS[nsd.name.lower()],
                                                    CARDINALITY[nsd.name.lower()]))

    return result


def _get_project_id(user_info):
    project_agent = agent.get_project_agent()
    for project in project_agent.find():
        if project.name == user_info.name:
            project_id = project.id
            break
    return project_id


def provide_resources(payload, user_info):
    project_id = _get_project_id(user_info=user_info)
    nsr = agent.get_agent("nsr", project_id=project_id).create(payload.get("nsd-id"))
    return messages_pb2.ProvideResourceResponse(resources=nsr)


def release_resources(payload, user_info):
    project_id = _get_project_id(user_info=user_info)
    nsr = agent.get_agent("nsr", project_id=project_id).delete(payload.get("nsr-id"))


def create_user(name, password):
    # TODO create tenants in openstacks
    project_agent = agent.get_project_agent()
    project = {
        'name': name,
        'description': 'the project for user %s' % name
    }
    project = project_agent.create(json.dumps(project))
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
    user_agent = agent.get_user_agent().create(json.dumps(user))
    user_info = messages_pb2.UserInfo()
    user_info.name = name
    user_info.password = password
    user_info.ob_project_id = project.id
    return None
