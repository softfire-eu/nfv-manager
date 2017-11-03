import json

from org.openbaton.cli.agents.agents import OpenBatonAgentFactory
from org.openbaton.cli.errors.errors import NfvoException
from sdk.softfire.utils import get_config

from eu.softfire.nfv.utils.static_config import CONFIG_FILE_PATH
from eu.softfire.nfv.utils.utils import get_logger

logger = get_logger(__name__)


def get_vim_instance_test():
    return {
        "name":           "vim-instance-test",
        "authUrl":        'http://test.test.ts',
        "tenant":         'test',
        "username":       'test',
        "password":       'test',
        "securityGroups": [
            'default'
        ],
        "type":           "test",
        "location":       {
            "name":      "Test of nowhere",
            "latitude":  "5.525876",
            "longitude": "31.314400"
        }
    }


class OBClient(object):
    def __init__(self, project_name=None):
        """
        If username and password are passed, it will create a openbaton agent using these ones. if not it will use the
        configuration parameter ones.

        :param project_name: the project of a specific user.
        """
        https = get_config("nfvo", "https", CONFIG_FILE_PATH).lower() == 'true'

        username = get_config("nfvo", "username", CONFIG_FILE_PATH)

        password = get_config("nfvo", "password", CONFIG_FILE_PATH)

        nfvo_ip = get_config("nfvo", "ip", CONFIG_FILE_PATH)
        nfvo_port = get_config("nfvo", "port", CONFIG_FILE_PATH)
        self.agent_factory = OpenBatonAgentFactory(nfvo_ip=nfvo_ip,
                                                   nfvo_port=nfvo_port,
                                                   https=https,
                                                   version=1,
                                                   username=username,
                                                   password=password,
                                                   project_id=None)
        if project_name:
            self.project_id = self._get_project_id(project_name)
            if self.project_id is None and project_name is not None:
                logger.warning('Project ID is None. No project found with the name {}'.format(project_name))

    def _get_project_id(self, project_name):
        project_agent = self.agent_factory.get_project_agent()
        for project in json.loads(project_agent.find()):
            if project.get('name') == project_name:
                return project.get('id')
        return None

    def list_nsds(self):
        return json.loads(self.agent_factory.get_ns_descriptor_agent(self.project_id).find())

    def create_nsr(self, nsd_id, body=None):
        return self.agent_factory.get_ns_records_agent(self.project_id).create(nsd_id, body)

    def delete_nsr(self, nsr_id):
        return self.agent_factory.get_ns_records_agent(self.project_id).delete(nsr_id)

    def create_project(self, project):
        for p in json.loads(self.list_projects()):
            if p.get('name') == project.get('name'):
                return p
        if isinstance(project, dict):
            project = json.dumps(project)
        ob_project = self.agent_factory.get_project_agent().create(project)
        self.project_id = ob_project.get('id')
        return ob_project

    def create_user(self, user):

        for us in json.loads(self.list_users()):
            if us.get('username') == user.get('username'):
                return us

        if isinstance(user, dict):
            user = json.dumps(user)
        return self.agent_factory.get_user_agent(self.project_id).create(user)

    def create_vim_instance(self, vim_instance):
        for vi in self.list_vim_instances():
            if vi.get('name') == vim_instance.get('name'):
                return vi
        if isinstance(vim_instance, dict):
            vim_instance = json.dumps(vim_instance)

        logger.debug("Posting vim %s" % vim_instance)
        return self.agent_factory.get_vim_instance_agent(self.project_id).create(vim_instance)

    def list_users(self):
        return self.agent_factory.get_user_agent(self.project_id).find()

    def list_projects(self):
        return self.agent_factory.get_project_agent().find()

    def list_vim_instances(self):
        return json.loads(self.agent_factory.get_vim_instance_agent(self.project_id).find())

    def list_images_network_flavors(self):
        images = []
        networks = []
        flavors = []
        vim_instance_agent = self.agent_factory.get_vim_instance_agent(self.project_id)

        for vim_instance in json.loads(vim_instance_agent.find()):

            vim_instance_name = vim_instance.get("name")
            if "-" in vim_instance_name:
                testbed_name = vim_instance_name.split("-")[-1]
            else:
                testbed_name = vim_instance_name
            for img in vim_instance.get("images"):
                images.append(
                    {
                        "testbed": testbed_name,
                        "name": img.get("name")
                    }
                )
            for net in vim_instance.get("networks"):
                networks.append(
                    {
                        "testbed": testbed_name,
                        "name": net.get("name")
                    }
                )
            for flavor in vim_instance.get("flavours"):
                flavors.append(
                    {
                        "testbed": testbed_name,
                        "name": flavor.get("flavour_key")
                    }
                )
        return images, networks, flavors

    def upload_package(self, package_path, name=None):
        package_agent = self.agent_factory.get_vnf_package_agent(self.project_id)
        try:
            return package_agent.create(package_path)
        except NfvoException as e:
            if not name:
                raise e
            for nsd in json.loads(self.agent_factory.get_ns_descriptor_agent(self.project_id).find()):
                for vnfd in nsd.get('vnfd'):
                    if vnfd.get('name') == name:
                        return {"id": vnfd.get('id')}
            raise e

    def create_nsd(self, nsd):
        if isinstance(nsd, dict):
            nsd = json.dumps(nsd)

        logger.debug("Uplading really: \n%s" % nsd)
        return self.agent_factory.get_ns_descriptor_agent(self.project_id).create(nsd)

    def get_nsd(self, nsd_id):
        return self.agent_factory.get_ns_descriptor_agent(self.project_id).find(nsd_id)

    def delete_nsd(self, nsd_id):
        self.agent_factory.get_ns_descriptor_agent(self.project_id).delete(nsd_id)

    def delete_vnfd(self, vnfd_id):
        self.agent_factory.get_vnf_descriptor_agent(self.project_id).delete(vnfd_id)

    def get_nsr(self, nsr_id):
        return self.agent_factory.get_ns_records_agent(self.project_id).find(nsr_id)

    def import_key(self, ssh_pub_key, name):

        key_agent = self.agent_factory.get_key_agent(self.project_id)
        for key in json.loads(key_agent.find()):
            if key.get('name') == name:
                key_agent.delete(key.get('id'))
                break

        key_agent.create(
            json.dumps(
                {
                    'name': name,
                    'projectId': self.project_id,
                    'publicKey': ssh_pub_key
                }
            )
        )

    def create_nsd_from_csar(self, location):
        return self.agent_factory.get_csarnsd_agent(self.project_id).create(location)

    def delete_user(self, username):
        for u in json.loads(self.list_users()):
            if u.get('username') == username:
                self.agent_factory.get_user_agent(self.project_id).delete(u.get('id'))

    def delete_project(self, ob_project_id):
        self.agent_factory.get_project_agent().delete(ob_project_id)

    def list_nsrs(self):
        return json.loads(self.agent_factory.get_ns_records_agent(self.project_id).find())

    def delete_vim_instance(self, _vim_id):
        self.agent_factory.get_vim_instance_agent(self.project_id).delete(_vim_id)
