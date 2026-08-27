# -*- coding: utf-8 -*-
"""后台 Job 管理：job_id -> 状态/进度/结果，前端轮询。"""
import threading
import traceback
import uuid


class Job(object):
    def __init__(self, kind):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind            # export / import-stage / import-apply
        self.phase = "初始化"
        self.current = 0
        self.total = 0
        self.message = ""
        self.status = "running"     # running / done / error / canceled / staged
        self.result = None
        self.error = None
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()

    def update(self, phase=None, current=None, total=None, message=None):
        with self._lock:
            if phase is not None:
                self.phase = phase
            if current is not None:
                self.current = current
            if total is not None:
                self.total = total
            if message is not None:
                self.message = message

    def finish(self, result):
        with self._lock:
            self.status = "done"
            self.result = result

    def stage(self, result=None):
        with self._lock:
            self.status = "staged"
            if result is not None:
                self.result = result

    def fail(self, error):
        with self._lock:
            self.status = "error"
            self.error = str(error)

    def canceled(self):
        with self._lock:
            self.status = "canceled"

    def check_cancel(self):
        if self.cancel_event.is_set():
            raise CancelledError()

    def snapshot(self):
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "phase": self.phase,
                "current": self.current,
                "total": self.total,
                "message": self.message,
                "status": self.status,
                "result": self.result,
                "error": self.error,
            }


class CancelledError(Exception):
    pass


_jobs = {}
_jobs_lock = threading.Lock()


def new_job(kind):
    job = Job(kind)
    with _jobs_lock:
        _jobs[job.id] = job
    return job


def get_job(job_id):
    with _jobs_lock:
        return _jobs.get(job_id)


def cancel_job(job_id):
    job = get_job(job_id)
    if not job:
        return False
    job.cancel_event.set()
    return True


def run_in_thread(job, fn):
    def wrapper():
        try:
            fn(job)
        except CancelledError:
            job.canceled()
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            job.fail("%s: %s" % (type(e).__name__, e))

    t = threading.Thread(target=wrapper, daemon=True)
    t.start()
    return t
