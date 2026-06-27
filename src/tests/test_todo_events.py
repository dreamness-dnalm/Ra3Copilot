import json
import unittest
from queue import Empty

from daemon.api.protocol import EVENT_TODOS_UPDATED
from daemon.supervisor import RunState, RunSupervisor, _todo_progress, _todos_from_tool_args


class TodoEventTests(unittest.TestCase):
    def test_write_todos_args_are_normalized(self) -> None:
        valid, todos = _todos_from_tool_args(
            {
                "todos": [
                    {"content": "分析项目", "status": "completed"},
                    {"content": "实现前端面板", "status": "in_progress"},
                    {"content": "运行测试", "status": "pending"},
                ]
            }
        )

        self.assertTrue(valid)
        self.assertEqual(
            todos,
            [
                {"content": "分析项目", "status": "completed"},
                {"content": "实现前端面板", "status": "in_progress"},
                {"content": "运行测试", "status": "pending"},
            ],
        )
        self.assertEqual(
            _todo_progress(todos),
            {
                "total": 3,
                "completed": 1,
                "inProgress": 1,
                "pending": 1,
                "percentage": 33,
            },
        )

    def test_write_todos_event_is_emitted_once_per_snapshot(self) -> None:
        state = RunState(
            run_id="run",
            client_id="client",
            thread_id="thread",
            agent_mode="universal",
            project_id="project",
            permission_policy="once",
        )
        supervisor = RunSupervisor()
        payload = {
            "todos": [
                {"content": "A", "status": "completed"},
                {"content": "B", "status": "pending"},
            ]
        }

        supervisor._emit_todos_from_tool_args(state, json.dumps(payload, ensure_ascii=False))
        event = state.events.get_nowait()

        self.assertEqual(event["type"], EVENT_TODOS_UPDATED)
        self.assertEqual(event["todos"], payload["todos"])
        self.assertEqual(event["progress"]["completed"], 1)
        self.assertEqual(event["progress"]["percentage"], 50)

        supervisor._emit_todos_from_tool_args(state, json.dumps(payload, ensure_ascii=False))
        with self.assertRaises(Empty):
            state.events.get_nowait()
