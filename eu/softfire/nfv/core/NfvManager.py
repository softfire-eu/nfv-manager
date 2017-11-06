import json
# from utils import os_utils_opnfv
import os
import time
import traceback
from os import listdir
from os.path import isfile, join
from threading import Thread

import yaml
from org.openbaton.cli.errors.errors import NfvoException
from org.openbaton.cli.openbaton import LIST_PRINT_KEY
from sdk.softfire.grpc import messages_pb2
from sdk.softfire.manager import AbstractManager
from sdk.softfire.utils import TESTBED_MAPPING
from sqlalchemy.orm.exc import NoResultFound

from eu.softfire.nfv.db.entities import Nsr
from eu.softfire.nfv.db.repositories import find, delete, save
from eu.softfire.nfv.utils import os_utils
from eu.softfire.nfv.utils.exceptions import NfvResourceValidationError, NfvResourceDeleteException, \
    MissingFileException
from eu.softfire.nfv.utils.ob_utils import OBClient
from eu.softfire.nfv.utils.os_utils import create_os_project
from eu.softfire.nfv.utils.static_config import CONFIG_FILE_PATH
from eu.softfire.nfv.utils.utils import get_available_nsds, get_logger, get_config

logger = get_logger(__name__)

AVAILABLE_AGENTS = LIST_PRINT_KEY.keys()

CARDINALITY = {
    'open5gcore': 1,
}


class UpdateStatusThread(Thread):
    def __init__(self, nfv_manager):
        Thread.__init__(self)
        self.stopped = False
        self.nfv_manager = nfv_manager

    def run(self):
        while not self.stopped:
            time.sleep(int(self.nfv_manager.get_config_value('system', 'update-delay', '10')))
            if not self.stopped:
                try:
                    self.nfv_manager.send_update()
                except Exception as e:
                    traceback.print_exc()
                    if hasattr(e, 'args'):
                        logger.error("got error while updating resources: %s " % e)
                    else:
                        logger.error("got unknown error while updating resources")

    def stop(self):
        self.stopped = True


def get_nsrs_to_check():
    return find(Nsr)


def add_nsr_to_check(username, nsr):
    try:
        nsr_exists = find(Nsr, _id=nsr.get('id'))
        if nsr_exists:
            delete(nsr_exists)
    except NoResultFound:
        pass

    nsr_to_save = Nsr()
    nsr_to_save.username = username
    nsr_to_save.id = nsr.get('id')
    nsr_to_save.status = nsr.get('status')
    nsr_to_save.vnf_log_url = {}

    for vnfr in nsr.get('vnfr'):
        for vdu in vnfr.get('vdu'):
            for vnfc_instance in vdu.get('vnfc_instance'):
                if not nsr_to_save.vnf_log_url.get(vnfr.get('name')):
                    nsr_to_save.vnf_log_url[vnfr.get('name')] = ""
                nsr_to_save.vnf_log_url[vnfr.get('name')] += "%s;" % vnfc_instance.get('hostname')
    save(nsr_to_save, Nsr)


def remove_nsr_to_check(nsr_id):
    try:
        delete(find(Nsr, _id=nsr_id))
    except NoResultFound:
        pass


def _update_nsr(nsr):
    logger.debug("Checking resources of user %s, nsr id %s" % (nsr.username, nsr.id))
    ob_client = OBClient(nsr.username)
    # check if the OBClient has a project ID. if not, something went wrong and the nsr is ignored for now.
    if ob_client.project_id is None:
        logger.error('The OBClient for user {} has no project ID. This should never happen. Does the user still exist in Open Baton?'.format(nsr.username))
        return None
    try:
        nsr_new = ob_client.get_nsr(nsr.id)
    except Exception as e:
        logger.error('Exception while fetching the NSR with ID {} of user {}. Does it really exist?'.format(nsr.id, nsr.username))
        return None
    try:
        nsr_new_dict = json.loads(nsr_new)
    except:
        logger.error('Not able to parse nsr to dictionary: {}'.format(nsr_new))
        return None
    if 'error' in nsr_new_dict:
        logger.error('Exception while updating the NSR with ID {} of user {}: {}'.format(nsr.id, nsr.username, nsr_new_dict.get('error')))
        return None
    add_nsr_to_check(nsr.username, nsr_new_dict)
    logger.debug("Status is: %s" % nsr_new_dict.get('status'))
    return nsr_new


def try_delete_vnfd(vnfd_id, ob_client):
    try:
        ob_client.delete_vnfd(vnfd_id)
    except:
        raise NfvResourceDeleteException('Not able to delete VNFD with id: %s' % vnfd_id)


def try_delete_nsd(nsd_id, ob_client):
    try:
        ob_client.delete_nsd(nsd_id)
    except:
        raise NfvResourceDeleteException('Not able to delete NSD with id: %s' % nsd_id)


def try_delete_nsr(nsr, ob_client):
    try:
        ob_client.delete_nsr(nsr.get('id'))
    except:
        raise NfvResourceDeleteException('Not able to delete NSR with id: %s' % nsr.get('id'))
    timer = 500
    time.sleep(5)
    while True:
        try:
            nsr = json.loads(ob_client.get_nsr(nsr.get('id')))
            if timer == 0:
                raise NfvResourceDeleteException('Not able to delete NSR with id: %s' % nsr.get('id'))
        except NfvoException:
            return
        timer -= 1
        time.sleep(2)


def remove_all(ob_client, force=False):
    if force or get_config('system', 'delete-all', CONFIG_FILE_PATH, 'false').lower() == 'true':
        logger.debug("removing everything!")
        for _nsr in ob_client.list_nsrs():
            ob_client.delete_nsr(_nsr.get('id'))
        for _nsd in ob_client.list_nsds():
            ob_client.delete_nsd(_nsd.get('id'))
        for _vim_instance in ob_client.list_vim_instances():
            ob_client.delete_vim_instance(_vim_instance.get('id'))


class NfvManager(AbstractManager):
    def __init__(self, config_file_path):
        super().__init__(config_file_path)
        with open(self.get_config_value('system', 'softfire-public-key'), "r") as sosftfire_ssh_pub_key:
            self.softfire_pub_key = sosftfire_ssh_pub_key.read().strip()

    def validate_resources(self, user_info=None, payload=None) -> None:

        request_dict = yaml.load(payload)
        logger.info("Validating %s " % request_dict)

        resource_id = request_dict.get("properties").get('resource_id')
        available_nsds = get_available_nsds()
        if resource_id not in available_nsds.keys():
            temp_csar_location = self.get_config_value('system', 'temp-csar-location',
                                                       '/etc/softfire/experiment-nsd-csar').rstrip('/')
            nsd_location = '{}/{}/{}.csar'.format(temp_csar_location, user_info.name, resource_id)
            file_name = request_dict.get("properties").get('file_name')
            logger.debug("Checking if nsd_location exists: %s and if there is filename: %s" % (
                os.path.exists(nsd_location), file_name))
            if not os.path.exists(nsd_location) and not file_name:
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

            :param user_info:
            :return: the list of ResourceMetadata
             :rtype list
            """
        result = []
        ob_client = OBClient(user_info.name)
        images, networks, flavours = ob_client.list_images_network_flavors()

        for image in images:
            testbed = image.get('testbed')
            resource_id = image.get('name')
            result.append(messages_pb2.ResourceMetadata(resource_id=resource_id,
                                                        description='',
                                                        cardinality=-1,
                                                        node_type='NfvImage',
                                                        testbed=TESTBED_MAPPING.get(testbed)))
        for net in networks:
            testbed = net.get('testbed')
            resource_id = net.get('name')
            result.append(messages_pb2.ResourceMetadata(resource_id=resource_id,
                                                        description='',
                                                        cardinality=-1,
                                                        node_type='NfvNetwork',
                                                        testbed=TESTBED_MAPPING.get(testbed)))
        for flavour in flavours:
            testbed = flavour.get('testbed')
            resource_id = flavour.get('name')
            result.append(messages_pb2.ResourceMetadata(resource_id=resource_id,
                                                        description='',
                                                        cardinality=-1,
                                                        node_type='NfvFlavor',
                                                        testbed=TESTBED_MAPPING.get(testbed)))
        return result

    def provide_resources(self, user_info, payload=None):
        """
            Deploy the selected resources. Payload looks like:
            {
                'properties': {
                    'nsd_name': 'my_nsd',
                    'file_name': 'Files/my_nsd.csar',
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
        resource_dict = json.loads(payload)
        logger.debug("Received %s " % resource_dict)
        ssh_pub_key = resource_dict.get("properties").get('ssh_pub_key')
        resource_id = resource_dict.get("properties").get("resource_id")
        monitoring_ip = resource_dict.get("properties").get("floatingIp")
        if not monitoring_ip:
            monitoring_ip = ""
        file_name = resource_dict.get("properties").get("file_name")
        nsd_name = resource_dict.get("properties").get("nsd_name")

        ob_client.import_key(self.softfire_pub_key, 'softfire-key')
        nsr_keys_to_use = ['softfire-key']
        if ssh_pub_key:
            logger.debug("creating user-key called: %s" % nsd_name)
            ob_client.import_key(ssh_pub_key.strip(), nsd_name)
            nsr_keys_to_use.append(nsd_name)

        # temp_csar_location = "{}/{}".format(
        #     self.get_config_value("system", "temp-csar-location", '/etc/softfire/experiment-nsd-csar').rstrip('/'),
        #     resource_id)
        available_nsds = get_available_nsds()
        nsd_chosen = available_nsds.get(resource_id)
        packages_location = "%s/%s" % (
            self.get_config_value("system", "packages-location", '/etc/softfire/packages').rstrip('/'), resource_id)
        vnfds = []
        testbeds = resource_dict.get("properties").get("testbeds")

        logger.debug("Checking if nsd_chosen is not none: %s" % nsd_chosen)
        logger.debug("and if path %s exists: %s" % (packages_location, os.path.exists(packages_location)))

        if nsd_chosen and os.path.exists(packages_location):
            for package in [f for f in listdir(packages_location) if isfile(join(packages_location, f))]:
                vnfd = ob_client.upload_package(join(packages_location, package), package.split('.')[0])
                vnfds.append({
                    'id': vnfd.get('id')
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
                    vdu_vim_instances[vdu_name] = ["vim-instance-%s" % testbeds.get(vdu_name)]

            body = json.dumps({
                "vduVimInstances": vdu_vim_instances,
                "keys": nsr_keys_to_use,
                "monitoringIp": monitoring_ip
            })
            logger.debug("Body is %s" % body)
            try:
                nsr = ob_client.create_nsr(nsd.get('id'), body=body)
            except Exception as e:
                logger.error('Exception while deploying NSR from NSD: {}'.format(e))
                logger.debug('Delete NSD {}'.format(nsd.get('id')))
                try:
                    ob_client.delete_nsd(nsd.get('id'))
                except Exception as e2:
                    logger.error('Could not remove NSD {}: {}'.format(nsd.get('id'), e2))
                raise e

            add_nsr_to_check(user_info.name, nsr)

        else:
            # nsd resource was added by the user and is not available for everyone
            temp_csar_location = self.get_config_value("system", "temp-csar-location",
                                                       "/etc/softfire/experiment-nsd-csar")
            csar_nsd_file_path = "{}/{}/{}".format(
                temp_csar_location.rstrip('/'), user_info.name, file_name[6:])
            if os.path.exists(csar_nsd_file_path):
                nsd = ob_client.create_nsd_from_csar(csar_nsd_file_path)
                logger.debug("Created NSD: %s" % nsd.get('name'))
            else:
                raise MissingFileException("File %s was not found" % csar_nsd_file_path)
            vdu_vim_instances = {}

            if "ANY" in testbeds.keys():
                for vnfd in nsd.get('vnfd'):
                    for vdu in vnfd.get('vdu'):
                        vdu_vim_instances[vdu.get('name')] = ["vim-instance-%s" % vim_name for vim_name in
                                                              testbeds.values()]
            else:
                logger.debug("Adding testbed mapping vdu : %s" % testbeds)
                for vdu_name, testbed in testbeds.items():
                    vdu_vim_instances[vdu_name] = ["vim-instance-%s" % testbed]
            body = json.dumps({
                "vduVimInstances": vdu_vim_instances,
                "keys": nsr_keys_to_use,
                "monitoringIp": monitoring_ip
            })
            logger.debug("Deploy NSR with body: %s" % body)

            if nsd:
                try:
                    nsr = ob_client.create_nsr(nsd.get('id'), body=body)
                except Exception as e:
                    logger.error('Exception while deploying NSR from NSD {}: {}'.format(nsd.get('id'), e))
                    logger.debug('Delete NSD {}'.format(nsd.get('id')))
                    try:
                        ob_client.delete_nsd(nsd.get('id'))
                    except Exception as e2:
                        logger.error('Could not remove NSD {}: {}'.format(nsd.get('id'), e2))
                    raise e
                add_nsr_to_check(user_info.name, nsr)



        if isinstance(nsr, dict):
            nsr = json.dumps(nsr)

        logger.info("Deployed resource: %s" % json.loads(nsr).get('name'))
        return [nsr]

    def create_user(self, user_info):
        """
            Create project in Open Stack and upload the new vim to Open Baton

            :param user_info:
            :return: the new user info updated
             :rtype: UserInfo

            """
        username = user_info.name
        password = user_info.password
        os_tenants = create_os_project(username=username, password=password, tenant_name=username)
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

        user_info.ob_project_id = project.get('id')
        # user_info.testbed_tenants = {}

        testbed_tenants = {}
        if os_tenants:
            for testbed_name, v in os_tenants.items():
                tenant_id = v.get('tenant_id')
                vim_instance = v.get('vim_instance')
                try:
                    vi = ob_client.create_vim_instance(vim_instance)
                    logger.debug("created vim instance with id: %s" % vi.get('id'))
                except NfvoException:
                    logger.warning("Not able to upload vim %s" % testbed_name)
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
        nsr = None
        try:
            nsr = json.loads(payload)
        except:
            logger.warning('Could not parse release resource payload to JSON: {}'.format(payload))
            traceback.print_exc()
            if nsr:
                remove_nsr_to_check(nsr.get('id'), True)
            return
        if nsr.get('type') == 'NfvResource' and nsr.get('properties') is not None:
            logger.debug('The payload does not seem to be an NSR so the resource was probably not yet deployed and nothing has to be removed from Open Baton.')
            return
        nsd_id = nsr.get('descriptor_reference')
        try:
            nsd = json.loads(ob_client.get_nsd(nsd_id))
        except NfvoException:
            traceback.print_exc()
            return
        vnfd_ids = []
        for vnfd in nsd.get('vnfd'):
            vnfd_ids.append(vnfd.get('id'))

        try:
            try_delete_nsr(nsr, ob_client)

            try_delete_nsd(nsd_id, ob_client)
            # TODO to be added if cascade is not enabled
            # for vnfd_id in vnfd_ids:
            #     self.try_delete_vnfd(vnfd_id, ob_client)
        except NfvResourceDeleteException as e:
            traceback.print_exc()
            logger.error("...ignoring...")

        remove_nsr_to_check(nsr.get('id'))
        logger.info("Removed resource %s" % nsr.get('name'))

        # remove_all(ob_client)

    def _update_status(self) -> dict:
        result = {}
        for nsrs in get_nsrs_to_check():
            if isinstance(nsrs, list):
                for nsr in nsrs:
                    if not result.get(nsr.username):
                        result[nsr.username] = []
                    if nsr.status.lower() not in ['active', 'error']:
                        nsr_new = _update_nsr(nsr)
                        if nsr_new is not None:
                            result[nsr.username].append(nsr_new)
            else:
                if not result.get(nsrs.username):
                    result[nsrs.username] = []
                if nsrs.status.lower() not in ['active', 'error']:
                    nsr_new = _update_nsr(nsrs)
                    if nsr_new is not None:
                        result[nsrs.username].append(nsr_new)

        return result

    def delete_user(self, user_info):
        logger.debug("Removing user %s" % user_info)
        username = user_info.name
        os_utils.delete_tenant_and_user(username=username, testbed_tenants=user_info.testbed_tenants)
        ob_client = OBClient(username)
        remove_all(ob_client, True)
        ob_client.delete_user(username=username)
        ob_client.delete_project(ob_project_id=user_info.ob_project_id)
