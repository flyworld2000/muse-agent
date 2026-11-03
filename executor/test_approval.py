import base64
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from approval import verify_approval_ticket


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()

        self.now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

        self.expected = {
            "expected_task_id": "task_test_001",
            "expected_plan_sha256": "a" * 64,
            "expected_candidate_id": "candidate_test_001",
            "expected_candidate_sha256": "b" * 64,
        }

        self.unsigned = {
            "schema_version": 1,
            "ticket_id": str(uuid.uuid4()),
            "task_id": self.expected["expected_task_id"],
            "approved_plan_sha256": self.expected["expected_plan_sha256"],
            "candidate_id": self.expected["expected_candidate_id"],
            "candidate_sha256": self.expected["expected_candidate_sha256"],
            "issued_at": (self.now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (self.now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        }

    def make_ticket(self, unsigned=None, private_key=None):
        data = dict(unsigned or self.unsigned)
        key = private_key or self.private_key
        signature = key.sign(canonical_json(data))
        ticket = dict(data)
        ticket["signature"] = base64.b64encode(signature).decode("ascii")
        return canonical_json(ticket)

    def verify(self, ticket_data, **overrides):
        expected = dict(self.expected)
        expected.update(overrides)
        return verify_approval_ticket(
            ticket_data,
            self.public_key,
            now=self.now,
            **expected,
        )

    def test_valid_ticket(self):
        result = self.verify(self.make_ticket())
        self.assertEqual(result["task_id"], self.expected["expected_task_id"])
        self.assertEqual(result["candidate_id"], self.expected["expected_candidate_id"])

    def test_tampered_signature_rejected(self):
        ticket = json.loads(self.make_ticket())
        ticket["candidate_sha256"] = "c" * 64
        with self.assertRaises(ValueError):
            self.verify(canonical_json(ticket))

    def test_duplicate_json_key_rejected(self):
        ticket = self.make_ticket().decode("utf-8")
        duplicate = ticket.replace(
            '"schema_version":1',
            '"schema_version":1,"schema_version":1',
            1,
        ).encode("utf-8")
        with self.assertRaises(ValueError):
            self.verify(duplicate)

    def test_wrong_task_id_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(), expected_task_id="another_task")

    def test_wrong_plan_hash_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(), expected_plan_sha256="c" * 64)

    def test_wrong_candidate_id_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(), expected_candidate_id="another_candidate")

    def test_wrong_candidate_digest_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(), expected_candidate_sha256="c" * 64)

    def test_expired_ticket_rejected(self):
        expired = dict(self.unsigned)
        expired["issued_at"] = (self.now - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
        expired["expires_at"] = (self.now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(expired))

    def test_future_issued_ticket_rejected(self):
        future = dict(self.unsigned)
        future["issued_at"] = (self.now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        future["expires_at"] = (self.now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(future))

    def test_lifetime_over_15_minutes_rejected(self):
        long_lived = dict(self.unsigned)
        long_lived["issued_at"] = self.now.isoformat().replace("+00:00", "Z")
        long_lived["expires_at"] = (self.now + timedelta(minutes=16)).isoformat().replace("+00:00", "Z")
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(long_lived))

    def test_wrong_public_key_rejected(self):
        other_key = Ed25519PrivateKey.generate()
        ticket = self.make_ticket()
        with self.assertRaises(ValueError):
            verify_approval_ticket(
                ticket,
                other_key.public_key(),
                now=self.now,
                **self.expected,
            )

    def test_unknown_field_rejected(self):
        extra = dict(self.unsigned)
        extra["unexpected"] = "value"
        with self.assertRaises(ValueError):
            self.verify(self.make_ticket(extra))

    def test_naive_current_time_rejected(self):
        with self.assertRaises(ValueError):
            verify_approval_ticket(
                self.make_ticket(),
                self.public_key,
                now=datetime(2026, 11, 1, 12, 0),
                **self.expected,
            )


if __name__ == "__main__":
    unittest.main()
