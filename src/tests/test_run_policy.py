import unittest

from daemon.runtime import normalize_permission_policy, prompt_for_policy


class RunPolicyTests(unittest.TestCase):
    def test_plan_policy_wraps_prompt_for_todo_planning(self) -> None:
        prompt = prompt_for_policy("整理这个工程", "plan")

        self.assertIn("计划模式", prompt)
        self.assertIn("write_todos", prompt)
        self.assertIn("不要调用 write_file、edit_file、execute", prompt)
        self.assertIn("用户请求：整理这个工程", prompt)

    def test_unknown_policy_falls_back_to_standard_run(self) -> None:
        self.assertEqual(normalize_permission_policy("unknown"), "once")
        self.assertEqual(prompt_for_policy("直接执行", "unknown"), "直接执行")
