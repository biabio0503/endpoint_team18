import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from repositories.postgres import _connection_error_code


class ConnectionDiagnosticsTest(unittest.TestCase):
    def test_classifies_driver_errors_without_returning_secrets(self):
        examples = {
            'password authentication failed for user secret': 'authentication_failed',
            'could not translate host name secret': 'dns_error',
            'connection timed out': 'connection_timeout',
            'network is unreachable': 'network_unreachable',
            'server certificate for secret does not match host name': 'tls_hostname_mismatch',
            'SSL certificate verify failed': 'tls_verification_failed',
            'invalid connection option secret': 'invalid_dsn',
        }
        for message, code in examples.items():
            with self.subTest(code=code):
                self.assertEqual(_connection_error_code(Exception(message)), code)

if __name__ == '__main__':
    unittest.main()
