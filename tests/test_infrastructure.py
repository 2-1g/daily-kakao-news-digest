import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InfrastructureContractTests(unittest.TestCase):
    def test_scheduler_is_0800_kst_and_has_no_retry(self):
        manifest = (ROOT / "infra/scheduler.yaml").read_text(encoding="utf-8")
        self.assertIn('schedule: "0 8 * * *"', manifest)
        self.assertIn("timeZone: Asia/Seoul", manifest)
        self.assertIn("retryCount: 0", manifest)
        self.assertIn("https://run.googleapis.com/v2/projects/PROJECT_ID/", manifest)

    def test_runtime_token_rotation_role_matches_refresh_protocol(self):
        role = (ROOT / "infra/runtime-token-rotator-role.yaml").read_text(
            encoding="utf-8")
        for permission in (
            "secretmanager.secrets.get",
            "secretmanager.secrets.update",
            "secretmanager.versions.access",
            "secretmanager.versions.add",
            "secretmanager.versions.disable",
            "secretmanager.versions.get",
        ):
            self.assertIn("- " + permission, role)
        self.assertNotIn("secretmanager.secrets.delete", role)
        self.assertNotIn("secretmanager.versions.destroy", role)

        contract = (ROOT / "infra/iam.md").read_text(encoding="utf-8")
        self.assertIn("runtime-token-rotator-role.yaml", contract)
        self.assertIn("Kakao token secret only", contract)

    def test_cloud_run_job_is_single_task_without_platform_retry(self):
        manifest = (ROOT / "infra/cloudrun-job.yaml").read_text(encoding="utf-8")
        self.assertIn("taskCount: 1", manifest)
        self.assertIn("maxRetries: 0", manifest)
        self.assertIn("news-digest-runtime@PROJECT_ID", manifest)
        self.assertNotIn("valueFrom:\n                  secretKeyRef", manifest)

    def test_container_drops_root_and_contains_no_secret_value(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER 65532:65532", dockerfile)
        self.assertNotIn("ACCESS_TOKEN", dockerfile.upper())
        self.assertNotIn("REFRESH_TOKEN", dockerfile.upper())

    def test_required_runbooks_exist_and_unknown_forbids_resend(self):
        names = ("oauth-bootstrap.md", "token-rotation.md",
                 "manual-reconciliation.md", "budget-suspension.md")
        for name in names:
            with self.subTest(name=name):
                self.assertTrue((ROOT / "docs/runbooks" / name).is_file())
        reconciliation = (ROOT / "docs/runbooks/manual-reconciliation.md").read_text(
            encoding="utf-8")
        self.assertIn("Automatic resend or continuation is forbidden", reconciliation)


if __name__ == "__main__":
    unittest.main()
