class _BaseException(Exception):
    def __init__(self, message=None) -> None:
        super().__init__()
        self.message = message


class OpenstackClientError(_BaseException):
    pass


class NfvResourceValidationError(_BaseException):
    pass


class NfvResourceDeleteException(_BaseException):
    pass


class NfvResourceProvisioningException(_BaseException):
    pass


class MissingFileException(NfvResourceProvisioningException):
    pass
