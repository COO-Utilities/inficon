"""
Inficon VGC502 Controller Interface
"""
import asyncio
import sys
import logging


class InficonVGC502:
    """Class for interfacing with InficonVGC502"""
    def __init__(self, address, port, timeout=1, log=True, quiet=False):
        # pylint: disable=too-many-arguments
        self.address = address
        self.port = int(port)
        self.timeout = timeout
        self.reader = None
        self.writer = None

        # Initialize logger
        if log:
            logfile = __name__.rsplit('.', 1)[-1] + '.log'
            self.logger = logging.getLogger(logfile)
            if not self.logger.handlers:
                if quiet:
                    self.logger.setLevel(logging.INFO)
                else:
                    self.logger.setLevel(logging.DEBUG)
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                file_handler = logging.FileHandler(logfile)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
        else:
            self.logger = None

        if self.logger:
            self.logger.info("Logger initialized for InficonVGC502")

    async def __aenter__(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.address, self.port)
            if self.logger:
                self.logger.info("Connected to %s:%d", self.address, self.port)
        except ConnectionRefusedError as err:
            if self.logger:
                self.logger.error("Connection refused: %s", err)
            raise DeviceConnectionError(
                f"Could not connect to {self.address}:{self.port}") from err
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            if self.logger:
                self.logger.info("Connection closed")

    async def read_pressure(self, gauge=1):
        """Method for reading pressure from InficonVGC502"""
        # pylint: disable=too-many-branches
        command = f'PR{gauge}\r\n'.encode('ascii')
        if self.logger:
            self.logger.debug("Sending command: %s", command)
        self.writer.write(command)
        await self.writer.drain()

        try:
            acknowledgment = await self.reader.readuntil(b'\r\n')
            acknowledgment = acknowledgment.strip()
            if self.logger:
                self.logger.debug("Acknowledgment received: %s", acknowledgment)
        except asyncio.TimeoutError:
            if self.logger:
                self.logger.warning("Timeout waiting for acknowledgment")
            return sys.float_info.max

        if acknowledgment == b'\x06':
            if self.logger:
                self.logger.debug("ACK received, sending ENQ")
            self.writer.write(b'\x05')
            await self.writer.drain()
            try:
                response = await self.reader.readuntil(b'\r\n')
                response_str = response.strip().decode('ascii')
                if self.logger:
                    self.logger.debug("Pressure response: %s", response_str)
                return float(response_str.split(',')[1])
            except (IndexError, ValueError) as e:
                if self.logger:
                    self.logger.error("Failed to parse response: %s", e)
                return sys.float_info.max
        elif acknowledgment == b'\x15':
            if self.logger:
                self.logger.error("Received NAK: Wrong command")
            raise WrongCommandError("Wrong command sent.")
        else:
            if self.logger:
                self.logger.error("Unknown acknowledgment: %s", acknowledgment)
            raise UnknownResponse(f"Unknown response: {acknowledgment}")


class WrongCommandError(Exception):
    """Exception raised when a wrong command is sent."""
    # pass


class UnknownResponse(Exception):
    """Exception raised when an unknown response is received."""
    # pass


class DeviceConnectionError(Exception):
    """Exception raised when a device connection error is received."""
    # pass
