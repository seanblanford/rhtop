"""Safe errors: never include server payloads, account numbers, or credentials."""


class RhtopError(Exception):
    """A local or remote operation could not be completed."""


class SchemaError(RhtopError):
    """The live broker contract is unsupported."""


class BrokerError(RhtopError):
    """A broker read failed."""


def known_error(error: BaseException) -> RhtopError | None:
    if isinstance(error, RhtopError):
        return error
    if isinstance(error, BaseExceptionGroup):
        errors = [known_error(child) for child in error.exceptions]
        if all(item is not None for item in errors):
            return RhtopError("; ".join(dict.fromkeys(str(item) for item in errors)))
    return None
