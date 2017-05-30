import json

# from utils import os_utils_opnfv
import os
from os import listdir

import yaml
from os.path import isfile, join

from org.openbaton.cli.errors.errors import NfvoException

from utils.exceptions import NfvResourceValidationError
from utils.utils import get_config
from sdk.softfire.manager import AbstractManager
from org.openbaton.cli.agents.agents import OpenBatonAgentFactory
from org.openbaton.cli.openbaton import LIST_PRINT_KEY

import utils.os_utils as os_utils
from sdk.softfire.grpc import messages_pb2
from utils.os_utils import create_os_project
from utils.utils import get_available_nsds, get_logger

logger = get_logger(__name__)

AVAILABLE_AGENTS = LIST_PRINT_KEY.keys()

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
    'any': messages_pb2.ANY
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

    def create_nsr(self, nsd_id, body=None):
        return self.agent.get_ns_records_agent(self.project_id).create(nsd_id, body)

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

    def list_images(self):
        res = []
        for vim_instance in json.loads(self.agent.get_vim_instance_agent(self.project_id).find()):

            vim_instance_name = vim_instance.get("name")
            if "-" in vim_instance_name:
                testbed_name = vim_instance_name.split("-")[-1]
            else:
                testbed_name = vim_instance_name
            for img in vim_instance.get("images"):
                res.append(
                    {
                        "testbed": testbed_name,
                        "name": img.get("name")
                    }
                )
        return res

    def upload_package(self, package_path, name=None):
        package_agent = self.agent.get_vnf_package_agent(self.project_id)
        try:
            return package_agent.create(package_path)
        except NfvoException as e:
            if not name:
                raise e
            for nsd in json.loads(self.agent.get_ns_descriptor_agent(self.project_id).find()):
                for vnfd in nsd.get('vnfd'):
                    if vnfd.get('name') == name:
                        return {"id": vnfd.get('id')}
            raise e

    def create_nsd(self, nsd):
        if isinstance(nsd, dict):
            nsd = json.dumps(nsd)

        logger.debug("Uplading really: \n%s" % nsd)
        return self.agent.get_ns_descriptor_agent(self.project_id).create(nsd)


class NfvManager(AbstractManager):
    def validate_resources(self, user_info=None, payload=None) -> None:
        # TODO Add validation of resource
        request_dict = yaml.load(payload)
        logger.info("Validating %s " % request_dict)

        resource_id = request_dict.get("properties").get('resource_id')
        available_nsds = get_available_nsds()
        if resource_id not in available_nsds.keys():
            if not request_dict.get("properties").get('file_name'):
                raise NfvResourceValidationError(
                    message="Resource id %s not in the available ones %s and no CSAR file provided" % (
                        resource_id, list(available_nsds.keys())))

        else:
            testbeds = request_dict.get("properties").get("testbeds")
            for vnf_type in testbeds.keys():
                if vnf_type not in available_nsds.get(resource_id).get("vnf_types") and vnf_type.upper() != "ANY":
                    raise NfvResourceValidationError(
                        message="Testbeds properties must be a dict containing the vnf type of the NS chosen or ANY, "
                                "%s not included in the possibilities %s" % (
                                    vnf_type, available_nsds.get("resource_id").get("vnf_types")))
        pass

    def refresh_resources(self, user_info):
        """
            List all available images for this tenant

            :param tenant_name: the tenant name
             :type tenant_name: str
            :return: the list of ResourceMetadata
             :rtype list
            """
        result = []
        ob_client = OBClient(user_info.name)
        for image in ob_client.list_images():
            testbed = image.get('testbed')
            resource_id = image.get('name')
            result.append(messages_pb2.ResourceMetadata(resource_id=resource_id,
                                                        description='',
                                                        cardinality=-1,
                                                        node_type='NfvImage',
                                                        testbed=TESTBED_MAPPING.get(testbed)))
        return result

    def provide_resources(self, user_info, payload=None):
        """
            Deploy the selected resources. Payload looks like:
            {
                'properties': {
                    'nsd_name': 'my_nsd',
                    'resource_id': 'open5gcore',
                    'testbeds': {
                        'ANY':
                        'fokus'
                    }
                },
                'type': 'NfvResource'
            }

            :param payload: the resources to be deployed
             :type payload: dict
            :param user_info: the user info requesting
            :return: the nsr deployed
             :rtype: ProvideResourceResponse
            """
        ob_client = OBClient(user_info.name)
        logger.debug("Payload is \n%s" % payload)
        resource_dict = yaml.load(yaml.load(payload))
        logger.debug("Received %s " % resource_dict)
        resource_id = resource_dict.get("properties").get("resource_id")
        nsd_name = resource_dict.get("properties").get("resource_id")
        packages_location = "%s/%s" % (get_config().get("system", "packages-location"), resource_id)
        available_nsds = get_available_nsds()
        nsd_chosen = available_nsds.get(resource_id)
        vnfds = []
        testbeds = resource_dict.get("properties").get("testbeds")

        if os.path.exists(packages_location) and nsd_chosen:
            for package in [f for f in listdir(packages_location) if isfile(join(packages_location, f))]:
                vnfds.append({
                    'id': ob_client.upload_package(join(packages_location, package), package.split('.')[0]).get('id')
                })

            virtual_links = [{"name": "softfire-internal"}]
            nsd = {
                "name": nsd_name,
                "version": "softfire_version",
                "vendor": user_info.name,
                "vnfd": vnfds,
                "vld": virtual_links
            }

            logger.debug("Uploading NSD: %s" % nsd)

            nsd = ob_client.create_nsd(nsd)

            logger.debug("Created NSD: %s" % nsd)
            vdu_vim_instances = {}

            if "ANY" in testbeds.keys():
                for vdu_name in nsd_chosen.get("vnf_types"):
                    vdu_vim_instances[vdu_name] = ["vim-instance-%s" % vim_name for vim_name in testbeds.values()]
            else:
                for vdu_name in nsd_chosen.get("vnf_types"):
                    vdu_vim_instances[vdu_name] = [testbeds.get(vdu_name)]

            body = json.dumps({
                "vduVimInstances": vdu_vim_instances
            })
            nsr = ob_client.create_nsr(nsd.get('id'), body=body)

        else:
            # TODO implement specific deployment
            nsr = {}
            # nsr = ob_client.create_nsr(payload.get("nsd-id"))
        if isinstance(nsr, dict):
            nsr = json.dumps(nsr)
        return [nsr]

    def create_user(self, username, password):
        """
            Create project in Open Stack and upload the new vim to Open Baton

            :param name: the username of the user, used here also as tenant name
             :type name: string
            :param password: the password of the user
             :type password: string
            :return: the new user info updated
             :rtype: UserInfo

            """
        os_tenants = create_os_project(tenant_name=username)
        ob_client = OBClient()
        project = {
            'name': username,
            'description': 'the project for user %s' % username
        }
        project = ob_client.create_project(project)
        user = {
            'username': username,
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
            name=username,
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

    def list_resources(self, user_info=None, payload=None):
        """
            list all available resources

            :param payload: Not used
            :param user_info: the user info requesting, if None only the shared resources will be returned 
            :return: list of ResourceMetadata
            """
        result = []

        if user_info and user_info.name:
            ob_client = OBClient(user_info.name)

            for nsd in ob_client.list_nsds():
                result.append(messages_pb2.ResourceMetadata(nsd.name,
                                                            nsd.get('description') or get_available_nsds[
                                                                nsd.name.lower()].get(
                                                                'description'),
                                                            CARDINALITY[nsd.name.lower()]))

                result.extend(self.refresh_resources(user_info))

        for k, v in get_available_nsds().items():
            testbed = v.get('testbed')
            node_type = v.get('node_type')
            cardinality = int(v.get('cardinality'))
            description = v.get('description')
            resource_id = k
            result.append(messages_pb2.ResourceMetadata(resource_id=resource_id,
                                                        description=description,
                                                        cardinality=cardinality,
                                                        node_type=node_type,
                                                        testbed=TESTBED_MAPPING.get(testbed)))

        return result

    def release_resources(self, user_info, payload=None):
        """
           Delete the NSR from openbaton based on user_info and the nsr
           :param payload: the NSR itself
           :type payload: dict
           :param user_info:
            :type user_info: UserInfo
           :return: None
           """
        ob_client = OBClient(user_info.name)

        logger.info("Deleting resources for user: %s" % user_info.name)
        logger.debug("Received this payload: %s" % payload)
        # ob_client.delete_nsr(payload.get("id"))
