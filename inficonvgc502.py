"""
Inficon VGC502 Controller Interface
"""
import sys
import socket
from errno import EISCONN

from hardware_device_base import HardwareDeviceBase


class InficonVGC502(HardwareDeviceBase):
    """Class for interfacing with InficonVGC502"""

    def __init__(self, log: bool=True, logfile: str =__name__.rsplit('.', 1)[-1],
                 timeout: int=1):
        """Initialize the InficonVGC502 class.
        Args:
            log (bool): If True, start logging.
            logfile (str, optional): Path to log file.
            timeout (int, optional): Timeout in seconds.
        """
        super().__init__(log, logfile)
        self.timeout = timeout
        self.sock: socket.socket | None = None

    def connect(self, *args, con_type="tcp") -> None:
        """ Connect to the controller. """
        if self.validate_connection_params(args):
            if con_type == "tcp":
                host = args[0]
                port = args[1]
                if self.sock is None:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    self.sock.connect((host, port))
                    self.logger.info("Connected to %s:%d", host, port)
                    self._set_connected(True)
                    # ensure subsequent ops also use timeout
                    self.sock.settimeout(self.timeout)

                except OSError as e:
                    if e.errno == EISCONN:
                        self.logger.info("Already connected")
                        self._set_connected(True)
                    else:
                        self.logger.error("Connection error: %s", e.strerror)
                        self._set_connected(False)
                if self.is_connected():
                    self._clear_socket()
            elif con_type == "serial":
                self.logger.error("Serial connection not supported")
            else:
                self.logger.error("Unknown con_type: %s", con_type)
        else:
            self.logger.error("Invalid connection arguments: %s", args)

    def _clear_socket(self):
        """Clear the socket connection."""
        if self.sock:
            self.sock.setblocking(False)
            while True:
                try:
                    _ = self.sock.recv(1024)
                except BlockingIOError:
                    break
            self.sock.setblocking(True)

    def disconnect(self):
        """Close the TCP connection."""
        try:
            self.logger.debug("Closing connection to controller")
            if self.sock:
                self.sock.close()
            self._set_connected(False)
        except Exception as ex:
            raise IOError(f"Failed to close connection: {ex}") from ex

    def _send_command(self, command: str, *args) -> bool:
        """
        Send a command to the controller.

        :param command: (str) Command to send.
        :param args: Arguments to send.
        :return: True on success, False on failure.
        """
        try:
            self.logger.debug("Sending command: %s", command)
            with self.lock:
                self.sock.sendall(command.encode())
        except Exception as ex:
            raise IOError(f"Failed to send command: {ex}") from ex
        return True

    def _read_reply(self, terminator: bytes = b"\r\n", max_bytes: int = 4096) -> str:
        """Read until 'terminator' or timeout. Returns bytes including the terminator."""
        buf = bytearray()
        try:
            while True:
                chunk = self.sock.recv(1)
                if not chunk:
                    # peer closed
                    break
                buf += chunk
                if buf.endswith(terminator):
                    break
                if len(buf) >= max_bytes:
                    break
            return buf.decode().strip()
        except Exception as ex:
            raise IOError(f"Failed to _read_reply: {ex}") from ex

    def set_pressure_unit(self, unit_code: int =1) -> bool:
        """ Set the pressure units
        :param unit_code: (int) Pressure unit code
        :return: True on success, False on failure.

        Codes: 0 - mbar, 1 - Torr, 2 - Pascal, 3 - Micron, 4 - hPascal, 5 - Volt
        """
        retval = False
        if unit_code < 0 or unit_code > 5:
            self.logger.error("Invalid pressure unit code: %s\nMust be between 0 and 5 inclusive",
                              unit_code)
        else:
            self._send_command(f"UNI,{unit_code}")
            received = int(self._read_reply(b"\r\n"))
            if received != unit_code:
                self.logger.error("Requested unit code not achieved: %d", received)
            else:
                retval = True
        return retval

    def get_pressure_unit(self) -> int:
        """ Get the pressure units"""
        self._send_command("UNI")
        received = int(self._read_reply(b"\r\n"))
        return received

    def read_pressure(self, gauge: int = 1) -> float:
        """Read pressure from gauge 1..n.
        Returns float, or sys.float_info.max on timeout/parse error."""
        # pylint: disable=too-many-branches
        if not isinstance(gauge, int) or gauge < 1:
            raise ValueError("gauge must be a positive integer")

        # Command format: PR{gauge}\r\n
        command = f"PR{gauge}\r\n"
        try:
            self._send_command(command)
        except DeviceConnectionError:
            self.logger.error("Connection error: %s", command)
            raise
        except OSError as e:
            self.logger.error("Failed to send command: %s", e)
            raise DeviceConnectionError("Write failed") from e

        # Read acknowledgment line (controller typically replies with ACK/NAK ending CRLF)
        try:
            acknowledgment = self._read_reply(b"\r\n")
            self.logger.debug("Acknowledgment received: %r", acknowledgment)
        except socket.timeout:
            # match original behavior: return max float on timeout
            return sys.float_info.max

        # Accept bare control char or control char followed by CRLF
        if acknowledgment == "\x06":  # ACK
            self.logger.debug("ACK received, sending ENQ")
            try:
                self._send_command("\x05")  # ENQ
                response = self._read_reply(b"\r\n")
            except socket.timeout:
                return sys.float_info.max
            except OSError as e:
                if self.logger:
                    self.logger.error("IO error while receiving response: %s", e)
                return sys.float_info.max

            self.logger.debug("Pressure response: %s", response)

            # Expected like: "PR1,<value>"
            try:
                parts = response.split(",")
                value = float(parts[1])
                return value
            except (IndexError, ValueError) as e:
                self.logger.error("Failed to parse response: %s", e)
                return sys.float_info.max

        if acknowledgment == "\x15":  # NAK
            self.logger.error("Received NAK: Wrong command")
            raise WrongCommandError("Wrong command sent.")

        self.logger.error("Unknown acknowledgment: %r", acknowledgment)
        raise UnknownResponse(f"Unknown response: {acknowledgment!r}")

    def get_atomic_value(self, item: str ="") -> float:
        """
            Read the latest value of a specific channel.

            Args:
                item (str): Channel name (e.g., "3A", "Out1")

            Returns:
                float: Current value, or NaN if invalid.
        """
        if item == "pressure":
            value = self.read_pressure()
        else:
            self.logger.error("Unknown item received: %r", item)
            value = sys.float_info.max
        return value

class WrongCommandError(Exception):
    """Exception raised when a wrong command is sent."""


class UnknownResponse(Exception):
    """Exception raised when an unknown response is received."""


class DeviceConnectionError(Exception):
    """Exception raised when a device connection error occurs."""
