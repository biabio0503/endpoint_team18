import os
from pathlib import Path
import subprocess
import sys
import unittest

APP = Path(__file__).resolve().parents[2] / 'app'


class DeploymentConfigTest(unittest.TestCase):
    def run_config(self, **overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ROADMAP_') and k not in ('PORT', 'RENDER')}
        env.update({'PYTHONPATH': str(APP), 'ROADMAP_DB_BACKEND': 'sqlite'})
        env.update(overrides)
        return subprocess.run([sys.executable, '-c', 'import config; config.validate_deployment(); print(config.API_HOST, config.API_PORT)'], env=env, capture_output=True, text=True)

    def test_local_and_render_binding(self):
        local = self.run_config(ROADMAP_API_PORT='8123')
        self.assertEqual(local.stdout.strip(), '127.0.0.1 8123')
        render = self.run_config(RENDER='true', PORT='10000', ROADMAP_DB_BACKEND='postgres', ROADMAP_DATABASE_URL='placeholder', ROADMAP_APP_ORIGIN='https://example.com')
        self.assertEqual(render.stdout.strip(), '0.0.0.0 10000')

    def test_invalid_configuration_fails(self):
        self.assertNotEqual(self.run_config(PORT='70000').returncode, 0)
        self.assertNotEqual(self.run_config(RENDER='true').returncode, 0)
        self.assertNotEqual(self.run_config(RENDER='true', ROADMAP_DB_BACKEND='postgres', ROADMAP_DATABASE_URL='placeholder', ROADMAP_APP_ORIGIN='http://example.com').returncode, 0)


if __name__ == '__main__':
    unittest.main()
