from concurrent import futures

import grpc
import time

from eu.softfire.messaging.grpc import messages_pb2_grpc, messages_pb2
from eu.softfire.utils.utils import get_logger, get_config

logger = get_logger('eu.softfire.messaging')
_ONE_DAY_IN_SECONDS = 60 * 60 * 24


def receive_forever():
    config = get_config()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=config.getint('system', 'server_threads')))
    messages_pb2_grpc.add_ManagerAgentServicer_to_server(ManagerAgent(), server)
    binding = '[::]:%s' % config.get('messaging', 'bind_port')
    logger.info("Start listening on %s" % binding)
    server.add_insecure_port(binding)
    server.start()
    try:
        while True:
            time.sleep(_ONE_DAY_IN_SECONDS)
    except KeyboardInterrupt:
        server.stop(0)


def register():
    config = get_config()
    channel = grpc.insecure_channel(
        '%s:%s' % (config.get("system", "experiment_manager_ip"), config.get("system", "experiment_manager_port")))
    stub = messages_pb2_grpc.RegistrationServiceStub(channel)
    response = stub.register(
        messages_pb2.RegisterMessage(name=config.get("system", "name"),
                                     endpoint="%s:%s" % (
                                     config.get("system", "ip"), config.get("messaging", "bind_port")),
                                     description=config.get("system", "description")))
    logger.debug("NFV manager received registration response: %s" % response.result)


def unregister():
    config = get_config()
    channel = grpc.insecure_channel(
        '%s:%s' % (config.get("system", "experiment_manager_ip"), config.get("system", "experiment_manager_port")))
    stub = messages_pb2_grpc.RegistrationServiceStub(channel)
    response = stub.unregister(
        messages_pb2.UnregisterMessage(name=config.get("system", "name"),
                                       endpoint="%s:%s" % (
                                       config.get("system", "ip"), config.get("messaging", "bind_port"))))
    logger.debug("NFV manager received unregistration response: %s" % response.result)


class ManagerAgent(messages_pb2_grpc.ManagerAgentServicer):
    def execute(self, request, context):
        if request.method == messages_pb2.LIST_RESOURCES:
            try:
                return messages_pb2.ResponseMessage(result=0,
                                                    list_resource=self.list_resources(payload=request.payload))
            except Exception as e:
                return messages_pb2.ResponseMessage(result=2, error_message=e)
        if request.method == messages_pb2.PROVIDE_RESOURCES:
            try:
                return messages_pb2.ResponseMessage(result=0,
                                                    provide_resource=self.provide_resources(payload=request.payload))
            except Exception as e:
                return messages_pb2.ResponseMessage(result=2, error_message=e)
        if request.method == messages_pb2.RELEASE_RESOURCES:
            try:
                self.release_resources(payload=request.payload)
                return messages_pb2.ResponseMessage(result=0)
            except Exception as e:
                return messages_pb2.ResponseMessage(result=2, error_message=e)

    def list_resources(self, payload=None):
        resources = [messages_pb2.ResourceMetadata("name", "descriprion", 1)]
        return messages_pb2.ListResourceResponse(resources=resources)

    def provide_resources(self, payload=None):
        return messages_pb2.ProvideResourceResponse(resources="")

    def release_resources(self, payload=None):
        pass
