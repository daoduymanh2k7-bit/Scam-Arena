import threading
import time
import pytest
from app.voice.scheduling import SpeechScheduler, SpeechBusy


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        threading.Event().wait(.005)
    assert predicate()


def test_four_accounts_each_get_a_turn_and_final_has_priority():
    scheduler = SpeechScheduler()
    release = threading.Event()
    order, errors = [], []
    def work(user, preview, hold=False):
        try:
            with scheduler.slot(user, preview):
                order.append((user, preview))
                if hold: assert release.wait(3)
        except Exception as exc: errors.append(exc)
    active = threading.Thread(target=work, args=("p1", True, True))
    active.start(); wait_until(lambda: scheduler.active is not None)
    threads = []
    try:
        for user in ("p2", "p3", "p4"):
            t = threading.Thread(target=work, args=(user, True)); t.start(); threads.append(t)
            wait_until(lambda: user in scheduler.drafts)
        final = threading.Thread(target=work, args=("p1", False)); final.start(); threads.append(final)
        wait_until(lambda: "p1" in scheduler.finals)
        with pytest.raises(SpeechBusy):
            with scheduler.slot("p2", True): pass
        assert scheduler.interval_ms() >= 3000
    finally:
        release.set(); active.join(3)
        for thread in threads: thread.join(3)
    assert not errors
    assert order == [("p1", True), ("p1", False), ("p2", True), ("p3", True), ("p4", True)]
    assert not scheduler.drafts and not scheduler.finals and scheduler.active is None


def test_four_simultaneous_finals_are_queued_instead_of_dropped():
    scheduler = SpeechScheduler(); order = []; errors = []; release = threading.Event()
    def work(user):
        try:
            with scheduler.slot(user, False):
                order.append(user)
                if user == "p1": assert release.wait(3)
        except Exception as exc: errors.append(exc)
    first = threading.Thread(target=work, args=("p1",)); first.start()
    wait_until(lambda: scheduler.active is not None)
    rest = []
    try:
        for user in ("p2", "p3", "p4"):
            t = threading.Thread(target=work, args=(user,)); t.start(); rest.append(t)
            wait_until(lambda: user in scheduler.finals)
    finally:
        release.set(); first.join(3)
        for thread in rest: thread.join(3)
    assert not errors and order == ["p1", "p2", "p3", "p4"]


def test_final_cancels_its_queued_draft_and_timeout_does_not_leak():
    scheduler = SpeechScheduler(preview_timeout=.1)
    failures = []
    def draft(user):
        try:
            with scheduler.slot(user, True): pass
        except SpeechBusy: failures.append(user)
    def final():
        with scheduler.slot("p2", False): pass
    with scheduler.slot("p1", True):
        queued = threading.Thread(target=draft, args=("p2",)); queued.start()
        wait_until(lambda: "p2" in scheduler.drafts)
        finishing = threading.Thread(target=final); finishing.start()
        wait_until(lambda: "p2" in scheduler.finals)
        queued.join(1); assert "p2" in failures
        expiring = threading.Thread(target=draft, args=("p3",)); expiring.start(); expiring.join(1)
        assert "p3" in failures and "p3" not in scheduler.drafts
    finishing.join(1)
    assert scheduler.interval_ms() >= 1000
