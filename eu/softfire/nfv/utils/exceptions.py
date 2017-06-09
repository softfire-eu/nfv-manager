class BaseException(Exception):
    def __init__(self, message=None) -> None:
        super().__init__()
        self.message = message


class OpenstackClientError(BaseException):
    pass


class NfvResourceValidationError(BaseException):
    pass


class NfvResourceDeleteException(BaseException):
    pass


class NfvResourceProvisioningException(BaseException):
    pass


class MissingFileException(NfvResourceProvisioningException):
    pass
