"""Tests for ``ClaudeProvider.select_option`` send protocol.

The digit and the trailing ``\\r`` must be sent in a single atomic
``write()`` so that the CLI's input-handling loop reads both bytes
in the same chunk.  Otherwise, a leaky permission menu (one that
auto-confirms on the digit and dismisses before the CR arrives)
would route the CR to the now-active composer, submitting whatever
text the user had typed-but-not-submitted.

Even small inter-byte gaps (e.g. 20 ms) are unsafe — each
``pty.send`` is a separate ``write()`` syscall, so the CLI's
``read()`` loop typically picks up the digit first and the CR in
the next iteration.  Only an atomic single-write puts both bytes
in the same kernel buffer.
"""

from unittest.mock import MagicMock

import pytest

from leap.cli_providers.claude import ClaudeProvider


class TestSelectOption:
    def test_single_digit_atomic(self) -> None:
        """Single digit + CR must be sent in ONE pty.send call."""
        provider = ClaudeProvider()
        sends: list[str] = []
        pty_send = MagicMock(side_effect=lambda d: sends.append(d))
        pty_sendline = MagicMock()
        result = provider.select_option(
            1, {1: "Yes"}, pty_send, pty_sendline,
        )
        assert result == {'status': 'sent'}
        pty_sendline.assert_not_called()
        assert sends == ['1\r']

    def test_no_pty_sendline_for_normal_options(self) -> None:
        """``pty_sendline`` introduces an output-settle gap (50–200 ms)
        between digit and CR that lets a leaky menu auto-confirm and
        leak the CR to the composer.  Provider must avoid it."""
        provider = ClaudeProvider()
        pty_send = MagicMock()
        pty_sendline = MagicMock()
        provider.select_option(
            2, {1: "Yes", 2: "No"}, pty_send, pty_sendline,
        )
        pty_sendline.assert_not_called()

    def test_multi_digit_sent_atomically(self) -> None:
        """Multi-digit options are sent in the same atomic write —
        digit + CR all land in the CLI's same ``read()`` chunk."""
        provider = ClaudeProvider()
        sends: list[str] = []
        pty_send = MagicMock(side_effect=lambda d: sends.append(d))
        pty_sendline = MagicMock()
        options = {n: f"Option {n}" for n in range(1, 11)}
        provider.select_option(10, options, pty_send, pty_sendline)
        assert sends == ['10\r']
        pty_sendline.assert_not_called()

    def test_invalid_option_returns_error(self) -> None:
        provider = ClaudeProvider()
        pty_send = MagicMock()
        pty_sendline = MagicMock()
        result = provider.select_option(
            99, {1: "Yes"}, pty_send, pty_sendline,
        )
        assert result['status'] == 'error'
        pty_send.assert_not_called()
        pty_sendline.assert_not_called()

    def test_type_something_returns_error(self) -> None:
        provider = ClaudeProvider()
        pty_send = MagicMock()
        pty_sendline = MagicMock()
        result = provider.select_option(
            4, {4: "Type something else"}, pty_send, pty_sendline,
        )
        assert result['status'] == 'error'
        assert 'type your answer' in result['error']
        pty_send.assert_not_called()
        pty_sendline.assert_not_called()
