import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'app'))
from repositories.postgres import StorageUnavailable, _connection_error_code, _validate_ca_file


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

    def test_bad_ca_path_and_bad_pem_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'secret-path.crt'
            for create in (False, True):
                if create:
                    path.write_text('not a certificate')
                with self.assertRaises(StorageUnavailable) as caught:
                    _validate_ca_file(str(path))
                self.assertNotIn(str(path), str(caught.exception))

    def test_system_trust_is_not_treated_as_a_path(self):
        _validate_ca_file('system')
        _validate_ca_file(None)


if __name__ == '__main__':
    unittest.main()
