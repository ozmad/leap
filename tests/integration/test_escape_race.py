"""The Escape race: when the user hits Escape during a running CLI,
the keystroke arms ``_interrupt_pending`` while state is still RUNNING,
so the subsequent 'Interrupted' bytes flip the tracker to interrupted
even if Stop hook signal processing is interleaved with the PTY render.

Under the IDLE-state gate, Esc keystrokes processed *after* the tracker
has already seen the idle signal (state is now IDLE) no longer arm the
flag — that path was a false-positive vector for ambient ``Interrupted``
substrings in conversational scrollback.  The realistic race below
(keypress arrives before the signal) is unaffected.
"""

from tests.conftest import PTYFixture


class TestEscapeRace:
    def test_interrupt_detected_when_pattern_lands_during_running(
        self, pty: PTYFixture,
    ) -> None:
        """Real-world ordering: Esc keystroke is processed while state
        is still RUNNING (flag armed), then 'Interrupted' lands on the
        PTY.  ``_handle_running_output`` catches the pattern + flag
        and transitions to interrupted before any Stop hook signal."""
        pty.tracker.on_send()
        assert pty.get_state() == 'running'

        pty.tracker.on_input(b'\x1b')  # state RUNNING — flag armed

        pty.send_line('echo Interrupted')
        pty.drain_to_tracker(timeout=1.0)

        assert pty.tracker.current_state == 'interrupted'
