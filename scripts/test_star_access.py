"""Permission discovery counts public write access, independently of pull requests."""
from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from collector.github import CollectionError, ReplayClient, UTC
import sync_star_access as access


QUERY = "/user/repos?" + urlencode({"visibility": "public", "affiliation": "owner,collaborator,organization_member", "per_page": 100})


def repository(name, *, private=False, **permissions):
    return {"full_name": name, "private": private, "permissions": permissions}


def client(rows, login="Haoming9527"):
    return ReplayClient({"/user": {"body": {"login": login}}, QUERY: {"body": rows}})


class AccessTests(unittest.TestCase):
    def test_public_direct_and_org_access_count_without_pull_requests(self):
        source = client([
            repository("Haoming9527/mine", admin=True),
            repository("other/no-pr-yet", push=True),
            repository("org/admin-project", admin=True),
            repository("org/maintained", maintain=True),
            repository("other/read-only", pull=True),
            repository("other/triage-only", triage=True),
            repository("other/private", private=True, push=True),
            repository("other/untrusted-role", push="true"),
            {"full_name": "other/missing-privacy", "permissions": {"push": True}},
            dict(repository("org/internal", admin=True), visibility="internal"),
        ])
        self.assertEqual(access.discover_collaborators("Haoming9527", source),
                         ["org/admin-project", "org/maintained", "other/no-pr-yet"])

    def test_identity_must_match_before_reading_repositories(self):
        source = client([], login="another-account")
        with self.assertRaises(CollectionError):
            access.discover_collaborators("Haoming9527", source)
        self.assertEqual(source.requests, 1)

    def test_all_pages_are_read_and_names_are_deduplicated(self):
        source = client([repository("Team/App", push=True)])
        source.responses[QUERY]["headers"] = {"Link": '<https://api.github.com/user/repos?page=2>; rel="next"'}
        source.responses["/user/repos?page=2"] = {"body": [
            repository("team/app", admin=True), repository("Alpha/Tool", maintain=True),
            repository("haoming9527/Own", push=True),
        ]}
        self.assertEqual(access.discover_collaborators("Haoming9527", source), ["Alpha/Tool", "Team/App"])

    def test_unrelated_configuration_is_preserved_and_access_is_replaced(self):
        config = {"github_username": "Haoming9527", "projects": [{"name": "Keep me"}],
                  "star_collaborator_repositories": ["old/access"], "role": "Engineer"}
        result = access.sync_config(config, client([]), datetime(2026, 11, 10, 10, 30, tzinfo=UTC))
        self.assertEqual(result["projects"], config["projects"])
        self.assertEqual(result["role"], "Engineer")
        self.assertEqual(result["star_collaborator_repositories"], [])
        self.assertEqual(result["star_access_verified_at"], "2026-11-10T10:30:00Z")
        self.assertEqual(config["star_collaborator_repositories"], ["old/access"])

    def test_failure_preserves_original_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            original = '{"github_username":"Haoming9527","star_collaborator_repositories":["keep/access"]}'
            path.write_text(original, encoding="utf-8")
            source = client([])
            del source.responses[QUERY]
            with patch.object(access, "access_token", return_value="secret-not-printed"), \
                    patch.object(access, "GitHubClient", return_value=source), \
                    patch("sys.stderr", new_callable=io.StringIO) as output:
                result = access.main(["--config", str(path)])
            self.assertEqual(result, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertNotIn("secret-not-printed", output.getvalue())

    def test_success_only_writes_public_names_and_verification_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text('{"github_username":"Haoming9527","keep":true}', encoding="utf-8")
            with patch.object(access, "access_token", return_value="secret-not-printed"), \
                    patch.object(access, "GitHubClient", return_value=client([repository("team/new", push=True)])), \
                    patch("sys.stdout", new_callable=io.StringIO) as output:
                result = access.main(["--config", str(path)])
            self.assertEqual(result, 0)
            saved = path.read_text(encoding="utf-8")
            self.assertNotIn("secret-not-printed", saved + output.getvalue())
            self.assertEqual(json.loads(saved)["star_collaborator_repositories"], ["team/new"])
            self.assertTrue(json.loads(saved)["keep"])


class TokenTests(unittest.TestCase):
    def test_environment_token_prevents_cli_lookup(self):
        with patch.dict("os.environ", {"GH_TOKEN": " env-token "}, clear=True), \
                patch.object(access.subprocess, "run") as run:
            self.assertEqual(access.access_token(), "env-token")
            run.assert_not_called()

    def test_cli_token_is_captured_and_failure_output_is_not_relayed(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(access.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "cli-token\n", "")
            self.assertEqual(access.access_token(), "cli-token")
            self.assertTrue(run.call_args.kwargs["capture_output"])
            run.return_value = subprocess.CompletedProcess([], 1, "", "do not relay this")
            with self.assertRaises(CollectionError) as error:
                access.access_token()
            self.assertNotIn("do not relay this", str(error.exception))


if __name__ == "__main__":
    unittest.main()
