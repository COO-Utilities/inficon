"""
Inficon VGC502 Controller Interface
"""
import sys
import socket
import logging


class InficonVGC502:
    """Class for interfacing with InficonVGC502"""

    def __init__(self, address, port, timeout=1, log=True, quiet=False):
        # pylint: disable=too-many-positional-arguments, too-many-arguments
        self.address = address
        self.port = int(port)
        self.timeout = timeout
        self.sock: socket.socket | None = None

        # Initialize logger
        if log:
            logfile = __name__.rsplit('.', 1)[-1] + '.log'
            self.logger = logging.getLogger(logfile)
            if not self.logger.handlers:
                self.logger.setLevel(logging.INFO if quiet else logging.DEBUG)
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                file_handler = logging.FileHandler(logfile)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
        else:
            self.logger = None

        if self.logger:
            self.logger.info("Logger initialized for InficonVGC502")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self):
        """Open a TCP connection to the controller."""
        try:
            self.sock = socket.create_connection((self.address, self.port), timeout=self.timeout)
            # ensure subsequent ops also use timeout
            self.sock.settimeout(self.timeout)
            if self.logger:
                self.logger.info("Connected to %s:%d", self.address, self.port)
        except (ConnectionRefusedError, OSError) as err:
            if self.logger:
                self.logger.error("Connection failed: %s", err)
            raise DeviceConnectionError(
                f"Could not connect to {self.address}:{self.port}"
            ) from err

    def close(self):
        """Close the TCP connection."""
        try:
            if self.sock:
                self.sock.close()
                if self.logger:
                    self.logger.info("Connection closed")
        finally:
            self.sock = None

    def _sendall(self, data: bytes):
        if not self.sock:
            raise DeviceConnectionError("Not connected.")
        if self.logger:
            self.logger.debug("Sending bytes: %r", data)
        self.sock.sendall(data)

    def _read_until(self, terminator: bytes = b"\r\n", max_bytes: int = 4096) -> bytes:
        """Read until 'terminator' or timeout. Returns bytes including the terminator."""
        if not self.sock:
            raise DeviceConnectionError("Not connected.")
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
            return bytes(buf)
        except socket.timeout:
            if self.logger:
                self.logger.warning("Timeout while reading from socket")
            raise

    def read_pressure(self, gauge: int = 1) -> float:
        """Read pressure from gauge 1..n. Returns float, or sys.float_info.max on timeout/parse error."""
        # pylint: disable=too-many-branches
        if not isinstance(gauge, int) or gauge < 1:
            raise ValueError("gauge must be a positive integer")

        # Command format: PR{gauge}\r\n
        command = f"PR{gauge}\r\n".encode("ascii")
        try:
            self._sendall(command)
        except DeviceConnectionError:
            raise
        except OSError as e:
            if self.logger:
                self.logger.error("Failed to send command: %s", e)
            raise DeviceConnectionError("Write failed") from e

        # Read acknowledgment line (controller typically replies with ACK/NAK ending CRLF)
        try:
            acknowledgment = self._read_until(b"\r\n").strip()
            if self.logger:
                self.logger.debug("Acknowledgment received: %r", acknowledgment)
        except socket.timeout:
            # match original behavior: return max float on timeout
            return sys.float_info.max

        # Accept bare control char or control char followed by CRLF
        if acknowledgment == b"\x06":  # ACK
            if self.logger:
                self.logger.debug("ACK received, sending ENQ")
            try:
                self._sendall(b"\x05")  # ENQ
                response = self._read_until(b"\r\n")
            except socket.timeout:
                return sys.float_info.max
            except OSError as e:
                if self.logger:
                    self.logger.error("IO error while receiving response: %s", e)
                return sys.float_info.max

            response_str = response.strip().decode("ascii", errors="replace")
            if self.logger:
                self.logger.debug("Pressure response: %s", response_str)

            # Expected like: "PR1,<value>"
            try:
                parts = response_str.split(",")
                value = float(parts[1])
                return value
            except (IndexError, ValueError) as e:
                if self.logger:
                    self.logger.error("Failed to parse response: %s", e)
                return sys.float_info.max

        if acknowledgment == b"\x15":  # NAK
            if self.logger:
                self.logger.error("Received NAK: Wrong command")
            raise WrongCommandError("Wrong command sent.")

        if self.logger:
            self.logger.error("Unknown acknowledgment: %r", acknowledgment)
        raise UnknownResponse(f"Unknown response: {acknowledgment!r}")


class WrongCommandError(Exception):
    """Exception raised when a wrong command is sent."""


class UnknownResponse(Exception):
    """Exception raised when an unknown response is received."""


class DeviceConnectionError(Exception):
    """Exception raised when a device connection error occurs."""
