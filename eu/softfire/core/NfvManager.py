from org.openbaton.cli.agents.agents import OpenBatonAgentFactory
from org.openbaton.cli.openbaton import LIST_PRINT_KEY

from eu.softfire.messaging.grpc import messages_pb2
from eu.softfire.utils.utils import get_config

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
    'open5gcore': "the description goes here"
}
CARDINALITY = {
    'open5gcore': 1
}


def list_resources(payload, user_info):
    project_id = _get_project_id(user_info)

    result = []
    for nsd in agent.get_agent("nsd", project_id=project_id).find():
        result.append(messages_pb2.ResourceMetadata(nsd.name, nsd.get('description') or DESCRIPTIONS[nsd.name.lower()],
                                                    CARDINALITY[nsd.name.lower()]))

    return result


def _get_project_id(user_info):
    project_agent = agent.get_agent("project", project_id=None)
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
