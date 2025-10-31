# tests/test_inficonvgc502_units_sync.py
import pytest
from unittest.mock import MagicMock, call

from inficonvgc502 import InficonVGC502, UnknownResponse


@pytest.fixture
def vgc502():
    """Creates an InficonVGC502 instance with mock logger."""
    return InficonVGC502(address="127.0.0.1", port=8000, log=False)


def test_set_pressure_unit_success(vgc502):
    # Mock low-level I/O so we don't need a real socket
    vgc502._sendall = MagicMock()
    # Device replies ACK (\x06\r\n)
    vgc502._read_until = MagicMock(return_value=b"\x06\r\n")

    # Pascal (example: 2)
    result = vgc502.set_pressure_unit(2)
    assert result is True

    # Verify the command was sent
    vgc502._sendall.assert_called_with(b"UNI,2\r\n")


def test_set_pressure_unit_invalid_value(vgc502):
    with pytest.raises(ValueError):
        vgc502.set_pressure_unit(9)  # out of allowed range


def test_set_pressure_unit_unexpected_response(vgc502):
    vgc502._sendall = MagicMock()
    # Device replies NAK or anything not ACK; original test expected UnknownResponse
    vgc502._read_until = MagicMock(return_value=b"\x15\r\n")

    with pytest.raises(UnknownResponse):
        vgc502.set_pressure_unit(1)


def test_get_pressure_unit(vgc502):
    vgc502._sendall = MagicMock()
    # First read: ACK to 'UNI\r\n'; Second read: the unit value line '3\r\n'
    vgc502._read_until = MagicMock(side_effect=[b"\x06\r\n", b"3\r\n"])

    result = vgc502.get_pressure_unit()
    assert result == 3

    # Ensure UNI and ENQ were written (order matters)
    vgc502._sendall.assert_has_calls([call(b"UNI\r\n"), call(b"\x05")])


def test_get_pressure_unit_invalid_response(vgc502):
    vgc502._sendall = MagicMock()
    # ACK followed by a non-integer value
    vgc502._read_until = MagicMock(side_effect=[b"\x06\r\n", b"X\r\n"])

    with pytest.raises(ValueError):
        vgc502.get_pressure_unit()
