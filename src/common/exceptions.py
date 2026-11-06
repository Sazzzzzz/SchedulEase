class ServiceError(Exception):
    """Base exception for service."""


class ConnectionError(ServiceError):
    """Raised for network or connection-related errors."""


class LoginError(ServiceError):
    """Raised for login-related errors."""


class ParseError(ServiceError):
    """Raised for errors in parsing data from the service, likely due to changes in the API or HTML structure."""


class ElectError(ServiceError):
    """Raised for errors during course election, such as failure to elect or cancel a course."""


class ConfigError(Exception):
    """Raised for errors in configuration, such as missing or invalid config file."""
