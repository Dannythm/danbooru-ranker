import asyncio
from enum import Enum
from datetime import datetime
from typing import Dict, Optional

class TaskState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ERROR = "error"

class Task:
    def __init__(self, task_id: str, name: str):
        self.id = task_id
        self.name = name
        self.state = TaskState.IDLE
        self.progress = 0
        self.message = ""
        self.current = 0
        self.total = 0
        self.created_at = datetime.now()
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set() # Initially not paused

    @property
    def is_cancelled(self):
        return self._cancel_event.is_set()

    @property
    def is_paused(self):
        return not self._pause_event.is_set()

    async def wait_if_paused(self):
        await self._pause_event.wait()

    def cancel(self):
        self.state = TaskState.CANCELLED
        self._cancel_event.set()
        # Ensure we don't get stuck in pause when cancelling
        self._pause_event.set()

    def pause(self):
        if self.state == TaskState.RUNNING:
            self.state = TaskState.PAUSED
            self._pause_event.clear()

    def resume(self):
        if self.state == TaskState.PAUSED:
            self.state = TaskState.RUNNING
            self._pause_event.set()

    def update(self, progress: int, message: str, current: int = 0, total: int = 0):
        self.progress = progress
        self.message = message
        self.current = current
        self.total = total

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "status": self.state.value,
            "progress": self.progress,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "created_at": self.created_at.isoformat()
        }

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}

    def create_task(self, task_id: str, name: str) -> Task:
        task = Task(task_id, name)
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def cancel_task(self, task_id: str):
        task = self.get_task(task_id)
        if task:
            task.cancel()

    def pause_task(self, task_id: str):
        task = self.get_task(task_id)
        if task:
            task.pause()

    def resume_task(self, task_id: str):
        task = self.get_task(task_id)
        if task:
            task.resume()

    def get_all_tasks(self):
        return {tid: task.to_dict() for tid, task in self.tasks.items()}

# Global instance
task_manager = TaskManager()
