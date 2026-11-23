"""Bounded, per-account FIFO speech work with final transcripts taking priority."""
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import math
import threading
import time


class SpeechBusy(RuntimeError):
    def __init__(self, message="Nhận diện đang bận. Vui lòng nói lại sau vài giây.", retry_after=2):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(eq=False)
class Ticket:
    user: str
    preview: bool
    cancelled: bool = False


class SpeechScheduler:
    def __init__(self, *, max_users=4, preview_timeout=6.0, final_timeout=12.0):
        self.condition = threading.Condition()
        self.drafts = OrderedDict()
        self.finals = OrderedDict()
        self.active = None
        self.last_draft_user = None
        self.preview_cost = 0.8
        self.max_users = max_users
        self.preview_timeout = preview_timeout
        self.final_timeout = final_timeout

    def interval_ms(self):
        with self.condition:
            # Include the requester that just completed, plus pending participants.
            users = set(self.drafts) | set(self.finals)
            if self.active:
                users.add(self.active.user)
            demand = min(self.max_users, max(1, len(users) + 1))
            # Reserve some CPU time for final transcripts, Piper and the web app.
            return min(5000, max(1000, math.ceil(self.preview_cost * demand * 1250)))

    def _next(self):
        if self.finals:
            return next(iter(self.finals.values()))
        if len(self.drafts) > 1 and next(iter(self.drafts)) == self.last_draft_user:
            self.drafts.move_to_end(self.last_draft_user)
        return next(iter(self.drafts.values()), None)

    @contextmanager
    def sample_slot(self, user):
        """No queue for optional dataset previews; calls already waiting always win.

        Running inference cannot be preempted; a call arriving afterwards may
        still wait for this bounded clip to complete.
        """
        with self.condition:
            if self.active is not None or self.finals or self.drafts:
                raise SpeechBusy("Cuộc gọi đang dùng bộ nhận diện. Mẫu đã lưu; hãy thử lại sau.", retry_after=5)
            self.active = Ticket(str(user), False)
        try:
            yield
        finally:
            with self.condition:
                self.active = None
                self.condition.notify_all()

    @contextmanager
    def slot(self, user, preview):
        ticket = Ticket(str(user), preview)
        queue = self.drafts if preview else self.finals
        deadline = time.monotonic() + (self.preview_timeout if preview else self.final_timeout)
        with self.condition:
            if preview and (ticket.user in self.finals or (self.active and self.active.user == ticket.user and not self.active.preview)):
                raise SpeechBusy(retry_after=1)
            if ticket.user in queue or (self.active and self.active.user == ticket.user and self.active.preview == preview):
                raise SpeechBusy(retry_after=1 if preview else 2)
            if len(queue) >= self.max_users:
                raise SpeechBusy(retry_after=1 if preview else 2)
            if not preview:
                stale = self.drafts.pop(ticket.user, None)
                if stale:
                    stale.cancelled = True
            queue[ticket.user] = ticket
            self.condition.notify_all()
            try:
                while self.active is not None or self._next() is not ticket:
                    remaining = deadline - time.monotonic()
                    if ticket.cancelled or remaining <= 0:
                        raise SpeechBusy(retry_after=1 if preview else 2)
                    self.condition.wait(remaining)
                if ticket.cancelled or time.monotonic() >= deadline:
                    raise SpeechBusy(retry_after=1 if preview else 2)
                queue.pop(ticket.user, None)
                self.active = ticket
            except BaseException:
                if queue.get(ticket.user) is ticket:
                    queue.pop(ticket.user)
                self.condition.notify_all()
                raise
        started = time.monotonic()
        try:
            yield
        finally:
            with self.condition:
                if preview:
                    elapsed = time.monotonic() - started
                    self.preview_cost = 0.7 * self.preview_cost + 0.3 * elapsed
                    self.last_draft_user = ticket.user
                self.active = None
                self.condition.notify_all()
